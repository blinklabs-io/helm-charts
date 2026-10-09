# cardano-node

## Internal peer mesh

`topology.mesh.enabled` generates a topology for each pod before the node starts.
Include every StatefulSet on the same Cardano network, including the current
release. Each peer uses its ordinal DNS name through its headless Service. The
current pod is excluded. Existing bootstrap, public, and local roots are retained.

```yaml
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

The example assumes the current release has `fullnameOverride: relay-a`.
