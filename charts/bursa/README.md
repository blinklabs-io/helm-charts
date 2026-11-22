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
