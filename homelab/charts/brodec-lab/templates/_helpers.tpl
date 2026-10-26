{{- define "brodec-lab.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "brodec-lab.selector" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "brodec-lab.labels" -}}
{{ include "brodec-lab.selector" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{- define "brodec-lab.labName" -}}
{{- $name := .Values.lab.name | default .Release.Name -}}
{{- if not (regexMatch "^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$" $name) -}}
{{- fail "lab.name: use 1 to 48 letters, digits, - and _" -}}
{{- end -}}
{{- $name -}}
{{- end -}}

{{- define "brodec-lab.switchSecret" -}}
{{- if .Values.switch.create -}}{{ include "brodec-lab.fullname" . }}-switch{{- else -}}{{ required "switch.existingSecret is needed when switch.create is false" .Values.switch.existingSecret }}{{- end -}}
{{- end -}}

{{/* The TCP port of a URL: its own, or 443/80 by scheme. */}}
{{- define "brodec-lab.port" -}}
{{- $u := urlParse . -}}
{{- $p := regexFind ":[0-9]+$" $u.host | trimPrefix ":" -}}
{{- if $p -}}{{ $p }}{{- else if eq $u.scheme "https" -}}443{{- else -}}80{{- end -}}
{{- end -}}
