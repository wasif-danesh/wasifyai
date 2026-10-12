#!/usr/bin/env bash
# Install the speech models into the speech server (Speaches) once: it downloads them on request, and
# without them every text to speech and speech to text job answers "not found" (ADR-0042, ADR-0043).
# The same list is in deploy/helm/wasifyai/values.yaml (speech.models) for the cluster.
#
# Usage: scripts/speech-models.sh [base_url]     (default http://localhost:8100, the Compose port)
# Safe to run again: a model already installed is skipped by the server.
set -uo pipefail
BASE="${1:-http://localhost:8100}"
MODELS=(
  "speaches-ai/Kokoro-82M-v1.0-ONNX"          # text to speech, 8 languages
  "deepdml/faster-whisper-large-v3-turbo-ct2" # speech to text
  "Systran/faster-whisper-large-v3"           # finds the language of a recording
)
for _ in $(seq 1 60); do curl -fsS -m 3 "$BASE/health" >/dev/null 2>&1 && break; sleep 2; done
curl -fsS -m 3 "$BASE/health" >/dev/null 2>&1 || { echo "speech server not reachable at $BASE"; exit 1; }
fail=0
for m in "${MODELS[@]}"; do
  enc="${m//\//%2F}"
  code="$(curl -sS -o /dev/null -w '%{http_code}' -m 3000 -X POST "$BASE/v1/models/$enc")"
  case "$code" in
    200|201|409) echo "ok: $m" ;;
    *) echo "FAILED ($code): $m"; fail=1 ;;
  esac
done
exit "$fail"
