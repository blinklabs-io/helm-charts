# dingo-operator

Deploys the [Dingo operator](https://github.com/blinklabs-io/dingo-operator),
which reconciles `DingoNode` resources into Dingo relays and block producers.
Deploy the nodes themselves with the [dingonodes](../dingonodes) chart or your
own `DingoNode` manifests.

Install one release per cluster: the operator reconciles every DingoNode
cluster-wide, and the CRD and ClusterRoles are cluster-scoped.

## TL;DR

```console
helm install dingo-operator oci://ghcr.io/blinklabs-io/helm-charts/charts/dingo-operator \
  --namespace dingo-operator --create-namespace
```

The chart requires Kubernetes 1.30 or later: the CRD's image transition rule
needs CRD validation ratcheting.

## CRD

The `DingoNode` CRD ships in `templates/`, not `crds/`, so `helm upgrade`
also upgrades it.

- `crds.install` (default `true`) renders the CRD. Set it to `false` to manage
  the CRD yourself.
- `crds.keep` (default `true`) adds `helm.sh/resource-policy: keep`, so
  uninstalling the release keeps the CRD and therefore every DingoNode. Set it
  to `false` to delete them with the release.

## Key Secret access

The operator reads each block producer's key Secret with `get` through an
uncached reader. The chart grants this per namespace with a Role and
RoleBinding, and leaves the grant to the deployment on purpose.

| Value | Effect |
| ----- | ------ |
| `rbac.keySecretsNamespaces` | Namespaces that get the Role. Empty grants access only in the release namespace. List every namespace that holds block-producer DingoNodes. |
| `rbac.readSecretNames` | Limits `get` to these Secret names plus `rbac.keySecretNames`, instead of every Secret in the namespace. List every Secret the operator reads: each block producer's `keys.secretRef` (with `pools`, every pool's `keys.secretRef`); with rotation `coldSigner` type `bursa`, its `mtlsSecretRef` (type `secret`: its `secretRef`); and with `signingAgent`, its `clientCertSecretRef` and `controlClientCertSecretRef`. A Secret missing here is refused at its first read. |
| `rbac.keySecretsUpdate` | Also grants `update` on the Secrets in `rbac.keySecretNames`. Rendering fails when `rbac.keySecretNames` is empty, because an update rule without `resourceNames` would cover every Secret in the namespace. |
| `rbac.keySecretNames` | Secrets the operator may update. |
| `rbac.watchKeySecrets` | Adds `list` and `watch` on Secrets and passes `--key-namespaces` to the operator, so a delivered key bundle is applied at once instead of on the periodic reconcile (up to two minutes later). Only metadata is cached, but RBAC cannot limit `list` to metadata or to named Secrets, so this grants read access to every Secret in those namespaces. Rendering fails when combined with `rbac.readSecretNames`. Requires an operator image that has `--key-namespaces`; older images exit on the unknown flag. |

Which rotation mode needs which:

| `rotation.mode` | Needs |
| --------------- | ----- |
| `MonitorOnly`, `Assisted` | Read only. The defaults are enough. |
| `Auto` | `rbac.keySecretsUpdate: true` and `rbac.keySecretNames`, because the operator writes the new opcert, and without `signingAgent` the new `kes.skey`, into the keys Secret. |

```yaml
rbac:
  keySecretsNamespaces:
    - cardano
  keySecretsUpdate: true
  keySecretNames:
    - producer-keys
  readSecretNames:
    - producer-mtls
```

## Metrics

The controller-runtime metrics endpoint listens on `metrics.port` (default
`8080`). With `metrics.secure` (default `true`) it authenticates scrapes with
TokenReview and authorizes them against the `<fullname>-metrics-reader`
ClusterRole, which allows `get` on `/metrics`. `<fullname>` is the release
name when it contains `dingo-operator`, and `<release>-dingo-operator`
otherwise.

Set `podMonitor.enabled: true` to scrape the operator with the Prometheus
Operator, which must already provide its CRDs. `podMonitor.interval` and
`podMonitor.labels` set the scrape interval and the PodMonitor's labels, for
example the label a Prometheus selects on. With `metrics.secure` the chart also
creates, in the release namespace:

- a ServiceAccount, `<fullname>-metrics-scraper`, with token automounting off;
- a `kubernetes.io/service-account-token` Secret,
  `<fullname>-metrics-scraper-token`, which the PodMonitor presents as a bearer
  token over HTTPS (the self-signed certificate is not verified);
- a ClusterRoleBinding of that ServiceAccount to the metrics-reader ClusterRole.

With `metrics.secure: false` the PodMonitor scrapes over plain HTTP and none of
these objects are rendered.

## Pod labels

The NetworkPolicies the operator renders for DingoNodes admit metrics scrapes
and node-to-client queries only from pods carrying the labels in `podLabels`:

```yaml
podLabels:
  dingo.blinklabs.io/metrics: allowed
  dingo.blinklabs.io/node-to-client: allowed
```

When DingoNodes live in another namespace, that namespace (the operator's) must
carry the same labels.

## Forger fence namespaces

`forgerFenceNamespaces` is passed as `--forger-fence-namespaces`. When two block
producers of one pool are in namespaces that are both listed, the newer is
refused and scaled to zero, as within one namespace. Across unlisted namespaces
a claim that names only the pool ID does not stop a producer, because a pool ID
is public. List only namespaces one party controls. Empty omits the flag.
Requires an operator image that has `--forger-fence-namespaces`; older images
exit on the unknown flag.

## Upgrading

1. Upgrade this chart. It carries the operator and the CRD that matches it.
2. Then upgrade or edit the DingoNodes.

A DingoNode that pins its Dingo image by digest must also set
`spec.image.capabilityVersion` to the Dingo release the image implements; it
selects UID, probe and optional feature support. The CRD bundled with operator
0.6.0 enforces these rules:

- a new digest requires `capabilityVersion`;
- changing the digest or the tag requires it;
- once declared, it must stay set while the image is digest-pinned;
- it is refused without a digest.

```yaml
spec:
  image:
    tag: "0.94.2"
    digest: sha256:<64 hex digits>
    capabilityVersion: "0.94.2"
```

An existing digest and tag pair that predates the field keeps working
unchanged. An existing digest without a tag is not exempt: the rule compares
the old object, so CRD validation ratcheting does not apply, and the next
update of that DingoNode is refused until it sets `capabilityVersion`.

## Values

See [values.yaml](values.yaml) for every setting. Key knobs:

| Key | Description | Default |
| --- | ----------- | ------- |
| `image.tag` | Operator image tag; the release whose CRD is bundled | `"0.7.0"` |
| `image.digest` | Immutable image digest (`sha256:...`); overrides the tag | `""` |
| `replicaCount` | Controller replicas; more than one requires `leaderElection.enabled` | `1` |
| `leaderElection.enabled` | Enable leader election | `false` |
| `crds.install` | Render the DingoNode CRD | `true` |
| `crds.keep` | Keep the CRD and every DingoNode on uninstall | `true` |
| `metrics.port` | Metrics endpoint port | `8080` |
| `metrics.secure` | Protect the metrics endpoint with authn/authz | `true` |
| `podMonitor.enabled` | Render a PodMonitor and, with `metrics.secure`, the scraper credentials | `false` |
| `forgerFenceNamespaces` | Namespaces trusted to fence each other's block producers | `[]` |
| `rbac.keySecretsNamespaces` | Namespaces where the operator may read key Secrets | `[]` (release namespace) |
| `rbac.keySecretsUpdate` | Grant `update` on `rbac.keySecretNames` | `false` |
| `rbac.keySecretNames` | Key Secrets the operator may update | `[]` |
| `rbac.readSecretNames` | Limit `get` to these Secrets plus `rbac.keySecretNames` | `[]` |
| `rbac.watchKeySecrets` | Watch Secret metadata for prompt key delivery | `false` |
| `podLabels` | Labels the DingoNode NetworkPolicies match | metrics and node-to-client `allowed` |
| `extraArgs` | Extra controller arguments | `[]` |
