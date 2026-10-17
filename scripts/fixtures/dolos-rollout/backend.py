"""Small API fixture: a replacement listens before its query tip catches up."""
import json
import os
import pathlib
import socketserver
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

started = time.monotonic()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        if "slow" in query:
            print("slow-request-started", flush=True)
            time.sleep(float(query["slow"][0]))
        if "reference" in sys.argv:
            body = b"cardano_node_metrics_slotNum_int 100\n"
        else:
            lagging = time.monotonic() - started < float(os.environ.get("LAG_SECONDS", "0"))
            slot = 90 if lagging else 100
            if urlparse(self.path).path == "/health":
                data = {"connection_status": "connected", "most_recent_checkpoint": slot}
            else:
                data = {"slot": slot, "time": int(time.time()), "revision": os.environ["REVISION"]}
            body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


class TCPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        pass


def client(url):
    results = {"requests": 0, "errors": []}
    while not pathlib.Path("/tmp/stop-client").exists():
        try:
            with urlopen(url, timeout=3) as response:
                data = json.load(response)
            if data["slot"] != 100:
                results["errors"].append("received stale API data")
        except Exception as error:
            results["errors"].append(type(error).__name__)
        results["requests"] += 1
        time.sleep(0.2)
    print(json.dumps(results), flush=True)
    return bool(results["errors"])


if "bootstrap" in sys.argv:
    sys.exit(0)
if len(sys.argv) > 1 and sys.argv[1] == "client":
    sys.exit(client(sys.argv[2]))
if "reference" in sys.argv:
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
else:
    for port in [3001, 1442]:
        server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
    socketserver.ThreadingTCPServer(("0.0.0.0", 50051), TCPHandler).serve_forever()
