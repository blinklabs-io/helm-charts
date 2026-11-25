#!/usr/bin/env python3
"""Assert the Bursa chart's render guards."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


CHART = Path(os.environ.get("BURSA_CHART_DIR", Path(__file__).resolve().parents[1] / "charts/bursa"))
FIXTURE = "signer-values.yaml"


def render(values=None, fixture=FIXTURE):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "values.yaml"
        path.write_text(yaml.safe_dump(values or {}))
        command = ["helm", "template", "review", str(CHART), "-f", str(CHART / "ci" / fixture), "-f", str(path)]
        return subprocess.run(command, text=True, capture_output=True)


def extra_env(*entries):
    base = [{"name": "SIGNER_WATERMARK_DSN", "valueFrom": {"secretKeyRef": {"name": "bursa-signer-watermark", "key": "dsn"}}}]
    return {"signer": {"extraEnv": base + list(entries)}}


class BursaSignerGuardTests(unittest.TestCase):
    def assertRenders(self, values=None):
        result = render(values)
        self.assertEqual(result.returncode, 0, result.stderr)

    def assertFails(self, values, message, fixture=FIXTURE):
        result = render(values, fixture)
        self.assertNotEqual(result.returncode, 0, "render succeeded")
        self.assertIn(message, result.stderr)

    def test_fixture_renders(self):
        self.assertRenders()

    def test_require_client_cert_from_value_from(self):
        for name in ("SIGNER_REQUIRE_CLIENT_CERT", "BURSA_SIGNER_SIGNER_REQUIRE_CLIENT_CERT"):
            with self.subTest(name=name):
                entry = {"name": name, "valueFrom": {"configMapKeyRef": {"name": "signer", "key": "require"}}}
                self.assertFails(extra_env(entry), "cannot come from valueFrom")

    def test_require_client_cert_true_values(self):
        for name in ("SIGNER_REQUIRE_CLIENT_CERT", "BURSA_SIGNER_SIGNER_REQUIRE_CLIENT_CERT"):
            for value in ("true", "TRUE", "1", "t"):
                with self.subTest(name=name, value=value, source="extraEnv"):
                    self.assertFails(extra_env({"name": name, "value": value}), "require_client_cert must be false")
                with self.subTest(name=name, value=value, source="environment"):
                    self.assertFails({"environment": {name: value}}, "require_client_cert must be false")

    def test_require_client_cert_false_renders(self):
        self.assertRenders(extra_env({"name": "SIGNER_REQUIRE_CLIENT_CERT", "value": "false"}))

    def test_require_client_cert_in_config(self):
        self.assertFails({"signer": {"config": {"signer": {"require_client_cert": True}}}}, "require_client_cert must be false")

    def test_secret_config_fields_rejected(self):
        cases = {
            "mnemonic": ({"mnemonic": "abandon"}, "MNEMONIC"),
            "api.jwt_secret": ({"api": {"jwt_secret": "s"}}, "API_JWT_SECRET"),
            "storage.dsn": ({"storage": {"dsn": "postgres://u:p@db/bursa"}}, "STORAGE_DSN"),
            "signer.jwt_secret": ({"signer": {"jwt_secret": "s"}}, "SIGNER_JWT_SECRET"),
            "signer.watermark.dsn": ({"signer": {"watermark": {"dsn": "postgres://u:p@db/wm"}}}, "dsn_env"),
        }
        for field, (config, hint) in cases.items():
            with self.subTest(field=field):
                result = render({"signer": {"config": config}})
                self.assertNotEqual(result.returncode, 0, "render succeeded")
                self.assertIn(f"signer.config.{field} must not be set", result.stderr)
                self.assertIn(hint, result.stderr)

    def test_secret_config_fields_empty_render(self):
        self.assertRenders({"signer": {"config": {
            "mnemonic": "",
            "api": {"jwt_secret": ""},
            "storage": {"dsn": ""},
            "signer": {"jwt_secret": "", "watermark": {"dsn": ""}},
        }}})

    def test_url_userinfo_in_config_rejected(self):
        url = "https://user:s3cr3tpw@hooks.example.com/authorize"
        backends = lambda field: {"signer": {"backends": [{"name": "cold", "type": "confidential-space", field: url}]}}
        cases = {
            "signer.policy_hook_url": ({"signer": {"policy_hook_url": url}}, "SIGNER_POLICY_HOOK_URL"),
            "signer.jwks_url": ({"signer": {"jwks_url": url}}, "SIGNER_JWKS_URL"),
            "api.jwks_url": ({"api": {"jwks_url": url}}, "API_JWKS_URL"),
            "signer.backends[0].jwks_url": (backends("jwks_url"), "no environment override"),
            "signer.backends[0].address": (backends("address"), "no environment override"),
        }
        for field, (config, hint) in cases.items():
            with self.subTest(field=field):
                result = render({"signer": {"config": config}})
                self.assertNotEqual(result.returncode, 0, "render succeeded")
                self.assertIn(f"signer.config.{field} must not carry URL userinfo", result.stderr)
                self.assertIn(hint, result.stderr)
                self.assertNotIn("s3cr3tpw", result.stderr)

    def test_url_userinfo_username_only_rejected(self):
        config = {"signer": {"policy_hook_url": "https://token@hooks.example.com/authorize"}}
        self.assertFails({"signer": {"config": config}}, "must not carry URL userinfo")

    def test_url_userinfo_in_env_value_rejected(self):
        url = "https://user:pass@keys.example.com/jwks"
        for name in (
            "SIGNER_POLICY_HOOK_URL", "BURSA_SIGNER_SIGNER_POLICY_HOOK_URL",
            "SIGNER_JWKS_URL", "BURSA_SIGNER_SIGNER_JWKS_URL",
            "API_JWKS_URL", "BURSA_API_API_JWKS_URL",
        ):
            with self.subTest(name=name, source="extraEnv"):
                self.assertFails(extra_env({"name": name, "value": url}), f"{name} must not carry URL userinfo")
            with self.subTest(name=name, source="environment"):
                self.assertFails({"environment": {name: url}}, f"{name} must not carry URL userinfo")
        with self.subTest(fixture="api-values.yaml"):
            self.assertFails({"environment": {"API_JWKS_URL": url}}, "API_JWKS_URL must not carry URL userinfo", "api-values.yaml")

    def test_urls_without_userinfo_render(self):
        url = "https://keys.example.com/jwks"
        self.assertRenders({"signer": {"config": {
            "api": {"jwks_url": url},
            "signer": {
                "policy_hook_url": url,
                "jwks_url": url,
                "backends": [{"name": "cold", "type": "confidential-space", "address": url, "jwks_url": url}],
            },
        }}})
        self.assertRenders({"environment": {"SIGNER_JWKS_URL": url}})
        ref = {"secretKeyRef": {"name": "bursa-signer-hook", "key": "url"}}
        self.assertRenders(extra_env({"name": "SIGNER_POLICY_HOOK_URL", "valueFrom": ref}))

    def test_watermark_type_from_value_from(self):
        entry = {"name": "BURSA_SIGNER_WATERMARK_TYPE", "valueFrom": {"configMapKeyRef": {"name": "signer", "key": "type"}}}
        self.assertFails(extra_env(entry), "cannot take BURSA_SIGNER_WATERMARK_TYPE")

    def test_pod_monitor_rejected(self):
        for fixture in ("api-values.yaml", "signer-values.yaml"):
            with self.subTest(fixture=fixture):
                self.assertFails({"podMonitor": {"enabled": True}}, "podMonitor.enabled is not supported", fixture)


class BursaKesAgentClientTests(unittest.TestCase):
    pin = "11" * 32

    def assertRenders(self, values=None):
        result = render(values, "kes-agent-values.yaml")
        self.assertEqual(result.returncode, 0, result.stderr)
        return [doc for doc in yaml.safe_load_all(result.stdout) if doc]

    def assertFails(self, values, message):
        result = render(values, "kes-agent-values.yaml")
        self.assertNotEqual(result.returncode, 0, "render succeeded")
        self.assertIn(message, result.stderr)

    def singleProfile(self, **fields):
        return {"kesAgent": {"config": {"kes_agent": {
            "profiles": [],
            "cold_vkey_hex": "00" * 32,
            "system_start": "2022-10-25T00:00:00Z",
            **fields,
        }}}}

    def test_profile_client_pins_render(self):
        docs = self.assertRenders()
        config = next(doc for doc in docs if doc["kind"] == "ConfigMap")
        agent = yaml.safe_load(config["data"]["config.yaml"])["kes_agent"]
        self.assertEqual(agent["profiles"][0]["sign_client_spki_sha256"], [self.pin])
        self.assertIn("attested_client_ca_file", agent)

    def test_remote_clients_require_verified_tls(self):
        self.assertFails({"kesAgent": {"tls": {"secretName": ""}}},
                         "needs kesAgent.tls.secretName")
        self.assertFails({"kesAgent": {"tls": {"clientCASecretName": ""}}},
                         "needs kesAgent.tls.clientCASecretName")
        self.assertFails({"kesAgent": {"tls": {"secretName": "", "clientCASecretName": ""},
                                      "config": {"kes_agent": {"attested_plaintext": True}}}},
                         "attested_plaintext cannot admit")

    def test_no_authorized_remote_role_is_rejected(self):
        self.assertFails({"kesAgent": {"config": {"kes_agent": {"profiles": [
            {"name": "local-only", "cold_vkey_hex": "00" * 32,
             "system_start": "2022-10-25T00:00:00Z"},
        ]}}}}, "authorization for at least one profile")
        self.assertFails(self.singleProfile(), "authorization for at least one profile")

    def test_control_only_and_unserved_profiles_render(self):
        self.assertRenders({"kesAgent": {"config": {"kes_agent": {"profiles": [
            {"name": "control-only", "cold_vkey_hex": "00" * 32,
             "system_start": "2022-10-25T00:00:00Z",
             "control_client_spki_sha256": [self.pin]},
            {"name": "local-only", "cold_vkey_hex": "22" * 32,
             "system_start": "2022-10-25T00:00:00Z"},
        ]}}}})

    def test_single_profile_config_roles_render(self):
        for role in ("sign", "control"):
            with self.subTest(role=role):
                self.assertRenders(self.singleProfile(**{f"{role}_client_spki_sha256": [self.pin]}))

    def test_single_profile_environment_roles_render(self):
        for role in ("SIGN", "CONTROL"):
            for prefix in ("", "BURSA_KESAGENT_"):
                name = f"{prefix}KESAGENT_{role}_CLIENT_SPKI_SHA256"
                with self.subTest(name=name, source="environment"):
                    values = self.singleProfile()
                    values["environment"] = {name: self.pin}
                    self.assertRenders(values)
                for entry in ({"name": name, "value": self.pin},
                              {"name": name, "valueFrom": {"secretKeyRef": {"name": "client-pins", "key": "pins"}}}):
                    with self.subTest(name=name, entry=entry):
                        values = self.singleProfile()
                        values["kesAgent"]["extraEnv"] = [entry]
                        self.assertRenders(values)

    def test_effective_environment_cannot_clear_the_last_role(self):
        values = self.singleProfile(sign_client_spki_sha256=[self.pin])
        values["environment"] = {"KESAGENT_SIGN_CLIENT_SPKI_SHA256": self.pin}
        values["kesAgent"]["extraEnv"] = [{"name": "BURSA_KESAGENT_KESAGENT_SIGN_CLIENT_SPKI_SHA256", "value": ""}]
        self.assertFails(values, "authorization for at least one profile")

    def test_empty_environment_map_value_is_not_emitted(self):
        values = self.singleProfile(sign_client_spki_sha256=[self.pin])
        name = "KESAGENT_SIGN_CLIENT_SPKI_SHA256"
        values["environment"] = {name: ""}
        docs = self.assertRenders(values)
        deployment = next(doc for doc in docs if doc["kind"] == "Deployment")
        env = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
        self.assertNotIn(name, [entry["name"] for entry in env])

    def test_unrecognized_environment_name_is_not_authorization(self):
        values = self.singleProfile()
        values["environment"] = {"BURSA_KESAGENT_SIGN_CLIENT_SPKI_SHA256": self.pin}
        self.assertFails(values, "authorization for at least one profile")

    def test_runtime_must_support_client_authorization(self):
        self.assertFails({"image": {"tag": "0.25.0"}}, "needs bursa 0.26.0 or newer")


FILE_FIXTURE = "kes-agent-file-values.yaml"
GUARD_DIR = "/var/lib/bursa/kes-agent"


def profile(**fields):
    base = {
        "name": "preview-pool",
        "cold_vkey_hex": "00" * 32,
        "system_start": "2022-10-25T00:00:00Z",
        "slots_per_kes_period": 129600,
        "sign_client_spki_sha256": ["11" * 32],
        "guard_file": f"{GUARD_DIR}/preview-pool.guard",
    }
    return {"kesAgent": {"config": {"kes_agent": {"profiles": [{**base, **fields}]}}}}


class BursaKesAgentFileStoreTests(unittest.TestCase):
    def assertRenders(self, values=None, fixture=FILE_FIXTURE):
        result = render(values, fixture)
        self.assertEqual(result.returncode, 0, result.stderr)
        return [doc for doc in yaml.safe_load_all(result.stdout) if doc]

    def assertFails(self, values, message, fixture=FILE_FIXTURE):
        result = render(values, fixture)
        self.assertNotEqual(result.returncode, 0, "render succeeded")
        self.assertIn(message, result.stderr)

    def test_file_store_renders(self):
        docs = self.assertRenders()
        deployment = next(doc for doc in docs if doc["kind"] == "Deployment")
        self.assertEqual(deployment["spec"]["replicas"], 1)
        self.assertEqual(deployment["spec"]["strategy"]["type"], "Recreate")
        volumes = deployment["spec"]["template"]["spec"]["volumes"]
        self.assertIn("persistentVolumeClaim", next(v for v in volumes if v["name"] == "guard"))
        config = next(doc for doc in docs if doc["kind"] == "ConfigMap")
        agent = yaml.safe_load(config["data"]["config.yaml"])["kes_agent"]
        self.assertEqual(agent["profiles"][0]["guard_file"], f"{GUARD_DIR}/preview-pool.guard")

    def test_default_store_type_is_file(self):
        self.assertRenders({"kesAgent": {"config": {"kes_agent": {"store": {"type": None}}}}})

    def test_single_replica_required(self):
        self.assertFails({"replicaCount": 2}, "replicaCount 1")

    def test_recreate_required(self):
        self.assertFails({"updateStrategy": {"type": "RollingUpdate"}}, "updateStrategy.type Recreate")

    def test_guard_file_required_per_profile(self):
        values = profile()
        del values["kesAgent"]["config"]["kes_agent"]["profiles"][0]["guard_file"]
        self.assertFails(values, "kes_agent.profiles[0].guard_file is required")

    def test_guard_file_must_be_absolute_and_clean(self):
        for path in ("guard.json", f"{GUARD_DIR}/../etc/guard", f"{GUARD_DIR}//guard"):
            with self.subTest(path=path):
                self.assertFails(profile(guard_file=path), "must be a clean absolute path")

    def test_guard_file_must_sit_under_a_mount(self):
        for path in ("/tmp/guard.json", f"{GUARD_DIR}-other/guard", GUARD_DIR):
            with self.subTest(path=path):
                self.assertFails(profile(guard_file=path), "must be under the mountPath")

    def test_guard_volume_must_be_a_pvc(self):
        volumes = (
            {"name": "guard", "emptyDir": {}},
            {"name": "other", "persistentVolumeClaim": {"claimName": "x"}},
        )
        for volume in volumes:
            with self.subTest(volume=volume):
                self.assertFails({"kesAgent": {"extraVolumes": [volume]}}, "persistentVolumeClaim")

    def test_guard_mount_must_be_writable(self):
        mount = {"name": "guard", "mountPath": GUARD_DIR, "readOnly": True}
        self.assertFails({"kesAgent": {"extraVolumeMounts": [mount]}}, "must not be readOnly")

    def test_deepest_mount_backs_the_guard(self):
        pvc = {"name": "guard", "persistentVolumeClaim": {"claimName": "x"}}
        scratch = {"name": "scratch", "emptyDir": {}}
        shadowed = {"kesAgent": {
            "extraVolumes": [pvc, scratch],
            "extraVolumeMounts": [{"name": "guard", "mountPath": "/var/lib/bursa"},
                                  {"name": "scratch", "mountPath": GUARD_DIR}],
        }}
        self.assertFails(shadowed, "persistentVolumeClaim")
        nested = {"kesAgent": {
            "extraVolumes": [scratch, pvc],
            "extraVolumeMounts": [{"name": "scratch", "mountPath": "/var/lib/bursa", "readOnly": True},
                                  {"name": "guard", "mountPath": GUARD_DIR}],
        }}
        self.assertRenders(nested)
        unclean = {"kesAgent": {
            "extraVolumes": [pvc, scratch],
            "extraVolumeMounts": [{"name": "guard", "mountPath": "/var/lib/bursa"},
                                  {"name": "scratch", "mountPath": "/var/lib/bursa/./kes-agent/"}],
        }}
        self.assertFails(unclean, "persistentVolumeClaim")

    def test_guard_volume_must_be_writable(self):
        pvc = {"name": "guard", "persistentVolumeClaim": {"claimName": "x", "readOnly": True}}
        self.assertFails({"kesAgent": {"extraVolumes": [pvc]}}, "must not be readOnly")

    def test_guard_under_a_chart_mount_refused(self):
        for root, guard in (("/run/bursa", "/run/bursa/kes-agent/pool.guard"),
                            ("/run", "/run/bursa/kes-agent-secrets/pool.guard"),
                            ("/etc/bursa", "/etc/bursa/kes-agent/client-ca/pool.guard")):
            with self.subTest(guard=guard):
                values = profile(guard_file=guard)
                values["kesAgent"]["extraVolumeMounts"] = [{"name": "guard", "mountPath": root}]
                self.assertFails(values, "is mounted by the chart")

    def test_single_profile_form_needs_top_level_guard_file(self):
        agent = {
            "profiles": None, "cold_vkey_hex": "00" * 32, "system_start": "2022-10-25T00:00:00Z",
            "slots_per_kes_period": 129600, "sign_client_spki_sha256": ["11" * 32],
        }
        single = {"kesAgent": {"config": {"kes_agent": agent}}}
        self.assertFails(single, "kes_agent.guard_file is required")
        agent["guard_file"] = f"{GUARD_DIR}/guard.json"
        self.assertRenders(single)
        agent["guard_file"] = "/tmp/guard.json"
        self.assertFails(single, "kes_agent.guard_file must be under the mountPath")

    def test_shared_key_settings_stay_refused(self):
        recipients = {"kesAgent": {"config": {"kes_agent": {"store": {"age_recipients": ["age1x"]}}}}}
        self.assertFails(recipients, "age_recipients needs kes_agent.store.type postgres")
        identity = {"kesAgent": {"ageIdentity": {"secretName": "age"}}}
        self.assertFails(identity, "needs kes_agent.store.type postgres")

    def test_dsn_env_refused_with_file_store(self):
        values = {"kesAgent": {"config": {"kes_agent": {"store": {"dsn_env": "KESAGENT_PG_DSN"}}}}}
        self.assertFails(values, "store.dsn_env needs kes_agent.store.type postgres")

    def test_unknown_store_type_refused(self):
        values = {"kesAgent": {"config": {"kes_agent": {"store": {"type": "s3"}}}}}
        self.assertFails(values, "kes_agent.store.type must be file or postgres")

    def test_postgres_path_unchanged(self):
        pg = "kes-agent-values.yaml"
        self.assertRenders(None, pg)
        self.assertRenders({"replicaCount": 3, "updateStrategy": {"type": "RollingUpdate"}}, pg)
        self.assertFails({"kesAgent": {"config": {"kes_agent": {"guard_file": "/x"}}}},
                         "kes_agent.guard_file must not be set with the postgres store", pg)
        self.assertFails({"kesAgent": {"config": {"kes_agent": {"profiles": [{"name": "p", "guard_file": "/x", "sign_client_spki_sha256": ["11" * 32]}]}}}},
                         "kes_agent.profiles[0].guard_file must not be set with the postgres store", pg)


class BursaKesAgentNetworkPolicyTests(unittest.TestCase):
    def docs(self, values, fixture):
        result = render(values, fixture)
        self.assertEqual(result.returncode, 0, result.stderr)
        return [doc for doc in yaml.safe_load_all(result.stdout) if doc]

    def policies(self, values, fixture):
        return [doc for doc in self.docs(values, fixture) if doc["kind"] == "NetworkPolicy"]

    def test_disabled_by_default(self):
        self.assertEqual(self.policies(None, "kes-agent-values.yaml"), [])

    def test_renders_when_enabled(self):
        peer = {"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "producers"}}}
        values = {"kesAgent": {"networkPolicy": {"enabled": True, "from": [peer]}}}
        (policy,) = self.policies(values, "kes-agent-values.yaml")
        self.assertEqual(policy["spec"]["policyTypes"], ["Ingress"])
        (rule,) = policy["spec"]["ingress"]
        self.assertEqual(rule["ports"], [{"port": "kes-agent", "protocol": "TCP"}])
        self.assertEqual(rule["from"], [peer])

    def test_metrics_port_follows_the_listener(self):
        scrape = {"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "monitoring"}}}
        values = {"kesAgent": {"networkPolicy": {"enabled": True, "metricsFrom": [scrape]}}}
        (policy,) = self.policies(values, "kes-agent-metrics-values.yaml")
        self.assertEqual(len(policy["spec"]["ingress"]), 2)
        rule = policy["spec"]["ingress"][1]
        self.assertEqual(rule["ports"], [{"port": "metrics", "protocol": "TCP"}])
        self.assertEqual(rule["from"], [scrape])
        (loopback,) = self.policies({"kesAgent": {"networkPolicy": {"enabled": True}}}, "kes-agent-values.yaml")
        self.assertEqual(len(loopback["spec"]["ingress"]), 1)

    def test_not_rendered_in_other_modes(self):
        values = {"kesAgent": {"networkPolicy": {"enabled": True}}}
        for fixture in ("signer-values.yaml", "api-values.yaml"):
            with self.subTest(fixture=fixture):
                names = [p["metadata"]["name"] for p in self.policies(values, fixture)]
                self.assertFalse([n for n in names if "kes-agent" in n], names)


class BursaApiServiceTests(unittest.TestCase):
    def documents(self, values):
        result = render(values, "api-values.yaml")
        self.assertEqual(result.returncode, 0, result.stderr)
        return {doc["kind"]: doc for doc in yaml.safe_load_all(result.stdout) if doc}

    def assertFails(self, values, message):
        result = render(values, "api-values.yaml")
        self.assertNotEqual(result.returncode, 0, "render succeeded")
        self.assertIn(message, result.stderr)

    def test_loopback_api_is_not_exposed_by_service(self):
        for address in (None, "127.0.0.1", "127.2.3.4", "::1", "[::1]", "localhost"):
            with self.subTest(address=address):
                values = {} if address is None else {"environment": {"API_LISTEN_ADDRESS": address}}
                docs = self.documents(values)
                container = docs["Deployment"]["spec"]["template"]["spec"]["containers"][0]
                self.assertIn({"name": "api", "containerPort": 8080}, container["ports"])
                self.assertNotIn("api", [port["name"] for port in docs["Service"]["spec"]["ports"]])

    def test_null_environment_uses_safe_api_defaults(self):
        docs = self.documents({"environment": None})
        container = docs["Deployment"]["spec"]["template"]["spec"]["containers"][0]
        self.assertIn({"name": "api", "containerPort": 8080}, container["ports"])
        self.assertNotIn("api", [port["name"] for port in docs["Service"]["spec"]["ports"]])

    def test_prefixed_api_environment_takes_precedence(self):
        docs = self.documents({
            "environment": {
                "API_LISTEN_ADDRESS": "127.0.0.1",
                "API_LISTEN_PORT": 8080,
                "BURSA_API_API_LISTEN_ADDRESS": "0.0.0.0",
                "BURSA_API_API_LISTEN_PORT": 9443,
                "BURSA_API_API_JWKS_URL": "https://issuer.example/jwks",
                "BURSA_API_API_JWT_AUDIENCE": "bursa-api",
                "BURSA_API_API_TLS_CERT_FILE": "/custom/cert",
                "BURSA_API_API_TLS_KEY_FILE": "/custom/key",
            },
        })
        container = docs["Deployment"]["spec"]["template"]["spec"]["containers"][0]
        self.assertIn({"name": "api", "containerPort": 9443}, container["ports"])
        self.assertIn("api", [port["name"] for port in docs["Service"]["spec"]["ports"]])

    def test_prefixed_public_and_empty_addresses_require_protection(self):
        self.assertFails({"environment": {"BURSA_API_API_LISTEN_ADDRESS": "0.0.0.0"}},
                         "requires api.auth.existingSecret")
        self.assertFails({"environment": {"API_LISTEN_ADDRESS": ""}},
                         "requires api.auth.existingSecret")

    def test_protected_api_uses_configured_port_and_secret_references(self):
        docs = self.documents({
            "environment": {"API_LISTEN_ADDRESS": "0.0.0.0", "API_LISTEN_PORT": 8443,
                            "API_JWT_AUDIENCE": "bursa-api"},
            "api": {"auth": {"existingSecret": "wallet-auth", "existingSecretKey": "jwt"},
                    "tls": {"secretName": "wallet-tls"}},
        })
        pod = docs["Deployment"]["spec"]["template"]["spec"]
        container = pod["containers"][0]
        env = {entry["name"]: entry for entry in container["env"]}
        self.assertEqual(pod["securityContext"]["runAsUser"], 65532)
        self.assertEqual(pod["securityContext"]["runAsGroup"], 65532)
        self.assertEqual(pod["securityContext"]["fsGroup"], 65532)
        self.assertEqual(env["API_JWT_SECRET"]["valueFrom"]["secretKeyRef"], {"name": "wallet-auth", "key": "jwt"})
        self.assertEqual(env["API_TLS_CERT_FILE"]["value"], "/etc/bursa/api/tls/tls.crt")
        self.assertEqual(env["API_TLS_KEY_FILE"]["value"], "/etc/bursa/api/tls/tls.key")
        self.assertIn({"name": "api", "containerPort": 8443}, container["ports"])
        self.assertIn({"name": "api-tls", "secret": {"secretName": "wallet-tls", "defaultMode": 0o440}}, pod["volumes"])
        self.assertIn({"name": "api", "port": 8080, "targetPort": "api"}, docs["Service"]["spec"]["ports"])

    def test_jwks_auth_exposes_the_api_without_a_literal_secret(self):
        docs = self.documents({
            "environment": {"API_LISTEN_ADDRESS": "::", "API_LISTEN_PORT": 9443,
                            "API_JWKS_URL": "https://issuer.example/jwks",
                            "API_JWT_AUDIENCE": "bursa-api"},
            "api": {"tls": {"secretName": "wallet-tls"}},
        })
        container = docs["Deployment"]["spec"]["template"]["spec"]["containers"][0]
        self.assertIn({"name": "api", "containerPort": 9443}, container["ports"])
        self.assertIn("api", [port["name"] for port in docs["Service"]["spec"]["ports"]])
        self.assertNotIn("API_JWT_SECRET", [entry["name"] for entry in container["env"]])

    def test_public_api_requires_authentication_and_tls(self):
        self.assertFails({"environment": {"API_LISTEN_ADDRESS": "0.0.0.0"}}, "requires api.auth.existingSecret")
        self.assertFails({"environment": {"API_LISTEN_ADDRESS": "127.999.999.999"}}, "requires api.auth.existingSecret")
        self.assertFails({"environment": {"API_LISTEN_ADDRESS": "0.0.0.0",
                                          "API_JWKS_URL": "https://issuer.example/jwks",
                                          "API_JWT_AUDIENCE": "bursa-api"}}, "requires api.tls.secretName")

    def test_literal_secret_environment_remains_compatible(self):
        docs = self.documents({"environment": {"API_LISTEN_ADDRESS": "0.0.0.0",
                                                "API_JWT_SECRET": "x" * 32,
                                                "API_JWT_AUDIENCE": "bursa-api"},
                               "api": {"tls": {"secretName": "wallet-tls"}}})
        env = docs["Deployment"]["spec"]["template"]["spec"]["containers"][0]["env"]
        self.assertIn({"name": "API_JWT_SECRET", "value": "x" * 32}, env)

    def test_new_secret_option_rejects_ambiguous_trust_sources(self):
        self.assertFails({"environment": {"API_JWT_SECRET": "x" * 32},
                          "api": {"auth": {"existingSecret": "wallet-auth"}}}, "cannot be combined")
        self.assertFails({"environment": {"API_JWKS_URL": "https://issuer.example/jwks"},
                          "api": {"auth": {"existingSecret": "wallet-auth"}}}, "mutually exclusive")
        self.assertFails({"environment": {"API_JWT_SECRET": "x" * 32,
                                          "API_JWKS_URL": "https://issuer.example/jwks"}},
                         "mutually exclusive")
        self.assertFails({"api": {"auth": {"existingSecret": "wallet-auth", "existingSecretKey": ""}}}, "existingSecretKey is required")

    def test_authentication_requires_audience(self):
        self.assertFails({"api": {"auth": {"existingSecret": "wallet-auth"}}},
                         "API_JWT_AUDIENCE is required")
        self.assertFails({"environment": {"API_JWKS_URL": "https://issuer.example/jwks"}},
                         "API_JWT_AUDIENCE is required")

    def test_tls_sources_must_be_complete_and_unambiguous(self):
        self.assertFails({"environment": {"API_TLS_CERT_FILE": "/custom/cert"}}, "must both be configured")
        self.assertFails({"environment": {"API_TLS_CERT_FILE": "/custom/cert", "API_TLS_KEY_FILE": "/custom/key"},
                          "api": {"tls": {"secretName": "wallet-tls"}}}, "cannot be combined")

    def test_invalid_api_port_is_rejected(self):
        for port in ("not-a-port", 0, "0", "65536"):
            with self.subTest(port=port):
                self.assertFails({"environment": {"API_LISTEN_PORT": port}}, "between 1 and 65535")


if __name__ == "__main__":
    unittest.main()
