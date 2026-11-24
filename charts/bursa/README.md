# Bursa Helm chart

The chart runs one Bursa mode per release: wallet API, remote signer, or KES
agent. The API listener is explicitly bound to `127.0.0.1` by default, so the
Service omits its API port. Metrics retain their existing Service port.

## Protected API Service

Set `environment.API_LISTEN_ADDRESS` to a pod-reachable address to expose the
API through the Service. A non-loopback listener requires TLS,
`API_JWT_AUDIENCE`, and exactly one JWT trust source.

For HS256 authentication, reference a Kubernetes Secret:

```yaml
environment:
  API_LISTEN_ADDRESS: "0.0.0.0"
  API_JWT_AUDIENCE: "bursa-api"
api:
  auth:
    existingSecret: bursa-api-auth
    existingSecretKey: jwt-secret
  tls:
    secretName: bursa-api-tls
```

The TLS Secret must use type `kubernetes.io/tls` or otherwise contain
`tls.crt` and `tls.key`. The chart injects the authentication key as
`API_JWT_SECRET` and mounts the TLS pair read-only. New deployments should not
put a literal `API_JWT_SECRET` in `environment`, because Deployment manifests
are readable.

For JWKS authentication, set `environment.API_JWKS_URL` instead of
`api.auth.existingSecret`. `API_JWT_ISSUER` can additionally constrain the
issuer. Bursa requires HTTPS for a non-loopback JWKS endpoint.

| Value | Default | Purpose |
| --- | --- | --- |
| `environment.API_LISTEN_ADDRESS` | `127.0.0.1` | API bind address; a non-loopback value enables the API Service port |
| `environment.API_LISTEN_PORT` | `8080` | Container API port and Service target port |
| `api.auth.existingSecret` | empty | Secret containing the HS256 key |
| `api.auth.existingSecretKey` | `API_JWT_SECRET` | Key selected from the authentication Secret |
| `api.tls.secretName` | empty | Secret containing `tls.crt` and `tls.key` |

## Signer mode

