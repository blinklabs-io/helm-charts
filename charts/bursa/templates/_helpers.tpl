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

{{- /* Environment names whose URL Bursa fetches with a Go HTTP client:
     the envconfig name and its BURSA_-prefixed form. */ -}}
{{- define "bursa.urlEnvNames" -}}
SIGNER_POLICY_HOOK_URL BURSA_SIGNER_SIGNER_POLICY_HOOK_URL SIGNER_JWKS_URL BURSA_SIGNER_SIGNER_JWKS_URL API_JWKS_URL BURSA_API_JWKS_URL
{{- end }}

{{- define "bursa.validate" -}}
{{- if not (has .Values.mode (list "api" "signer" "kes-agent")) -}}
{{- fail (printf "mode must be \"api\", \"signer\" or \"kes-agent\", got %q" (toString .Values.mode)) -}}
{{- end -}}
{{- if eq .Values.mode "kes-agent" -}}
{{- include "bursa.validateKesAgent" . -}}
{{- end -}}
{{- if .Values.podMonitor.enabled -}}
{{- fail "podMonitor.enabled is not supported: Bursa serves metrics on loopback only and refuses a non-loopback METRICS_LISTEN_ADDRESS" -}}
{{- end -}}
{{- range $k, $v := .Values.environment -}}
{{- if and (has $k (include "bursa.urlEnvNames" "" | splitList " ")) $v -}}
{{- if (urlParse (toString $v)).userinfo -}}
{{- $hint := ternary "; set it in signer.extraEnv with valueFrom" "" (eq $.Values.mode "signer") -}}
{{- fail (printf "%s must not carry URL userinfo as a literal environment value: the Deployment is readable%s" $k $hint) -}}
{{- end -}}
{{- end -}}
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
{{- /* Go HTTP clients send URL userinfo as Basic authentication, so a URL
     carrying it is a credential too. */ -}}
{{- $urlFields := list
      (list "signer.policy_hook_url" (dig "signer" "policy_hook_url" "" $cfg) "set SIGNER_POLICY_HOOK_URL in signer.extraEnv with valueFrom")
      (list "signer.jwks_url" (dig "signer" "jwks_url" "" $cfg) "set SIGNER_JWKS_URL in signer.extraEnv with valueFrom")
      (list "api.jwks_url" (dig "api" "jwks_url" "" $cfg) "set API_JWKS_URL in signer.extraEnv with valueFrom") -}}
{{- range $i, $b := (dig "signer" "backends" list $cfg) -}}
{{- $b = $b | default dict -}}
{{- range $f := list "address" "jwks_url" -}}
{{- $urlFields = append $urlFields (list (printf "signer.backends[%d].%s" $i $f) (get $b $f) "Bursa reads no environment override for it") -}}
{{- end -}}
{{- end -}}
{{- range $urlFields -}}
{{- $v := toString (index . 1) -}}
{{- if $v -}}
{{- if (urlParse $v).userinfo -}}
{{- fail (printf "signer.config.%s must not carry URL userinfo: Go HTTP clients send it as Basic authentication and the signer config is a ConfigMap; %s" (index . 0) (index . 2)) -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- range .Values.signer.extraEnv -}}
{{- if and (has (toString .name) (include "bursa.urlEnvNames" "" | splitList " ")) .value -}}
{{- if (urlParse (toString .value)).userinfo -}}
{{- fail (printf "%s must not carry URL userinfo as a literal signer.extraEnv value: the Deployment is readable; set it with valueFrom" .name) -}}
{{- end -}}
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

