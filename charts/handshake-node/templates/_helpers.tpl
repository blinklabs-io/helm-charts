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
Handshake network selector. Fails template rendering for unsupported values so
labels and daemon flags cannot silently disagree. Restricted to the networks
the upstream handshake-node image actually implements as CLI flags; testnet
and simnet are rejected by the daemon and therefore not offered here.
*/}}
{{- define "handshake-node.network" -}}
{{- $n := default "main" .Values.network -}}
{{- $valid := list "main" "regtest" -}}
{{- if not (has $n $valid) -}}
{{- fail (printf "handshake-node: unsupported network %q. Supported: main, regtest." $n) -}}
{{- end -}}
{{- $n -}}
{{- end -}}

{{/*
Suffix-aware component name. Truncates the fullname so the returned value
stays within the 63-character DNS label limit even when a long release name
or fullnameOverride is combined with a component suffix like "-p2p".
Call as: include "handshake-node.componentName" (dict "ctx" . "suffix" "-p2p")
*/}}
{{- define "handshake-node.componentName" -}}
{{- $ctx := .ctx -}}
{{- $suffix := .suffix -}}
{{- $max := int (sub 63 (len $suffix)) -}}
{{- printf "%s%s" (include "handshake-node.fullname" $ctx | trunc $max | trimSuffix "-") $suffix -}}
{{- end -}}

{{/*
Name of the headless Service backing the StatefulSet.
*/}}
{{- define "handshake-node.headlessName" -}}
{{- include "handshake-node.componentName" (dict "ctx" . "suffix" "-headless") -}}
{{- end -}}

{{/*
Per-component Service names. Each reserves the suffix length so a maximum
63-char fullname override still renders a valid Service name.
*/}}
{{- define "handshake-node.p2pName" -}}
{{- include "handshake-node.componentName" (dict "ctx" . "suffix" "-p2p") -}}
{{- end -}}
{{- define "handshake-node.rpcName" -}}
{{- include "handshake-node.componentName" (dict "ctx" . "suffix" "-rpc") -}}
{{- end -}}
{{- define "handshake-node.metricsName" -}}
{{- include "handshake-node.componentName" (dict "ctx" . "suffix" "-metrics") -}}
{{- end -}}
{{- define "handshake-node.stratumName" -}}
{{- include "handshake-node.componentName" (dict "ctx" . "suffix" "-stratum") -}}
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
Selector labels. Deliberately excludes handshake_network because
StatefulSet.spec.selector is immutable in Kubernetes; a network change on
helm upgrade would fail with `spec: Forbidden`. name + instance already
isolate the release. The network label is still exposed on general resource
and pod metadata via handshake-node.labels for observability.
*/}}
{{- define "handshake-node.matchLabels" -}}
app.kubernetes.io/name: {{ include "handshake-node.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
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
Defaults to rpc.enabled when rpcService.enabled is unset (null). Never renders
unless rpc.enabled is true so the Service always has a backend.
*/}}
{{- define "handshake-node.rpcService.enabled" -}}
{{- if not .Values.rpc.enabled -}}
{{- "false" -}}
{{- else if kindIs "invalid" .Values.rpcService.enabled -}}
{{- "true" -}}
{{- else -}}
{{- ternary "true" "false" .Values.rpcService.enabled -}}
{{- end -}}
{{- end -}}
