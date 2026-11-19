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