{{- define "bursa.validateKesAgent" -}}
{{- $tag := toString .Values.image.tag -}}
{{- if regexMatch "^v?[0-9]+\\.[0-9]+\\.[0-9]+$" $tag -}}
{{- if semverCompare "<0.23.0-0" $tag -}}
{{- fail (printf "mode kes-agent needs bursa 0.23.0 or newer (shared store, profiles and listener transport options); image.tag is %q" $tag) -}}
{{- end -}}
{{- end -}}
{{- if not (int .Values.kesAgent.metricsPort) -}}
{{- fail "kesAgent.metricsPort must not be 0: the readiness probe queries /readyz on the metrics listener" -}}
{{- end -}}
{{- $cfg := default dict .Values.kesAgent.config -}}
{{- $k := default dict $cfg.kes_agent -}}
{{- if and $k.mode (ne (toString $k.mode) "sign") -}}
{{- fail (printf "kesAgent.config.kes_agent.mode must be sign (or unset), got %q: serve-key pushes the key over a Unix socket, which cannot reach a producer in another pod" (toString $k.mode)) -}}
{{- end -}}
{{- range $f := list "service_socket" "control_socket" "attested_listen_address" "attested_tls_cert_file" "attested_tls_key_file" "attested_client_ca_file" -}}
{{- if hasKey $k $f -}}
{{- fail (printf "kesAgent.config.kes_agent.%s is set by the chart and must not be set" $f) -}}
{{- end -}}
{{- end -}}
{{- if or (hasKey (default dict $cfg.metrics) "address") (hasKey (default dict $cfg.metrics) "port") -}}
{{- fail "kesAgent.config.metrics is set by the chart: use kesAgent.metricsPort" -}}
{{- end -}}
{{- $plain := eq (toString $k.attested_plaintext) "true" -}}
{{- if and $plain .Values.kesAgent.tls.secretName -}}
{{- fail "kesAgent.tls.secretName and kes_agent.attested_plaintext cannot both be set: the agent refuses TLS files on a plaintext listener" -}}
{{- end -}}
{{- if and (not $plain) (not .Values.kesAgent.tls.secretName) -}}
{{- fail "mode kes-agent needs kesAgent.tls.secretName, or kes_agent.attested_plaintext: true with transport security provided elsewhere" -}}
{{- end -}}
{{- if and .Values.kesAgent.tls.clientCASecretName (not .Values.kesAgent.tls.secretName) -}}
{{- fail "kesAgent.tls.clientCASecretName requires kesAgent.tls.secretName" -}}
{{- end -}}
{{- $store := default dict $k.store -}}
{{- $pg := eq (toString $store.type) "postgres" -}}
{{- if hasKey $store "dsn" -}}
{{- fail "kesAgent.config.kes_agent.store.dsn must not be set: the config is a ConfigMap; set store.dsn_env and that variable in kesAgent.extraEnv with valueFrom" -}}
{{- end -}}
{{- if and $pg (not $store.dsn_env) -}}
{{- fail "kes_agent.store.type postgres needs store.dsn_env" -}}
{{- end -}}
{{- /* A guard file in a pod does not survive a restart unless it sits on
     a persistent volume, and a ReadWriteOnce volume plus the guard's lock
     stall a rolling update, so the chart takes only the shared store. */ -}}
{{- if not $pg -}}
{{- fail "mode kes-agent requires kes_agent.store.type postgres: a guard lost on restart lets the agent sign a second header for a slot, and replicas must share one guard" -}}
{{- end -}}
{{- if or (hasKey $k "guard_file") (gt (len (default list $k.profiles)) 0) -}}
{{- range $i, $p := (default list $k.profiles) -}}
{{- if hasKey (default dict $p) "guard_file" -}}
{{- fail (printf "kes_agent.profiles[%d].guard_file must not be set with the postgres store" $i) -}}
{{- end -}}
{{- end -}}
{{- if hasKey $k "guard_file" -}}
{{- fail "kes_agent.guard_file must not be set with the postgres store" -}}
{{- end -}}
{{- end -}}
{{- if hasKey $store "age_identity_file" -}}
{{- fail "kesAgent.config.kes_agent.store.age_identity_file is set by the chart: use kesAgent.ageIdentity.secretName" -}}
{{- end -}}
{{- if and $store.age_recipients (not .Values.kesAgent.ageIdentity.secretName) -}}
{{- fail "kes_agent.store.age_recipients needs kesAgent.ageIdentity.secretName: the agent sets both or neither" -}}
{{- end -}}
{{- if and .Values.kesAgent.ageIdentity.secretName (not $store.age_recipients) -}}
{{- fail "kesAgent.ageIdentity.secretName needs kes_agent.store.age_recipients" -}}
{{- end -}}
{{- if and .Values.kesAgent.ageIdentity.secretName (not $pg) -}}
{{- fail "kesAgent.ageIdentity.secretName needs kes_agent.store.type postgres: the sealed key lives in the shared store" -}}
{{- end -}}
{{- if and .Values.kesAgent.ageIdentity.secretName (not .Values.kesAgent.ageIdentity.key) -}}
{{- fail "kesAgent.ageIdentity.key is required with kesAgent.ageIdentity.secretName" -}}
{{- end -}}
{{- /* Bursa applies environment variables after the config file, so these
     would undo what the chart sets or checks above. */ -}}
{{- $owned := list "KESAGENT_MODE" "KESAGENT_SERVICE_SOCKET" "KESAGENT_CONTROL_SOCKET" "KESAGENT_ATTESTED_LISTEN_ADDRESS" "KESAGENT_ATTESTED_TLS_CERT_FILE" "KESAGENT_ATTESTED_TLS_KEY_FILE" "KESAGENT_ATTESTED_CLIENT_CA_FILE" "KESAGENT_ATTESTED_PLAINTEXT" "KESAGENT_GUARD_FILE" "METRICS_LISTEN_ADDRESS" "METRICS_LISTEN_PORT" -}}
{{- $envNames := list -}}
{{- range $n, $v := .Values.environment -}}{{- if $v -}}{{- $envNames = append $envNames $n -}}{{- end -}}{{- end -}}
{{- range .Values.kesAgent.extraEnv -}}{{- $envNames = append $envNames (toString .name) -}}{{- end -}}
{{- range $envNames -}}
{{- if has . $owned -}}
{{- fail (printf "%s must not be set in kes-agent mode: it overrides the config file the chart renders and validates" .) -}}
{{- end -}}
{{- end -}}
{{- range .Values.kesAgent.extraEnv -}}
{{- if and (eq (toString .name) (toString $store.dsn_env)) .value -}}
{{- fail (printf "%s must come from valueFrom in kesAgent.extraEnv: the Deployment is readable" .name) -}}
{{- end -}}
{{- end -}}
{{- end }}

