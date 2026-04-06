{{/*
Expand the name of the chart.
If .Values.nameOverride is not set, use .Chart.Name.
*/}}
{{- define "extUtxorpcOperator.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a fully qualified app name.
If .Values.fullnameOverride is set, use it.
Otherwise, combine .Release.Name and chart name (or nameOverride).
*/}}
{{- define "extUtxorpcOperator.fullname" -}}
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
{{- define "extUtxorpcOperator.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Common labels.
*/}}
{{- define "extUtxorpcOperator.labels" -}}
helm.sh/chart: {{ include "extUtxorpcOperator.chart" . }}
{{ include "extUtxorpcOperator.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/*
Selector labels.
*/}}
{{- define "extUtxorpcOperator.selectorLabels" -}}
app.kubernetes.io/name: {{ include "extUtxorpcOperator.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Build the EXTENSION_URL_PER_NETWORK value from the extensionUrlsPerNetwork map.
*/}}
{{- define "extUtxorpcOperator.extensionUrlsPerNetwork" -}}
{{- $pairs := list -}}
{{- range $network, $url := .Values.extensionUrlsPerNetwork -}}
  {{- $pairs = append $pairs (printf "%s=%s" $network $url) -}}
{{- end -}}
{{- sortAlpha $pairs | join "," -}}
{{- end -}}
