{{/*
Expand the name of the chart.
*/}}
{{- define "extBlockfrostOperator.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a fully qualified app name.
*/}}
{{- define "extBlockfrostOperator.fullname" -}}
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
{{- define "extBlockfrostOperator.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Common labels.
*/}}
{{- define "extBlockfrostOperator.labels" -}}
helm.sh/chart: {{ include "extBlockfrostOperator.chart" . }}
{{ include "extBlockfrostOperator.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/*
Selector labels.
*/}}
{{- define "extBlockfrostOperator.selectorLabels" -}}
app.kubernetes.io/name: {{ include "extBlockfrostOperator.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
