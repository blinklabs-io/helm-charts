# handshake-node

Deploys [handshake-node](https://github.com/blinklabs-io/handshake-node) — the
Go implementation of a Handshake (HNS) blockchain full node from Blink Labs —
as a Kubernetes StatefulSet.

This chart is distinct from the [`hsd`](../hsd) chart, which packages the
JavaScript reference implementation from `handshake-org`.

## TL;DR

```console
helm install my-handshake-node oci://ghcr.io/blinklabs-io/helm-charts/charts/handshake-node
```

## Introduction

The chart deploys a single-replica StatefulSet running `handshake-node`
against the Handshake mainnet by default. Persistent state is stored in a
PersistentVolumeClaim mounted at `/home/handshake/.handshake-node`.

Security-relevant defaults:

- The container runs as the non-root `handshake` user baked into the upstream
  image with `runAsNonRoot: true`, all Linux capabilities dropped, no
  privilege escalation, `readOnlyRootFilesystem: true`, and the
  `RuntimeDefault` seccomp profile.
- The peer-to-peer Service is `ClusterIP` by default. Public exposure via
  `NodePort` or `LoadBalancer` is an explicit operator choice.
- The authenticated TLS RPC listener (port `12037`) is not exposed unless
  `rpc.enabled=true`. When enabled, the chart renders a `ClusterIP`-only
  Service that stays inside the cluster.
- RPC credentials are read from an existing Kubernetes Secret via
  `secretKeyRef` — they are never taken from `values.yaml` or a ConfigMap.
- The Prometheus metrics endpoint (`12039`) and Stratum server (`12040`) are
  disabled by default. When enabled they are kept on private `ClusterIP`
  Services.

## Prerequisites

- Kubernetes 1.27+
- Helm 3.8+ (for OCI registry support)
- A default StorageClass (or set `persistence.storageClass`)

## Installing the chart

```console
helm install my-handshake-node \
  oci://ghcr.io/blinklabs-io/helm-charts/charts/handshake-node \
  --namespace handshake --create-namespace
```

## Uninstalling the chart

```console
helm uninstall my-handshake-node --namespace handshake
```

The PVC is retained by default (`persistence.retention.whenDeleted=Retain`).
Delete it manually if you no longer need the chain data:

```console
kubectl -n handshake delete pvc data-my-handshake-node-0
```

## Persistence

The chart provisions a PVC via `volumeClaimTemplates`:

```yaml
persistence:
  enabled: true
  accessModes:
    - ReadWriteOnce
  size: 200Gi
  # storageClass: fast-ssd
  retention:
    whenDeleted: Retain
    whenScaled: Retain
```

To bind an existing claim instead, set `persistence.existingClaim`:

```yaml
persistence:
  enabled: true
  existingClaim: my-existing-handshake-pvc
```

## RPC Secret

RPC is disabled by default. To enable it, create a Kubernetes Secret with the
credentials, then reference it from `values.yaml`:

```console
kubectl -n handshake create secret generic handshake-node-rpc \
  --from-literal=rpcuser=hnsuser \
  --from-literal=rpcpass='replace-with-a-strong-password'
```

```yaml
rpc:
  enabled: true
  existingSecret: handshake-node-rpc
  userKey: rpcuser
  passwordKey: rpcpass
config:
  # REQUIRED when rpc.enabled=true. Comma-separated CIDR list the daemon
  # will accept RPC connections from. ClusterIP alone does not restrict
  # source pods, so set this to the Pod/Service CIDR of trusted clients
  # (or a NetworkPolicy-enforced range).
  rpcallowip: "10.0.0.0/8"
```

The chart injects the credentials as the `HANDSHAKE_NODE_RPCUSER` and
`HANDSHAKE_NODE_RPCPASS` environment variables via `secretKeyRef`. It also
renders a `ClusterIP`-only Service named `<release>-handshake-node-rpc` on
port `12037`. If you need remote clients to reach RPC, port-forward the
service or front it with an in-cluster gateway that terminates its own TLS —
do not change the Service type in this chart.

## Metrics

Enable the Prometheus endpoint (disabled by default):

```yaml
metrics:
  enabled: true
  # Optional. Leave unset ("") to let the chart derive the bind:
  #   0.0.0.0:<metrics.service.port> when allowPublic=true
  #   127.0.0.1:<metrics.service.port> when allowPublic=false
  # listen: ""
  allowPublic: true
  serviceMonitor:
    enabled: true
    interval: 30s
```

The metrics `Service` is always `ClusterIP` and is only rendered when
`metrics.allowPublic=true`; a loopback-only listener has no reachable
backend, so the chart suppresses the Service (and any `ServiceMonitor`) in
that case. Prometheus Operator users can turn on the `ServiceMonitor` with
`metrics.serviceMonitor.enabled=true`.

## Stratum

Stratum is disabled by default. To turn it on for internal miners:

```console
kubectl -n handshake create secret generic handshake-node-stratum \
  --from-literal=stratumuser=worker \
  --from-literal=stratumpass='replace-with-a-strong-password'
```

```yaml
stratum:
  enabled: true
  # Optional. Derived from stratum.service.port + allowPublic when unset.
  # listen: ""
  allowPublic: true
  miningAddress: hs1qyourhandshakeaddress
  auth:
    existingSecret: handshake-node-stratum
  service:
    enabled: true
    type: ClusterIP
```

Public exposure requires `stratum.allowPublic=true` and both
`miningAddress` and `auth.existingSecret` (validated at render time). The
Stratum Service is only rendered when `stratum.allowPublic=true` because
loopback listeners cannot be reached through a ClusterIP.

## Service exposure

The peer-to-peer Service defaults to `ClusterIP`. To advertise the node on the
public Handshake network you must explicitly opt in:

```yaml
service:
  p2p:
    type: LoadBalancer
    port: 12038
    loadBalancerSourceRanges:
      - 0.0.0.0/0
```

Use `NodePort` if you route through an external load balancer:

```yaml
service:
  p2p:
    type: NodePort
    port: 12038
    nodePort: 32038
```

## Mainnet operations examples

Full mainnet node with private RPC, metrics enabled, and a beefier PVC:

```yaml
network: main
image:
  tag: "0.1.1-rc1"

persistence:
  size: 400Gi
  storageClass: fast-ssd

rpc:
  enabled: true
  existingSecret: handshake-node-rpc

metrics:
  enabled: true
  serviceMonitor:
    enabled: true

resources:
  requests:
    cpu: 1
    memory: 2Gi
  limits:
    cpu: 4
    memory: 8Gi

topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: ScheduleAnyway
    labelSelector:
      matchLabels:
        app.kubernetes.io/name: handshake-node
```

## Upgrade

```console
helm upgrade my-handshake-node \
  oci://ghcr.io/blinklabs-io/helm-charts/charts/handshake-node \
  --namespace handshake \
  --reuse-values \
  --version <new-chart-version>
```

The PVC survives an upgrade because retention defaults to `Retain`. Chart
upgrades that only change the container image trigger a rolling restart of
the single StatefulSet pod.

## Values reference

See [`values.yaml`](values.yaml) for the full list of tunables. Key knobs:

| Key                              | Description                                                  | Default                              |
| -------------------------------- | ------------------------------------------------------------ | ------------------------------------ |
| `image.repository`               | Image name                                                   | `ghcr.io/blinklabs-io/handshake-node` |
| `image.tag`                      | Image tag (never `latest`)                                   | `0.1.1-rc1`                          |
| `network`                        | Handshake network: `main`, `regtest`, `simnet`, `testnet`    | `main`                               |
| `persistence.size`               | PVC size                                                     | `200Gi`                              |
| `persistence.storageClass`       | StorageClass name                                            | cluster default                      |
| `rpc.enabled`                    | Enable authenticated RPC                                     | `false`                              |
| `rpc.existingSecret`             | Name of Secret with `rpcuser`/`rpcpass`                      | `""`                                 |
| `metrics.enabled`                | Enable Prometheus endpoint                                   | `false`                              |
| `metrics.serviceMonitor.enabled` | Create ServiceMonitor                                        | `false`                              |
| `stratum.enabled`                | Enable Stratum server                                        | `false`                              |
| `service.p2p.type`               | P2P Service type                                             | `ClusterIP`                          |
| `podSecurityContext`             | Pod-level security context                                   | non-root, seccomp `RuntimeDefault`   |
| `securityContext`                | Container security context                                   | drop ALL, no privilege escalation    |
| `resources`                      | CPU/memory requests/limits                                   | `{}`                                 |
