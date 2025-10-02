{{/*
Expand the name of the chart.
If .Values.nameOverride is not set, use .Chart.Name.
*/}}
{{- define "extOgmiosOperator.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a fully qualified app name.
If .Values.fullnameOverride is set, use it.
Otherwise, combine .Release.Name and chart name (or nameOverride).
*/}}
{{- define "extOgmiosOperator.fullname" -}}
{{- if .Values.fullnameOverride -}}
  {{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" | lower -}}
{{- else -}}
  {{- $name := default .Chart.Name .Values.nameOverride -}}
  {{- if contains $name .Release.Name -}}
    {{- .Release.Name | trunc 63 | trimSuffix "-" | lower -}}
  {{- else -}}
    {{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" | lower -}}
  {{- end -}}
{{- end -}}
{{- end -}}

{{/*
Chart name and version for the chart label.
*/}}
{{- define "extOgmiosOperator.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Common labels.
*/}}
{{- define "extOgmiosOperator.labels" -}}
helm.sh/chart: {{ include "extOgmiosOperator.chart" . }}
{{ include "extOgmiosOperator.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/*
Selector labels.
*/}}
{{- define "extOgmiosOperator.selectorLabels" -}}
app.kubernetes.io/name: {{ include "extOgmiosOperator.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
