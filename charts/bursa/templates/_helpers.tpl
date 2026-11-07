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
{{- if .Values.podMonitor.enabled -}}
{{- fail "podMonitor.enabled is not supported: Bursa serves metrics on loopback only and refuses a non-loopback METRICS_LISTEN_ADDRESS" -}}
{{- end -}}
{{- if eq .Values.mode "signer" -}}
{{- if not .Values.signer.tls.secretName -}}
{{- fail "signer.tls.secretName is required in signer mode: the signer refuses a plaintext non-loopback listener" -}}
{{- end -}}
{{- $cfg := default dict .Values.signer.config -}}
{{- /* The config file is a ConfigMap, so credentials must reach Bursa through
     the environment instead: signer.extraEnv with valueFrom. */ -}}
{{- $secretFields := list
      (list "mnemonic" (list "mnemonic") "set MNEMONIC in signer.extraEnv with valueFrom")
      (list "api.jwt_secret" (list "api" "jwt_secret") "set API_JWT_SECRET in signer.extraEnv with valueFrom")
      (list "storage.dsn" (list "storage" "dsn") "set STORAGE_DSN in signer.extraEnv with valueFrom")
      (list "signer.jwt_secret" (list "signer" "jwt_secret") "set SIGNER_JWT_SECRET in signer.extraEnv with valueFrom")
      (list "signer.watermark.dsn" (list "signer" "watermark" "dsn") "set signer.watermark.dsn_env and that variable in signer.extraEnv with valueFrom") -}}
{{- range $secretFields -}}
{{- $path := index . 1 -}}
{{- $v := "" -}}
{{- if eq (len $path) 1 -}}{{- $v = dig (index $path 0) "" $cfg -}}
{{- else if eq (len $path) 2 -}}{{- $v = dig (index $path 0) (index $path 1) "" $cfg -}}
{{- else -}}{{- $v = dig (index $path 0) (index $path 1) (index $path 2) "" $cfg -}}
{{- end -}}
{{- if $v -}}
{{- fail (printf "signer.config.%s must not be set: the signer config is a ConfigMap; %s" (index . 0) (index . 2)) -}}
{{- end -}}
{{- end -}}
{{- $s := $cfg.signer | default dict -}}
{{- $wm := $s.watermark | default dict -}}
{{- /* Bursa applies environment variables after the config file, and
     signer.extraEnv follows environment in the pod, so later entries win. */ -}}
{{- $wmType := toString ($wm.type | default "") -}}
{{- $wmMode := toString ($wm.mode | default "") -}}
{{- $wmUnknown := false -}}
{{- range $k, $v := .Values.environment -}}
{{- if and (eq $k "BURSA_SIGNER_WATERMARK_TYPE") $v -}}{{- $wmType = toString $v -}}{{- end -}}
{{- if and (eq $k "BURSA_SIGNER_WATERMARK_MODE") $v -}}{{- $wmMode = toString $v -}}{{- end -}}
{{- end -}}
{{- range .Values.signer.extraEnv -}}
{{- if has (toString .name) (list "BURSA_SIGNER_WATERMARK_TYPE" "BURSA_SIGNER_WATERMARK_MODE") -}}
{{- if .valueFrom -}}{{- $wmUnknown = true -}}
{{- else if eq (toString .name) "BURSA_SIGNER_WATERMARK_TYPE" -}}{{- $wmType = toString .value -}}
{{- else -}}{{- $wmMode = toString .value -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- if gt (int .Values.replicaCount) 1 -}}
{{- if $wmUnknown -}}
{{- fail "replicaCount > 1 in signer mode cannot take BURSA_SIGNER_WATERMARK_TYPE or BURSA_SIGNER_WATERMARK_MODE from valueFrom: the chart must see that every replica shares a postgres watermark" -}}
{{- end -}}
{{- if ne $wmType "postgres" -}}
{{- fail (printf "replicaCount > 1 in signer mode requires a postgres watermark shared by every replica, got type %q after environment overrides" $wmType) -}}
{{- end -}}
{{- if not (has (lower $wmMode) (list "" "enforce")) -}}
{{- fail (printf "replicaCount > 1 in signer mode requires watermark mode enforce, got %q after environment overrides" $wmMode) -}}
{{- end -}}
{{- end -}}
{{- /* Bursa reads require_client_cert from either variable and parses it
     with strconv.ParseBool, so 1 and t are true too. */ -}}
{{- $ccNames := list "SIGNER_REQUIRE_CLIENT_CERT" "BURSA_SIGNER_SIGNER_REQUIRE_CLIENT_CERT" -}}
{{- $ccTrue := list "1" "t" "true" -}}
{{- $envRequire := false -}}
{{- range $k, $v := .Values.environment -}}
{{- if and (has $k $ccNames) (has (lower (toString $v)) $ccTrue) -}}{{- $envRequire = true -}}{{- end -}}
{{- end -}}
{{- range .Values.signer.extraEnv -}}
{{- if has (toString .name) $ccNames -}}
{{- if .valueFrom -}}
{{- fail (printf "%s cannot come from valueFrom in this chart: the chart must see that require_client_cert stays false" .name) -}}
{{- end -}}
{{- if has (lower (toString .value)) $ccTrue -}}{{- $envRequire = true -}}{{- end -}}
{{- end -}}
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
