# dingonodes

Deploys [DingoNode](https://github.com/blinklabs-io/dingo-operator) resources
from values. Install the
[dingo-operator](../dingo-operator) chart first; it provides the DingoNode CRD
and the controller that turns each DingoNode into a running node.

Each enabled node gets:

- a DingoNode named after its key in `nodes`, with `defaults.spec` merged under
  the node's own `spec` (the node wins; lists are replaced, not merged);
- a PodMonitor of the same name, which a label-selected Prometheus can pick up
  through `podMonitor.labels`.

Each release also gets a NetworkPolicy, `<release>-metrics`, that admits
`metricsNetworkPolicy.from` to the metrics port. It is not rendered while `from`
is empty. No node may take that name, because the operator names each node's own
NetworkPolicy after the node.

## Example

```yaml
nodes:
  preview-relay:
    spec:
      role: relay
      network: preview
      podLabels:
        team: example

podMonitor:
  labels:
    release: prometheus
  podTargetLabels:
    - team

metricsNetworkPolicy:
  from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: monitoring
      podSelector:
        matchLabels:
          app.kubernetes.io/name: prometheus
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: dingo-operator
      podSelector:
        matchLabels:
          app.kubernetes.io/name: dingo-operator
```

## Notes

- A node's `false`, `0` or `""` overrides the value in `defaults.spec`; lists
  are replaced, not merged.
- `nodes.<name>.enabled: false` removes the node's DingoNode and PodMonitor and
  keeps its spec in values. Its PVC has no owner, so the data survives. Helm
  reads `keep` from the live object, so under `keep: true` the node stays: set
  `keep: false` in one upgrade, then `enabled: false` in the next.
- `keep: true` adds `helm.sh/resource-policy: keep` to the DingoNodes,
  PodMonitors and extra objects, so they survive an uninstall or a release
  rename.
- `extraObjects` renders additional manifests as given, for example a
  NetworkPolicy that admits relays in another namespace to a block producer.
- Do not render a block producer's keys Secret through `extraObjects` under
  `spec.blockProducer.rotation.mode: Auto`. The operator writes each new opcert,
  and the new `kes.skey` unless a signing agent holds the KES key, into that
  Secret, and the next `helm upgrade` restores the data the chart rendered
  (Helm's three-way patch), so the producer returns to an expiring key. Under
  `Auto`, create the keys Secret outside the release, only when it is absent,
  and never re-apply it. Under `Assisted`, re-applying the Secret on each
  deploy is how a new opcert reaches the node. `keep: true` only stops Helm
  deleting the Secret; it does not stop an upgrade from reverting its data.
- To move a keys Secret out of `extraObjects`, back it up, annotate the live
  Secret directly (`kubectl annotate secret <name>
  helm.sh/resource-policy=keep`), then remove it from `extraObjects` in the
  next upgrade. Helm reads that annotation from the live object and leaves the
  Secret in place; without it, the upgrade deletes the Secret. Do not add the
  annotation through `keep: true` or any other upgrade that still renders the
  Secret: under `Auto` the operator can rotate the keys before that upgrade,
  and the upgrade then restores the rendered data.

See [values.yaml](values.yaml) for every setting.
