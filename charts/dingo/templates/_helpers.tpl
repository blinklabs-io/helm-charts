{{- define "dingo.name" -}}
{{ .Chart.Name }}
{{- end }}

{{- define "dingo.fullname" -}}
{{ .Release.Name }}
{{- end }}

{{- define "dingo.labels" -}}
app.kubernetes.io/name: {{ include "dingo.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}
