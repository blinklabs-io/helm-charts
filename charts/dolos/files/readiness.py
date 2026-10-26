"""Keep API endpoints out of Services until queries and synchronization are healthy."""

import json
import math
import re
import socket
import sys
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

MAX_RESPONSE_BYTES = 1024 * 1024


class RejectRedirects(HTTPRedirectHandler):
    def redirect_request(
        self, _request, _file, _code, _message, _headers, _new_url
    ):
        return None


HTTP_OPENER = build_opener(RejectRedirects)


class ProbeServer(ThreadingHTTPServer):
    daemon_threads = True
    max_connections = 16
    request_timeout_seconds = 2

    def __init__(self, *args, **kwargs):
        self._connection_slots = threading.BoundedSemaphore(self.max_connections)
        super().__init__(*args, **kwargs)

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(self.request_timeout_seconds)
        return request, address

    def process_request(self, request, client_address):
        if not self._connection_slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._connection_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._connection_slots.release()


def read_url(url, timeout):
    if urlsplit(url).scheme not in ("http", "https"):
        raise ValueError("health URLs must use HTTP or HTTPS")
    with HTTP_OPENER.open(url, timeout=timeout) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("health response exceeds size limit")
    return body


def fetch(url, timeout):
    # A socket timeout resets as bytes arrive. A child deadline also bounds DNS,
    # headers and slow bodies, and reaps the blocked reader before failover.
    try:
        result = subprocess.run(
            [sys.executable, "-B", __file__, "--fetch", url, str(timeout)],
            capture_output=True, timeout=timeout, check=True,
        )
    except subprocess.TimeoutExpired as error:
        raise TimeoutError("health request exceeded its total deadline") from error
    except subprocess.CalledProcessError as error:
        raise OSError("health request failed") from error
    return result.stdout.decode("utf-8")


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
    samples = [float(slot) for slot in slots]
    if any(not math.isfinite(slot) or slot < 0 for slot in samples):
        raise ValueError("reference has an invalid Cardano tip metric")
    return int(max(samples))


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
        self.started_at = time.monotonic()
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

    def is_live(self):
        with self.lock:
            progress = self.checked_at if self.checked_at is not None else self.started_at
            budget = 2 * max(
                self.config["maxCheckAgeSeconds"],
                self.config["pollIntervalSeconds"] + self.config["requestTimeoutSeconds"] * (len(self.config["referenceTipURLs"]) + 3),
            )
            return self.worker.is_alive() and time.monotonic() - progress <= budget


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
                healthy = monitor.is_live()
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

    ProbeServer(("0.0.0.0", config["port"]), Handler).serve_forever()


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--fetch":
        try:
            sys.stdout.buffer.write(read_url(sys.argv[2], float(sys.argv[3])))
        except (OSError, ValueError):
            sys.exit(1)
    else:
        main()
