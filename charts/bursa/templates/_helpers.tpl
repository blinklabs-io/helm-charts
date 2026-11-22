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
SIGNER_POLICY_HOOK_URL BURSA_SIGNER_SIGNER_POLICY_HOOK_URL SIGNER_JWKS_URL BURSA_SIGNER_SIGNER_JWKS_URL API_JWKS_URL BURSA_API_API_JWKS_URL
{{- end }}

{{- define "bursa.validate" -}}
{{- if not (has .Values.mode (list "api" "signer" "kes-agent")) -}}
{{- fail (printf "mode must be \"api\", \"signer\" or \"kes-agent\", got %q" (toString .Values.mode)) -}}
{{- end -}}
{{- if eq .Values.mode "kes-agent" -}}
{{- include "bursa.validateKesAgent" . -}}
{{- end -}}
{{- if .Values.podMonitor.enabled -}}
{{- if ne .Values.mode "kes-agent" -}}
{{- fail (printf "podMonitor.enabled is not supported in mode %s: it serves metrics on loopback only" .Values.mode) -}}
{{- else if include "bursa.kesAgentMetricsLoopback" . -}}
{{- fail "podMonitor.enabled needs a non-loopback kesAgent.metricsAddress, such as 0.0.0.0: a loopback listener cannot be scraped" -}}
{{- end -}}
{{- end -}}
{{- range $k, $v := .Values.environment -}}
{{- if and (has $k (include "bursa.urlEnvNames" "" | splitList " ")) $v -}}
{{- if (urlParse (toString $v)).userinfo -}}
{{- $hint := ternary "; set it in signer.extraEnv with valueFrom" "" (eq $.Values.mode "signer") -}}
{{- fail (printf "%s must not carry URL userinfo as a literal environment value: the Deployment is readable%s" $k $hint) -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- if eq .Values.mode "api" -}}
{{- include "bursa.apiValidation" . -}}
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
{{- if semverCompare "<0.26.0-0" $tag -}}
{{- fail (printf "mode kes-agent needs bursa 0.26.0 or newer (verified remote client authorization); image.tag is %q" $tag) -}}
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
{{- fail "kesAgent.config.metrics is set by the chart: use kesAgent.metricsAddress and kesAgent.metricsPort" -}}
{{- end -}}
{{- $maddr := toString .Values.kesAgent.metricsAddress -}}
{{- if regexMatch "^[^:\\[]+:[0-9]+$|^\\[.*\\]:[0-9]+$" $maddr -}}
{{- fail (printf "kesAgent.metricsAddress must be a host without a port (use kesAgent.metricsPort), got %q" $maddr) -}}
{{- end -}}
{{- if and (not (include "bursa.kesAgentMetricsLoopback" .)) (regexMatch "^v?[0-9]+\\.[0-9]+\\.[0-9]+$" $tag) -}}
{{- if semverCompare "<0.26.0-0" $tag -}}
{{- fail (printf "a non-loopback kesAgent.metricsAddress needs bursa 0.26.0 or newer, which accepts a non-loopback metrics listener; image.tag is %q" $tag) -}}
{{- end -}}
{{- end -}}
{{- $plain := eq (toString $k.attested_plaintext) "true" -}}
{{- if $plain -}}
{{- fail "mode kes-agent requires verified mutual TLS: kes_agent.attested_plaintext cannot admit remote signing or control clients" -}}
{{- end -}}
{{- if not .Values.kesAgent.tls.secretName -}}
{{- fail "mode kes-agent needs kesAgent.tls.secretName for verified mutual TLS" -}}
{{- end -}}
{{- if not .Values.kesAgent.tls.clientCASecretName -}}
{{- fail "mode kes-agent needs kesAgent.tls.clientCASecretName to verify remote client certificates" -}}
{{- end -}}
{{- /* Profiles may be control-only or unserved. The listener needs one
     authorized role somewhere; otherwise every remote session is refused.
     For the single-profile form, envconfig prefers the prefixed variable.
     A valueFrom list is unknown here and may contain valid client pins. */ -}}
{{- $hasClients := false -}}
{{- $profiles := default list $k.profiles -}}
{{- if $profiles -}}
{{- range $profiles -}}
{{- if or .sign_client_spki_sha256 .control_client_spki_sha256 -}}
{{- $hasClients = true -}}
{{- end -}}
{{- end -}}
{{- else -}}
{{- $pinEnv := dict -}}
{{- $names := list "KESAGENT_SIGN_CLIENT_SPKI_SHA256" "BURSA_KESAGENT_KESAGENT_SIGN_CLIENT_SPKI_SHA256" "KESAGENT_CONTROL_CLIENT_SPKI_SHA256" "BURSA_KESAGENT_KESAGENT_CONTROL_CLIENT_SPKI_SHA256" -}}
{{- range $name, $value := .Values.environment -}}
{{- if and $value (has $name $names) -}}
{{- $_ := set $pinEnv $name (ne (trimAll " ," (toString $value)) "") -}}
{{- end -}}
{{- end -}}
{{- range .Values.kesAgent.extraEnv -}}
{{- if has (toString .name) $names -}}
{{- $_ := set $pinEnv (toString .name) (or (not (empty .valueFrom)) (ne (trimAll " ," (toString (default "" .value))) "")) -}}
{{- end -}}
{{- end -}}
{{- range $role := list "sign" "control" -}}
{{- $present := not (empty (get $k (printf "%s_client_spki_sha256" $role))) -}}
{{- range $name := list (printf "KESAGENT_%s_CLIENT_SPKI_SHA256" (upper $role)) (printf "BURSA_KESAGENT_KESAGENT_%s_CLIENT_SPKI_SHA256" (upper $role)) -}}
{{- if hasKey $pinEnv $name -}}
{{- $present = get $pinEnv $name -}}
{{- end -}}
{{- end -}}
{{- if $present -}}{{- $hasClients = true -}}{{- end -}}
{{- end -}}
{{- end -}}
{{- if not $hasClients -}}
{{- fail "mode kes-agent needs sign_client_spki_sha256 or control_client_spki_sha256 authorization for at least one profile; otherwise every remote session is refused" -}}
{{- end -}}
{{- /* The config file is a ConfigMap, so a credential from a reused
     application config must not reach it. */ -}}
{{- $secretFields := list
      (list "mnemonic" (dig "mnemonic" "" $cfg))
      (list "api.jwt_secret" (dig "api" "jwt_secret" "" $cfg))
      (list "storage.dsn" (dig "storage" "dsn" "" $cfg))
      (list "signer.jwt_secret" (dig "signer" "jwt_secret" "" $cfg))
      (list "signer.watermark.dsn" (dig "signer" "watermark" "dsn" "" $cfg)) -}}
{{- range $secretFields -}}
{{- if index . 1 -}}
{{- fail (printf "kesAgent.config.%s must not be set: the config is a ConfigMap, and the KES agent does not use it" (index . 0)) -}}
{{- end -}}
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
     would undo what the chart sets or checks above. envconfig reads each
     under its BURSA_ prefixed name too: BURSA_KESAGENT_<name> for the
     kes_agent section and BURSA_METRICS_<name> for metrics. */ -}}
{{- $bare := list "KESAGENT_MODE" "KESAGENT_SERVICE_SOCKET" "KESAGENT_CONTROL_SOCKET" "KESAGENT_ATTESTED_LISTEN_ADDRESS" "KESAGENT_ATTESTED_TLS_CERT_FILE" "KESAGENT_ATTESTED_TLS_KEY_FILE" "KESAGENT_ATTESTED_CLIENT_CA_FILE" "KESAGENT_ATTESTED_PLAINTEXT" "KESAGENT_GUARD_FILE" "METRICS_LISTEN_ADDRESS" "METRICS_LISTEN_PORT" -}}
{{- $owned := list -}}
{{- range $bare -}}
{{- $owned = append $owned . -}}
{{- if hasPrefix "KESAGENT_" . -}}
{{- $owned = append $owned (printf "BURSA_KESAGENT_%s" .) -}}
{{- else -}}
{{- $owned = append $owned (printf "BURSA_METRICS_%s" .) -}}
{{- end -}}
{{- end -}}
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
{{- if and $store.dsn_env (get (default dict .Values.environment) (toString $store.dsn_env)) -}}
{{- fail (printf "%s must not be set in environment: the Deployment is readable; set it in kesAgent.extraEnv with valueFrom" (toString $store.dsn_env)) -}}
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
{{- $_ := set $store "age_identity_file" "/run/bursa/kes-agent-secrets/age-identity.txt" -}}
{{- $_ := set $k "store" $store -}}
{{- end -}}
{{- $_ := set $cfg "kes_agent" $k -}}
{{- $_ := set $cfg "metrics" (dict "address" (default "127.0.0.1" (toString .Values.kesAgent.metricsAddress)) "port" (int .Values.kesAgent.metricsPort)) -}}
{{- toYaml $cfg -}}
{{- end }}

