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
```

## Notes

- A node's `false`, `0` or `""` overrides the value in `defaults.spec`; lists
  are replaced, not merged.
- `nodes.<name>.enabled: false` removes the node's DingoNode and PodMonitor and
  keeps its spec in values. Its PVC has no owner, so the data survives.
- `keep: true` adds `helm.sh/resource-policy: keep` to the DingoNodes,
  PodMonitors and extra objects, so they survive an uninstall or a release
  rename.
- `extraObjects` renders additional manifests as given, for example a
  NetworkPolicy that admits relays in another namespace to a block producer.

See [values.yaml](values.yaml) for every setting.
