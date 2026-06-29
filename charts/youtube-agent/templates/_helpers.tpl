{{/*
앱 이름 (릴리즈명 또는 차트명으로 제한 63자)
*/}}
{{- define "youtube-agent.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "youtube-agent.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name (include "youtube-agent.name" .) | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "youtube-agent.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
app.kubernetes.io/name: {{ include "youtube-agent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "youtube-agent.selectorLabels" -}}
app.kubernetes.io/name: {{ include "youtube-agent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
