# cardano-node

## Internal peer mesh

`topology.mesh.enabled` generates a topology for each pod before the node starts.
It requires `topology.enabled: true`.
Include every StatefulSet on the same Cardano network, including the current
release. Each peer uses its ordinal DNS name through its headless Service. The
current pod is excluded. Existing bootstrap, public, and local roots are retained.

```yaml
fullnameOverride: relay-a
replicaCount: 2
topology:
  enabled: true
  mesh:
    enabled: true
    statefulSets:
      - name: relay-a
        service: relay-a-headless
        namespace: nodes
        replicas: 2
        port: 3001
      - name: relay-b
        service: relay-b-headless
        namespace: nodes
        replicas: 2
        port: 3001
```

Use pod listener ports: headless DNS resolves directly to pods and does not
translate Service ports. `topology.mesh.clusterDomain` defaults to `cluster.local`.
The generator image must provide `/bin/sh` and `jq`; override
`topology.mesh.image` to use another compatible image.

Each internal peer gets a separate local-root group with valency 1,
`diffusionMode: InitiatorAndResponder`, `advertise: false`, and `trustable: true`.
Use this feature only for nodes you operate and trust. Configure both ends with
the same network membership to maintain active transaction diffusion in both
directions. Do not mix networks or rely on a load-balanced Service to reach
individual replicas.

Membership is explicit and does not query the Kubernetes API. Update membership
replica counts when scaling. The current release's count and headless Service
must match its chart values. Zero replicas omit that StatefulSet's peers.
Regenerate topology by restarting pods after membership changes, respecting the
chart's update strategy. The generated file is not updated by SIGHUP.
`topology.reloadable` cannot be combined with the mesh.

Install the example release in namespace `nodes` so its self-membership entry
matches the release namespace.

## Sync readiness and upgrades

```yaml
replicaCount: 2
minReadySeconds: 60
availability:
  enabled: true
  maxTipAgeSeconds: 600
  cliTimeoutSeconds: 10
  periodSeconds: 30
  failureThreshold: 2
  drainDelaySeconds: 60
  terminationGracePeriodSeconds: 180
podDisruptionBudget:
  enabled: true
  maxUnavailable: 1
```

The opt-in gate runs `cardano-cli latest query tip` against the local Unix socket.
It requires local ledger state: chain-sync fallback output cannot pass. It then
uses `query slot-number` and the node's era history to convert the freshness
cutoff into a slot and rejects an older tip, even if `syncProgress` rounds to
100%. This handles era transitions and custom slot lengths without depending
on another relay's readiness. UTC on the host must be correct. A network-wide
block gap longer than `maxTipAgeSeconds` makes all nodes unready; tune the bound
for the network. The cutoff is clamped to genesis start for new networks.

The image must supply cardano-cli with `latest query tip` and `latest query
slot-number`, jq, GNU date and GNU timeout. Query timeouts are bounded; the exec
probe allows enough time for both queries. No liveness probe restarts the node
during ledger replay or catch-up. The socat proxy must also accept connections
before the pod is ready.

For JSON node configs, `ShelleyGenesisFile` resolves relative to `CARDANO_CONFIG`.
Network selection comes from that genesis file, including custom network magic.
For YAML configs, set the absolute genesis path explicitly:

```yaml
cardano_config: /opt/cardano/config/prime-mainnet/configuration.yaml
availability:
  enabled: true
  shelleyGenesisPath: /opt/cardano/config/prime-mainnet/genesis/shelley/genesis.json
```

The ordinary Service routes only to ready pods. The headless Service publishes
unready pod addresses when gating is enabled so mesh peers can discover syncing
nodes without a readiness deadlock. Use it for peer discovery, not API routing:
direct pod/headless clients bypass the gate, including its N2C port. Custom API
Services must also exclude unready pods. StatefulSet selectors, names and PVC
identities are unchanged.

Both the node and socat keep serving during the native pre-stop sleep, allowing
endpoint propagation and finite requests to finish before SIGTERM. Lifecycle
sleep requires Kubernetes 1.30+ with the feature enabled (stable in 1.34); set
`drainDelaySeconds: 0` to omit it. Termination grace must exceed the sleep and
allow database shutdown. Long-lived protocol connections must reconnect;
readiness cannot move an established connection to another pod.

Keep healthy spare replicas on separate hosts. `minReadySeconds` holds the next
ordinal until its replacement has stayed ready. `updateStrategy` accepts both
the existing `RollingUpdate`/`OnDelete` strings and a full StatefulSet strategy:

```yaml
updateStrategy:
  type: RollingUpdate
  rollingUpdate:
    partition: 1
```

A disruption budget protects voluntary evictions, not StatefulSet updates. Its
default `maxUnavailable: 0` protects one replica; explicitly allow one when
operating redundant replicas. Configure Helm/Helmfile to wait for readiness and
serialize AZ releases; the chart does not serialize separate releases. Readiness
is not producer fencing and does not enable or disable forging.

For first adoption, existing pods still lack probes and drain hooks. Withdraw
legacy API backends and drain requests before their first replacement, preserving
healthy capacity elsewhere. Adding values does not retrofit old containers.
Preserve PVCs and confirm replacement nodes are ready before upgrading the
application image. A chart rollback does not reverse a database migration.

Availability is disabled by default. `minReadySeconds` defaults to 0; shutdown
and existing probe behavior are unchanged while it is disabled. Enabling it
defaults to 600-second tip freshness, 10-second CLI timeouts, a 30-second probe
interval, two failed probes before withdrawal, 30-second draining, and a
180-second termination grace. `shelleyGenesisPath` defaults to empty (JSON config
autodetection). Probe success admits the caught-up pod immediately;
`minReadySeconds` separately controls rollout stability.

## Validation

Install Python 3, Helm, jq and GNU coreutils, then:

```sh
python3 -m pip install -r scripts/requirements-cardano-tests.txt
python3 -B scripts/test-cardano-readiness.py
```

`python3 -B scripts/test-cardano-readiness-devnet.py` requires Docker and checks
the real probe against a disposable private devnet without network access.
`python3 -B scripts/test-cardano-readiness-rollout.py` also requires k3d and
kubectl. It uses a fixture to check client routing, peer DNS, connection draining,
ordered replacements, eviction protection and retained PVC identities in a
uniquely named disposable cluster. It never uses the current kubeconfig.
