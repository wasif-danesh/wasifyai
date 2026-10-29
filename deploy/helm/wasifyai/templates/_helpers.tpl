{{- define "wasifyai.labels" -}}
app.kubernetes.io/part-of: wasifyai
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{/* wasifyai.selector: dict "root" . "component" "api" */}}
{{- define "wasifyai.selector" -}}
app.kubernetes.io/name: wasifyai
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/* wasifyai.image: dict "root" . "name" "api" */}}
{{- define "wasifyai.image" -}}
{{ .root.Values.image.registry }}/{{ .name }}:{{ .root.Values.image.tag }}
{{- end -}}

{{- define "wasifyai.pullSecrets" -}}
{{- with .Values.image.pullSecrets }}
imagePullSecrets:
{{- toYaml . | nindent 2 }}
{{- end }}
{{- end -}}

{{- define "wasifyai.ollamaUrl" -}}
{{- if .Values.ollama.externalUrl -}}{{ .Values.ollama.externalUrl }}{{- else -}}http://{{ .Release.Name }}-ollama:11434{{- end -}}
{{- end -}}

{{/* Models the Ollama pod must pull. */}}
{{- define "wasifyai.ollamaModels" -}}
{{- join " " .Values.ollama.models -}}
{{- end -}}

{{/* Env vars that give a workload its database connection. */}}
{{- define "wasifyai.dbEnv" -}}
{{- if .Values.postgres.enabled }}
- name: POSTGRES_PASSWORD
  valueFrom:
    secretKeyRef: { name: {{ .Values.secrets.existingSecret }}, key: POSTGRES_PASSWORD }
- name: DATABASE_URL
  value: "postgresql+asyncpg://{{ .Values.postgres.user }}:$(POSTGRES_PASSWORD)@{{ .Release.Name }}-postgres:5432/{{ .Values.postgres.database }}"
{{- else }}
- name: DATABASE_URL
  valueFrom:
    secretKeyRef: { name: {{ .Values.secrets.existingSecret }}, key: DATABASE_URL }
{{- end }}
{{- end -}}

{{- define "wasifyai.storageEndpoint" -}}
{{- if .Values.storage.enabled -}}http://{{ .Release.Name }}-storage:8333{{- else -}}{{ .Values.storage.endpoint }}{{- end -}}
{{- end -}}

{{- define "wasifyai.comfyuiUrl" -}}
{{- if .Values.comfyui.enabled -}}http://{{ .Release.Name }}-comfyui:{{ .Values.comfyui.port }}{{- else -}}{{ .Values.env.COMFYUI_BASE_URL }}{{- end -}}
{{- end -}}

{{/* Object storage settings for the API and the media worker. */}}
{{- define "wasifyai.storageEnv" -}}
- { name: STORAGE_ENDPOINT, value: {{ include "wasifyai.storageEndpoint" . | quote }} }
- { name: STORAGE_PUBLIC_ENDPOINT, value: {{ .Values.storage.publicEndpoint | quote }} }
- { name: STORAGE_BUCKET, value: {{ .Values.storage.bucket | quote }} }
- { name: STORAGE_REGION, value: {{ .Values.storage.region | quote }} }
- { name: STORAGE_ACCESS_KEY, value: {{ .Values.storage.accessKey | quote }} }
- name: STORAGE_SECRET_KEY
  valueFrom:
    secretKeyRef: { name: {{ .Values.secrets.existingSecret }}, key: STORAGE_SECRET_KEY }
{{- end -}}

{{/* Env shared by the API and the migration job. */}}
{{- define "wasifyai.apiEnv" -}}
{{ include "wasifyai.dbEnv" . }}
{{ include "wasifyai.tracingEnv" (dict "root" . "service" "wasifyai-api") }}
{{ include "wasifyai.langfuseEnv" . }}
- name: REDIS_URL
  value: "redis://{{ .Release.Name }}-redis:6379/0"
- name: LITELLM_BASE_URL
  value: "http://{{ .Release.Name }}-litellm:4000"
- name: LITELLM_API_KEY
  valueFrom:
    secretKeyRef: { name: {{ .Values.secrets.existingSecret }}, key: LITELLM_API_KEY }
- name: OLLAMA_BASE_URL
  value: {{ include "wasifyai.ollamaUrl" . | quote }}
- name: COMFYUI_BASE_URL
  value: {{ .Values.env.COMFYUI_BASE_URL | quote }}
- name: COMFYUI_VIDEO_BASE_URL
  value: {{ .Values.env.COMFYUI_VIDEO_BASE_URL | quote }}
- name: LOG_LEVEL
  value: {{ .Values.env.LOG_LEVEL | quote }}
- name: PRODUCT_ENV
  value: {{ .Values.env.PRODUCT_ENV | quote }}
- name: SAFEGUARDS_FORCE_ON
  value: {{ .Values.safeguards.forceOn | quote }}
