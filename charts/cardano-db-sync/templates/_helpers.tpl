{{/* vim: set filetype=mustache: */}}
{{/*
Expand the name of the chart.
*/}}
{{- define "cardano-db-sync.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "cardano-db-sync.fullname" -}}
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
{{- define "cardano-db-sync.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}


{{/*
Define Cardano network.
*/}}
{{- define "cardano-db-sync.network" -}}
{{- if .Values.cardano_network -}}
{{ .Values.cardano_network }}
{{- else -}}
"preview"
{{- end -}}
{{- end -}}

{{/*
Common labels
*/}}
{{- define "cardano-db-sync.labels" -}}
app.kubernetes.io/name: {{ include "cardano-db-sync.fullname" . }}
helm.sh/chart: {{ include "cardano-db-sync.chart" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
cardano_network: {{ include "cardano-db-sync.network" . }}
cardano_service: cardano-db-sync
{{- end -}}

{{/*
cardano-db-sync selector labels
*/}}
{{- define "cardano-db-sync.selectorLabels" -}}
app.kubernetes.io/name: {{ include "cardano-db-sync.fullname" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
cardano_network: {{ include "cardano-db-sync.network" . }}
cardano_service: cardano-db-sync
{{- end -}}
