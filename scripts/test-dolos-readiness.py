import importlib.util
import json
import pathlib
import subprocess
import tempfile
import yaml
import time
import unittest
from unittest.mock import patch

path = pathlib.Path(__file__).resolve().parents[1] / "charts" / "dolos" / "files" / "readiness.py"
spec = importlib.util.spec_from_file_location("readiness", path)
readiness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(readiness)


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "requestTimeoutSeconds": 2,
            "maxTipAgeSeconds": 600,
            "maxSlotLag": 5,
            "minibfPort": 3001,
            "minikupoPort": 1442,
            "grpcPort": 50051,
            "referenceTipURLs": ["http://reference-a/metrics", "http://reference-b/metrics"],
            "maxCheckAgeSeconds": 30,
        }
        self.responses = {
            "http://127.0.0.1:3001/blocks/latest": json.dumps({"slot": 100, "time": 1000}),
            "http://127.0.0.1:1442/health": json.dumps({"connection_status": "connected", "most_recent_checkpoint": 100}),
            "http://reference-a/metrics": "cardano_node_metrics_slotNum_int 102\n",
            "http://reference-b/metrics": 'cardano_node_metrics_slotNum_int{network="mainnet"} 103\n',
        }
        self.connections = []

    def fetch(self, url, timeout):
        value = self.responses[url]
        if isinstance(value, Exception):
            raise value
        return value

    def run_check(self):
        readiness.check(self.config, self.fetch, lambda port, timeout: self.connections.append(port), lambda: 1100)

    def test_synced_apis(self):
        self.run_check()
        self.assertEqual(self.connections, [50051])

    def test_open_http_health_does_not_admit_stale_data(self):
        self.responses["http://127.0.0.1:3001/blocks/latest"] = json.dumps({"slot": 10, "time": 1000})
        with self.assertRaisesRegex(ValueError, "behind the reference"):
            self.run_check()

    def test_reference_failover(self):
        self.responses["http://reference-a/metrics"] = OSError("unreachable")
        self.run_check()
        self.responses["http://reference-b/metrics"] = OSError("unreachable")
        with self.assertRaisesRegex(ValueError, "no reference"):
            self.run_check()

    def test_newest_reference_wins(self):
        self.responses["http://reference-a/metrics"] = "cardano_node_metrics_slotNum_int 95\n"
        self.responses["http://reference-b/metrics"] = "cardano_node_metrics_slotNum_int 110\n"
        with self.assertRaisesRegex(ValueError, "behind the reference"):
            self.run_check()

    def test_stalled_reference_and_backend(self):
        self.responses["http://127.0.0.1:3001/blocks/latest"] = json.dumps({"slot": 100, "time": 100})
        with self.assertRaisesRegex(ValueError, "freshness"):
            self.run_check()

    def test_invalid_latest_block(self):
        for body in ["invalid", "{}", '{"slot": true, "time": 1000}']:
            with self.subTest(body=body):
                self.responses["http://127.0.0.1:3001/blocks/latest"] = body
                with self.assertRaises((ValueError, KeyError)):
                    self.run_check()

    def test_minikupo_not_ready(self):
        for health in [{}, {"connection_status": "disconnected", "most_recent_checkpoint": 100}, {"connection_status": "connected", "most_recent_checkpoint": 90}]:
            with self.subTest(health=health):
                self.responses["http://127.0.0.1:1442/health"] = json.dumps(health)
                with self.assertRaises(ValueError):
                    self.run_check()

    def test_optional_minikupo(self):
        self.config["minikupoPort"] = 0
        del self.responses["http://127.0.0.1:1442/health"]
        self.run_check()

    def test_grpc_unavailable(self):
        def disconnected(*args):
            raise OSError("closed")
        with self.assertRaises(OSError):
            readiness.check(self.config, self.fetch, disconnected, lambda: 1100)

    def test_cache_starts_closed_and_expires(self):
        monitor = readiness.Monitor(self.config)
        self.assertFalse(monitor.is_ready())
        monitor.ready = True
        monitor.checked_at = time.monotonic()
        self.assertTrue(monitor.is_ready())
        with patch.object(readiness.time, "monotonic", return_value=monitor.checked_at + 31):
            self.assertFalse(monitor.is_ready())



