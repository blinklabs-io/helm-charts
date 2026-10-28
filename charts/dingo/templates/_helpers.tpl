{{/* vim: set filetype=mustache: */}}
{{/*
Expand the name of the chart.
*/}}
{{- define "dingo.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "dingo.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "dingo.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Container image reference. Prefers an immutable digest when image.digest is set
(repository@sha256:...); otherwise falls back to repository:tag.
*/}}
{{- define "dingo.image" -}}
{{- if .Values.image.digest -}}
{{- printf "%s@%s" .Values.image.repository .Values.image.digest -}}
{{- else -}}
{{- printf "%s:%s" .Values.image.repository (.Values.image.tag | toString) -}}
{{- end -}}
{{- end -}}

{{- define "dingo.tieredServiceName" -}}
{{- $maxBase := int (sub 62 (len .tier)) -}}
{{- printf "%s-%s" (include "dingo.fullname" .root | trunc $maxBase | trimSuffix "-") .tier -}}
{{- end -}}

{{/*
Define Cardano network from environment map.
*/}}
{{- define "dingo.network" -}}
{{- if .Values.environment.CARDANO_NETWORK -}}
{{ .Values.environment.CARDANO_NETWORK }}
{{- else -}}
preview
{{- end -}}
{{- end -}}

{{/*
Common labels
*/}}
{{- define "dingo.labels" -}}
app.kubernetes.io/name: {{ include "dingo.name" . }}
helm.sh/chart: {{ include "dingo.chart" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
cardano_network: {{ include "dingo.network" . }}
cardano_service: dingo
{{- end -}}

{{/*
Selector labels
*/}}
{{- define "dingo.matchLabels" -}}
app.kubernetes.io/name: {{ include "dingo.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
cardano_network: {{ include "dingo.network" . }}
cardano_service: dingo
{{- end -}}

{{- define "dingo.blockProducer.keysSecretName" -}}
{{- if .Values.blockProducer.existingSecret -}}
{{- .Values.blockProducer.existingSecret -}}
{{- else -}}
{{- printf "%s-keys" (include "dingo.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/*
Validate the block producer key source when block production is enabled.
*/}}
{{- define "dingo.blockProducer.validateKeys" -}}
{{- if .Values.blockProducer.existingSecret -}}
{{- if .Values.blockProducer.keys -}}
{{- fail "blockProducer.existingSecret and blockProducer.keys are mutually exclusive; remove blockProducer.keys when using an existing Secret" -}}
{{- end -}}
{{- $_ := required "blockProducer.kesKey is required when blockProducer.existingSecret is set" .Values.blockProducer.kesKey -}}
{{- $_ := required "blockProducer.opCertKey is required when blockProducer.existingSecret is set" .Values.blockProducer.opCertKey -}}
{{- $_ := required "blockProducer.vrfKey is required when blockProducer.existingSecret is set" .Values.blockProducer.vrfKey -}}
{{- else -}}
{{- $keys := required "blockProducer.keys is required when blockProducer.enabled=true" .Values.blockProducer.keys -}}
{{- $keyNames := dict -}}
{{- range $keys }}
{{- $_ := set $keyNames .name true -}}
{{- end -}}
{{- $_ := required "blockProducer.keys must include kes.skey" (get $keyNames "kes.skey") -}}
{{- $_ := required "blockProducer.keys must include node.cert" (get $keyNames "node.cert") -}}
{{- $_ := required "blockProducer.keys must include vrf.skey" (get $keyNames "vrf.skey") -}}
{{- end -}}
{{- end -}}

{{/*
Renders "true" when a Leios BLS vote signing key is configured, otherwise
renders nothing so it can be used as a condition.
*/}}
{{- define "dingo.blockProducer.blsEnabled" -}}
{{- if .Values.blockProducer.existingSecret -}}
{{- .Values.blockProducer.blsKey | default "" -}}
{{- else -}}
{{- range .Values.blockProducer.keys -}}
{{- if eq .name "bls.skey" -}}true{{- end -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "dingo.availabilityConfig" -}}
{{- $healthPort := .Values.availability.healthPort -}}
{{- if hasKey .Values.environment "DINGO_HEALTH_PORT" -}}
{{- $healthPort = index .Values.environment "DINGO_HEALTH_PORT" -}}
{{- end -}}
{{- $lag := .Values.availability.maxSlotLag -}}
{{- if hasKey .Values.environment "DINGO_HEALTH_READY_GAP_SLOTS" -}}
{{- $lag = index .Values.environment "DINGO_HEALTH_READY_GAP_SLOTS" -}}
{{- end -}}
{{- if or (not (regexMatch "^[0-9]+$" (toString $healthPort))) (lt (int $healthPort) 1) (gt (int $healthPort) 65535) -}}
{{- fail "availability requires a nonzero health port; check DINGO_HEALTH_PORT" -}}
{{- end -}}
{{- if or (not (regexMatch "^[0-9]+$" (toString $lag))) (lt (int $lag) 1) -}}
{{- fail "availability requires a positive maxSlotLag; check DINGO_HEALTH_READY_GAP_SLOTS" -}}
{{- end -}}
{{- if le (int .Values.availability.terminationGracePeriodSeconds) (int .Values.availability.drainDelaySeconds) -}}
{{- fail "availability.terminationGracePeriodSeconds must exceed drainDelaySeconds" -}}
{{- end -}}
{{- if and (gt (int .Values.availability.drainDelaySeconds) 0) (not (semverCompare ">=1.30.0-0" .Capabilities.KubeVersion.Version)) -}}
{{- fail "availability.drainDelaySeconds requires Kubernetes 1.30 or newer; set it to zero to omit native lifecycle sleep" -}}
{{- end -}}
{{- $ports := list -}}
{{- $reserved := list -}}
{{- range $name, $env := dict "relay" "CARDANO_PORT" "private" "CARDANO_PRIVATE_PORT" "metrics" "CARDANO_METRICS_PORT" -}}
{{- $port := default (index $.Values.service.ports $name) (index $.Values.environment $env) -}}
{{- if or (not (regexMatch "^[0-9]+$" (toString $port))) (gt (int $port) 65535) -}}
{{- fail (printf "availability requires a valid %s listener port" $name) -}}
{{- end -}}
{{- $reserved = append $reserved (int $port) -}}
{{- if and (gt (int $port) 0) (or (eq $name "relay") (and (eq $name "private") $.Values.service.private.enabled)) -}}
{{- $ports = append $ports (int $port) -}}
{{- end -}}
{{- end -}}
{{- $blockfrostPort := 0 -}}
{{- if eq (lower (toString (get .Values.environment "DINGO_STORAGE_MODE"))) "api" -}}
{{- $listeners := dict "utxorpc" "DINGO_UTXORPC_PORT" "blockfrost" "DINGO_BLOCKFROST_PORT" "mesh" "DINGO_MESH_PORT" "kupo" "DINGO_PLUGINS_API_KUPO_CONFIG_PORT" "bark" "DINGO_BARK_PORT" "midnight" "DINGO_MIDNIGHT_PORT" -}}
{{- range $name, $env := $listeners -}}
{{- $port := default "0" (default (index $.Values.service.ports $name) (index $.Values.environment $env)) -}}
{{- if or (not (regexMatch "^[0-9]+$" (toString $port))) (gt (int $port) 65535) -}}
{{- fail (printf "availability requires a valid %s listener port" $name) -}}
{{- end -}}
{{- if gt (int $port) 0 -}}
{{- $ports = append $ports (int $port) -}}
{{- if eq $name "blockfrost" -}}{{- $blockfrostPort = int $port -}}{{- end -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- $scheme := .Values.availability.blockfrostScheme -}}
{{- if eq $scheme "auto" -}}
{{- $scheme = ternary "https" "http" (eq (get .Values.environment "DINGO_API_TLS_MODE") "server") -}}
{{- end -}}
{{- $ports = uniq $ports -}}
{{- if has (int $healthPort) (concat $reserved $ports) -}}
{{- fail "availability healthPort must not conflict with a node, metrics or API listener" -}}
{{- end -}}
{{- $budget := add 2 (mul (int .Values.availability.requestTimeoutSeconds) (add 1 (len $ports) (ternary 1 0 (gt $blockfrostPort 0)))) -}}
{{- dict "healthPort" (int $healthPort) "maxSlotLag" (int $lag) "listenerPorts" $ports "blockfrostPort" $blockfrostPort "blockfrostScheme" $scheme "timeoutSeconds" $budget | toJson -}}
{{- end -}}