{{- define "bursa.kesAgentConfig" -}}
{{- $cfg := deepCopy (default dict .Values.kesAgent.config) -}}
{{- $k := deepCopy (default dict $cfg.kes_agent) -}}
{{- $_ := set $k "mode" "sign" -}}
{{- $_ := set $k "service_socket" "/run/bursa/kes-agent/service.sock" -}}
{{- $_ := set $k "control_socket" "/run/bursa/kes-agent/control.sock" -}}
{{- $_ := set $k "attested_listen_address" (printf ":%d" (int .Values.kesAgent.port)) -}}
{{- if .Values.kesAgent.tls.secretName -}}
{{- $_ := set $k "attested_tls_cert_file" "/run/bursa/kes-agent-secrets/tls.crt" -}}
{{- $_ := set $k "attested_tls_key_file" "/run/bursa/kes-agent-secrets/tls.key" -}}
{{- end -}}
{{- if .Values.kesAgent.tls.clientCASecretName -}}
{{- $_ := set $k "attested_client_ca_file" "/etc/bursa/kes-agent/client-ca/ca.crt" -}}
{{- end -}}
{{- if .Values.kesAgent.ageIdentity.secretName -}}
{{- $store := deepCopy (default dict $k.store) -}}
{{- $_ := set $store "age_identity_file" (printf "/run/bursa/kes-agent-secrets/%s" .Values.kesAgent.ageIdentity.key) -}}
{{- $_ := set $k "store" $store -}}
{{- end -}}
{{- $_ := set $cfg "kes_agent" $k -}}
{{- $_ := set $cfg "metrics" (dict "address" "127.0.0.1" "port" (int .Values.kesAgent.metricsPort)) -}}
{{- toYaml $cfg -}}
{{- end }}
