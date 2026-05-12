{{/* vim: set filetype=mustache: */}}
{{/*
Expand the name of the chart.
*/}}
{{- define "hsd.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "hsd.fullname" -}}
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
Network-aware fullname
*/}}
{{- define "hsd.network-fullname" -}}
{{- $name := include "hsd.fullname" . -}}
{{- $network := include "hsd.network" . -}}
{{- printf "%s-%s" $name $network -}}
{{- end -}}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "hsd.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Define Handshake network.
*/}}
{{- define "hsd.network" -}}
{{- if .Values.handshake_network -}}
{{ .Values.handshake_network }}
{{- else -}}
"main"
{{- end -}}
{{- end -}}

{{/*
Define port helpers based on network
*/}}
{{- define "hsd.p2p-port" -}}
{{- $network := include "hsd.network" . -}}
{{- index .Values.networkPorts $network "p2p" -}}
{{- end -}}

{{- define "hsd.brontide-port" -}}
{{- $network := include "hsd.network" . -}}
{{- index .Values.networkPorts $network "brontide" -}}
{{- end -}}

{{- define "hsd.http-port" -}}
{{- $network := include "hsd.network" . -}}
{{- index .Values.networkPorts $network "http" -}}
{{- end -}}

{{- define "hsd.ns-port" -}}
{{- $network := include "hsd.network" . -}}
{{- index .Values.networkPorts $network "ns" -}}
{{- end -}}

{{- define "hsd.rs-port" -}}
{{- $network := include "hsd.network" . -}}
{{- index .Values.networkPorts $network "rs" -}}
{{- end -}}

{{/*
Define resource requirements based on network
*/}}
{{- define "hsd.resources" -}}
{{- $network := include "hsd.network" . -}}
{{ toYaml (index .Values.networkResources $network) }}
{{- end -}}

{{/*
Define storage size based on network
*/}}
{{- define "hsd.storage-size" -}}
{{- $network := include "hsd.network" . -}}
{{- if .Values.storage.size -}}
{{- .Values.storage.size -}}
{{- else -}}
{{- index .Values.networkStorage $network -}}
{{- end -}}
{{- end -}}

{{/*
Common labels
*/}}
{{- define "hsd.labels" -}}
app.kubernetes.io/name: {{ include "hsd.name" . }}
helm.sh/chart: {{ include "hsd.chart" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
handshake_network: {{ include "hsd.network" . }}
{{- end -}}
