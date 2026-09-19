# Bursa Helm chart

The chart runs the Bursa API on port `8080` and metrics on port `8081`. The
API listener defaults to `127.0.0.1`, so the default Service exposes metrics
only. The API Service port is added only when `API_LISTEN_ADDRESS` is reachable
from the Service.

## Protected API service

Set a pod-reachable listener and configure exactly one supported authentication
mode. For JWT secret authentication, reference an existing Kubernetes Secret;
the secret value is never accepted in `values.yaml`:

```yaml
environment:
  API_LISTEN_ADDRESS: "0.0.0.0"
  API_LISTEN_PORT: 8080
  API_JWT_ISSUER: "https://issuer.example"
  API_JWT_AUDIENCE: "bursa"
api:
  auth:
    existingSecret: bursa-api-jwt
    existingSecretKey: API_JWT_SECRET
```

The referenced key must contain a JWT secret of at least 32 bytes. The
application enforces that minimum at startup. JWT issuer and audience are
optional non-secret settings.

JWKS authentication is mutually exclusive with the Secret mode:

```yaml
environment:
  API_LISTEN_ADDRESS: "0.0.0.0"
  API_JWKS_URL: "https://issuer.example/.well-known/jwks.json"
  API_JWT_ISSUER: "https://issuer.example"
  API_JWT_AUDIENCE: "bursa"
```

A non-loopback listener without either authentication mode fails Helm
rendering. `API_JWT_SECRET` must not be placed in `environment`; use
`api.auth.existingSecret` and `api.auth.existingSecretKey` instead.

Before this chart version is released, `appVersion` and the default image tag
must identify a Bursa release that implements these API authentication settings.
Do not enable protected mode with an older image that does not recognize them.

The default, protected, loopback-only, JWKS, and invalid listener cases can be
checked with `charts/bursa/ci/render-test.sh`.
