{{- define "adder.name" -}}
{{ .Chart.Name }}
{{- end }}

{{- define "adder.fullname" -}}
{{ .Release.Name }}
{{- end }}

{{- define "adder.selectorLabels" -}}
app.kubernetes.io/name: {{ include "adder.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "adder.labels" -}}
app.kubernetes.io/name: {{ include "adder.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "adder.serviceAccountName" -}}
{{ .Values.serviceAccount.name | default (printf "%s-sa" .Release.Name) }}
{{- end -}}
