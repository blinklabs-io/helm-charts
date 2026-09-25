# dingo

Deploys [Dingo](https://github.com/blinklabs-io/dingo) — the Go implementation
of a Cardano blockchain node from Blink Labs — as a Kubernetes StatefulSet.

## TL;DR

```console
helm install my-dingo oci://ghcr.io/blinklabs-io/helm-charts/charts/dingo
```

## Introduction

The chart deploys a single-replica StatefulSet running `dingo` against the
Cardano `preview` network by default. Chain state is stored in a
PersistentVolumeClaim mounted at `CARDANO_DATABASE_PATH` (`/data`). An optional
init container bootstraps the database from a Mithril snapshot using dingo's
built-in Mithril client.

### Security defaults

- The container runs as the non-root `dingo` user baked into the upstream image
  (UID 1000 / GID 1000), pinned numerically via `podSecurityContext.runAsUser`
  / `runAsGroup` so kubelet can enforce `runAsNonRoot: true` without resolving
  the image's `/etc/passwd`. `fsGroup: 1000` makes the mounted PVC writable by
  the non-root user on first mount.
- The container security context drops all Linux capabilities, disallows
  privilege escalation, enables `readOnlyRootFilesystem: true`, and sets the
  `RuntimeDefault` seccomp profile. Writable scratch paths — `/tmp` and the
  `/ipc` socket directory — are provided as `emptyDir` mounts so the read-only
  root filesystem does not break the node.
- The ServiceAccount API token is not automounted
  (`automountServiceAccountToken: false`); dingo does not talk to the
  Kubernetes API.

### Service exposure

Service exposure is split into tiers so public relay traffic is separated from
the private node API and metrics:

- `<release>-dingo-relay` — the public P2P relay Service. This is the **only**
  Service intended for external exposure and it carries **only** the relay
  port. It defaults to `ClusterIP`.
- `<release>-dingo-private` — the node private API plus optional local APIs
  (UTxO RPC, Blockfrost, Mesh). `ClusterIP` only; never published externally.
- `<release>-dingo-metrics` — the Prometheus metrics endpoint. `ClusterIP`
  only.

For a safe upgrade, the chart also renders a backward-compatibility Service that
preserves the original `<release>-dingo` name:

- `<release>-dingo` — `ClusterIP`-only compatibility Service carrying the same
  ports the pre-split Service did (relay, private, metrics, and any enabled API
  ports). It exists so existing consumers, DNS references, and monitoring
  bindings that still target `<release>-dingo` keep working during migration.
  It never publishes the relay externally. Enabled by default; disable it once
  all consumers have moved to the tiered Services:

  ```yaml
  service:
    compatibility:
      enabled: false
  ```

To publish the relay on the public Cardano network, explicitly opt in:

```yaml
service:
  relay:
    type: LoadBalancer
    loadBalancerSourceRanges:
      - 0.0.0.0/0
```

The private API and metrics ports stay internal. To reach them from outside the
cluster, front them with an authenticated ingress/gateway, or restrict access
with a NetworkPolicy:

```yaml
networkPolicy:
  enabled: true
  privateIngressFrom:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: my-app-namespace
  metricsIngressFrom:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: monitoring
```

When enabled, the NetworkPolicy leaves the relay port open to all sources and
restricts the private API and metrics ports to the configured peers.

## Image pinning, provenance, and SBOM

The chart references the image by mutable tag by default. For reproducible,
tamper-evident deployments, pin the image by immutable digest:

```yaml
image:
  repository: ghcr.io/blinklabs-io/dingo
  digest: "sha256:<digest>"
```

When `image.digest` is set, the container is referenced as
`repository@sha256:...` and the mutable `tag` is ignored, so a deployment always
resolves to the exact image content.

Resolve the digest for a given tag:

```console
docker buildx imagetools inspect ghcr.io/blinklabs-io/dingo:0.70.6 \
  --format '{{ "{{" }}.Manifest.Digest{{ "}}" }}'
```

### Verify provenance and SBOM before pinning

Blink Labs publishes signed provenance (SLSA build attestations) and an SBOM
alongside the image. Verify them before recording a digest:

```console
# Keyless signature / provenance attestation (GitHub OIDC issuer)
cosign verify-attestation \
  --type slsaprovenance \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp '^https://github.com/blinklabs-io/dingo' \
  ghcr.io/blinklabs-io/dingo@sha256:<digest>

# Download and inspect the SBOM attestation
cosign download attestation \
  --predicate-type https://spdx.dev/Document \
  ghcr.io/blinklabs-io/dingo@sha256:<digest>
```

Only pin a digest that passes verification.

## Prerequisites

- Kubernetes 1.21+ (NetworkPolicy support if `networkPolicy.enabled=true`)
- Helm 3.8+ (for OCI registry support)
- A default StorageClass (or set `persistence.storageClass`)

## Values reference

See [`values.yaml`](values.yaml) for the full list of tunables. Key knobs:

| Key                             | Description                                               | Default                        |
| ------------------------------- | --------------------------------------------------------- | ------------------------------ |
| `image.repository`              | Image name                                                | `ghcr.io/blinklabs-io/dingo`   |
| `image.tag`                     | Image tag (used when `image.digest` is empty)             | `0.70.6`                       |
| `image.digest`                  | Immutable image digest (`sha256:...`); overrides tag      | `""`                           |
| `automountServiceAccountToken`  | Mount the SA token into the pod                           | `false`                        |
| `podSecurityContext`            | Pod-level security context                                | non-root, seccomp RuntimeDefault |
| `securityContext`               | Container security context                                | drop ALL, read-only rootfs     |
| `service.relay.type`            | Public relay Service type                                 | `ClusterIP`                    |
| `service.private.enabled`       | Render the private (ClusterIP) API Service                | `true`                         |
| `service.metrics.enabled`       | Render the metrics (ClusterIP) Service                    | `true`                         |
| `service.compatibility.enabled` | Render the `<release>-dingo` compatibility Service        | `true`                         |
| `networkPolicy.enabled`         | Restrict private/metrics ports to explicit peers          | `false`                        |
| `mithril.enabled`               | Bootstrap the DB from a Mithril snapshot                  | `true`                         |
| `persistence.size`              | PVC size                                                  | `60Gi`                         |
