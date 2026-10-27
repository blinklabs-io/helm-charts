import importlib.util
import json
import pathlib
import socket
import subprocess
import time
import tempfile
import threading
from urllib.request import urlopen
from urllib.error import HTTPError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from unittest.mock import patch

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("readiness", ROOT / "charts/dolos/files/readiness.py")
readiness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(readiness)


class FetchDeadlineTests(unittest.TestCase):
    def test_slow_headers_and_body_allow_reference_failover(self):
        for slow_path in ("/slow-headers", "/slow-body"):
            with self.subTest(path=slow_path):
                stop = threading.Event()
                started = threading.Event()
                fallback = threading.Event()

                class Handler(BaseHTTPRequestHandler):
                    def do_GET(self):
                        try:
                            if self.path == "/metrics":
                                fallback.set()
                                self.send_response(200)
                                self.end_headers()
                                self.wfile.write(b"cardano_node_metrics_slotNum_int 1000\n")
                            else:
                                if self.path == "/slow-headers":
                                    self.wfile.write(b"HTTP/1.1 200 OK\r\nX-Slow: ")
                                else:
                                    self.send_response(200)
                                    self.end_headers()
                                started.set()
                                while not stop.is_set():
                                    self.wfile.write(b"x")
                                    self.wfile.flush()
                                    stop.wait(0.02)
                        except (BrokenPipeError, ConnectionResetError):
                            pass

                    def log_message(self, *_args):
                        pass

                server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base = f"http://127.0.0.1:{server.server_port}"
                config = dict(requestTimeoutSeconds=1, maxTipAgeSeconds=600,
                              maxSlotLag=60, minibfPort=3001, minikupoPort=0, grpcPort=50051, referenceTipURLs=[base + slow_path, base + "/metrics"])
                errors = []
                complete = threading.Event()

                def fetch(url, timeout):
                    if url.endswith("/blocks/latest"):
                        return json.dumps({"slot": 1000, "time": 1792954800})
                    return readiness.fetch(url, timeout)

                def check():
                    try:
                        readiness.check(config, fetch, lambda port, timeout: None, lambda: 1792954860)
                    except Exception as error:
                        errors.append(error)
                    finally:
                        complete.set()

                worker = threading.Thread(target=check, daemon=True)
                worker.start()
                try:
                    self.assertTrue(started.wait(5), "slow response never started")
                    self.assertTrue(complete.wait(5), "slow response prevented reference failover")
                    self.assertFalse(errors, errors)
                    self.assertTrue(fallback.is_set(), "healthy fallback was not queried")
                finally:
                    stop.set()
                    server.shutdown()
                    server.server_close()
                    thread.join(5)
                    worker.join(5)

    def test_fetch_restricts_schemes(self):
        with self.assertRaises(OSError):
            readiness.fetch("file:///etc/hosts", 2)

    def test_read_url_rejects_redirects(self):
        reached = threading.Event()

        class TargetHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                reached.set()
                self.send_response(200)
                self.end_headers()

            def log_message(self, *_args):
                pass

        target = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header(
                    "Location",
                    f"http://127.0.0.1:{target.server_port}/internal",
                )
                self.end_headers()

            def log_message(self, *_args):
                pass

        redirect = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        threads = [
            threading.Thread(target=server.serve_forever, daemon=True)
            for server in (target, redirect)
        ]
        for thread in threads:
            thread.start()
        try:
            with self.assertRaises(HTTPError):
                readiness.read_url(
                    f"http://127.0.0.1:{redirect.server_port}/metrics",
                    2,
                )
            self.assertFalse(reached.is_set())
        finally:
            for server in (redirect, target):
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(5)

    def start_probe_server(self, max_connections, request_timeout_seconds):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

        class TestServer(readiness.ProbeServer):
            pass

        TestServer.max_connections = max_connections
        TestServer.request_timeout_seconds = request_timeout_seconds
        server = TestServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        worker.start()

        def stop():
            server.shutdown()
            server.server_close()
            worker.join(5)

        self.addCleanup(stop)
        return server

    def test_probe_connections_are_bounded(self):
        # The server deadline outlasts the rejection wait, so an accepted idle
        # connection cannot satisfy the assertion by timing out.
        server = self.start_probe_server(2, 2)
        clients = []
        try:
            for _ in range(server.max_connections):
                clients.append(socket.create_connection(server.server_address, timeout=1))
            deadline = time.monotonic() + 1
            while server._connection_slots.acquire(blocking=False):
                server._connection_slots.release()
                if time.monotonic() >= deadline:
                    self.fail("probe connections did not reach the configured bound")
                time.sleep(0.01)

            rejected = socket.create_connection(server.server_address, timeout=1)
            rejected.settimeout(0.3)
            try:
                self.assertEqual(rejected.recv(1), b"")
            except ConnectionResetError:
                pass
            except socket.timeout:
                self.fail("over-limit probe connection was accepted")
            finally:
                rejected.close()
        finally:
            for client in clients:
                client.close()

    def test_probe_connection_has_total_deadline(self):
        server = self.start_probe_server(2, 0.5)
        client = socket.create_connection(server.server_address, timeout=3)
        stop = threading.Event()

        # Each byte arrives well inside the per-read timeout.
        def trickle():
            try:
                client.sendall(b"GET /readyz HTTP/1.1\r\nX-Slow: ")
                while not stop.wait(0.1):
                    client.sendall(b"x")
            except OSError:
                pass

        sender = threading.Thread(target=trickle, daemon=True)
        started = time.monotonic()
        sender.start()
        try:
            try:
                closed = client.recv(1) == b""
            except ConnectionResetError:
                closed = True
            except socket.timeout:
                closed = False
            self.assertTrue(
                closed and time.monotonic() - started < 2,
                "trickling probe client held its connection past the total deadline",
            )
        finally:
            stop.set()
            sender.join(5)
            client.close()


class BudgetTests(unittest.TestCase):
    def test_cache_age_covers_optional_apis_and_fractional_timeouts(self):
        cases = [
            ([], 2, 10, False), ([], 2, 11, False), ([], 2, 12, True),
            (["--set", "ports.minikupo=1442", "--set", "service.ports.minikupo=11442"], 2, 13, False),
            (["--set", "ports.minikupo=1442", "--set", "service.ports.minikupo=11442"], 2, 14, True),
            ([], 0.75, 7, False), ([], 0.75, 8, True),
        ]
        for args, timeout, age, valid in cases:
            with self.subTest(args=args, timeout=timeout, age=age):
                result = subprocess.run(["helm", "template", "test", str(ROOT / "charts/dolos"), "--kube-version", "1.34.0", "--set", "availability.enabled=true", "--set", "availability.referenceTipURLs[0]=http://relay/metrics", "--set-json", f"availability.requestTimeoutSeconds={timeout}", "--set", f"availability.maxCheckAgeSeconds={age}", *args], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode == 0, valid, result.stderr)


if __name__ == "__main__":
    unittest.main()