class ChartTests(unittest.TestCase):
    chart = pathlib.Path(__file__).resolve().parents[1] / "charts" / "dolos"

    def render(self, values, kube="1.35.0", ok=True):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "values.json"
            path.write_text(json.dumps(values))
            result = subprocess.run(["helm", "template", "api", str(self.chart), "--namespace", "dolos", "--kube-version", kube, "-f", str(path)], capture_output=True, text=True)
        if not ok:
            self.assertNotEqual(result.returncode, 0, result.stdout)
            return result.stderr
        self.assertEqual(result.returncode, 0, result.stderr)
        return [d for d in yaml.safe_load_all(result.stdout) if d]

    def enabled(self):
        return {"availability": {"enabled": True, "referenceTipURLs": ["http://relay:12798/metrics"]}, "replicaCount": 2, "minReadySeconds": 60, "podDisruptionBudget": {"enabled": True}}

    def test_default_compatibility(self):
        docs = self.render({})
        sts = next(d for d in docs if d["kind"] == "StatefulSet")
        self.assertEqual([c["name"] for c in sts["spec"]["template"]["spec"]["containers"]], ["dolos", "socat-ntc"])
        self.assertFalse(any(d["kind"] == "PodDisruptionBudget" for d in docs))
        self.assertNotIn("lifecycle", sts["spec"]["template"]["spec"]["containers"][0])

    def test_enabled_availability_and_identity(self):
        baseline = self.render({})
        docs = self.render(self.enabled())
        old = next(d for d in baseline if d["kind"] == "StatefulSet")
        sts = next(d for d in docs if d["kind"] == "StatefulSet")
        self.assertEqual(sts["spec"]["selector"], old["spec"]["selector"])
        self.assertEqual(sts["spec"]["volumeClaimTemplates"], old["spec"]["volumeClaimTemplates"])
        self.assertEqual(sts["spec"]["serviceName"], old["spec"]["serviceName"])
        self.assertEqual(sts["spec"]["minReadySeconds"], 60)
        self.assertEqual(sts["spec"]["template"]["metadata"]["labels"]["dolos.blinklabs.io/serving"], "true")
        pod = sts["spec"]["template"]["spec"]
        helper = next(c for c in pod["containers"] if c["name"] == "availability")
        self.assertIn("@sha256:", helper["image"])
        self.assertEqual(helper["readinessProbe"]["httpGet"], {"path": "/readyz", "port": "availability"})
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertTrue(helper["securityContext"]["readOnlyRootFilesystem"])
        self.assertEqual(pod["containers"][0]["lifecycle"]["preStop"], {"sleep": {"seconds": 30}})
        pdb = next(d for d in docs if d["kind"] == "PodDisruptionBudget")
        self.assertEqual(pdb["spec"]["selector"], sts["spec"]["selector"])
        self.assertEqual(pdb["spec"]["maxUnavailable"], 1)
        config = next(d for d in docs if d["kind"] == "ConfigMap")
        self.assertEqual(json.loads(config["data"]["readiness.json"])["minikupoPort"], 0)
        for d in docs:
            if d["kind"] == "Service":
                self.assertEqual(d["spec"]["selector"]["dolos.blinklabs.io/serving"], "true")
                self.assertNotIn("availability", [p["name"] for p in d["spec"]["ports"]])

    def test_custom_ports_and_partition(self):
        values = self.enabled()
        values.update({"ports": {"minibf": 8301, "grpc": 8500, "minikupo": 8442}, "service": {"ports": {"minikupo": 11442}}, "updateStrategy": {"type": "RollingUpdate", "rollingUpdate": {"partition": 1}}})
        docs = self.render(values)
        sts = next(d for d in docs if d["kind"] == "StatefulSet")
        self.assertEqual(sts["spec"]["updateStrategy"]["rollingUpdate"]["partition"], 1)
        config = json.loads(next(d for d in docs if d["kind"] == "ConfigMap")["data"]["readiness.json"])
        self.assertEqual((config["grpcPort"], config["minibfPort"], config["minikupoPort"]), (8500, 8301, 8442))

    def test_on_delete(self):
        values = self.enabled()
        values["updateStrategy"] = {"type": "OnDelete"}
        sts = next(d for d in self.render(values) if d["kind"] == "StatefulSet")
        self.assertEqual(sts["spec"]["updateStrategy"], {"type": "OnDelete"})

    def test_guards(self):
        for key, value, message in [("referenceTipURLs", [], "requires at least one"), ("drainDelaySeconds", 180, "must exceed"), ("maxCheckAgeSeconds", 5, "must exceed"), ("port", 50051, "must not conflict")]:
            with self.subTest(key=key):
                values = self.enabled()
                values["availability"][key] = value
                self.assertIn(message, self.render(values, ok=False))
        self.assertIn("1.30", self.render(self.enabled(), kube="1.29.0", ok=False))
        values = self.enabled()
        values["availability"]["drainDelaySeconds"] = 0
        self.render(values, kube="1.29.0")

    def test_invalid_limits(self):
        values = self.enabled()
        values["availability"]["requestTimeoutSeconds"] = 0
        self.render(values, ok=False)


if __name__ == "__main__":
    unittest.main()
