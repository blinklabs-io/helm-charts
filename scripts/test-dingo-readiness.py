#!/usr/bin/env python3
"""Exercise the rendered Dingo readiness probe against changing live endpoints."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest

import yaml

CHART = Path(os.environ.get("DINGO_CHART_DIR", Path(__file__).resolve().parents[1] / "charts/dingo"))


def render(values, kube_version="1.35.0"):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "values.yaml"
        path.write_text(yaml.safe_dump(values))
        result = subprocess.run(
            ["helm", "template", "gate", str(CHART), "--kube-version", kube_version, "-f", str(path)],
            capture_output=True, text=True, check=True,
        )
        return [item for item in yaml.safe_load_all(result.stdout) if item]


def pod_spec(objects):
    return next(x for x in objects if x["kind"] == "StatefulSet")["spec"]["template"]["spec"]


def command(objects):
    return pod_spec(objects)["containers"][0]["readinessProbe"]["exec"]["command"]


@contextmanager
def endpoint(tls=False):
    state = {"/readyz": 200, "/api/v0/blocks/latest": 200, "delay": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(state["delay"])
            self.send_response(state.get(self.path, 404))
            self.end_headers()
            try:
                self.wfile.write(b'{"slot":100,"height":5}')
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    with tempfile.TemporaryDirectory() as directory:
        if tls:
            cert, key = Path(directory) / "cert.pem", Path(directory) / "key.pem"
            subprocess.run(
                ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                 "-subj", "/CN=api.example.test", "-keyout", str(key), "-out", str(cert)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(cert, key)
            server.socket = context.wrap_socket(server.socket, server_side=True)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield server.server_port, state
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)


def execute(objects):
    script = next(x["data"]["readiness.sh"] for x in objects if x["kind"] == "ConfigMap")
    args = command(objects)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "readiness.sh"
        path.write_text(script)
        return subprocess.run([args[0], str(path), *args[2:]], capture_output=True, timeout=8).returncode


class RenderTests(unittest.TestCase):
    def test_disabled_preserves_existing_workload(self):
        objects = render({})
        self.assertNotIn("readinessProbe", pod_spec(objects)["containers"][0])
        self.assertFalse(any(x["kind"] == "ConfigMap" and "readiness.sh" in x.get("data", {}) for x in objects))

    def test_core_gate_and_persistent_identity(self):
        base, gated = render({}), render({"availability": {"enabled": True}, "minReadySeconds": 20})
        old = next(x["spec"] for x in base if x["kind"] == "StatefulSet")
        new = next(x["spec"] for x in gated if x["kind"] == "StatefulSet")
        self.assertEqual(old["selector"], new["selector"])
        self.assertEqual(old["volumeClaimTemplates"], new["volumeClaimTemplates"])
        container = pod_spec(gated)["containers"][0]
        self.assertIn("readinessProbe", container)
        self.assertEqual(new["minReadySeconds"], 20)
        self.assertNotIn("livenessProbe", container)
        self.assertNotIn("startupProbe", container)
        self.assertEqual(command(gated)[2:], ["12799", "2", "0", "http", "3001"])
        self.assertEqual(container["lifecycle"]["preStop"]["sleep"]["seconds"], 30)
        self.assertEqual(pod_spec(gated)["terminationGracePeriodSeconds"], 180)
        for service in (x for x in gated if x["kind"] == "Service"):
            self.assertEqual(service["spec"].get("publishNotReadyAddresses", False), service["spec"].get("clusterIP") == "None")

    def test_api_ports_tls_and_environment_precedence(self):
        objects = render({
            "availability": {"enabled": True},
            "apiTLS": {"existingSecret": "api-cert"},
            "environment": {"DINGO_STORAGE_MODE": "api", "DINGO_API_TLS_MODE": "server", "DINGO_HEALTH_PORT": "12800",
                            "DINGO_HEALTH_READY_GAP_SLOTS": "60", "DINGO_BLOCKFROST_PORT": "3100",
                            "DINGO_UTXORPC_PORT": "0"},
            "service": {"private": {"enabled": True}, "ports": {"utxorpc": 9090, "blockfrost": 3000, "bark": 50052}},
        })
        args = command(objects)
        self.assertEqual(args[2:6], ["12800", "2", "3100", "https"])
        self.assertEqual(set(args[6:]), {"3001", "3002", "3100", "50052"})
        env = pod_spec(objects)["containers"][0]["env"]
        self.assertEqual([x["value"] for x in env if x["name"] == "DINGO_HEALTH_PORT"], ["12800"])
        self.assertEqual([x["value"] for x in env if x["name"] == "DINGO_HEALTH_READY_GAP_SLOTS"], ["60"])
        self.assertEqual(pod_spec(objects)["containers"][0]["readinessProbe"]["timeoutSeconds"], 14)

    def test_midnight_server_switch_controls_listener_check(self):
        values = {"availability": {"enabled": True}, "service": {"private": {"enabled": True}}, "environment": {"DINGO_STORAGE_MODE": "api", "DINGO_MIDNIGHT_PORT": "50051", "DINGO_MIDNIGHT_ENABLED": "false"}}
        for setting in (None, "false", False, "0", "f", "FALSE"):
            with self.subTest(setting=setting):
                if setting is not None:
                    values["environment"]["DINGO_MIDNIGHT_SERVER_ENABLED"] = setting
                self.assertNotIn("50051", command(render(values))[6:])
        for setting in ("true", True, "1", "t", "TRUE"):
            values["environment"]["DINGO_MIDNIGHT_SERVER_ENABLED"] = setting
            self.assertIn("50051", command(render(values))[6:])

    def test_explicit_tls_policy_and_scheme_override(self):
        base = {"availability": {"enabled": True}, "service": {"private": {"enabled": True}}, "environment": {"DINGO_STORAGE_MODE": "api", "DINGO_API_TLS_MODE": "server", "DINGO_BLOCKFROST_PORT": "3000"}}
        self.assertEqual(command(render(base))[5], "https")
        base["environment"]["DINGO_API_TLS_MODE"] = "disabled"
        base["apiTLS"] = {"existingSecret": "unused-cert"}
        self.assertEqual(command(render(base))[5], "http")
        base["availability"]["blockfrostScheme"] = "http"
        self.assertEqual(command(render(base))[5], "http")

    def test_invalid_configuration_fails_early(self):
        cases = [
            {"environment": {"DINGO_HEALTH_PORT": "0"}},
            {"environment": {"DINGO_HEALTH_READY_GAP_SLOTS": "0"}},
            {"availability": {"healthPort": 3001}},
            {"availability": {"healthPort": 12798}},
            {"availability": {"healthPort": 3000}, "environment": {"DINGO_STORAGE_MODE": "api", "DINGO_BLOCKFROST_PORT": "3000"}},
            {"availability": {"drainDelaySeconds": 180}},
            {"availability": {"requestTimeoutSeconds": 0}},
            {"availability": {"blockfrostScheme": "ftp"}},
            {"environment": {"DINGO_STORAGE_MODE": "api", "DINGO_BLOCKFROST_PORT": "bad"}},
        ]
        for values in cases:
            with self.subTest(values=values):
                values.setdefault("availability", {})["enabled"] = True
                values.setdefault("service", {})["private"] = {"enabled": True}
                with self.assertRaises(subprocess.CalledProcessError):
                    render(values)
        with self.assertRaises(subprocess.CalledProcessError):
            render({"availability": {"enabled": True}}, kube_version="1.29.0")
        objects = render({"availability": {"enabled": True, "drainDelaySeconds": 0}}, kube_version="1.29.0")
        self.assertNotIn("lifecycle", pod_spec(objects)["containers"][0])


class RuntimeTests(unittest.TestCase):
    def values(self, health, relay, api=None, tls=False, private=None):
        result = {"availability": {"enabled": True, "healthPort": health, "requestTimeoutSeconds": 1}, "service": {"ports": {"relay": relay}}}
        if api:
            result["service"]["private"] = {"enabled": True}
            result["service"]["ports"]["private"] = private
            result["environment"] = {"DINGO_STORAGE_MODE": "api", "DINGO_BLOCKFROST_PORT": str(api)}
        if tls:
            result["apiTLS"] = {"existingSecret": "api-cert"}
            result["environment"]["DINGO_API_TLS_MODE"] = "server"
        return result

    def test_starting_or_stale_node_is_not_ready_then_recovers(self):
        with endpoint() as (health, state), endpoint() as (relay, _):
            objects = render(self.values(health, relay))
            for status, expected in [(503, False), (200, True), (503, False)]:
                state["/readyz"] = status
                self.assertEqual(execute(objects) == 0, expected)

    def test_missing_listener_is_not_ready(self):
        with endpoint() as (health, _):
            with socket.socket() as reserved:
                reserved.bind(("127.0.0.1", 0))
                closed_port = reserved.getsockname()[1]
                objects = render(self.values(health, closed_port))
                self.assertNotEqual(execute(objects), 0)

    def test_open_api_with_failed_query_is_not_ready(self):
        with endpoint() as (health, _), endpoint() as (relay, _), endpoint() as (api, state), endpoint() as (private, _):
            objects = render(self.values(health, relay, api, private=private))
            state["/api/v0/blocks/latest"] = 503
            self.assertNotEqual(execute(objects), 0)
            state["/api/v0/blocks/latest"] = 200
            self.assertEqual(execute(objects), 0)

    def test_https_query_with_public_hostname_certificate(self):
        with endpoint() as (health, _), endpoint() as (relay, _), endpoint(tls=True) as (api, _), endpoint() as (private, _):
            self.assertEqual(execute(render(self.values(health, relay, api, tls=True, private=private))), 0)

    def test_hung_health_request_has_a_total_deadline(self):
        with endpoint() as (health, state), endpoint() as (relay, _):
            state["delay"] = 4
            objects = render(self.values(health, relay))
            started = time.monotonic()
            self.assertNotEqual(execute(objects), 0)
            self.assertLess(time.monotonic() - started, 2.5)


if __name__ == "__main__":
    unittest.main()
