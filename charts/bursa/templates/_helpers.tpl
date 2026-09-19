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

{{/* Report whether the configured API listener is reachable only by the pod. */}}
{{- define "bursa.apiLoopback" -}}
{{- $address := trim (toString (get .Values.environment "API_LISTEN_ADDRESS")) -}}
{{- if or (eq (lower $address) "localhost") (regexMatch "^127(?:\\.(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])){3}$" $address) (or (eq $address "::1") (eq $address "[::1]")) -}}
true
{{- else -}}
false
{{- end -}}
{{- end }}

{{/*
Validate the API listener before rendering any workload. An empty address is
the application's wildcard-bind default, so it is intentionally treated as a
non-loopback listener here.
*/}}
{{- define "bursa.apiValidation" -}}
{{- $address := trim (toString (get .Values.environment "API_LISTEN_ADDRESS")) -}}
{{- $jwksURL := trim (toString (get .Values.environment "API_JWKS_URL")) -}}
{{- $secretName := trim (toString .Values.api.auth.existingSecret) -}}
{{- $secretKey := trim (toString .Values.api.auth.existingSecretKey) -}}
{{- $loopback := eq (trim (include "bursa.apiLoopback" .)) "true" -}}
{{- if hasKey .Values.environment "API_JWT_SECRET" -}}
{{- fail "environment.API_JWT_SECRET is not supported; store the secret in a Kubernetes Secret and set api.auth.existingSecret and api.auth.existingSecretKey" -}}
{{- end -}}
{{- if and $secretName $jwksURL -}}
{{- fail "api.auth.existingSecret and environment.API_JWKS_URL are mutually exclusive" -}}
{{- end -}}
{{- if $secretName -}}
{{- $_ := required "api.auth.existingSecretKey is required when api.auth.existingSecret is set" $secretKey -}}
{{- end -}}
{{- if and (not $loopback) (not (or $secretName $jwksURL)) -}}
{{- fail "a non-loopback API_LISTEN_ADDRESS requires api.auth.existingSecret or environment.API_JWKS_URL" -}}
{{- end -}}
{{- end }}
