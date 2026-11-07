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
            "API_JWKS_URL", "BURSA_API_JWKS_URL",
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


if __name__ == "__main__":
    unittest.main()
