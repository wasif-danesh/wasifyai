#!/usr/bin/env bash
# Smoke test against the local kind cluster. SMOKE_EXPECT_DONE=1 also requires the model
# round trip to succeed (needs a reachable Ollama); otherwise a clean `error` event is accepted,
# which still proves web -> BFF -> API -> LiteLLM wiring.
set -uo pipefail
. "$(dirname "$0")/lib.sh"
NS=wasifyai; fail=0
check() { if eval "$2" >/dev/null 2>&1; then ok "$1"; else bad "$1"; fail=1; fi; }

step "Smoke test"
check "migration job completed" "kubectl -n $NS wait --for=condition=complete job/wasifyai-migrate --timeout=180s"
check "all deployments available" "kubectl -n $NS wait --for=condition=available deploy --all --timeout=180s"
check "usage_events table exists" "kubectl -n $NS exec statefulset/wasifyai-postgres -- psql -U wasifyai -d wasifyai -tAc \"select to_regclass('public.usage_events')\" | grep -q usage_events"
check "rag_chunks table + pgvector extension exist" "kubectl -n $NS exec statefulset/wasifyai-postgres -- psql -U wasifyai -d wasifyai -tAc \"select to_regclass('public.rag_chunks'), (select count(*) from pg_extension where extname='vector')\" | grep -q 'rag_chunks|1'"
check "web serves / (HTTP 200)" "curl -fsS -m 10 -o /dev/null http://localhost:3000/"

check "Image page renders" "curl -fsS -m 20 http://localhost:3000/image | grep -q 'data-workspace'"
check "images API answers through the BFF" "curl -fsS -m 10 http://localhost:3000/api/products/wasifyai-image/images | grep -q '\"images\"'"
check "uploading something that is not a picture is refused" "test \"\$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'content-type: image/png' --data-binary 'not a picture' http://localhost:3000/api/products/wasifyai-image/uploads/images)\" = 422"

check "videos API answers through the BFF" "curl -fsS -m 10 http://localhost:3000/api/products/wasifyai-video/videos?status=working | grep -q '\"videos\"'"
check "My creations renders" "curl -fsS -m 20 http://localhost:3000/creations | grep -q 'My creations'"
check "prompt enhancing needs a known kind" "test \"\$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'content-type: application/json' -d '{\"kind\":\"nope\",\"prompt\":\"x\"}' http://localhost:3000/api/products/wasifyai-video/prompt/enhance)\" = 422"

# Model aliases live in LiteLLM's database and are seeded by the API (ADR-0025). The local overlay runs
# with AUTH_MODE=stub, where the dev user is an admin, so ask the API from inside its own pod. The
# expected list is the API's own (model_defaults.yaml), not a number written here.
check "default model aliases are seeded in the gateway" "kubectl -n $NS exec deploy/wasifyai-api -c api -- python -c \"import urllib.request,json,sys,yaml; from wasifyai_api.model_access import DEFAULTS_FILE; want=set(yaml.safe_load(DEFAULTS_FILE.read_text())['aliases']); m=json.load(urllib.request.urlopen('http://localhost:8000/admin/models',timeout=20))['models']; sys.exit(0 if {x['alias'] for x in m}==want and all(x['source']=='default' for x in m) else 1)\""

# Media pipeline: queue -> worker (stub mode) -> object storage -> completion -> graph resumes.
# Needs no LLM or GPU, so it also runs in CI.
media="$(curl -sN -m 120 -X POST http://localhost:3000/api/products/media-demo/runs \
  -H 'content-type: application/json' -d '{"input":{"prompt":"a lighthouse"}}' 2>&1)"
check "media job: queued, ran, completed" "printf '%s' \"\$media\" | grep -q 'event: job_progress' && printf '%s' \"\$media\" | grep -q '\"status\": \"completed\"'"
check "media run finished with done and an image URL" "printf '%s' \"\$media\" | tail -4 | grep -q 'event: done' && printf '%s' \"\$media\" | grep -q 'image_url'"
check "worker usage recorded (job.completed)" "kubectl -n $NS exec statefulset/wasifyai-postgres -- psql -U wasifyai -d wasifyai -tAc \"select count(*) from usage_events where kind='job.completed'\" | grep -qv '^0\$'"

