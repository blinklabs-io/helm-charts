#!/usr/bin/env python3
"""Check optional Dingo API ports across Services and ingress policies."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml

CHART = Path(os.environ.get('DINGO_TEST_CHART', Path(__file__).resolve().parents[1] / 'charts/dingo'))
PORTS = {'utxorpc': 9090, 'blockfrost': 3000, 'mesh': 8080, 'kupo': 1442, 'bark': 50052, 'midnight': 50051}
ENVS = {'utxorpc': 'DINGO_UTXORPC_PORT', 'blockfrost': 'DINGO_BLOCKFROST_PORT', 'mesh': 'DINGO_MESH_PORT', 'kupo': 'DINGO_PLUGINS_API_KUPO_CONFIG_PORT', 'bark': 'DINGO_BARK_PORT', 'midnight': 'DINGO_MIDNIGHT_PORT'}

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
        for api, port in PORTS.items():
            for use_env in [False, True]:
                with self.subTest(api=api, use_env=use_env):
                    values = {'environment': {ENVS[api]: str(port)}} if use_env else {'service': {'ports': {api: port}}}
                    with self.assertRaises(subprocess.CalledProcessError) as error:
                        render(values)
                    self.assertIn(f'API port {api} requires service.private.enabled=true', error.exception.stderr)

    def test_unsupported_bind_setting_rejected(self):
        with self.assertRaises(subprocess.CalledProcessError) as error:
            render({'environment': {'DINGO_API_BIND_ADDR': '127.0.0.1'}})
        self.assertIn('use environment.CARDANO_BIND_ADDR', error.exception.stderr)
        render({'environment': {'DINGO_API_BIND_ADDR': None}})

    def test_private_ports_and_policy(self):
        for use_env in [False, True]:
            for peers in [[], [{'podSelector': {}}]]:
                with self.subTest(use_env=use_env, peers=peers):
                    values = {'service': {'private': {'enabled': True}, 'ports': PORTS},
                              'networkPolicy': {'enabled': False, 'privateIngressFrom': peers}}
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
                    if peers:
                        private = next(r for r in policy['spec']['ingress'] if r.get('from') == peers)
                        self.assertTrue(set(expected.values()) <= {p['port'] for p in private['ports']})
                    else:
                        self.assertEqual(policy['spec']['ingress'], [{'ports': [{'protocol': 'TCP', 'port': 3001}]}])

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
