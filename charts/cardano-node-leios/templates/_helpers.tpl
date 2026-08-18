{{- define "cardano-node-leios.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "cardano-node-leios.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "cardano-node-leios.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "cardano-node-leios.labels" -}}
app.kubernetes.io/name: {{ include "cardano-node-leios.name" . }}
helm.sh/chart: {{ include "cardano-node-leios.chart" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
cardano_network: {{ .Values.cardano_network }}
cardano_service: cardano-node-leios
{{- end -}}

{{- define "cardano-node-leios.matchLabels" -}}
app.kubernetes.io/name: {{ include "cardano-node-leios.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
cardano_network: {{ .Values.cardano_network }}
cardano_service: cardano-node-leios
{{- end -}}

{{/*
The pinned config.json, with the Prometheus bind address rebound from
127.0.0.1 (unreachable via pod IP) to 0.0.0.0. Shared by configmap.yaml
(actual content) and statefulset.yaml (checksum annotation) so the two
can never drift apart.
*/}}
{{- define "cardano-node-leios.renderedConfig" -}}
{{- .Files.Get "files/musashi/config.json" | replace "PrometheusSimple suffix 127.0.0.1 12798" "PrometheusSimple suffix 0.0.0.0 12798" -}}
{{- end -}}
