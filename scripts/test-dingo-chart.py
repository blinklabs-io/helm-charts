#!/usr/bin/env python3
"""Assert the Dingo chart's rendered contracts."""

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


def dingo_env(values=None):
    container = one(render(values), "StatefulSet")["spec"]["template"]["spec"]["containers"][0]
    return container["env"]


def render_error(values):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "values.yaml"
        path.write_text(yaml.safe_dump(values))
        result = subprocess.run(
            ["helm", "template", "review", str(CHART), "-f", str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
    if result.returncode == 0:
        raise AssertionError("helm template unexpectedly succeeded")
    return result.stderr


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
                objects = render({"service": {"type": service_type, "annotations": {"legacy": "kept"},
                                              "private": {"enabled": True}},
                                  "environment": {"DINGO_UTXORPC_PORT": "9090"}})
                compat = next(o for o in objects if o["kind"] == "Service" and o["metadata"]["name"] == "review-dingo")
                self.assertEqual(compat["spec"]["type"], service_type)
                self.assertEqual(compat["metadata"]["annotations"]["legacy"], "kept")
                self.assertEqual([p["name"] for p in compat["spec"]["ports"]], ["relay"],
                                 "external compatibility Service must not publish private endpoints")

    def test_internal_compatibility_keeps_ports(self):
        objects = render({"environment": {"DINGO_UTXORPC_PORT": "9090"},
                          "service": {"private": {"enabled": True}}})
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
                          "service": {"private": {"enabled": True}},
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

    def bls_render(self, values=None, fixture=None):
        objects = render(values, fixture)
        pod = one(objects, "StatefulSet")["spec"]["template"]["spec"]
        init = next(c for c in pod["initContainers"] if c["name"] == "prepare-block-producer-keys")
        env = {e["name"]: e.get("value") for e in pod["containers"][0]["env"]}
        return objects, pod, init, env

    def run_init(self, init, names):
        with tempfile.TemporaryDirectory() as directory:
            source, dest = Path(directory) / "source", Path(directory) / "keys"
            source.mkdir()
            dest.mkdir()
            for name in names:
                (source / name).write_text("synthetic key")
                (source / name).chmod(0o640)
            script = init["args"][0].replace("/var/run/dingo-keys-source", str(source)).replace("/keys/", str(dest) + "/")
            subprocess.run(["/bin/sh", "-c", script], check=True)
            return {f.name: (f.stat().st_mode & 0o777) for f in dest.iterdir()}

    def test_bls_key_absent_by_default(self):
        for fixture in ("blockproducer-inline-keys-values.yaml", "blockproducer-existing-secret-values.yaml"):
            with self.subTest(fixture=fixture):
                _, pod, init, env = self.bls_render(fixture=fixture)
                self.assertNotIn("DINGO_LEIOS_VOTE_SIGNING_KEY_FILE", env)
                self.assertNotIn("bls.skey", init["args"][0])
                volumes = {v["name"]: v for v in pod["volumes"]}
                items = volumes["block-producer-keys-source"]["secret"].get("items", [])
                self.assertNotIn("bls.skey", [i["path"] for i in items])
                modes = self.run_init(init, ("kes.skey", "vrf.skey", "node.cert"))
                self.assertEqual(sorted(modes), ["kes.skey", "node.cert", "vrf.skey"])

    def test_bls_key_inline(self):
        bls = {"name": "bls.skey", "type": "BlsSigningKey_bls12-381-BLS-Signature-Minimal-Signature-Size", "description": "Leios BLS Vote Signing Key",
               "cborHex": "5820" + "ab" * 32}
        fixture = "blockproducer-inline-keys-values.yaml"
        base_keys = yaml.safe_load((CHART / "ci" / fixture).read_text())["blockProducer"]["keys"]
        objects, pod, init, env = self.bls_render({"blockProducer": {"enabled": True, "keys": base_keys + [bls]}})
        self.assertEqual(env["DINGO_LEIOS_VOTE_SIGNING_KEY_FILE"], "/keys/bls.skey")
        modes = self.run_init(init, ("kes.skey", "vrf.skey", "node.cert", "bls.skey"))
        self.assertEqual(modes["bls.skey"], 0o600)
        secret = next(o for o in objects if o["kind"] == "Secret")
        self.assertIn("bls.skey", secret["data"])
        sums = lambda o: one(o, "StatefulSet")["spec"]["template"]["metadata"]["annotations"]["checksum/keys"]
        self.assertNotEqual(sums(objects), sums(render({"blockProducer": {"enabled": True, "keys": base_keys}})))

    def test_bls_key_existing_secret(self):
        fixture = "blockproducer-existing-secret-custom-keys-values.yaml"
        _, pod, init, env = self.bls_render({"blockProducer": {"blsKey": "bls-skey"}}, fixture)
        self.assertEqual(env["DINGO_LEIOS_VOTE_SIGNING_KEY_FILE"], "/keys/bls.skey")
        volumes = {v["name"]: v for v in pod["volumes"]}
        items = {i["path"]: i["key"] for i in volumes["block-producer-keys-source"]["secret"]["items"]}
        self.assertEqual(items["bls.skey"], "bls-skey")
        modes = self.run_init(init, ("kes.skey", "vrf.skey", "node.cert", "bls.skey"))
        self.assertEqual(modes["bls.skey"], 0o600)

    def test_bls_key_existing_secret_unset(self):
        _, pod, init, env = self.bls_render(fixture="blockproducer-existing-secret-custom-keys-values.yaml")
        self.assertNotIn("DINGO_LEIOS_VOTE_SIGNING_KEY_FILE", env)
        volumes = {v["name"]: v for v in pod["volumes"]}
        self.assertEqual([i["path"] for i in volumes["block-producer-keys-source"]["secret"]["items"]],
                         ["kes.skey", "node.cert", "vrf.skey"])

    def test_listener_ports_rendered_from_service_ports(self):
        pod = one(render({"service": {"ports": {"relay": 3010, "private": 3011, "metrics": 12800}}}),
                  "StatefulSet")["spec"]["template"]["spec"]
        entries = pod["containers"][0]["env"]
        for name, port in (("CARDANO_PORT", "3010"), ("CARDANO_PRIVATE_PORT", "3011"), ("CARDANO_METRICS_PORT", "12800")):
            self.assertEqual([e["value"] for e in entries if e["name"] == name], [port])
        ports = {p["name"]: p["containerPort"] for p in pod["containers"][0]["ports"]}
        self.assertEqual((ports["relay"], ports["private"], ports["metrics"]), (3010, 3011, 12800))

    def test_user_set_listener_ports_not_duplicated(self):
        env = {"CARDANO_PORT": "4001", "CARDANO_PRIVATE_PORT": "4002", "CARDANO_METRICS_PORT": "14000"}
        pod = one(render({"environment": env, "service": {"ports": {"relay": 3010}}}),
                  "StatefulSet")["spec"]["template"]["spec"]
        entries = pod["containers"][0]["env"]
        for name, port in env.items():
            self.assertEqual([e["value"] for e in entries if e["name"] == name], [port])

    def test_api_bind_addr_defaults_and_override(self):
        default_entries = one(render(), "StatefulSet")["spec"]["template"]["spec"]["containers"][0]["env"]
        self.assertEqual([e["value"] for e in default_entries if e["name"] == "CARDANO_BIND_ADDR"], ["0.0.0.0"])
        override_entries = one(render({"environment": {"CARDANO_BIND_ADDR": "127.0.0.1"}}),
                               "StatefulSet")["spec"]["template"]["spec"]["containers"][0]["env"]
        self.assertEqual([e["value"] for e in override_entries if e["name"] == "CARDANO_BIND_ADDR"], ["127.0.0.1"])

    def test_observability_defaults_are_inert(self):
        entries = dingo_env()
        names = {entry["name"] for entry in entries}
        self.assertFalse(any(name.startswith("DINGO_TRACING_") for name in names))
        self.assertFalse(any(name.startswith("OTEL_") for name in names))

        configured = dingo_env({"environment": {"DINGO_TRACING_ENABLED": "true"}})
        self.assertEqual([entry["value"] for entry in configured
                          if entry["name"] == "DINGO_TRACING_ENABLED"], ["true"])

    def test_tracing_values_override_environment(self):
        values = {
            "observability": {
                "tracing": {
                    "enabled": True,
                    "endpoint": "https://collector.example/v1/traces",
                    "serviceName": "relay",
                    "sampleRatio": "0.25",
                    "alwaysSamplePools": [" pool1alpha ", "", "   ", "pool1beta"],
                },
                "resourceAttributes": {
                    "deployment.environment": "preview cluster",
                    "team": "core,protocol",
                },
            },
            "environment": {
                "DINGO_TRACING_ENABLED": "false",
                "DINGO_TRACING_ENDPOINT": "http://old-collector",
                "DINGO_TRACING_SERVICE_NAME": "old-name",
                "DINGO_TRACING_SAMPLE_RATIO": "1",
                "DINGO_TRACING_ALWAYS_SAMPLE_POOLS": "old-pool",
                "OTEL_RESOURCE_ATTRIBUTES": "old=value",
            },
        }
        entries = dingo_env(values)
        by_name = {entry["name"]: entry for entry in entries}
        for name in (
            "DINGO_TRACING_ENABLED",
            "DINGO_TRACING_ENDPOINT",
            "DINGO_TRACING_SERVICE_NAME",
            "DINGO_TRACING_SAMPLE_RATIO",
            "DINGO_TRACING_ALWAYS_SAMPLE_POOLS",
            "OTEL_RESOURCE_ATTRIBUTES",
        ):
            self.assertEqual([entry["name"] for entry in entries].count(name), 1)
        self.assertEqual(by_name["DINGO_TRACING_ENABLED"]["value"], "true")
        self.assertEqual(by_name["DINGO_TRACING_ENDPOINT"]["value"],
                         "https://collector.example/v1/traces")
        self.assertEqual(by_name["DINGO_TRACING_SERVICE_NAME"]["value"], "relay")
        self.assertEqual(by_name["DINGO_TRACING_SAMPLE_RATIO"]["value"], "0.25")
        self.assertEqual(by_name["DINGO_TRACING_ALWAYS_SAMPLE_POOLS"]["value"],
                         "pool1alpha,pool1beta")
        self.assertEqual(
            by_name["OTEL_RESOURCE_ATTRIBUTES"]["value"],
            "k8s.pod.name=$(DINGO_OTEL_POD_NAME),"
            "k8s.namespace.name=$(DINGO_OTEL_NAMESPACE_NAME),"
            "k8s.node.name=$(DINGO_OTEL_NODE_NAME),"
            "cardano.network.name=preview,"
            "deployment.environment=preview%20cluster,"
            "team=core%2Cprotocol",
        )
        self.assertEqual(by_name["DINGO_OTEL_POD_NAME"]["valueFrom"]["fieldRef"]["fieldPath"],
                         "metadata.name")
        self.assertEqual(by_name["DINGO_OTEL_NAMESPACE_NAME"]["valueFrom"]["fieldRef"]["fieldPath"],
                         "metadata.namespace")
        self.assertEqual(by_name["DINGO_OTEL_NODE_NAME"]["valueFrom"]["fieldRef"]["fieldPath"],
                         "spec.nodeName")

    def test_tracing_defaults_service_name_to_release_fullname(self):
        entries = dingo_env({"observability": {"tracing": {"enabled": True}}})
        self.assertEqual([entry["value"] for entry in entries
                          if entry["name"] == "DINGO_TRACING_SERVICE_NAME"], ["review-dingo"])

    def test_zero_sample_ratio_is_not_erased(self):
        entries = dingo_env({"observability": {"tracing": {"sampleRatio": 0}}})
        self.assertEqual([entry["value"] for entry in entries
                          if entry["name"] == "DINGO_TRACING_SAMPLE_RATIO"], ["0"])

    def test_otlp_values_override_environment(self):
        values = {
            "observability": {
                "otlp": {
                    "endpoint": "https://collector.example",
                    "protocol": "grpc",
                    "logs": True,
                    "metrics": True,
                    "headersSecret": {"name": "otel-headers", "key": "headers"},
                }
            },
            "environment": {
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://old-collector",
                "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
                "OTEL_EXPORTER_OTLP_HEADERS": "authorization=plaintext",
                "OTEL_LOGS_EXPORTER": "none",
                "OTEL_METRICS_EXPORTER": "none",
            },
        }
        entries = dingo_env(values)
        by_name = {entry["name"]: entry for entry in entries}
        for name in (
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "OTEL_EXPORTER_OTLP_PROTOCOL",
            "OTEL_EXPORTER_OTLP_HEADERS",
            "OTEL_LOGS_EXPORTER",
            "OTEL_METRICS_EXPORTER",
        ):
            self.assertEqual([entry["name"] for entry in entries].count(name), 1)
        self.assertEqual(by_name["OTEL_EXPORTER_OTLP_ENDPOINT"]["value"],
                         "https://collector.example")
        self.assertEqual(by_name["OTEL_EXPORTER_OTLP_PROTOCOL"]["value"], "grpc")
        self.assertEqual(by_name["OTEL_LOGS_EXPORTER"]["value"], "otlp")
        self.assertEqual(by_name["OTEL_METRICS_EXPORTER"]["value"], "otlp")
        secret_ref = by_name["OTEL_EXPORTER_OTLP_HEADERS"]["valueFrom"]["secretKeyRef"]
        self.assertEqual(secret_ref, {"name": "otel-headers", "key": "headers"})
        self.assertIn("OTEL_RESOURCE_ATTRIBUTES", by_name)

    def test_otlp_headers_require_complete_secret_reference(self):
        for headers, message in (
            ({"name": "otel-headers", "key": ""}, "headersSecret.key is required"),
            ({"name": "", "key": "headers"}, "headersSecret.name is required"),
        ):
            with self.subTest(headers=headers):
                values = {"observability": {"otlp": {"headersSecret": headers}}}
                self.assertIn(message, render_error(values))

    def test_resource_identity_attributes_cannot_be_overridden(self):
        values = {
            "observability": {
                "tracing": {"enabled": True},
                "resourceAttributes": {"k8s.pod.name": "forged-name"},
            }
        }
        self.assertIn("cannot override chart-managed attribute", render_error(values))


if __name__ == "__main__":
    unittest.main()
