#!/usr/bin/env bash
# Fast, side-effect-free check that the machine is ready for `make dev`.
# Exits non-zero on any blocking problem and points at `make setup`.
set -u
. "$(dirname "$0")/lib.sh"

fail=0
need() { bad "$1"; fail=1; }

step "Preflight"

for t in "$CONTAINER_ENGINE" uv pnpm node curl; do
  have "$t" && ok "$t found" || need "$t is not installed"
done

if have "$CONTAINER_ENGINE"; then
  if "$CONTAINER_ENGINE" info >/dev/null 2>&1; then
    ok "$CONTAINER_ENGINE engine is running"
  else
    need "$CONTAINER_ENGINE engine is not running (macOS: 'podman machine start')"
  fi
  if "$CONTAINER_ENGINE" compose version >/dev/null 2>&1; then
    ok "compose provider available"
  else
    need "'$CONTAINER_ENGINE compose' has no compose provider installed"
  fi
fi

mem="$(podman_vm_mem_mb)"
if [ -n "$mem" ] && [ "$mem" -lt 4096 ]; then
  warn "Podman VM has ${mem} MB RAM; the stack needs about 4 GB (make setup offers to resize it)"
fi

if [ -f "$ROOT/.env" ]; then
  for k in LITELLM_API_KEY LITELLM_SALT_KEY STORAGE_SECRET_KEY; do
    v="$(env_value $k)"
    if [ -z "$v" ] || [ "$v" = "sk-dev-change-me" ] || [ "$v" = "change-me" ]; then
      need ".env has no real $k (run make setup)"
    else
      ok ".env has $k set"
    fi
  done
else
  need ".env is missing"
fi

if ollama_up; then
  ok "Ollama reachable at $OLLAMA_URL"
  for m in $(required_models); do
    ollama_has_model "$m" && ok "model $m available" || need "model $m is not pulled (ollama pull $m)"
  done
else
  need "Ollama is not reachable at $OLLAMA_URL"
fi

[ -d "$ROOT/.venv" ] && ok "Python deps installed" || need "Python deps missing (uv sync --all-packages)"
[ -d "$ROOT/node_modules" ] && ok "Node deps installed" || need "Node deps missing (pnpm install)"

if [ "$fail" -ne 0 ]; then
  printf '\n%sNot ready.%s Run %smake setup%s to fix everything above automatically.\n' "$RED" "$RESET" "$BOLD" "$RESET"
  exit 1
fi
printf '\n%sAll good.%s\n' "$GREEN" "$RESET"
