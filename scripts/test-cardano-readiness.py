#!/usr/bin/env python3
"""Exercise local ledger readiness and the chart's routing contract."""
import datetime
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHART = ROOT / "charts/cardano-node"
SCRIPT = CHART / "files/readiness.sh"


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="cardano-readiness-")
        self.addCleanup(self.directory.cleanup)
        self.root = pathlib.Path(self.directory.name)
        self.genesis = self.root / "shelley genesis.json"
        self.genesis.write_text(json.dumps({"networkId": "Testnet", "networkMagic": 42, "systemStart": "2000-01-01T00:00:00Z"}))
        self.config = self.root / "config.json"
        self.config.write_text(json.dumps({"ShelleyGenesisFile": self.genesis.name}))
        cli = self.root / "cardano-cli"
        cli.write_text(f"#!{sys.executable}\n" + '''import json,os,sys,time
with open(os.environ["CLI_LOG"], "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[3] == "tip":
    time.sleep(float(os.environ.get("CLI_DELAY", "0")))
    print(os.environ["CLI_TIP"])
else:
    if os.environ.get("CLI_SLOT_FAIL"):
        sys.exit(1)
    print(os.environ["CLI_MINIMUM"])
''')
        cli.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.root) + ":" + os.environ["PATH"], CARDANO_CONFIG=str(self.config), CARDANO_NODE_SOCKET_PATH="/ipc/node.socket", READINESS_CLI_TIMEOUT_SECONDS="1", READINESS_MAX_TIP_AGE_SECONDS="600", CLI_LOG=str(self.root / "cli.log"), CLI_MINIMUM="1000", CLI_TIP=json.dumps({"era": "Conway", "slot": 1000, "syncProgress": "100.00"}))

    def probe(self, ready=True):
        result = subprocess.run(["/bin/sh", str(SCRIPT)], env=self.env, capture_output=True, text=True, timeout=5)
        if ready:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return [json.loads(line) for line in (self.root / "cli.log").read_text().splitlines()] if (self.root / "cli.log").exists() else []

    def test_ready_local_state_and_custom_magic(self):
        calls = self.probe()
        self.assertEqual(calls[0][:5], ["latest", "query", "tip", "--testnet-magic", "42"])
        self.assertEqual(calls[1][2], "slot-number")
        self.assertNotIn("--utc-time", calls[1])
        cutoff = next(a for a in calls[1] if a.endswith("Z"))
        age = time.time() - datetime.datetime.fromisoformat(cutoff.replace("Z", "+00:00")).timestamp()
        self.assertTrue(598 <= age <= 603, age)

    def test_mainnet_uses_mainnet_flag(self):
        genesis = json.loads(self.genesis.read_text())
        genesis["networkId"] = "Mainnet"
        self.genesis.write_text(json.dumps(genesis))
        self.assertIn("--mainnet", self.probe()[0])

    def test_stale_tip_even_when_percentage_rounds_to_100(self):
        self.env["CLI_TIP"] = json.dumps({"era": "Conway", "slot": 999, "syncProgress": "100.00"})
        self.probe(False)

    def test_chain_sync_fallback_is_not_ledger_readiness(self):
        self.env["CLI_TIP"] = json.dumps({"slot": 1000, "block": 500})
        self.assertEqual(len(self.probe(False)), 1)

    def test_invalid_sync_progress_fails_closed(self):
        for progress in [None, True, [], "invalid", "-1", "101"]:
            with self.subTest(progress=progress):
                self.env["CLI_TIP"] = json.dumps({"era": "Conway", "slot": 1000, "syncProgress": progress})
                self.probe(False)

    def test_unavailable_era_history_fails_closed(self):
        self.env["CLI_SLOT_FAIL"] = "true"
        self.probe(False)

    def test_invalid_payloads_fail_closed(self):
        for tip in ["invalid", "null", '{"era":"Conway","slot":true,"syncProgress":"100.00"}', '{"era":"Conway","slot":-1,"syncProgress":"100.00"}', '{"era":"Conway","slot":1.5,"syncProgress":"100.00"}', '{"era":"Conway","slot":1e999,"syncProgress":"100.00"}']:
            with self.subTest(tip=tip):
                self.env["CLI_TIP"] = tip
                self.probe(False)

    def test_invalid_slot_cutoff_fails_closed(self):
        for minimum in ["", "null", "-1", "true", "1.5", "1e999"]:
            with self.subTest(minimum=minimum):
                self.env["CLI_MINIMUM"] = minimum
                self.probe(False)

    def test_query_timeout_is_bounded(self):
        self.env["CLI_DELAY"] = "10"
        started = time.monotonic()
        self.probe(False)
        self.assertLess(time.monotonic() - started, 3)

    def test_yaml_config_has_explicit_genesis_override(self):
        self.config.write_text("ShelleyGenesisFile: shelley genesis.json\n")
        self.env["READINESS_SHELLEY_GENESIS_PATH"] = str(self.genesis)
        self.probe()
        self.env.pop("READINESS_SHELLEY_GENESIS_PATH")
        self.probe(False)

    def test_new_network_cutoff_clamps_to_genesis(self):
        genesis = json.loads(self.genesis.read_text())
        genesis["systemStart"] = datetime.datetime.fromtimestamp(time.time() - 10, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.genesis.write_text(json.dumps(genesis))
        self.assertIn(genesis["systemStart"], self.probe()[1])


class ChartTests(unittest.TestCase):
    def render(self, values, kube="1.35.0", valid=True):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "values.json"
            path.write_text(json.dumps(values))
            result = subprocess.run(["helm", "template", "relay", str(CHART), "-n", "nodes", "--kube-version", kube, "-f", str(path)], capture_output=True, text=True)
        if not valid:
            self.assertNotEqual(result.returncode, 0)
            return []
        self.assertEqual(result.returncode, 0, result.stderr)
        return [d for d in yaml.safe_load_all(result.stdout) if d]

    def sts(self, docs):
        return next(d for d in docs if d["kind"] == "StatefulSet")

    def test_defaults_preserve_existing_behavior(self):
        docs = self.render({})
        pod = self.sts(docs)["spec"]["template"]["spec"]
        self.assertNotIn("terminationGracePeriodSeconds", pod)
        self.assertTrue(all("readinessProbe" not in c for c in pod["containers"]))
        self.assertFalse(any(d["kind"] == "PodDisruptionBudget" for d in docs))

    def test_identity_storage_and_routing(self):
        old = self.sts(self.render({}))
        docs = self.render({"availability": {"enabled": True}, "replicaCount": 2, "minReadySeconds": 60, "podDisruptionBudget": {"enabled": True, "maxUnavailable": 1}})
        sts = self.sts(docs)
        for field in ["selector", "volumeClaimTemplates", "serviceName"]:
            self.assertEqual(sts["spec"][field], old["spec"][field])
        self.assertEqual(sts["spec"]["minReadySeconds"], 60)
        pod = sts["spec"]["template"]["spec"]
        self.assertEqual(pod["terminationGracePeriodSeconds"], 180)
        for container in pod["containers"]:
            self.assertIn("readinessProbe", container)
            self.assertEqual(container["lifecycle"]["preStop"]["sleep"]["seconds"], 30)
        for service in [d for d in docs if d["kind"] == "Service"]:
            self.assertEqual(service["spec"].get("publishNotReadyAddresses", False), service["spec"].get("clusterIP") == "None")
        self.assertEqual(next(d for d in docs if d["kind"] == "PodDisruptionBudget")["spec"]["selector"], sts["spec"]["selector"])

    def test_custom_socket_proxy_port(self):
        docs = self.render({"availability": {"enabled": True}, "service": {"ports": {"socatNtc": {"targetPort": 30333}}}})
        socat = self.sts(docs)["spec"]["template"]["spec"]["containers"][1]
        self.assertEqual(socat["readinessProbe"]["tcpSocket"]["port"], 30333)

    def test_mesh_and_custom_network_configuration(self):
        for network in ["mainnet", "preprod", "preview", "prime-mainnet", "prime-testnet"]:
            with self.subTest(network=network):
                docs = self.render({"cardano_network": network, "cardano_config": "/custom/configuration.yaml", "availability": {"enabled": True, "shelleyGenesisPath": "/custom/genesis.json"}, "topology": {"enabled": True, "mesh": {"enabled": True, "statefulSets": [{"name": "relay-cardano-node", "service": "relay-cardano-node-headless", "namespace": "nodes", "replicas": 1, "port": 3001}]}}})
                pod = self.sts(docs)["spec"]["template"]["spec"]
                self.assertIn("generate-topology", [c["name"] for c in pod["initContainers"]])
                env = {e["name"]: e.get("value") for e in pod["containers"][0]["env"]}
                self.assertEqual(env["READINESS_SHELLEY_GENESIS_PATH"], "/custom/genesis.json")
                self.assertEqual(env["CARDANO_CONFIG"], "/custom/configuration.yaml")
                self.assertEqual(env["CARDANO_NETWORK"], network)

    def test_legacy_and_full_update_strategy(self):
        for strategy in ["OnDelete", {"type": "RollingUpdate", "rollingUpdate": {"partition": 1}}, None]:
            with self.subTest(strategy=strategy):
                sts = self.sts(self.render({"updateStrategy": strategy}))
                expected = strategy if isinstance(strategy, dict) else {"type": strategy or "OnDelete"}
                self.assertEqual(sts["spec"]["updateStrategy"], expected)

    def test_invalid_shutdown_and_probe_settings(self):
        for values, kube in [({"availability": {"enabled": True, "drainDelaySeconds": 180}}, "1.35.0"), ({"availability": {"enabled": True}}, "1.29.0"), ({"availability": {"cliTimeoutSeconds": 0}}, "1.35.0")]:
            self.render(values, kube, valid=False)
        docs = self.render({"availability": {"enabled": True, "drainDelaySeconds": 0}}, "1.29.0")
        self.assertNotIn("lifecycle", self.sts(docs)["spec"]["template"]["spec"]["containers"][0])


if __name__ == "__main__":
    unittest.main()
