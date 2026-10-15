"""Keep API endpoints out of Services until queries and synchronization are healthy."""

import json
import re
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen

MAX_RESPONSE_BYTES = 1024 * 1024


def fetch(url, timeout):
    with urlopen(url, timeout=timeout) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("health response exceeds size limit")
    return body.decode("utf-8")


def connect(port, timeout):
    with socket.create_connection(("127.0.0.1", port), timeout=timeout):
        pass


def reference_slot(body):
    slots = re.findall(
        r"^cardano_node_metrics_slotNum_int(?:\{[^\n]*\})?\s+([0-9.eE+-]+)\s*$",
        body,
        re.MULTILINE,
    )
    if not slots:
        raise ValueError("reference has no Cardano tip metric")
    return max(int(float(slot)) for slot in slots)


def check(config, fetcher=fetch, connector=connect, now=time.time):
    timeout = config["requestTimeoutSeconds"]
    block = json.loads(fetcher(
        f'http://127.0.0.1:{config["minibfPort"]}/blocks/latest', timeout
    ))
    slot, timestamp = block["slot"], block["time"]
    if type(slot) is not int or type(timestamp) is not int or slot < 0:
        raise ValueError("latest block has invalid slot or timestamp")
    age = now() - timestamp
    if age < -30 or age > config["maxTipAgeSeconds"]:
        raise ValueError("latest block is outside the freshness window")
    references = []
    for url in config["referenceTipURLs"]:
        try:
            references.append(reference_slot(fetcher(url, timeout)))
        except (OSError, ValueError, OverflowError):
            continue
    if not references:
        raise ValueError("no reference relay tip is available")
    if max(references) - slot > config["maxSlotLag"]:
        raise ValueError("Dolos is behind the reference relay tip")
    if config["minikupoPort"]:
        health = json.loads(fetcher(
            f'http://127.0.0.1:{config["minikupoPort"]}/health', timeout
        ))
        checkpoint = health.get("most_recent_checkpoint")
        if health.get("connection_status") != "connected" or type(checkpoint) is not int:
            raise ValueError("MiniKupo query health is unavailable")
        if slot - checkpoint > config["maxSlotLag"]:
            raise ValueError("MiniKupo is behind MiniBlockfrost")
    connector(config["grpcPort"], timeout)


class Monitor:
    def __init__(self, config):
        self.config = config
        self.lock = threading.Lock()
        self.ready = False
        self.checked_at = None
        self.worker = threading.Thread(target=self.poll, daemon=True)

    def poll(self):
        previous = None
        while True:
            reason = "ready"
            try:
                check(self.config)
                ready = True
            except Exception as error:
                ready = False
                reason = str(error) if isinstance(error, ValueError) else type(error).__name__
            if (ready, reason) != previous:
                print(json.dumps({"ready": ready, "reason": reason}), flush=True)
                previous = (ready, reason)
            with self.lock:
                self.ready = ready
                self.checked_at = time.monotonic()
            time.sleep(self.config["pollIntervalSeconds"])

    def is_ready(self):
        with self.lock:
            return (
                self.ready
                and self.checked_at is not None
                and time.monotonic() - self.checked_at <= self.config["maxCheckAgeSeconds"]
            )


def main():
    with open(sys.argv[1], encoding="utf-8") as source:
        config = json.load(source)
    if not config["referenceTipURLs"]:
        raise ValueError("at least one referenceTipURL is required")
    monitor = Monitor(config)
    monitor.worker.start()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/readyz":
                healthy = monitor.is_ready()
            elif self.path == "/healthz":
                healthy = monitor.worker.is_alive()
            else:
                self.send_error(404)
                return
            body = b"ready\n" if healthy else b"unavailable\n"
            self.send_response(200 if healthy else 503)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    ThreadingHTTPServer(("0.0.0.0", config["port"]), Handler).serve_forever()


if __name__ == "__main__":
    main()