`mode: signer` runs `bursa signer`, the remote signing service. The full
configuration reference is the
[Bursa signer runbook](https://github.com/blinklabs-io/bursa/blob/main/docs/signer/runbook.md).
`signer.config` is the signer config file: the chart sets `signer.listen_address`,
`signer.listen_port` and the TLS file paths, and passes everything else through.
Because the file is a ConfigMap, rendering fails when it carries a credential
(`mnemonic`, `api.jwt_secret`, `storage.dsn`, `signer.jwt_secret`,
`signer.watermark.dsn`). Supply those through `signer.extraEnv` with
`valueFrom`; a watermark DSN is named by `signer.watermark.dsn_env`.

- Server TLS is required: set `signer.tls.secretName` to a `kubernetes.io/tls`
  Secret. `signer.tls.clientCASecretName` (a Secret with `ca.crt`) enables mTLS
  client authentication. The chart refuses `require_client_cert: true`, because
  the kubelet HTTPS probes present no client certificate; requests to the
  signer API without one still get 401.
- Backends are listed under `signer.backends`. A `sops` backend reads
  SOPS-encrypted `*.json` key files from the Secret named by
  `signer.sopsKeys.secretName`, mounted at `/etc/bursa/signer/sops-keys`, and
  decrypts them with the age identity in `signer.ageKey.secretName`. A `sops`
  backend may set `profile` to bind it to one network; the other backend types
  and profile routing are described in the runbook.
- Each key needs a `signer.keys` entry with `allowed_requests`; a key with no
  entry can sign nothing.
- `signer.callers` maps a caller to the key hashes it may use. The subject is
  the client certificate URI SAN, else DNS SAN, else common name.
- Operational certificates need a per-KES-key grant, required since Bursa
  v0.26.0: list the cold key in the caller's `keys`, and each staged KES
  verification key under `opcerts[].kes_vkeys` for that cold key.
- `/readyz` checks that the watermark store is writable.

The watermark records the highest counter signed per key, so it must survive a
restart. A single replica can use the `file` store. Several replicas must share
one `postgres` store: the chart refuses `replicaCount` above 1 unless the
watermark type is `postgres` and its mode is `enforce`.

### Single replica

The `file` watermark is a SQLite file, so mount a PersistentVolumeClaim, which
the chart does not create, and keep two pods from opening it at once with the
`Recreate` update strategy.

```yaml
mode: signer
replicaCount: 1
updateStrategy:
  type: Recreate
signer:
  config:
    signer:
      watermark:
        type: file
        path: /var/lib/bursa/signer/watermark.sqlite
        mode: enforce
      backends:
        - name: cold
          type: sops
          path: /etc/bursa/signer/sops-keys
      callers:
        - subject: dingo-operator
          keys: ["<cold key hash>"]
          opcerts:
            - key: "<cold key hash>"
              kes_vkeys: ["<staged KES verification key>"]
      keys:
        - hash: "<cold key hash>"
          backend: cold
          allowed_requests: ["opcert"]
  tls:
    secretName: bursa-signer-tls
    clientCASecretName: bursa-signer-client-ca
  sopsKeys:
    secretName: bursa-signer-cold-keys
  ageKey:
    secretName: bursa-signer-age
  extraVolumes:
    - name: watermark
      persistentVolumeClaim:
        claimName: bursa-signer-watermark
  extraVolumeMounts:
    - name: watermark
      mountPath: /var/lib/bursa/signer
```

### Multiple replicas

Every replica points at the same PostgreSQL database. The DSN comes from a
Secret through `dsn_env`; a remote database needs `sslmode=verify-full` in it.
The database role must be able to create the watermark tables on first start.

```yaml
mode: signer
replicaCount: 2
affinity:
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchLabels:
            app.kubernetes.io/name: bursa
            app.kubernetes.io/instance: <release>
        topologyKey: kubernetes.io/hostname
podDisruptionBudget:
  enabled: true
signer:
  config:
    signer:
      watermark:
        type: postgres
        dsn_env: SIGNER_WATERMARK_DSN
        mode: enforce
      backends:
        - name: cold
          type: sops
          path: /etc/bursa/signer/sops-keys
      callers:
        - subject: dingo-operator
          keys: ["<cold key hash>"]
          opcerts:
            - key: "<cold key hash>"
              kes_vkeys: ["<staged KES verification key>"]
      keys:
        - hash: "<cold key hash>"
          backend: cold
          allowed_requests: ["opcert"]
  tls:
    secretName: bursa-signer-tls
    clientCASecretName: bursa-signer-client-ca
  sopsKeys:
    secretName: bursa-signer-cold-keys
  ageKey:
    secretName: bursa-signer-age
  extraEnv:
    - name: SIGNER_WATERMARK_DSN
      valueFrom:
        secretKeyRef:
          name: bursa-signer-watermark
          key: dsn
```

Do not move an active signer from `file` to PostgreSQL by repointing it: Bursa
does not import watermark history, so the runbook's controlled cutover applies.

`signer.networkPolicy` restricts ingress to the signer port and, optionally,
egress to the watermark database, custody backends and DNS.

| Value | Default | Purpose |
| --- | --- | --- |
| `signer.config` | `{}` | Signer config file contents, passed through |
| `signer.port` | `8090` | Signer HTTPS port, which also serves `/healthz` and `/readyz` |
| `signer.tls.secretName` | empty | Server certificate Secret; required |
| `signer.tls.clientCASecretName` | empty | CA Secret that enables mTLS client authentication |
| `signer.sopsKeys.secretName` | empty | Secret of SOPS-encrypted `*.json` key files |
| `signer.ageKey.secretName` | empty | Secret holding the age identity for SOPS decryption |
| `signer.extraEnv` | `[]` | Extra environment, such as the watermark DSN from a `secretKeyRef` |
| `signer.extraVolumes` / `signer.extraVolumeMounts` | `[]` | Extra volumes, such as a watermark PVC |
| `signer.networkPolicy.enabled` | `false` | Create a NetworkPolicy; `from` must list a peer |

## KES agent client authorization

`mode: kes-agent` requires Bursa 0.26.0 or newer. Remote signing and control
sessions need a verified client TLS certificate whose public key is pinned in
the selected profile's role list. Set both `kesAgent.tls.secretName` (the
listener's `tls.crt` and `tls.key`) and `kesAgent.tls.clientCASecretName` (the
client issuer's `ca.crt`). Plaintext or TLS without client verification cannot
admit remote sessions.

Configure each producer's public-key fingerprint in its profile:

```yaml
mode: kes-agent
kesAgent:
  tls:
    secretName: kes-agent-tls
    clientCASecretName: producer-client-ca
  config:
    kes_agent:
      store:
        type: postgres
        dsn_env: KESAGENT_PG_DSN
      profiles:
        - name: preview-pool
          cold_vkey_hex: "<pool cold verification key, hex>"
          system_start: "2022-10-25T00:00:00Z"
          slots_per_kes_period: 129600
          sign_client_spki_sha256: ["<producer client SPKI SHA-256, 64 hex characters>"]
  extraEnv:
    - name: KESAGENT_PG_DSN
      valueFrom:
        secretKeyRef:
          name: kes-agent-store
          key: dsn
```

Compute a client's fingerprint with
`openssl x509 -in client.crt -pubkey -noout | openssl pkey -pubin -outform DER | openssl dgst -sha256`.
Add `control_client_spki_sha256` only for clients permitted to install or rotate
keys. Control permission grants no signing permission. A profile can be
control-only or have no remote clients; the chart requires at least one
authorized role across all profiles.

For a single profile without `profiles`, put the role lists directly under
`kes_agent`. The runtime also accepts `KESAGENT_SIGN_CLIENT_SPKI_SHA256` and
`KESAGENT_CONTROL_CLIENT_SPKI_SHA256`, or the fully prefixed forms
`BURSA_KESAGENT_KESAGENT_SIGN_CLIENT_SPKI_SHA256` and
`BURSA_KESAGENT_KESAGENT_CONTROL_CLIENT_SPKI_SHA256`,
from `environment` or `kesAgent.extraEnv`, including `valueFrom` references.
Do not combine these global lists with `profiles`.

## KES agent guard store

The agent must not lose its record of signed slots, so the chart accepts two
guard stores.

- `kes_agent.store.type: postgres` is shared by any number of replicas.
  `guard_file` must be unset.
- `kes_agent.store.type: file` (the default when `store` is unset) keeps one
  guard file per profile, or `kes_agent.guard_file` when `profiles` is unset.
  It is limited to a single agent: `replicaCount: 1`,
  `updateStrategy.type: Recreate`, and every guard file an absolute path under
  the `mountPath` of a writable `kesAgent.extraVolumeMounts` entry whose
  `kesAgent.extraVolumes` entry is a `persistentVolumeClaim`. Rendering fails
  otherwise. `age_recipients`, `kesAgent.ageIdentity` and `store.dsn_env` need
  `postgres`.

```yaml
mode: kes-agent
replicaCount: 1
updateStrategy:
  type: Recreate
kesAgent:
  config:
    kes_agent:
      store:
        type: file
      profiles:
        - name: preview-pool
          cold_vkey_hex: "<pool cold verification key, hex>"
          system_start: "2022-10-25T00:00:00Z"
          slots_per_kes_period: 129600
          guard_file: /var/lib/bursa/kes-agent/preview-pool.guard
          sign_client_spki_sha256: ["<producer client SPKI SHA-256, 64 hex characters>"]
  extraVolumes:
    - name: guard
      persistentVolumeClaim:
        claimName: kes-agent-guard
  extraVolumeMounts:
    - name: guard
      mountPath: /var/lib/bursa/kes-agent
```

`kesAgent.networkPolicy` restricts ingress to the attested listener port. When
the metrics listener is not loopback, a second rule admits the metrics port.

| Value | Default | Purpose |
| --- | --- | --- |
| `kesAgent.extraVolumes` / `kesAgent.extraVolumeMounts` | `[]` | Extra volumes, such as the guard PVC |
| `kesAgent.networkPolicy.enabled` | `false` | Create a NetworkPolicy for `kes-agent` mode |
| `kesAgent.networkPolicy.from` | `[]` | Peers admitted to the attested listener; empty admits any source |
| `kesAgent.networkPolicy.metricsFrom` | `[]` | Peers admitted to the metrics port; empty admits any source |

## KES agent metrics

In `kes-agent` mode the metrics listener, which also serves `/healthz` and
`/readyz`, binds `kesAgent.metricsAddress` on `kesAgent.metricsPort`. It binds
loopback by default. Set the address to `0.0.0.0` to let Prometheus scrape it:
the container then exposes a `metrics` port and `podMonitor.enabled: true` is
accepted. A non-loopback address needs Bursa 0.26.0 or newer.

```yaml
mode: kes-agent
image:
  tag: "0.26.0"
kesAgent:
  metricsAddress: "0.0.0.0"
podMonitor:
  enabled: true
```

| Value | Default | Purpose |
| --- | --- | --- |
| `kesAgent.metricsAddress` | `127.0.0.1` | Metrics bind host, without a port |
| `kesAgent.metricsPort` | `8082` | Metrics port; the readiness probe needs it, so it cannot be 0 |
| `podMonitor.enabled` | `false` | Create a PodMonitor; `kes-agent` mode with a non-loopback address only |
