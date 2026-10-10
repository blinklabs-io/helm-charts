#!/usr/bin/env python3
"""Exercise per-pod Cardano topology generation and its chart wiring."""

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


CHARTS = Path(__file__).resolve().parents[1] / 'charts'


def render(chart, values):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'values.yaml'
        path.write_text(yaml.safe_dump(values))
        result = subprocess.run(
            ['helm', 'template', 'relay', str(CHARTS / chart), '-n', 'nodes', '-f', str(path)],
            text=True, capture_output=True,
        )
    if result.returncode:
        raise ValueError(result.stderr)
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def values():
    return {
        'fullnameOverride': 'relay-a', 'replicaCount': 2,
        'service': {'ports': {'ntn': {'targetPort': 3002}}},
        'topology': {
            'enabled': True, 'bootstrapPeers': [{'address': 'bootstrap.example', 'port': 3001}],
            'localRoots': [{'accessPoints': [{'address': 'external.example', 'port': 9001}],
                            'advertise': False, 'trustable': False, 'valency': 1}],
            'publicRoots': [], 'peerSnapshotFile': 'peer-snapshot.json', 'useLedgerAfterSlot': 42,
            'mesh': {'enabled': True, 'clusterDomain': 'internal.example', 'statefulSets': [
                {'name': name, 'service': name + '-headless', 'namespace': 'nodes',
                 'replicas': count, 'port': 3002}
                for name, count in [('relay-a', 2), ('relay-b', 2), ('disabled', 0)]
            ]},
        },
    }


def generate(objects, pod):
    maps = {o['metadata']['name']: o['data'] for o in objects if o['kind'] == 'ConfigMap'}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for name in ('mesh', 'base-topology', 'generated'):
            (root / name).mkdir()
        mesh = maps['relay-a-mesh']
        (root / 'mesh/peers.json').write_text(mesh['peers.json'])
        (root / 'base-topology/topology.json').write_text(maps['relay-a-topology']['topology.json'])
        script = mesh['generate.sh']
        for name in ('mesh', 'base-topology', 'generated'):
            script = script.replace('/' + name + '/', str(root / name) + '/')
        env = dict(os.environ, POD_NAME=pod, POD_NAMESPACE='nodes',
                   HEADLESS_SERVICE=pod.rsplit('-', 1)[0] + '-headless', CLUSTER_DOMAIN='internal.example')
        subprocess.run(['sh', '-eu', '-c', script], env=env, check=True)
        return json.loads((root / 'generated/topology.json').read_text())


class MeshTests(unittest.TestCase):
    def test_full_mesh_and_external_preservation(self):
        for chart in ('cardano-node', 'cardano-node-leios'):
            with self.subTest(chart=chart):
                objects = render(chart, values())
                for pod in ('relay-a-0', 'relay-a-1', 'relay-b-0', 'relay-b-1'):
                    topology = generate(objects, pod)
                    self.assertEqual(topology['bootstrapPeers'], [{'address': 'bootstrap.example', 'port': 3001}])
                    self.assertEqual(topology['useLedgerAfterSlot'], 42)
                    self.assertEqual(topology['peerSnapshotFile'], 'peer-snapshot.json')
                    self.assertEqual(topology['localRoots'][0]['accessPoints'][0]['address'], 'external.example')
                    groups = topology['localRoots'][1:]
                    expected = {
                        f'{name}-{ordinal}.{name}-headless.nodes.svc.internal.example'
                        for name in ('relay-a', 'relay-b') for ordinal in range(2)
                        if f'{name}-{ordinal}' != pod
                    }
                    self.assertEqual({g['accessPoints'][0]['address'] for g in groups}, expected)
                    self.assertEqual(len(groups), 3)
                    for group in groups:
                        self.assertEqual(group['accessPoints'][0]['port'], 3002)
                        self.assertEqual(group['valency'], 1)
                        self.assertEqual(group['diffusionMode'], 'InitiatorAndResponder')
                        self.assertFalse(group['advertise'])
                pod_spec = next(o for o in objects if o['kind'] == 'StatefulSet')['spec']['template']['spec']
                init = pod_spec['initContainers'][0]
                self.assertEqual(init['name'], 'generate-topology')
                if chart == 'cardano-node-leios':
                    security = init['securityContext']
                    self.assertFalse(security['allowPrivilegeEscalation'])
                    self.assertEqual(security['capabilities']['drop'], ['ALL'])
                    self.assertEqual(security['seccompProfile']['type'], 'RuntimeDefault')
                self.assertEqual(init['command'], ['/bin/sh', '/mesh/generate.sh'])
                volumes = {v['name']: v for v in pod_spec['volumes']}
                self.assertIn('emptyDir', volumes['generated-topology'])
                node = pod_spec['containers'][0]
                mount = next(m for m in node['volumeMounts'] if m['name'] == 'generated-topology')
                self.assertEqual(mount['subPath'], 'topology.json')
                if chart == 'cardano-node':
                    env = {item['name']: item.get('value') for item in node['env']}
                    self.assertEqual(env['CARDANO_TOPOLOGY'], '/opt/cardano/config/preview/topology.json')
                else:
                    self.assertEqual(node['args'][node['args'].index('--topology') + 1], '/config/musashi/topology.json')

    def test_singleton_and_duplicate_membership(self):
        for chart in ('cardano-node', 'cardano-node-leios'):
            config = values()
            config['replicaCount'] = 1
            members = config['topology']['mesh']['statefulSets']
            members[0]['replicas'] = 1
            members[1]['replicas'] = 0
            members.append(copy.deepcopy(members[0]))
            self.assertEqual(len(generate(render(chart, config), 'relay-a-0')['localRoots']), 1)

    def test_invalid_membership(self):
        for chart in ('cardano-node', 'cardano-node-leios'):
            for key, value in [('replicas', -1), ('replicas', 1.5), ('port', 0), ('port', 65536),
                               ('port', 'bad'), ('port', 3001), ('service', 'wrong-headless'), ('replicas', 1),
                               ('namespace', 'other-network')]:
                with self.subTest(chart=chart, key=key, value=value):
                    config = values()
                    config['topology']['mesh']['statefulSets'][0][key] = value
                    with self.assertRaises(ValueError):
                        render(chart, config)
            config = values()
            config['topology']['mesh']['statefulSets'] = []
            with self.assertRaises(ValueError):
                render(chart, config)

    def test_default_and_incompatible_modes(self):
        for chart in ('cardano-node', 'cardano-node-leios'):
            objects = render(chart, {})
            self.assertFalse(any(o['metadata']['name'].endswith('-mesh') for o in objects))
        for override in ({'reloadable': True}, {'enabled': False}):
            config = values()
            config['topology'].update(override)
            with self.assertRaises(ValueError):
                render('cardano-node', config)
        config = values()
        config['mithril'] = {'enabled': True}
        objects = render('cardano-node', config)
        pod = next(o for o in objects if o['kind'] == 'StatefulSet')['spec']['template']['spec']
        self.assertEqual([c['name'] for c in pod['initContainers']], ['generate-topology', 'mithril-snapshot'])


if __name__ == '__main__':
    unittest.main()
