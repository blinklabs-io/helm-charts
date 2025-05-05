{{- define "cdnsd.name" -}}
{{ .Chart.Name }}
{{- end }}

{{- define "cdnsd.fullname" -}}
{{ .Release.Name }}
{{- end }}

{{- define "cdnsd.selectorLabels" -}}
app.kubernetes.io/name: {{ include "cdnsd.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "cdnsd.labels" -}}
app.kubernetes.io/name: {{ include "cdnsd.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "cdnsd.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "cdnsd.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}