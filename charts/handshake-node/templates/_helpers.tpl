{{/* vim: set filetype=mustache: */}}
{{/*
Expand the name of the chart.
*/}}
{{- define "handshake-node.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
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
Network-aware fullname
*/}}
{{- define "handshake-node.network-fullname" -}}
{{- $name := include "handshake-node.fullname" . -}}
{{- $network := include "handshake-node.network" . -}}
{{- printf "%s-%s" $name $network -}}
{{- end -}}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "handshake-node.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Define Handshake network.
*/}}
{{- define "handshake-node.network" -}}
{{- if .Values.handshake_network -}}
{{ .Values.handshake_network }}
{{- else -}}
"main"
{{- end -}}
{{- end -}}

{{/*
Define port helpers based on network
*/}}
{{- define "handshake-node.p2p-port" -}}
{{- $network := include "handshake-node.network" . -}}
{{- index .Values.networkPorts $network "p2p" -}}
{{- end -}}

{{- define "handshake-node.brontide-port" -}}
{{- $network := include "handshake-node.network" . -}}
{{- index .Values.networkPorts $network "brontide" -}}
{{- end -}}

{{- define "handshake-node.http-port" -}}
{{- $network := include "handshake-node.network" . -}}
{{- index .Values.networkPorts $network "http" -}}
{{- end -}}

{{- define "handshake-node.ns-port" -}}
{{- $network := include "handshake-node.network" . -}}
{{- index .Values.networkPorts $network "ns" -}}
{{- end -}}

{{- define "handshake-node.rs-port" -}}
{{- $network := include "handshake-node.network" . -}}
{{- index .Values.networkPorts $network "rs" -}}
{{- end -}}

{{/*
Define resource requirements based on network
*/}}
{{- define "handshake-node.resources" -}}
{{- $network := include "handshake-node.network" . -}}
{{- if .Values.resources -}}
{{- toYaml .Values.resources -}}
{{- else -}}
{{- toYaml (index .Values.networkResources $network) -}}
{{- end -}}
{{- end -}}

{{/*
Define storage size based on network
*/}}
{{- define "handshake-node.storage-size" -}}
{{- $network := include "handshake-node.network" . -}}
{{- if .Values.storage.size -}}
{{- .Values.storage.size -}}
{{- else -}}
{{- index .Values.networkStorage $network -}}
{{- end -}}
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
