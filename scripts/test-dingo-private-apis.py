#!/usr/bin/env python3
"""Check optional Dingo API ports across Services and ingress policies."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml

CHART = Path(os.environ.get('DINGO_TEST_CHART', Path(__file__).resolve().parents[1] / 'charts/dingo'))
PORTS = {'kupo': 1442, 'bark': 50052, 'midnight': 50051}
ENVS = {'kupo': 'DINGO_PLUGINS_API_KUPO_CONFIG_PORT', 'bark': 'DINGO_BARK_PORT', 'midnight': 'DINGO_MIDNIGHT_PORT'}

def render(values):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'values.yaml'
        path.write_text(yaml.safe_dump(values))
        result = subprocess.run(['helm', 'template', 'api', str(CHART), '-f', str(path)], capture_output=True, text=True, check=True)
        return [d for d in yaml.safe_load_all(result.stdout) if d]

class PrivateAPIs(unittest.TestCase):
    def test_disabled_by_default(self):
        for d in render({}):
            if d['kind'] == 'Service':
                self.assertFalse(set(PORTS) & {p['name'] for p in d['spec']['ports']})

    def test_configured_apis_require_private_opt_in(self):
        for use_env in [False, True]:
            with self.subTest(use_env=use_env):
                values = {'service': {'ports': PORTS}}
                if use_env:
                    values['environment'] = {ENVS[k]: str(v) for k, v in PORTS.items()}
                docs = render(values)
                for d in docs:
                    if d['kind'] == 'Service':
                        self.assertFalse(
                            set(PORTS) & {p['name'] for p in d['spec']['ports']},
                            'configured private APIs exposed without private-Service opt-in',
                        )

    def test_private_ports_and_policy(self):
        for use_env in [False, True]:
            with self.subTest(use_env=use_env):
                values = {'service': {'private': {'enabled': True}, 'ports': PORTS}, 'networkPolicy': {'privateIngressFrom': [{'podSelector': {}}]}}
                expected = dict(PORTS)
                if use_env:
                    expected = {k: v + 1 for k, v in PORTS.items()}
                    values['environment'] = {ENVS[k]: str(v) for k, v in expected.items()}
                docs = render(values)
                sts = next(d for d in docs if d['kind'] == 'StatefulSet')
                pod_ports = {p['name']: p['containerPort'] for p in sts['spec']['template']['spec']['containers'][0]['ports']}
                for k, v in expected.items():
                    self.assertEqual(pod_ports.get(k), v, f'{k} container port is missing or incorrect')
                for tier in ['private', 'compatibility']:
                    svc = next(d for d in docs if d['kind'] == 'Service' and d['metadata']['name'] == ('api-dingo-private' if tier == 'private' else 'api-dingo'))
                    ports = {p['name']: p['targetPort'] for p in svc['spec']['ports']}
                    for k, v in expected.items():
                        self.assertEqual(ports.get(k), v, f'{k} missing from {tier} Service')
                policy = next(d for d in docs if d['kind'] == 'NetworkPolicy')
                private = next(r for r in policy['spec']['ingress'] if r.get('from') == [{'podSelector': {}}])
                self.assertTrue(set(expected.values()) <= {p['port'] for p in private['ports']})

    def test_public_services_exclude_apis(self):
        for kind in ['LoadBalancer', 'NodePort']:
            docs = render({'service': {'relay': {'type': kind}, 'compatibility': {'type': kind}, 'private': {'enabled': True}, 'ports': PORTS}})
            for d in docs:
                if d['kind'] == 'Service' and d['spec']['type'] == kind:
                    self.assertEqual([p['name'] for p in d['spec']['ports']], ['relay'])
            policy = next(d for d in docs if d['kind'] == 'NetworkPolicy')
            allowed = {p['port'] for r in policy['spec']['ingress'] for p in r['ports']}
            self.assertFalse(set(PORTS.values()) & allowed)

if __name__ == '__main__':
    unittest.main()
