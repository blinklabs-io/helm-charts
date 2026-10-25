import importlib.util
import json
import pathlib
import subprocess
import time
import tempfile
import threading
from urllib.request import urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
import unittest
from unittest.mock import patch

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("readiness", ROOT / "charts/ogmios/files/readiness.py")
readiness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(readiness)


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.config = dict(requestTimeoutSeconds=2, maxTipAgeSeconds=600,
                           maxSlotLag=60, referenceTipURLs=["http://a/metrics", "http://b/metrics"],
                           pollIntervalSeconds=5, maxCheckAgeSeconds=30)
        self.health = dict(connectionStatus="connected", lastKnownTip={"slot": 1000},
                           lastTipUpdate="2026-10-25T19:00:00.123456789Z")
        self.now = 1792954860
        self.references = {"http://a/metrics": 1020, "http://b/metrics": 1030}

    def fetch(self, url, timeout):
        if url.endswith("/health"):
            return json.dumps(self.health)
        slot = self.references[url]
        if isinstance(slot, Exception):
            raise slot
        return f'cardano_node_metrics_slotNum_int{{network="test"}} {slot}\n'

    def check(self):
        readiness.check(self.config, self.fetch, lambda: self.now)

    def test_v6_and_v7_health(self):
        self.check()
        self.health["lastTipUpdate"] = "2026-10-25T19:00:00+00:00"
        self.check()

    def test_disconnected_even_with_recent_tip(self):
        self.health["connectionStatus"] = "disconnected"
        with self.assertRaisesRegex(ValueError, "disconnected"):
            self.check()

    def test_stale_tip_with_agreeing_references(self):
        self.now += 601
        with self.assertRaisesRegex(ValueError, "freshness"):
            self.check()

    def test_newest_reference_and_lag_boundary(self):
        self.references["http://b/metrics"] = 1060
        self.check()
        self.references["http://b/metrics"] = 1061
        with self.assertRaisesRegex(ValueError, "behind"):
            self.check()

    def test_zero_lag(self):
        self.config["maxSlotLag"] = 0
        self.references = dict.fromkeys(self.references, 1000)
        self.check()
        self.references["http://b/metrics"] = 1001
        with self.assertRaises(ValueError):
            self.check()

    def test_reference_failover_then_total_outage(self):
        self.references["http://a/metrics"] = OSError()
        self.check()
        self.references["http://b/metrics"] = OSError()
        with self.assertRaisesRegex(ValueError, "no reference"):
            self.check()

    def test_invalid_health(self):
        for field, values in {"lastKnownTip": ["origin", {}, {"slot": True}, {"slot": -1}],
                              "lastTipUpdate": [None, "bad", "2026-10-25T19:00:00", "2026-10-26T19:00:00Z"]}.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    original = self.health[field]
                    self.health[field] = value
                    with self.assertRaises(ValueError):
                        self.check()
                    self.health[field] = original

    def test_invalid_reference(self):
        for sample in ("-1", "nan", "1e999", "junk"):
            with self.subTest(sample=sample):
                with self.assertRaises(ValueError):
                    readiness.reference_slot("cardano_node_metrics_slotNum_int " + sample)

    def test_monitor_starts_closed_and_expires_cached_success(self):
        monitor = readiness.Monitor(self.config)
        self.assertFalse(monitor.is_ready())
        with patch.object(readiness.time, "monotonic", return_value=100):
            monitor.ready, monitor.checked_at = True, 70
            self.assertTrue(monitor.is_ready())
            monitor.checked_at = 69
            self.assertFalse(monitor.is_ready())

    def test_backend_failure_does_not_fail_monitor_liveness(self):
        monitor = readiness.Monitor(self.config)
        monitor.checked_at = time.monotonic()
        with patch.object(monitor.worker, "is_alive", return_value=True):
            self.assertTrue(monitor.is_live())
            self.assertFalse(monitor.is_ready())