{{- define "bursa.apiEnv" -}}
{{- $environment := default dict .root.Values.environment -}}
{{- $prefixedName := printf "BURSA_API_%s" .name -}}
{{- if hasKey $environment $prefixedName -}}
{{- printf "%v" (get $environment $prefixedName) -}}
{{- else if hasKey $environment .name -}}
{{- printf "%v" (get $environment .name) -}}
{{- else -}}
{{- .default -}}
{{- end -}}
{{- end -}}

{{- define "bursa.apiLoopback" -}}
{{- $address := include "bursa.apiEnv" (dict "root" . "name" "API_LISTEN_ADDRESS" "default" "127.0.0.1") | trim | lower -}}
{{- if or (eq $address "localhost") (regexMatch "^127(?:\\.(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])){3}$" $address) (has $address (list "::1" "[::1]")) -}}true{{- else -}}false{{- end -}}
{{- end -}}

{{- define "bursa.apiPort" -}}
{{- $port := include "bursa.apiEnv" (dict "root" . "name" "API_LISTEN_PORT" "default" "8080") -}}
{{- if or (not (regexMatch "^[0-9]+$" $port)) (lt (int $port) 1) (gt (int $port) 65535) -}}
{{- fail "API_LISTEN_PORT must be an integer between 1 and 65535" -}}
{{- end -}}
{{- int $port -}}
{{- end -}}

