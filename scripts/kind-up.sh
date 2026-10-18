#!/usr/bin/env bash
# Build images, create a local kind cluster, and install the chart with the local overlay.
set -euo pipefail
. "$(dirname "$0")/lib.sh"
cd "$ROOT"

CLUSTER=wasifyai; NS=wasifyai; TAG=dev; REG=localhost/wasifyai
# KIND_MODE=full (the default): every service runs as a pod, nothing native: Ollama with its models, the CPU
#   and ComfyUI. Needs a Podman VM of about 24 GB and a few tens of GB of
#   model downloads on first start; no GPU, so the GPU media models are placeholders (stub mode).
# KIND_MODE=light: the small cluster CI uses: Ollama is native or absent.
MODE="${KIND_MODE:-full}"
[ "$CONTAINER_ENGINE" = "podman" ] && export KIND_EXPERIMENTAL_PROVIDER=podman

step "Checking tools"
miss=0
for t in kind kubectl helm "$CONTAINER_ENGINE"; do
  have "$t" && ok "$t" || { bad "$t is not installed"; miss=1; }
done
[ "$miss" -eq 0 ] || { printf '\nRun %smake setup-k8s%s to install the missing tools.\n' "$BOLD" "$RESET"; exit 1; }
"$CONTAINER_ENGINE" info >/dev/null 2>&1 || { bad "$CONTAINER_ENGINE is not running (macOS: podman machine start)"; exit 1; }
mem="$(podman_vm_mem_mb)"
if [ -n "$mem" ] && [ "$mem" -lt 5500 ]; then
  bad "The Podman VM has only ${mem} MB RAM; kind plus the stack needs about 6 GB."
  printf 'Run %smake setup-k8s%s (offers to resize it), or: podman machine stop && podman machine set --memory 6144 && podman machine start\n' "$BOLD" "$RESET"
  exit 1
fi
if [ "$PLATFORM" = "linux" ] && [ "$CONTAINER_ENGINE" = "podman" ] && [ "$(id -u)" -ne 0 ]; then
  warn "Rootless Podman: kind needs cgroup v2 with cpu/cpuset/io delegation (see docs/runbooks/linux-kind.md). If cluster creation fails, run: sudo -E env \"PATH=\$PATH\" make kind-up"
fi

step "Building images"
IMAGES=("api:services/api" "media-worker:services/media-worker" "web:apps/web")
[ "$MODE" = "full" ] && IMAGES+=("comfyui:services/comfyui")
for pair in "${IMAGES[@]}"; do
  name="${pair%%:*}"; dir="${pair##*:}"
  "$CONTAINER_ENGINE" build -q -f "$dir/Containerfile" -t "$REG/$name:$TAG" . >/dev/null
  ok "built $REG/$name:$TAG"
done

step "Cluster"
if kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  ok "cluster $CLUSTER exists"
else
  kind create cluster --config deploy/kind/cluster.yaml
fi
kubectl config use-context "kind-$CLUSTER" >/dev/null

step "Loading images into the cluster"
for pair in "${IMAGES[@]}"; do
  name="${pair%%:*}"; img="$REG/$name:$TAG"
  if [ "$CONTAINER_ENGINE" = "podman" ]; then
    tar="$(mktemp -t wasifyai-image).tar"
    "$CONTAINER_ENGINE" save -o "$tar" "$img" >/dev/null
    kind load image-archive "$tar" --name "$CLUSTER" >/dev/null; rm -f "$tar"
  else
    kind load docker-image "$img" --name "$CLUSTER" >/dev/null
  fi
  ok "loaded $img"
done

step "Secrets"
scripts/k8s-secrets.sh "$NS"

OLLAMA_EXTERNAL_URL="${OLLAMA_EXTERNAL_URL:-}"
if [ "$MODE" = "light" ]; then
  # Where can pods reach the Ollama running natively on this machine?
  OLLAMA_EXTERNAL_URL="${OLLAMA_EXTERNAL_URL:-}"
  if [ -z "$OLLAMA_EXTERNAL_URL" ]; then
    node="$CLUSTER-control-plane"
    host="host.containers.internal"; [ "$CONTAINER_ENGINE" = "docker" ] && host="host.docker.internal"
    ip="$("$CONTAINER_ENGINE" exec "$node" getent hosts "$host" 2>/dev/null | awk '{print $1; exit}')"
    [ -n "$ip" ] && OLLAMA_EXTERNAL_URL="http://$ip:11434" || OLLAMA_EXTERNAL_URL="http://127.0.0.1:11434"
  fi
  ok "Ollama URL for pods: $OLLAMA_EXTERNAL_URL"
fi

extra=()
[ "${KIND_SAFEGUARDS:-0}" = "1" ] && extra+=(--set safeguards.forceOn=true)

step "Installing the chart"
if [ "$MODE" = "full" ]; then
  # nothing native: every service is a pod
  helm upgrade --install wasifyai deploy/helm/wasifyai -n "$NS" \
    -f deploy/helm/wasifyai/values/local.yaml \
    --set ollama.enabled=true --set ollama.externalUrl= \
    --set comfyui.enabled=true --set "comfyui.image=$REG/comfyui:$TAG" \
    --set env.PRODUCT_ENV=kind \
    ${extra[@]+"${extra[@]}"} \
    --wait --timeout 90m
else
  helm upgrade --install wasifyai deploy/helm/wasifyai -n "$NS" \
    -f deploy/helm/wasifyai/values/local.yaml \
    --set "ollama.externalUrl=$OLLAMA_EXTERNAL_URL" \
    ${extra[@]+"${extra[@]}"} \
    --wait --timeout 10m
fi

if [ "$MODE" = "full" ] && [ "${KIND_MONITORING:-1}" = "1" ]; then
  # needs the telegram and heartbeat values in .env; without them the cluster is still usable
  scripts/monitoring-up.sh || warn "monitoring was not installed (see above); run make monitoring-up when ready"
fi

if [ "$MODE" = "full" ]; then
  step "Waiting for the model downloads (Ollama: a first start takes a while)"
  kubectl -n "$NS" wait --for=condition=complete job --all --timeout=90m
fi

printf '\n%sReady.%s Open %shttp://localhost:3000%s. Check with: make kind-test. Remove with: make kind-down\n' \
  "$GREEN" "$RESET" "$BOLD" "$RESET"