- name: MAX_JOBS_PER_USER
  value: {{ .Values.jobs.maxPerUser | quote }}
{{ include "wasifyai.mediaSecretsEnv" . }}
- name: AUTH_MODE
  value: {{ .Values.auth.mode | quote }}
{{- if ne .Values.auth.mode "stub" }}
- name: API_AUTH_SECRET
  valueFrom:
    secretKeyRef: { name: {{ .Values.secrets.existingSecret }}, key: API_AUTH_SECRET }
- name: ADMIN_EMAILS
  value: {{ .Values.auth.adminEmails | quote }}
{{- end }}
{{- include "wasifyai.storageEnv" . | nindent 0 }}
{{- /* notebooks and speech are always on (no switches): their settings */}}
- { name: NOTEBOOKS_SCHEMA, value: {{ .Values.notebooks.schema | quote }} }
- { name: NOTEBOOKS_EMBED_MODEL, value: {{ .Values.notebooks.embedModel | quote }} }
- { name: NOTEBOOKS_EMBED_DIMENSION, value: {{ .Values.notebooks.embedDimension | quote }} }
- { name: VOICE_SCHEMA, value: {{ .Values.voice.schema | quote }} }
{{- with .Values.voice.modelsFile }}
- { name: VOICE_MODELS_FILE, value: {{ . | quote }} }
{{- end }}
{{- end -}}

{{/* Encrypts media provider API keys saved in the admin area. Optional: without it the admin area refuses to save a key. */}}
{{- define "wasifyai.mediaSecretsEnv" -}}
- name: MEDIA_SECRETS_KEY
  valueFrom:
    secretKeyRef: { name: {{ .Values.secrets.existingSecret }}, key: MEDIA_SECRETS_KEY, optional: true }
{{- end -}}

{{/* Sign-in settings for the web pod (ADR-0030). Provider keys are optional: a provider with no key is simply not offered. */}}
{{- define "wasifyai.webAuthEnv" -}}
- name: AUTH_MODE
  value: {{ .Values.auth.mode | quote }}
{{- if ne .Values.auth.mode "stub" }}
- name: AUTH_TRUST_HOST
  value: "true"
{{- with .Values.auth.url }}
- name: AUTH_URL
  value: {{ . | quote }}
{{- end }}
{{- range $key := list "AUTH_SECRET" "API_AUTH_SECRET" }}
- name: {{ $key }}
  valueFrom:
    secretKeyRef: { name: {{ $.Values.secrets.existingSecret }}, key: {{ $key }} }
{{- end }}
{{- range $key := list "AUTH_GOOGLE_ID" "AUTH_GOOGLE_SECRET" "AUTH_GITHUB_ID" "AUTH_GITHUB_SECRET" "AUTH_MICROSOFT_ENTRA_ID_ID" "AUTH_MICROSOFT_ENTRA_ID_SECRET" "AUTH_MICROSOFT_ENTRA_ID_ISSUER" }}
- name: {{ $key }}
  valueFrom:
    secretKeyRef: { name: {{ $.Values.secrets.existingSecret }}, key: {{ $key }}, optional: true }
{{- end }}
{{- end }}
{{- end -}}

{{/* Traces (stage O1): OTLP to Tempo when tracing.otlpEndpoint is set. Call with (dict "root" . "service" "<name>"). */}}
{{- define "wasifyai.tracingEnv" -}}
{{- with .root.Values.tracing.otlpEndpoint }}
- { name: OTEL_EXPORTER_OTLP_ENDPOINT, value: {{ . | quote }} }
- { name: OTEL_SERVICE_NAME, value: {{ $.service | quote }} }
- { name: OTEL_TRACES_SAMPLER, value: parentbased_traceidratio }
- { name: OTEL_TRACES_SAMPLER_ARG, value: {{ $.root.Values.tracing.sampleRatio | quote }} }
{{- end }}
{{- end -}}

{{/* LLM traces in Langfuse (ADR-0050): the keys come from the Secret and are optional. */}}
{{- define "wasifyai.langfuseEnv" -}}
{{- with .Values.langfuse.baseUrl }}
- { name: LANGFUSE_BASE_URL, value: {{ . | quote }} }
- { name: LANGFUSE_CAPTURE_CONTENT, value: {{ $.Values.langfuse.captureContent | quote }} }
- name: LANGFUSE_PUBLIC_KEY
  valueFrom:
    secretKeyRef: { name: {{ $.Values.secrets.existingSecret }}, key: LANGFUSE_PUBLIC_KEY, optional: true }
- name: LANGFUSE_SECRET_KEY
  valueFrom:
    secretKeyRef: { name: {{ $.Values.secrets.existingSecret }}, key: LANGFUSE_SECRET_KEY, optional: true }
{{- end }}
{{- end -}}