{{- define "bursa.apiValidation" -}}
{{- $jwks := include "bursa.apiEnv" (dict "root" . "name" "API_JWKS_URL" "default" "") | trim -}}
{{- $secret := .Values.api.auth.existingSecret | trim -}}
{{- $literalSecret := include "bursa.apiEnv" (dict "root" . "name" "API_JWT_SECRET" "default" "") -}}
{{- if and $secret $literalSecret -}}
{{- fail "api.auth.existingSecret cannot be combined with environment.API_JWT_SECRET" -}}
{{- end -}}
{{- if and $secret $jwks -}}
{{- fail "api.auth.existingSecret and API_JWKS_URL are mutually exclusive" -}}
{{- end -}}
{{- if and $literalSecret $jwks -}}
{{- fail "API_JWT_SECRET and API_JWKS_URL are mutually exclusive" -}}
{{- end -}}
{{- if and $secret (not .Values.api.auth.existingSecretKey) -}}
{{- fail "api.auth.existingSecretKey is required with api.auth.existingSecret" -}}
{{- end -}}
{{- $cert := include "bursa.apiEnv" (dict "root" . "name" "API_TLS_CERT_FILE" "default" "") -}}
{{- $key := include "bursa.apiEnv" (dict "root" . "name" "API_TLS_KEY_FILE" "default" "") -}}
{{- if and .Values.api.tls.secretName (or $cert $key) -}}
{{- fail "api.tls.secretName cannot be combined with API_TLS_CERT_FILE or API_TLS_KEY_FILE" -}}
{{- end -}}
{{- if ne (empty $cert) (empty $key) -}}
{{- fail "API_TLS_CERT_FILE and API_TLS_KEY_FILE must both be configured" -}}
{{- end -}}
{{- if and (or $secret $literalSecret $jwks) (not (include "bursa.apiEnv" (dict "root" . "name" "API_JWT_AUDIENCE" "default" "") | trim)) -}}
{{- fail "API_JWT_AUDIENCE is required with API JWT/JWKS authentication" -}}
{{- end -}}
{{- if eq (include "bursa.apiLoopback" .) "false" -}}
{{- if not (or $secret $literalSecret $jwks) -}}
{{- fail "a non-loopback API_LISTEN_ADDRESS requires api.auth.existingSecret or API_JWKS_URL" -}}
{{- end -}}
{{- if not (or .Values.api.tls.secretName (and $cert $key)) -}}
{{- fail "a non-loopback API_LISTEN_ADDRESS requires api.tls.secretName or API TLS files" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- /* Non-empty when the KES agent's metrics listener binds loopback, by
     the rule Bursa applies (netip.Addr.IsLoopback): an empty address (Bursa
     binds 127.0.0.1), localhost, 127.0.0.0/8, or ::1 in any spelling,
     including IPv4-mapped 127.0.0.0/8 (::ffff:127.0.0.1, ::ffff:7f00:1).
     Brackets and an IPv6 zone are ignored. */ -}}
{{- define "bursa.kesAgentMetricsLoopback" -}}
{{- $a := toString .Values.kesAgent.metricsAddress | trim | lower -}}
{{- if and (hasPrefix "[" $a) (hasSuffix "]" $a) -}}
{{- $a = $a | trimPrefix "[" | trimSuffix "]" -}}
{{- end -}}
{{- $a = splitList "%" $a | first -}}
{{- $v4lo := "^127\\.(25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])(\\.(25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])){2}$" -}}
{{- if or (eq $a "") (eq $a "localhost") (regexMatch $v4lo $a) -}}
true
{{- else if contains ":" $a -}}
{{- $halves := splitList "::" $a -}}
{{- if le (len $halves) 2 -}}
{{- $head := list -}}
{{- if ne (index $halves 0) "" -}}{{- $head = splitList ":" (index $halves 0) -}}{{- end -}}
{{- $tail := list -}}
{{- if and (eq (len $halves) 2) (ne (index $halves 1) "") -}}{{- $tail = splitList ":" (index $halves 1) -}}{{- end -}}
{{- /* A trailing dotted quad fills the last two groups. */ -}}
{{- $v4 := "" -}}
{{- $width := 8 -}}
{{- if and $tail (contains "." (last $tail)) -}}
{{- $v4 = last $tail -}}{{- $tail = initial $tail -}}{{- $width = 6 -}}
{{- else if and (not $tail) $head (eq (len $halves) 1) (contains "." (last $head)) -}}
{{- $v4 = last $head -}}{{- $head = initial $head -}}{{- $width = 6 -}}
{{- end -}}
{{- $fill := sub $width (add (len $head) (len $tail)) | int -}}
{{- $ok := or (and (eq (len $halves) 1) (eq $fill 0)) (and (eq (len $halves) 2) (ge $fill 1)) -}}
{{- $groups := $head -}}
{{- range until (max $fill 0 | int) -}}{{- $groups = append $groups "0" -}}{{- end -}}
{{- $groups = concat $groups $tail -}}
{{- range $groups -}}{{- if not (regexMatch "^[0-9a-f]{1,4}$" .) -}}{{- $ok = false -}}{{- end -}}{{- end -}}
{{- if $ok -}}
{{- $zero := true -}}
{{- range $i, $g := $groups -}}
{{- if and (lt $i 5) (not (regexMatch "^0+$" $g)) -}}{{- $zero = false -}}{{- end -}}
{{- end -}}
{{- if $v4 -}}
{{- if and $zero (eq (index $groups 5) "ffff") (regexMatch $v4lo $v4) -}}true{{- end -}}
{{- else -}}
{{- $g5 := index $groups 5 -}}{{- $g6 := index $groups 6 -}}{{- $g7 := index $groups 7 -}}
{{- if and $zero (regexMatch "^0+$" $g5) (regexMatch "^0+$" $g6) (regexMatch "^0{0,3}1$" $g7) -}}true
{{- else if and $zero (eq $g5 "ffff") (regexMatch "^7f[0-9a-f]{2}$" $g6) -}}true
{{- end -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- end -}}
