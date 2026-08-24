# hydrozoa

Deploys one [Hydrozoa](https://github.com/cardano-hydrozoa/hydrozoa) head or
coil peer as a single-replica Kubernetes StatefulSet.

> Hydrozoa's upstream deployment guide describes the current release as a
> demo that must not hold production value. This chart does not change that
> security posture.

The chart uses the official upstream
`ghcr.io/cardano-hydrozoa/hydrozoa:0.1.11` image. Hydrozoa is not currently
packaged under `ghcr.io/blinklabs-io`, so there is no Blink image to prefer.

## Deployment model

Install one release per Hydrozoa peer. Do not scale a release: every peer has
its own signing identity, private config, PKCS12 keystore, and RocksDB state.
For example, a fleet can use releases named `head-0`, `head-1`, `coil-0`, and
`coil-1` with `fullnameOverride` set to the same stable peer name used in the
shared Hydrozoa head configuration.

Prerequisites:

- Kubernetes 1.29+ (native sidecar containers)
- Helm 3.8+
- a default StorageClass, or an explicitly selected/existing PVC
- an already generated Hydrozoa `head-config.json` and per-peer `private.json`

## Required config Secret

The private config contains a wallet and external-service credentials. Both
runtime JSON files therefore come from an existing Secret and are never
accepted inline through Helm values:

```console
kubectl -n hydrozoa create secret generic coil-0-hydrozoa-config \
  --from-file=head-config.json=./head-config/head-config.json \
  --from-file=private.json=./private/coil-0/private.json
```

The Secret keys are configurable through `config.headConfigKey` and
`config.privateConfigKey`. They are projected into `/configs/head-config.json`
and `/configs/private.json`, and the default image invocation is:

```text
hydrozoa serve /configs/head-config.json /configs/private.json
```

## PKCS12 keystore Secret

Put the keystore file and password in a Secret. A Secret may contain multiple
peer keystores; each chart release selects its own key with
`tls.keystoreKey`:

```console
kubectl -n hydrozoa create secret generic hydrozoa-coil-tls \
  --from-file=coil-0.p12=./coil-0.p12 \
  --from-file=coil-1.p12=./coil-1.p12 \
  --from-literal=password='<keystore-password>'
```

Example values for `coil-0`:

```yaml
fullnameOverride: coil-0

node:
  role: coil

config:
  existingSecret: coil-0-hydrozoa-config

tls:
  enabled: true
  existingSecret: hydrozoa-coil-tls
  keystoreKey: coil-0.p12
  passwordKey: password
  fileName: coil-0.p12
```

The selected file is mounted read-only at
`/etc/hydrozoa/tls/coil-0.p12`. Its password is loaded through a
`secretKeyRef`, then the chart builds these JVM properties in `JAVA_OPTS`:

```text
-Djavax.net.ssl.keyStore=/etc/hydrozoa/tls/coil-0.p12
-Djavax.net.ssl.keyStoreType=PKCS12
-Djavax.net.ssl.keyStorePassword=$(HYDROZOA_KEYSTORE_PASSWORD)
```

Kubernetes expands that reference from the preceding Secret-backed environment
entry before starting the image entrypoint. The password is not stored in the
rendered manifest or Helm release values, though the JVM necessarily receives
it as a system property.

## Install

```console
helm install coil-0 \
  oci://ghcr.io/blinklabs-io/helm-charts/charts/hydrozoa \
  --namespace hydrozoa --create-namespace \
  -f coil-0-values.yaml
```

For a head peer, set `node.role: head` (the default). The chart then renders
the HTTP and peer Service plus `/health` and `/ready` probes. Ensure
`service.http.port` matches `httpPort` in `private.json`, and
`service.peer.port` matches the peer's advertised/bind port in the shared and
private Hydrozoa configuration. Coil peers dial out and render no public
Service or HTTP probes.

## Containers that start before Hydrozoa

Use `initContainers` for one-shot preparation that must finish before the
Hydrozoa process:

```yaml
initContainers:
  - name: prepare-config
    image: example/preparer:1.0.0
    args: [prepare, /shared]
    volumeMounts:
      - name: shared
        mountPath: /shared
```

Use `sidecars` for Kubernetes native sidecars. The chart renders each entry
inside `initContainers` with `restartPolicy: Always`, so it starts before
Hydrozoa and stays running for the Pod lifetime. When Hydrozoa must wait for
the sidecar to become usable, give the sidecar a `startupProbe`; Kubernetes
does not start the main container until that probe succeeds:

```yaml
sidecars:
  - name: tls-proxy
    image: example/tls-proxy:1.0.0
    ports:
      - name: proxy
        containerPort: 4001
    startupProbe:
      tcpSocket:
        port: proxy
      periodSeconds: 1
      failureThreshold: 60
```

The Pod always defines volumes named `config`, `data`, `tmp`, and (when TLS is
enabled) `keystore`. Add shared volumes through `extraVolumes`, mount them in
Hydrozoa with `extraVolumeMounts`, and reference them from each init/sidecar
container's own `volumeMounts`.

## Persistent state

Hydrozoa stores consensus and EUTXO RocksDB data under
`/opt/docker/.hydrozoa-data`. The chart creates a retained `ReadWriteOnce` PVC
by default. To use an existing claim:

```yaml
persistence:
  enabled: true
  existingClaim: coil-0-hydrozoa-data
```

Deleting a Hydrozoa PVC can remove the recovery state for funds held by a
head. The chart therefore retains generated claims when the StatefulSet is
deleted. Secret updates do not restart the process automatically; restart the
Pod deliberately after reviewing new config or keystore material.
