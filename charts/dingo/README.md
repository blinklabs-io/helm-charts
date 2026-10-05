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
- Block-producer keys are copied by a non-root init container into a
  memory-backed volume with mode `0600`, then mounted read-only by Dingo.
  The projected Secret is visible only to that init container: `fsGroup` can
  widen Secret file permissions, and Dingo rejects group-readable signing keys.
  Keys are staged once per Pod. After updating an external Secret, replace the
  Pod: restarting only the process or container keeps the previous staged keys.
  Set `blockProducer.podAnnotations` to a credential revision that changes with
  each rotation to trigger replacement; inline keys already have a checksum.
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
  Disabled by default, matching the operator's node-to-client opt-in.
- `<release>-dingo-metrics` — the Prometheus metrics endpoint. `ClusterIP`
  only.

For a safe upgrade, the chart also renders a backward-compatibility Service that
preserves the original `<release>-dingo` name:

- `<release>-dingo` — compatibility Service carrying relay, private, metrics,
  and enabled API ports when its type is `ClusterIP`. For `LoadBalancer` and
  `NodePort`, it carries **only relay** so private endpoints stay internal. It
  exists so existing consumers, DNS references, and monitoring bindings that
  still target `<release>-dingo` keep working during migration. Enabled by
  default.

  To avoid dropping external reachability on upgrade, it inherits the legacy
  `service.type` (and `service.sessionAffinity` / `service.annotations`). A
  release that previously set `service.type: LoadBalancer` keeps the same
  Service name — and therefore the same cloud load balancer and external
  address — after upgrade. Before upgrading an externally exposed legacy
  Service, enable private access with its authorized peers and move private API
  and metrics clients to the internal `-private`
  and `-metrics` Services or an authenticated gateway. External access to
  those ports is intentionally removed. Fresh installs default to `ClusterIP`.

  To complete the hardened split, move consumers to the tiered
  relay/private/metrics Services (publish the relay via `service.relay.type`),
  then disable the compatibility Service:

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
cluster, front them with an authenticated ingress/gateway. Before enabling
`service.private.enabled`, configure authorized peers and ensure the CNI
enforces NetworkPolicy. The opt-in sets `CARDANO_PRIVATE_BIND_ADDR` to
`0.0.0.0` unless explicitly overridden, and always renders a NetworkPolicy,
even if `networkPolicy.enabled` is false. Empty peer lists deny private access:

```yaml
service:
  private:
    enabled: true
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

For relay nodes, enabling NetworkPolicy leaves P2P open to all sources unless
`networkPolicy.relayIngressFrom` restricts it. Private API and metrics ports
are allowed only from their configured peers; empty peer lists deny ingress.

Block producers always get a NetworkPolicy, even when `networkPolicy.enabled`
is false. All ingress is denied until explicitly granted. Before upgrading a
block producer, grant its relays access with `relayIngressFrom` and its
monitoring clients access with `metricsIngressFrom`. For example:

```yaml
networkPolicy:
  relayIngressFrom:
    - podSelector:
        matchLabels:
          app.kubernetes.io/instance: my-relay
  metricsIngressFrom:
    - namespaceSelector:
        matchLabels:
          dingo.blinklabs.io/metrics: allowed
      podSelector:
        matchLabels:
          dingo.blinklabs.io/metrics: allowed
```

The metrics example matches the operator's explicit grant: label both the
monitoring pod and its namespace. Metrics access does not grant private API
access. Egress remains open for DNS, Cardano peers, and Mithril.

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
docker buildx imagetools inspect ghcr.io/blinklabs-io/dingo:0.73.2 \
  --format '{{.Manifest.Digest}}'
```

### Verify provenance and SBOM before pinning

The [image release workflow](https://github.com/blinklabs-io/dingo/blob/main/.github/workflows/publish.yml)
creates GitHub build provenance attestations for architecture-specific images.
Resolve the digest for the architecture you will run (for example, the
`0.73.2-amd64` or `0.73.2-arm64` tag) and verify it before pinning:

```console
gh attestation verify oci://ghcr.io/blinklabs-io/dingo@sha256:<digest> \
  --repo blinklabs-io/dingo \
  --signer-workflow blinklabs-io/dingo/.github/workflows/publish.yml
```

Do not assume the combined multi-architecture index has its own attestation;
verify each selected architecture's image. The release workflow does not
currently publish a signed SBOM. If your deployment requires an SBOM, obtain
one tied to the same digest and verify its issuer before pinning. When an SPDX
SBOM attestation is available, use
[GitHub CLI attestation verification](https://cli.github.com/manual/gh_attestation_verify)
to verify and inspect it:

```console
gh attestation verify oci://ghcr.io/blinklabs-io/dingo@sha256:<digest> \
  --repo blinklabs-io/dingo \
  --signer-workflow blinklabs-io/dingo/.github/workflows/publish.yml \
  --predicate-type https://spdx.dev/Document/v2.3 \
  --format json --jq '.[].verificationResult.statement.predicate'
```

Only pin a digest after the required verification succeeds. Missing provenance
or SBOM attestations do not count as successful verification.

## Prerequisites

- Kubernetes 1.21+ (NetworkPolicy support if `networkPolicy.enabled=true`)
- Helm 3.8+ (for OCI registry support)
- A default StorageClass (or set `persistence.storageClass`)

## Values reference

See [`values.yaml`](values.yaml) for the full list of tunables. Key knobs:

| Key                             | Description                                               | Default                        |
| ------------------------------- | --------------------------------------------------------- | ------------------------------ |
| `image.repository`              | Image name                                                | `ghcr.io/blinklabs-io/dingo`   |
| `image.tag`                     | Image tag (used when `image.digest` is empty)             | `0.73.2`                       |
| `image.digest`                  | Immutable image digest (`sha256:...`); overrides tag      | `""`                           |
| `automountServiceAccountToken`  | Mount the SA token into the pod                           | `false`                        |
| `podSecurityContext`            | Pod-level security context                                | non-root, seccomp RuntimeDefault |
| `securityContext`               | Container security context                                | drop ALL, read-only rootfs     |
| `service.relay.type`            | Public relay Service type                                 | `ClusterIP`                    |
| `service.private.enabled`       | Opt into the private API listener, Service and ingress policy | `false`                    |
| `service.metrics.enabled`       | Render the metrics (ClusterIP) Service                    | `true`                         |
| `service.compatibility.enabled` | Render the `<release>-dingo` compatibility Service        | `true`                         |
| `networkPolicy.enabled`         | Enable relay policy; always rendered for producers and private-Service opt-ins | `false`       |
| `networkPolicy.relayIngressFrom` | P2P peers; empty allows relay ingress and denies block-producer ingress | `[]`             |
| `mithril.enabled`               | Bootstrap the DB from a Mithril snapshot                  | `true`                         |
| `persistence.size`              | PVC size                                                  | `60Gi`                         |