# KIND_MODE=full: nothing is native, so check each pod that stands in for a host service really works.
if kubectl -n $NS get deploy wasifyai-comfyui >/dev/null 2>&1; then
  step "Pods that replace native services"
  check "Ollama pod has the language model" "kubectl -n $NS exec deploy/wasifyai-ollama -- ollama list | grep -q gemma4"
  check "speech server has its models installed" "kubectl -n $NS exec deploy/wasifyai-speech -- curl -fsS localhost:8000/v1/models | grep -q Kokoro"
  check "lip sync server is reachable from the worker" "kubectl -n $NS exec deploy/wasifyai-media-worker -c media-worker -- python -c \"import urllib.request; urllib.request.urlopen('http://wasifyai-lipsync:8000/health', timeout=5)\""
  check "ComfyUI pod answers" "kubectl -n $NS exec deploy/wasifyai-comfyui -- python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8188/system_stats', timeout=5)\""
  # Bind the demo product to the ComfyUI pod: the worker sends a real graph (no models needed) and gets a real file.
  kubectl -n $NS exec deploy/wasifyai-api -c api -- python -c "
import json, urllib.request
r = urllib.request.Request('http://localhost:8000/admin/media/media-demo/image.generate', method='PUT',
    data=json.dumps({'backend': 'comfyui-local', 'config': {'base_url': 'http://wasifyai-comfyui:8188'}}).encode(),
    headers={'content-type': 'application/json'})
print(urllib.request.urlopen(r, timeout=10).status)" >/dev/null 2>&1
  sleep 5   # the worker caches binding lookups for a few seconds
  real="$(curl -sN -m 180 -X POST http://localhost:3000/api/products/media-demo/runs \
    -H 'content-type: application/json' -d '{"input":{"prompt":"a lighthouse"}}' 2>&1)"
  check "media job ran on the ComfyUI pod and finished" "printf '%s' \"\$real\" | grep -q 'image_url'"
  check "ComfyUI pod really executed the graph" "kubectl -n $NS exec deploy/wasifyai-comfyui -- python -c \"import json,urllib.request; assert json.load(urllib.request.urlopen('http://localhost:8188/history', timeout=5))\""
fi

# Monitoring (ADR-0048), when installed: Prometheus must see the API and the worker and the alert rules.
if kubectl get ns monitoring >/dev/null 2>&1 && kubectl -n monitoring get pod prometheus-monitoring-prometheus-0 >/dev/null 2>&1; then
  step "Monitoring"
  prom() { kubectl get --raw "/api/v1/namespaces/monitoring/services/monitoring-prometheus:9090/proxy$1"; }
  check "Prometheus scrapes the API and the worker" "prom '/api/v1/targets' | python3 -c \"import json,sys; t=[x for x in json.load(sys.stdin)['data']['activeTargets'] if 'wasifyai' in x['labels'].get('service','')]; sys.exit(0 if len(t)>=2 and all(x['health']=='up' for x in t) else 1)\""
  check "the alert rules are loaded (with the Watchdog)" "prom '/api/v1/rules' | grep -q Watchdog"
  check "Alertmanager has Telegram and heartbeat receivers (ALERT_NOTIFICATIONS=on) or the null receiver (off)" "kubectl -n monitoring get secret alertmanager-wasifyai-config -o jsonpath='{.data.alertmanager\\.yaml}' | base64 -d | grep -qE 'telegram_configs|receiver: .null.'"
fi

out="$(curl -sN -m 300 -X POST http://localhost:3000/api/products/hello/runs \
  -H 'content-type: application/json' -d '{"input":{"message":"Say hi"}}' 2>&1)"
last="$(printf '%s' "$out" | grep '^event:' | tail -1 | awk '{print $2}')"
if [ "${SMOKE_EXPECT_DONE:-0}" = "1" ]; then
  [ "$last" = "done" ] && ok "streamed run finished with done" || { bad "run ended with '${last:-nothing}', expected done"; fail=1; }
else
  [ "$last" = "done" ] || [ "$last" = "error" ] && ok "streamed run terminated cleanly ($last)" || { bad "no terminal event (got '${last:-nothing}')"; fail=1; }
fi

if [ "${SMOKE_EXPECT_DONE:-0}" = "1" ]; then
  check "token usage recorded for the run" "kubectl -n $NS exec statefulset/wasifyai-postgres -- psql -U wasifyai -d wasifyai -tAc \"select count(*) from usage_events where kind='llm.output_tokens'\" | grep -qv '^0\$'"
fi

[ "$fail" -eq 0 ] && printf '\n%sSmoke test passed.%s\n' "$GREEN" "$RESET" || { printf '\n%sSmoke test FAILED.%s\n' "$RED" "$RESET"; exit 1; }