class HTTPTests(unittest.TestCase):
    setUp = HealthTests.setUp
    fetch = HealthTests.fetch
    def test_actual_probe_health_failure_and_recovery(self):
        config = dict(self.config, port=0, pollIntervalSeconds=0.02)
        original_check = readiness.check
        servers = []
        server_created = threading.Event()

        def server_factory(address, handler):
            server = ThreadingHTTPServer(("127.0.0.1", address[1]), handler)
            servers.append(server)
            server_created.set()
            return server

        def probe(path):
            try:
                with urlopen(f"http://127.0.0.1:{servers[0].server_port}/{path}", timeout=2) as response:
                    return response.status
            except HTTPError as error:
                return error.code

        def wait_status(path, expected):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if probe(path) == expected:
                    return
                time.sleep(0.02)
            self.fail(f"{path} did not reach HTTP {expected}")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as source:
            json.dump(config, source)
            source.flush()
            with patch.object(readiness.sys, "argv", ["readiness.py", source.name]), \
                 patch.object(readiness, "ThreadingHTTPServer", side_effect=server_factory), \
                 patch.object(readiness, "check", side_effect=lambda config: original_check(config, self.fetch, lambda: self.now)):
                worker = threading.Thread(target=readiness.main, daemon=True)
                worker.start()
                self.assertTrue(server_created.wait(5))
                try:
                    wait_status("readyz", 200)
                    self.references["http://b/metrics"] = 2000
                    wait_status("readyz", 503)
                    self.assertEqual(probe("healthz"), 200)
                    self.references["http://b/metrics"] = 1030
                    wait_status("readyz", 200)
                    self.health["connectionStatus"] = "disconnected"
                    wait_status("readyz", 503)
                    self.assertEqual(probe("healthz"), 200)
                finally:
                    servers[0].shutdown()
                    servers[0].server_close()
                    worker.join(5)


class ChartTests(unittest.TestCase):
    def render(self, *args, ok=True):
        result = subprocess.run(["helm", "template", "test", str(ROOT / "charts/ogmios"),
                                 "--kube-version", "1.34.0", *args], text=True, capture_output=True)
        self.assertEqual(result.returncode == 0, ok, result.stderr)
        return list(yaml.safe_load_all(result.stdout)) if ok else []

    def enabled(self, *args, **kwargs):
        return self.render("--set", "availability.enabled=true", "--set",
                           "availability.referenceTipURLs[0]=http://relay/metrics", *args, **kwargs)

    def deployment(self, objects):
        return next(o for o in objects if o["kind"] == "Deployment")

    def test_default_has_no_sidecar(self):
        dep = self.deployment(self.render())
        self.assertEqual(len(dep["spec"]["template"]["spec"]["containers"]), 2)

    def test_enabled_v6_and_v7(self):
        for tag in ("v6.14.0", "v7.0.0"):
            objects = self.enabled("--set", "image.tag=" + tag, "--set", "service.enabled=true")
            dep = self.deployment(objects)
            containers = dep["spec"]["template"]["spec"]["containers"]
            self.assertEqual(dep["spec"]["strategy"]["rollingUpdate"], dict(maxSurge=1, maxUnavailable=0))
            self.assertEqual(dep["spec"]["minReadySeconds"], 30)
            gate = containers[2]
            self.assertEqual(gate["readinessProbe"]["httpGet"]["path"], "/readyz")
            self.assertEqual(gate["livenessProbe"]["httpGet"]["path"], "/healthz")
            for container in containers[:2]:
                self.assertEqual(container["lifecycle"]["preStop"]["sleep"]["seconds"], 30)
            cm = next(o for o in objects if o["kind"] == "ConfigMap" and "readiness.py" in o["data"])
            compile(cm["data"]["readiness.py"], "readiness.py", "exec")
            self.assertEqual(json.loads(cm["data"]["readiness.json"])["maxSlotLag"], 60)
            svc = next(o for o in objects if o["kind"] == "Service")
            self.assertEqual(svc["spec"]["selector"], dep["spec"]["selector"]["matchLabels"])

    def test_invalid_values(self):
        self.render("--set", "availability.enabled=true", ok=False)
        for value in ("availability.maxSlotLag=-1", "availability.port=1337",
                      "availability.maxCheckAgeSeconds=5", "availability.drainDelaySeconds=90"):
            self.enabled("--set", value, ok=False)

    def test_recreate_and_zero_drain(self):
        dep = self.deployment(self.enabled("--set", "updateStrategy.type=Recreate",
                                          "--set", "availability.drainDelaySeconds=0"))
        self.assertEqual(dep["spec"]["strategy"], {"type": "Recreate"})
        self.assertNotIn("lifecycle", dep["spec"]["template"]["spec"]["containers"][0])


if __name__ == "__main__":
    unittest.main()
