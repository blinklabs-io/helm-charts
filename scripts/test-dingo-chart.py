#!/usr/bin/env python3
"""Assert the Dingo chart's rendered security and migration contracts."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


CHART = Path(os.environ.get("DINGO_CHART_DIR", Path(__file__).resolve().parents[1] / "charts/dingo"))


def render(values=None, fixture=None):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "values.yaml"
        path.write_text(yaml.safe_dump(values or {}))
        command = ["helm", "template", "review", str(CHART)]
        if fixture:
            command.extend(["-f", str(CHART / "ci" / fixture)])
        command.extend(["-f", str(path)])
        output = subprocess.check_output(command, text=True)
        return [doc for doc in yaml.safe_load_all(output) if doc]


def one(objects, kind):
    return next(obj for obj in objects if obj["kind"] == kind)


class DingoChartTests(unittest.TestCase):
    def test_hardened_defaults(self):
        objects = render()
        pod = one(objects, "StatefulSet")["spec"]["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertFalse(one(objects, "ServiceAccount")["automountServiceAccountToken"])
        context = pod["securityContext"]
        for key in ("runAsUser", "runAsGroup", "fsGroup"):
            self.assertEqual(context[key], 1000)
        self.assertTrue(context["runAsNonRoot"])
        self.assertEqual(context["seccompProfile"]["type"], "RuntimeDefault")
        volumes = {v["name"]: v for v in pod["volumes"]}
        for container in pod["containers"] + pod["initContainers"]:
            security = container["securityContext"]
            self.assertTrue(security["readOnlyRootFilesystem"])
            self.assertTrue(security["runAsNonRoot"])
            self.assertFalse(security["allowPrivilegeEscalation"])
            self.assertEqual(security["capabilities"]["drop"], ["ALL"])
            mounts = {m["mountPath"]: m for m in container["volumeMounts"]}
            self.assertIn("emptyDir", volumes[mounts["/tmp"]["name"]])
        mounts = {m["mountPath"]: m for m in pod["containers"][0]["volumeMounts"]}
        self.assertIn("emptyDir", volumes[mounts["/ipc"]["name"]])
        for service in (obj for obj in objects if obj["kind"] == "Service"):
            self.assertEqual(service["spec"]["type"], "ClusterIP")

    def test_external_opt_in(self):
        objects = render(fixture="external-optin-values.yaml")
        services = {o["metadata"]["name"]: o for o in objects if o["kind"] == "Service"}
        self.assertNotIn("review-dingo", services)
        relay = services["review-dingo-relay"]["spec"]
        self.assertEqual(relay["type"], "LoadBalancer")
        self.assertEqual([p["name"] for p in relay["ports"]], ["relay"])
        self.assertEqual(relay["loadBalancerSourceRanges"], ["0.0.0.0/0"])
        for name in ("private", "metrics"):
            self.assertEqual(services[f"review-dingo-{name}"]["spec"]["type"], "ClusterIP")
        container = one(objects, "StatefulSet")["spec"]["template"]["spec"]["containers"][0]
        fixture = yaml.safe_load((CHART / "ci/external-optin-values.yaml").read_text())
        self.assertEqual(container["image"], "ghcr.io/blinklabs-io/dingo@" + fixture["image"]["digest"])

    def test_relay_node_port(self):
        for service_type in ("NodePort", "LoadBalancer", "ClusterIP"):
            for node_port in ("", 31001):
                with self.subTest(service_type=service_type, node_port=node_port):
                    objects = render({"service": {"relay": {"type": service_type, "nodePort": node_port}}})
                    relay = next(o for o in objects if o["kind"] == "Service" and
                                 o["metadata"]["name"] == "review-dingo-relay")
                    port = relay["spec"]["ports"][0]
                    if service_type in ("NodePort", "LoadBalancer") and node_port:
                        self.assertEqual(port.get("nodePort"), node_port)
                    else:
                        self.assertNotIn("nodePort", port)

    def test_private_listener_requires_opt_in(self):
        objects = render()
        self.assertFalse(any(o["kind"] == "Service" and o["metadata"]["name"] == "review-dingo-private"
                             for o in objects))
        container = one(objects, "StatefulSet")["spec"]["template"]["spec"]["containers"][0]
        self.assertNotIn("CARDANO_PRIVATE_BIND_ADDR", {e["name"] for e in container["env"]})

    def test_private_opt_in_sets_listener_and_policy(self):
        for bind in (None, "", "127.0.0.1"):
            with self.subTest(bind=bind):
                peers = [{"podSelector": {"matchLabels": {"access": "allowed"}}}]
                values = {"service": {"private": {"enabled": True}},
                          "networkPolicy": {"enabled": False, "privateIngressFrom": peers}}
                if bind is not None:
                    values["environment"] = {"CARDANO_PRIVATE_BIND_ADDR": bind}
                objects = render(values)
                container = one(objects, "StatefulSet")["spec"]["template"]["spec"]["containers"][0]
                addresses = [e["value"] for e in container["env"] if e["name"] == "CARDANO_PRIVATE_BIND_ADDR"]
                self.assertEqual(addresses, [bind or "0.0.0.0"])
                self.assertTrue(any(o["kind"] == "NetworkPolicy" for o in objects))
                rules = one(objects, "NetworkPolicy")["spec"]["ingress"]
                private_rule = next(r for r in rules if any(p["port"] == 3002 for p in r["ports"]))
                self.assertEqual(private_rule["from"], peers)
        objects = render({"service": {"private": {"enabled": True}}, "networkPolicy": {"enabled": False}})
        self.assertTrue(any(o["kind"] == "NetworkPolicy" for o in objects))
        self.assertEqual(one(objects, "NetworkPolicy")["spec"]["ingress"],
                         [{"ports": [{"protocol": "TCP", "port": 3001}]}])

    def test_legacy_external_service_is_relay_only(self):
        for service_type in ("LoadBalancer", "NodePort"):
            with self.subTest(service_type=service_type):
                objects = render({"service": {"type": service_type, "annotations": {"legacy": "kept"}},
                                  "environment": {"DINGO_UTXORPC_PORT": "9090"}})
                compat = next(o for o in objects if o["kind"] == "Service" and o["metadata"]["name"] == "review-dingo")
                self.assertEqual(compat["spec"]["type"], service_type)
                self.assertEqual(compat["metadata"]["annotations"]["legacy"], "kept")
                self.assertEqual([p["name"] for p in compat["spec"]["ports"]], ["relay"],
                                 "external compatibility Service must not publish private endpoints")

    def test_internal_compatibility_keeps_ports(self):
        objects = render({"environment": {"DINGO_UTXORPC_PORT": "9090"}})
        compat = next(o for o in objects if o["kind"] == "Service" and o["metadata"]["name"] == "review-dingo")
        self.assertEqual([p["name"] for p in compat["spec"]["ports"]], ["relay", "private", "metrics", "utxorpc"])

    def test_long_tiered_service_names(self):
        objects = render({"fullnameOverride": "d" * 63, "service": {"private": {"enabled": True}}})
        names = [o["metadata"]["name"] for o in objects if o["kind"] == "Service" and
                 o["metadata"].get("labels", {}).get("dingo.blinklabs.io/service-tier") in ("public", "private")]
        self.assertEqual(len(names), 3)
        self.assertEqual(len(set(names)), 3)
        for name in names:
            self.assertLessEqual(len(name), 63, "tiered Service name exceeds Kubernetes DNS label limit")

    def test_block_producer_stages_private_keys(self):
        for fixture in ("blockproducer-inline-keys-values.yaml", "blockproducer-existing-secret-values.yaml",
                        "blockproducer-existing-secret-custom-keys-values.yaml"):
            for mithril in (False, True):
                with self.subTest(fixture=fixture, mithril=mithril):
                    objects = render({"mithril": {"enabled": mithril}}, fixture)
                    pod = one(objects, "StatefulSet")["spec"]["template"]["spec"]
                    volumes = {v["name"]: v for v in pod["volumes"]}
                    destination = volumes["block-producer-keys"]
                    self.assertIn("emptyDir", destination, "keys must be staged outside the fsGroup-widened Secret")
                    self.assertEqual(destination["emptyDir"]["medium"], "Memory")
                    mounts = {m["name"]: m for m in pod["containers"][0]["volumeMounts"]}
                    self.assertNotIn("block-producer-keys-source", mounts)
                    self.assertTrue(mounts["block-producer-keys"]["readOnly"])
                    init = next(c for c in pod["initContainers"] if c["name"] == "prepare-block-producer-keys")
                    self.assertEqual(any(c["name"] == "mithril-sync" for c in pod["initContainers"]), mithril)
                    self.assertTrue(init["securityContext"]["readOnlyRootFilesystem"])
                    with tempfile.TemporaryDirectory() as directory:
                        source, dest = Path(directory) / "source", Path(directory) / "keys"
                        source.mkdir()
                        dest.mkdir()
                        for name in ("kes.skey", "vrf.skey", "node.cert"):
                            file = source / name
                            file.write_text("synthetic key")
                            file.chmod(0o640)
                        script = init["args"][0].replace("/var/run/dingo-keys-source", str(source)).replace("/keys/", str(dest) + "/")
                        subprocess.run(["/bin/sh", "-c", script], check=True)
                        for name in ("kes.skey", "vrf.skey", "node.cert"):
                            self.assertEqual((dest / name).stat().st_mode & 0o777, 0o600)
                            self.assertEqual((dest / name).read_text(), "synthetic key")

    def test_block_producer_defaults_deny_ingress(self):
        objects = render(fixture="blockproducer-existing-secret-values.yaml")
        self.assertTrue(any(o["kind"] == "NetworkPolicy" for o in objects),
                        "block producers must always render a NetworkPolicy")
        policy = one(objects, "NetworkPolicy")
        self.assertEqual(policy["spec"]["ingress"], [], "block producers must deny unsolicited ingress")

    def test_network_policy_uses_listener_ports(self):
        peers = [{"podSelector": {"matchLabels": {"access": "allowed"}}}]
        objects = render({"environment": {"CARDANO_PORT": "4001", "CARDANO_PRIVATE_PORT": "4002",
                                          "CARDANO_METRICS_PORT": "14000", "DINGO_UTXORPC_PORT": "9090",
                                          "DINGO_BLOCKFROST_PORT": "3000", "DINGO_MESH_PORT": "8080"},
                          "networkPolicy": {"enabled": True, "relayIngressFrom": peers,
                                            "privateIngressFrom": peers, "metricsIngressFrom": peers}})
        rules = one(objects, "NetworkPolicy")["spec"]["ingress"]
        self.assertEqual([[p["port"] for p in rule["ports"]] for rule in rules],
                         [[4001], [4002, 9090, 3000, 8080], [14000]])
        for rule in rules:
            self.assertEqual(rule.get("from"), peers, "ingress must require the configured peers")

    def test_empty_private_peers_deny_private_ports(self):
        rules = one(render({"networkPolicy": {"enabled": True}}), "NetworkPolicy")["spec"]["ingress"]
        self.assertEqual(rules, [{"ports": [{"protocol": "TCP", "port": 3001}]}])


if __name__ == "__main__":
    unittest.main()
