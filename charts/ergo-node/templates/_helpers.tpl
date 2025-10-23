{{/* vim: set filetype=mustache: */}}
{{/*
Expand the name of the chart.
*/}}
{{- define "ergo-node.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "ergo-node.fullname" -}}
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
Network-aware fullname
*/}}
{{- define "ergo-node.network-fullname" -}}
{{- $name := include "ergo-node.fullname" . -}}
{{- $network := include "ergo-node.network" . -}}
{{- printf "%s-%s" $name $network | trunc 63 | trimSuffix "-" -}}
{{- end -}}


{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "ergo-node.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}


{{/*
Define ergo network.
*/}}
{{- define "ergo-node.network" -}}
{{- if .Values.ergo_network -}}
{{ .Values.ergo_network }}
{{- else -}}
mainnet
{{- end -}}
{{- end -}}

{{/*
Common labels
*/}}
{{- define "ergo-node.labels" -}}
app.kubernetes.io/name: {{ include "ergo-node.name" . }}
helm.sh/chart: {{ include "ergo-node.chart" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
ergo_network: {{ include "ergo-node.network" . }}
ergo_service: ergo-node
{{- end -}}

{{/*
ergo node selector labels
*/}}
{{- define "ergo-node.matchLabels" -}}
app.kubernetes.io/name: {{ include "ergo-node.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
ergo_network: {{ include "ergo-node.network" . }}
ergo_service: ergo-node
{{- end -}}
