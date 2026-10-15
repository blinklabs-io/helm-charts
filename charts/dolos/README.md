# Dolos

The chart preserves one data PVC per StatefulSet ordinal. A RollingUpdate replaces
one ordinal at a time. API traffic must go through a Service that selects Ready
pods; direct pod IPs and headless DNS clients cannot receive that guarantee.

## API availability during upgrades

For an API-serving installation, enable the query and synchronization gate:

```yaml
replicaCount: 2
minReadySeconds: 60
terminationGracePeriodSeconds: 180
availability:
  enabled: true
  referenceTipURLs:
    - http://relay-a:12798/metrics
    - http://relay-b:12798/metrics
  maxSlotLag: 60
  maxTipAgeSeconds: 600
  drainDelaySeconds: 60
podDisruptionBudget:
  enabled: true
  maxUnavailable: 1
```

The small readiness container queries MiniBlockfrost's `/blocks/latest`, compares
its slot with the newest available reference relay tip, checks MiniKupo when
configured, and connects to the gRPC listener. A listening socket or `/health`
HTTP 200 alone cannot prove that Dolos has caught up. A wall-clock freshness bound
also rejects a backend and reference that have stalled together. Tune it for the
network's block frequency; an unusually long network-wide block gap can make all
backends unready. Reference URLs must serve Cardano Prometheus metrics containing
`cardano_node_metrics_slotNum_int`. Multiple URLs provide failover; if every
reference fails, readiness fails closed.

The helper starts unready and expires cached health if its checker stops making
progress. It checks in the background so kubelet's readiness endpoint remains
responsive when a reference is slow. Its image is digest-pinned, requires no
Kubernetes credentials, and runs without root or a writable root filesystem.

Keep at least two healthy replicas per AZ on separate hosts before upgrading.
A disruption budget protects voluntary evictions; it does not serialize
StatefulSet updates. Configure Helm/Helmfile to wait for readiness and serialize
AZ releases. `minReadySeconds` prevents the next ordinal being replaced until
its replacement has remained healthy for the chosen period. `updateStrategy`
accepts Kubernetes' full StatefulSet strategy, including a RollingUpdate
partition for staged rollout.

On pod termination, Kubernetes removes it from ready Service endpoints. The
native pre-stop sleep keeps Dolos serving during endpoint propagation and gives
finite in-flight requests time to finish before SIGTERM. This needs Kubernetes
1.30+ with lifecycle sleep enabled (stable in 1.34); set the delay to zero to omit
the hook. The termination grace must exceed the drain delay and leave enough time
for Dolos to close databases and requests. Do not force-delete pods or bypass
readiness during an upgrade.

Dolos cancels UTxORPC streams on shutdown. An established TCP/HTTP2 stream cannot
be moved to a different pod by a Service or readiness probe. Stream consumers
must reconnect and resume from their last processed chain point. A drain delay
is not a promise of uninterrupted infinite streams, and request retries must not
blindly replay transaction submission.

The opt-in gate adds the mutable `dolos.blinklabs.io/serving="true"` pod label to
its headless Service selector. It never changes the immutable StatefulSet selector.
External aggregation Services may use the same label to support explicit drain.
Before first enabling this on an existing release, label currently healthy pods
`serving=true`; otherwise the updated Service selector will initially match none.
Pods without the new pre-stop hook must be withdrawn from aggregation Services
and allowed to drain before their first replacement. Re-admit them on upgrade
failure only after verifying query and sync health. A deployment orchestrator
must serialize this adoption across AZs as well as later upgrades.

Bootstrap additional replicas and confirm API query health before changing the
Dolos image. Upgrade one AZ and observe API error rates, tip agreement, and pod
readiness before upgrading the next. Stop on a failed readiness gate; preserve
PVCs and investigate. After restoring a failed StatefulSet's previous template,
Kubernetes can require deletion of only its unhealthy updated ordinal to recover
from the failed ordered rollout. Do not delete its PVC. Database migrations may
prevent downgrading an image against the same data; Helm rollback is not a data
rollback.

## Availability values

| Value | Default | Purpose |
| --- | --- | --- |
| `availability.enabled` | `false` | Opt into query and sync readiness. |
| `availability.referenceTipURLs` | `[]` | Required reference relay metrics URLs when enabled. |
| `availability.maxSlotLag` | `60` | Largest allowed slot gap to the reference or between API checkpoints. |
| `availability.maxTipAgeSeconds` | `600` | Largest allowed latest-block age. |
| `availability.requestTimeoutSeconds` | `2` | Timeout per upstream check. |
| `availability.pollIntervalSeconds` | `5` | Delay between check rounds. |
| `availability.maxCheckAgeSeconds` | `30` | Maximum age of cached readiness. |
| `availability.port` | `18081` | Pod-local readiness HTTP port; not exposed by the chart's Service. |
| `availability.drainDelaySeconds` | `30` | Delay before Dolos receives SIGTERM. |
| `minReadySeconds` | `0` | Continuous readiness required before the next ordinal update. |
| `terminationGracePeriodSeconds` | `180` | Total drain and shutdown budget. |
| `podDisruptionBudget.enabled` | `false` | Protect against voluntary disruptions. |
| `podDisruptionBudget.maxUnavailable` | `1` | Allowed unavailable replicas per release. |

## Validation

`python3 -B scripts/test-dolos-readiness.py` exercises query health and the render
matrix. `python3 -B scripts/test-dolos-rollout.py` uses Docker, k3d, kubectl and Helm
to run an isolated rolling-upgrade simulation. It uses an API fixture rather than
bootstrapping Cardano: the replacement listens before it catches up, a request
overlaps termination, client queries continue through a ClusterIP Service, and
the test verifies endpoint exclusion, eviction refusal, and retained PVC IDs.
