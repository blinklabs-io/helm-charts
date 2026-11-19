{{/*
Labels on chart-owned objects.
*/}}
{{- define "dingonodes.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: {{ .Release.Name | quote }}
{{- end }}

{{/*
helm.sh/resource-policy: keep while .Values.keep is set, so uninstalling or
renaming the release leaves the object in place for another release to adopt.
*/}}
{{- define "dingonodes.keepAnnotations" -}}
{{- if .Values.keep -}}
annotations:
  helm.sh/resource-policy: keep
{{- end }}
{{- end }}
