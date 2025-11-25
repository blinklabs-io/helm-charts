# OpenVPN Helm Chart

This Helm chart deploys OpenVPN in a Kubernetes cluster for secure, no-log VPN services.

## Installation

```bash
helm install my-openvpn ./charts/openvpn
```

## Configuration

See `values.yaml` for configuration options. Key security settings include:

- Use `secret: true` for certificate and key files to store them as Secrets.
- Enable `networkPolicy.enabled` to restrict pod traffic.
- Configure strong OpenVPN settings in `configFiles` (e.g., TLS 1.3, PFS, no compression).
- Set resource limits and requests appropriately.

## Security Notes

- This chart provides examples and recommendations for hardened OpenVPN configurations to enhance privacy and security (e.g., no logging, strong ciphers via `configFiles`).
- Regularly rotate certificates using cert-manager.
- Scan images for vulnerabilities.
- Enable network policies and audit logging at the cluster level.

## Testing

Run Helm tests:

```bash
helm test my-openvpn
```