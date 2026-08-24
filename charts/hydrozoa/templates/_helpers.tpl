{{/* Expand the chart name. */}}
{{- define "hydrozoa.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Build the fully qualified application name. */}}
{{- define "hydrozoa.fullname" -}}
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

{{/* Chart name and version for labels. */}}
{{- define "hydrozoa.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Append a suffix while retaining the Kubernetes 63-character limit. */}}
{{- define "hydrozoa.componentName" -}}
{{- $ctx := .ctx -}}
{{- $suffix := .suffix -}}
{{- $max := int (sub 63 (len $suffix)) -}}
{{- printf "%s%s" (include "hydrozoa.fullname" $ctx | trunc $max | trimSuffix "-") $suffix -}}
{{- end -}}

{{- define "hydrozoa.headlessName" -}}
{{- include "hydrozoa.componentName" (dict "ctx" . "suffix" "-headless") -}}
{{- end -}}

{{/* Validate and return the Kubernetes-facing node role. */}}
{{- define "hydrozoa.role" -}}
{{- $role := required "node.role is required (supported values: head, coil)" .Values.node.role -}}
{{- if not (has $role (list "head" "coil")) -}}
{{- fail (printf "hydrozoa: unsupported node.role %q. Supported values: head, coil." $role) -}}
{{- end -}}
{{- $role -}}
{{- end -}}

{{/* Common labels. */}}
{{- define "hydrozoa.labels" -}}
helm.sh/chart: {{ include "hydrozoa.chart" . }}
{{ include "hydrozoa.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/component: {{ include "hydrozoa.role" . }}
{{- end -}}

{{/* Stable selector labels; role and versions are deliberately excluded. */}}
{{- define "hydrozoa.selectorLabels" -}}
app.kubernetes.io/name: {{ include "hydrozoa.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* Service account name. */}}
{{- define "hydrozoa.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "hydrozoa.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}
