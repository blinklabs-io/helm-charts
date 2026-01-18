{{/*
Expand the name of the chart.
*/}}
{{- define "wireguard.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "wireguard.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "wireguard.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "wireguard.labels" -}}
helm.sh/chart: {{ include "wireguard.chart" . }}
{{ include "wireguard.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "wireguard.selectorLabels" -}}
app.kubernetes.io/name: {{ include "wireguard.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app: wireguard
region: {{ .Values.region }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "wireguard.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "wireguard.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Get the WireGuard private key secret name
*/}}
{{- define "wireguard.secretName" -}}
{{- if .Values.wireguard.existingSecret }}
{{- .Values.wireguard.existingSecret }}
{{- else }}
{{- printf "%s-keys" (include "wireguard.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{/*
Get the JWT public key ConfigMap name
*/}}
{{- define "wireguard.jwtConfigMapName" -}}
{{- if .Values.api.existingJwtConfigMap }}
{{- .Values.api.existingJwtConfigMap }}
{{- else }}
{{- printf "%s-jwt-pubkey" (include "wireguard.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
