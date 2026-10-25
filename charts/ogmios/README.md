# Ogmios

Runs Ogmios with a socat sidecar forwarding a remote Cardano node socket.
The chart supports Ogmios v6 and v7 images.

## Readiness and rolling upgrades

The default HTTP probe accepts HTTP 202 as successful. Enable `availability`
to require a connected node, a valid chain tip, a recent tip update, and slot
lag within the configured limit of the newest reachable reference relay.
Reference URLs must serve Cardano node Prometheus metrics for the same network.
Multiple URLs provide failover; if all fail, readiness fails closed.

```yaml
availability:
  enabled: true
  referenceTipURLs:
    - http://relay-a:12798/metrics
    - http://relay-b:12798/metrics
```

The sidecar exposes `/readyz` on port 18081. Readiness removes the entire pod
from normal Services, including Services managed outside this chart, without
restarting Ogmios. Services must respect readiness and must not set
`publishNotReadyAddresses`. Its separate `/healthz` checks the monitor worker,
not backend health. Existing Ogmios liveness and readiness overrides remain in
effect; backend outages therefore do not cause restarts through this sidecar.

`lastTipUpdate` measures the time Ogmios received a tip, not the block's creation
time. Reference slot comparison catches replay of old blocks with recent update
timestamps. References must be independently healthy; simultaneous stale
references can conceal lag until tip updates stop. No Kubernetes API access or
new Service selector is needed.

| Value | Default | Meaning |
| --- | --- | --- |
| `availability.enabled` | `false` | Add the semantic readiness sidecar. |
| `availability.referenceTipURLs` | `[]` | At least one same-network relay metrics URL when enabled. |
| `availability.maxSlotLag` | `60` | Maximum lag behind the newest reachable relay, inclusive; zero requires no lag. |
| `availability.maxTipAgeSeconds` | `600` | Maximum age of the last tip update. |
| `availability.requestTimeoutSeconds` | `2` | Timeout per health or reference request. |
| `availability.pollIntervalSeconds` | `5` | Pause between checks. |
| `availability.maxCheckAgeSeconds` | `30` | Expiry of cached successful checks; must exceed the poll interval. |
| `availability.port` | `18081` | Sidecar probe listener; must differ from 1337. |
| `availability.drainDelaySeconds` | `30` | Delay before terminating Ogmios and socat; zero disables it. Requires Kubernetes 1.30+. |
| `availability.resources` | 10m CPU/32Mi requested, 64Mi memory limit | Sidecar resource budget. |
| `availability.image` | Pinned Python Alpine image | Sidecar runtime; digest takes precedence over tag. |
| `minReadySeconds` | `30` | Continuous readiness before a replacement counts as available, when enabled. |
| `terminationGracePeriodSeconds` | `90` | Shutdown budget when enabled; must exceed the drain delay. |
| `updateStrategy.rollingUpdate` | `maxSurge: 1`, `maxUnavailable: 0` | Keep old available replicas until replacements are ready. Requires capacity for a surge pod. |

A terminating pod leaves normal Service endpoints before the shutdown delay.
Both Ogmios and socat remain alive during that delay so finite requests can
complete. Existing WebSocket sessions eventually disconnect and clients must
reconnect. This does not migrate live sessions between pods.

For first adoption, existing pods retain their old probes and shutdown behavior
until replaced. Keep another availability zone healthy and deploy one zone at a
time. This gate does not retroactively protect old pods. Probe port access from
kubelets and egress to DNS and reference metrics must remain allowed by any
external NetworkPolicies. Do not expose the sidecar probe port through client
Services.

## Validation

Run `python3 -B scripts/test-ogmios-readiness.py` for health and rendered-manifest
checks. Run `python3 -B scripts/test-ogmios-rollout.py` for an isolated k3d test
of endpoint withdrawal, recovery without restarts, and a surge rollout with
warming replicas. The rollout test substitutes HTTP fixtures for Ogmios and its
socket backend and uses the actual readiness sidecar and Kubernetes probes.
