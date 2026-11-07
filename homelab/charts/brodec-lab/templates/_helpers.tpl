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

{{/* The guests' brain as {url, model, keySecret}: guestBrain's own, or with sameAsBrain the
     lab's brain. Empty url: no guest brain (guests get a polite "can't answer"). */}}
{{- define "brodec-lab.guestBrain" -}}
{{- $g := .Values.guestBrain | default dict -}}
{{- if $g.sameAsBrain -}}
{{- if $g.url -}}{{- fail "guestBrain: set sameAsBrain or url, not both" -}}{{- end -}}
{{- toYaml (dict "url" .Values.brain.url "model" .Values.brain.model "keySecret" .Values.brain.keySecret) -}}
{{- else -}}
{{- toYaml (dict "url" ($g.url | default "") "model" ($g.model | default "") "keySecret" ($g.keySecret | default (dict "name" "" "key" "key"))) -}}
{{- end -}}
{{- end -}}

{{/* The media server's image: the tag, pinned to its digest when one is set; the ffmpeg build
     when the lab transcodes. */}}
{{- define "brodec-lab.mediamtxImage" -}}
{{- $m := .Values.mediaServer.image -}}
{{- $ffmpeg := ne (.Values.mediaServer.transcode | default "none") "none" -}}
{{- $tag := ternary (printf "%s-ffmpeg" $m.tag) $m.tag $ffmpeg -}}
{{- $digest := ternary $m.ffmpegDigest $m.digest $ffmpeg -}}
{{- if $digest -}}{{ $m.repository }}:{{ $tag }}@{{ $digest }}{{- else -}}{{ $m.repository }}:{{ $tag }}{{- end -}}
{{- end -}}

{{/* The media server's ports devices use: name, port, protocol, and whether the tailnet
     forwards it (TCP only: the tailnet sidecar runs in userspace). The control API (9997) and
     the bridge's auth hook (9108) are never here. */}}
{{- define "brodec-lab.mediaPorts" -}}
- { name: rtmp, port: 1935, protocol: TCP, tailnet: true }
- { name: srt, port: 8890, protocol: UDP, tailnet: false }
- { name: webrtc, port: 8889, protocol: TCP, tailnet: true }
- { name: ice-udp, port: 8189, protocol: UDP, tailnet: false }
- { name: ice-tcp, port: 8189, protocol: TCP, tailnet: true }
- { name: hls, port: 8888, protocol: TCP, tailnet: true }
{{- if .Values.mediaServer.recording.existingClaim }}
- { name: playback, port: 9996, protocol: TCP, tailnet: true }
{{- end }}
{{- end -}}

{{/* The relay's TCP/UDP port (turn:/turns: host:port; 3478, or 5349 for turns, by default). */}}
{{- define "brodec-lab.turnPort" -}}
{{- $u := . | trimPrefix "turns:" | trimPrefix "turn:" | splitList "?" | first -}}
{{- $p := regexFind ":[0-9]+$" $u | trimPrefix ":" -}}
{{- if $p -}}{{ $p }}{{- else if hasPrefix "turns:" . -}}5349{{- else -}}3478{{- end -}}
{{- end -}}

{{/* Tailscale serve's config: the media ports the tailnet forwards (TCP), to the pod's loopback. */}}
{{- define "brodec-lab.tailnetServe" -}}
{{- $tcp := dict -}}
{{- range (include "brodec-lab.mediaPorts" . | fromYamlArray) -}}
{{- if .tailnet -}}{{- $_ := set $tcp (toString .port) (dict "TCPForward" (printf "127.0.0.1:%v" .port)) -}}{{- end -}}
{{- end -}}
{{- dict "TCP" $tcp | toJson -}}
{{- end -}}
