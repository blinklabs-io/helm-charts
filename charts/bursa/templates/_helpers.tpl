{{- define "bursa.name" -}}
{{ .Chart.Name }}
{{- end }}

{{- define "bursa.fullname" -}}
{{ .Release.Name }}
{{- end }}

{{- define "bursa.labels" -}}
app.kubernetes.io/name: {{ include "bursa.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "bursa.validate" -}}
{{- if not (has .Values.mode (list "api" "signer")) -}}
{{- fail (printf "mode must be \"api\" or \"signer\", got %q" (toString .Values.mode)) -}}
{{- end -}}
{{- if eq .Values.mode "signer" -}}
{{- if not .Values.signer.tls.secretName -}}
{{- fail "signer.tls.secretName is required in signer mode: the signer refuses a plaintext non-loopback listener" -}}
{{- end -}}
{{- if .Values.podMonitor.enabled -}}
{{- fail "podMonitor.enabled is not supported in signer mode: the signer serves metrics on loopback only" -}}
{{- end -}}
{{- $s := (default dict .Values.signer.config).signer | default dict -}}
{{- $wm := $s.watermark | default dict -}}
{{- if and (gt (int .Values.replicaCount) 1) (ne (toString $wm.type) "postgres") -}}
{{- fail "replicaCount > 1 in signer mode requires signer.config.signer.watermark.type: postgres, a watermark shared by every replica" -}}
{{- end -}}
{{- $envRequire := false -}}
{{- range $k, $v := .Values.environment -}}
{{- if and (eq $k "SIGNER_REQUIRE_CLIENT_CERT") (eq (lower (toString $v)) "true") -}}{{- $envRequire = true -}}{{- end -}}
{{- end -}}
{{- range .Values.signer.extraEnv -}}
{{- if and (eq (toString .name) "SIGNER_REQUIRE_CLIENT_CERT") (eq (lower (toString .value)) "true") -}}{{- $envRequire = true -}}{{- end -}}
{{- end -}}
{{- if or (eq (toString $s.require_client_cert) "true") $envRequire -}}
{{- fail "require_client_cert must be false in this chart: the kubelet HTTPS probes present no client certificate; requests to the signer API without one still get 401" -}}
{{- end -}}
{{- if and .Values.signer.networkPolicy.enabled (not .Values.signer.networkPolicy.from) -}}
{{- fail "signer.networkPolicy.from must list at least one peer when the NetworkPolicy is enabled" -}}
{{- end -}}
{{- if and .Values.signer.ageKey.secretName (not .Values.signer.ageKey.key) -}}
{{- fail "signer.ageKey.key is required with signer.ageKey.secretName" -}}
{{- end -}}
{{- end -}}
{{- end }}

{{- define "bursa.signerConfig" -}}
{{- $cfg := deepCopy (default dict .Values.signer.config) -}}
{{- $s := deepCopy (default dict $cfg.signer) -}}
{{- $_ := set $s "listen_address" "0.0.0.0" -}}
{{- $_ := set $s "listen_port" (int .Values.signer.port) -}}
{{- $_ := set $s "tls_cert_file" "/etc/bursa/signer/tls/tls.crt" -}}
{{- $_ := set $s "tls_key_file" "/etc/bursa/signer/tls/tls.key" -}}
{{- if .Values.signer.tls.clientCASecretName -}}
{{- $_ := set $s "client_ca_cert" "/etc/bursa/signer/client-ca/ca.crt" -}}
{{- end -}}
{{- $_ := set $cfg "signer" $s -}}
{{- toYaml $cfg -}}
{{- end }}
