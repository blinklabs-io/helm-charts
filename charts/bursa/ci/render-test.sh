#!/usr/bin/env bash
set -euo pipefail

chart_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

render() {
  local name="$1"
  local values_file="${2:-}"
  if [[ -n "$values_file" ]]; then
    helm template "bursa-${name}" "$chart_dir" -f "$chart_dir/ci/${values_file}" >"$tmp_dir/${name}.yaml"
  else
    helm template "bursa-${name}" "$chart_dir" >"$tmp_dir/${name}.yaml"
  fi
}

service_api_ports() {
  awk '
    /^kind: Service$/ { in_service = 1; next }
    /^---$/ { in_service = 0 }
    in_service && /- name: api$/ { count++ }
    END { print count + 0 }
  ' "$1"
}

expect_render_failure() {
  local name="$1"
  local values_file="$2"
  local expected_message="$3"
  if helm template "bursa-${name}" "$chart_dir" \
    -f "$chart_dir/ci/${values_file}" \
    >"$tmp_dir/${name}.yaml" 2>"$tmp_dir/${name}.err"; then
    echo "${name} rendered successfully" >&2
    exit 1
  fi
  grep -q "$expected_message" "$tmp_dir/${name}.err"
}

render default default-values.yaml
render loopback loopback-values.yaml
render protected protected-values.yaml
render jwks jwks-values.yaml

[[ "$(service_api_ports "$tmp_dir/default.yaml")" == 0 ]]
[[ "$(service_api_ports "$tmp_dir/loopback.yaml")" == 0 ]]
[[ "$(service_api_ports "$tmp_dir/protected.yaml")" == 1 ]]
[[ "$(service_api_ports "$tmp_dir/jwks.yaml")" == 1 ]]
grep -A2 -q 'name: API_JWT_SECRET' "$tmp_dir/protected.yaml"
grep -A2 -q 'valueFrom:' "$tmp_dir/protected.yaml"
grep -q 'containerPort: 9090' "$tmp_dir/protected.yaml"
grep -q 'targetPort: 9090' "$tmp_dir/protected.yaml"

expect_render_failure \
  unprotected \
  invalid-unprotected.yaml \
  'requires api.auth.existingSecret or environment.API_JWKS_URL'
expect_render_failure \
  pseudo-loopback \
  invalid-pseudo-loopback.yaml \
  'requires api.auth.existingSecret or environment.API_JWKS_URL'
expect_render_failure \
  plain-secret \
  invalid-plain-secret.yaml \
  'environment.API_JWT_SECRET is not supported'
expect_render_failure \
  mixed-auth \
  invalid-mixed-auth.yaml \
  'api.auth.existingSecret and environment.API_JWKS_URL are mutually exclusive'

echo "Bursa Helm render matrix passed"
