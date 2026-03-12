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

{{/*
Validate required block producer key files when block production is enabled.
*/}}
{{- define "dingo.blockProducer.validateKeys" -}}
{{- $keys := required "blockProducer.keys is required when blockProducer.enabled=true" .Values.blockProducer.keys -}}
{{- $keyNames := dict -}}
{{- range $keys }}
{{- $_ := set $keyNames .name true -}}
{{- end -}}
{{- $_ := required "blockProducer.keys must include kes.skey" (get $keyNames "kes.skey") -}}
{{- $_ := required "blockProducer.keys must include node.cert" (get $keyNames "node.cert") -}}
{{- $_ := required "blockProducer.keys must include vrf.skey" (get $keyNames "vrf.skey") -}}
{{- end -}}
