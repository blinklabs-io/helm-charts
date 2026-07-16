{{/* vim: set filetype=mustache: */}}
{{/*
Expand the name of the chart.
*/}}
{{- define "handshake-node.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Fully qualified app name.
*/}}
{{- define "handshake-node.fullname" -}}
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
Chart name/version label.
*/}}
{{- define "handshake-node.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Handshake network selector.
*/}}
{{- define "handshake-node.network" -}}
{{- default "main" .Values.network -}}
{{- end -}}

{{/*
Common labels
*/}}
{{- define "handshake-node.labels" -}}
app.kubernetes.io/name: {{ include "handshake-node.name" . }}
helm.sh/chart: {{ include "handshake-node.chart" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
handshake_network: {{ include "handshake-node.network" . }}
{{- end -}}

{{/*
Selector labels
*/}}
{{- define "handshake-node.matchLabels" -}}
app.kubernetes.io/name: {{ include "handshake-node.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
handshake_network: {{ include "handshake-node.network" . }}
{{- end -}}

{{/*
Service account name.
*/}}
{{- define "handshake-node.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "handshake-node.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/*
Return "true" when the private RPC ClusterIP Service should be rendered.
Defaults to rpc.enabled when rpcService.enabled is unset (null).
*/}}
{{- define "handshake-node.rpcService.enabled" -}}
{{- if kindIs "invalid" .Values.rpcService.enabled -}}
{{- ternary "true" "false" .Values.rpc.enabled -}}
{{- else -}}
{{- ternary "true" "false" .Values.rpcService.enabled -}}
{{- end -}}
{{- end -}}
