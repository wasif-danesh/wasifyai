# Shared helpers for setup/preflight/dev scripts. Source this file; bash 3.2 compatible.

CONTAINER_ENGINE="${CONTAINER_ENGINE:-podman}"
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -t 1 ]; then
  RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; BOLD=$'\033[1m'; RESET=$'\033[0m'
else
  RED=""; GREEN=""; YELLOW=""; BOLD=""; RESET=""
fi

ok()   { printf '%s✓%s %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '%s!%s %s\n' "$YELLOW" "$RESET" "$*"; }
bad()  { printf '%s✗%s %s\n' "$RED" "$RESET" "$*"; }
step() { printf '\n%s==> %s%s\n' "$BOLD" "$*" "$RESET"; }
have() { command -v "$1" >/dev/null 2>&1; }

# Models the stack needs, derived from the single source of truth (the API's model defaults).
required_models() {
  # Only models served by the local Ollama: an alias counts when its `api_base` is an Ollama one. Hosted
  # aliases (`openai/tts-1`, `openai/whisper-1`) have no Ollama api_base and are not pulled.
  grep -vE '^[[:space:]]*#' "$ROOT/services/api/src/wasifyai_api/model_defaults.yaml" |
    awk '
      /^[[:space:]]*model:/ { m = $2; next }
      /^[[:space:]]*api_base:.*OLLAMA/ && m != "" { print m; m = "" }
    ' | sed -E 's#^(ollama(_chat)?|openai)/##' | sort -u
}

ollama_up() { curl -fsS -m 3 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; }

ollama_has_model() {
  # Untagged names in config (e.g. nomic-embed-text) are listed by Ollama as <name>:latest.
  curl -fsS -m 5 "$OLLAMA_URL/api/tags" 2>/dev/null | grep -qE "\"name\":\"$1(:latest)?\""
}

env_value() { # env_value KEY -> value from .env (never printed by callers)
  [ -f "$ROOT/.env" ] || return 0
  grep -E "^$1=" "$ROOT/.env" | head -1 | cut -d= -f2-
}

# ---- platform detection ------------------------------------------------------------------
OS="$(uname -s)"
case "$(uname -m)" in
  x86_64|amd64) _a=(x86_64 amd64 x64) ;;
  arm64|aarch64) _a=(arm64 arm64 arm64) ;;
  *) _a=("$(uname -m)" "$(uname -m)" "$(uname -m)") ;;
esac
ARCH="${ARCH:-${_a[0]}}"; GOARCH="${GOARCH:-${_a[1]}}"; NODEARCH="${NODEARCH:-${_a[2]}}"
# darwin | linux. Env overrides exist so installers can be tested for another target.
PLATFORM="${PLATFORM:-$(printf '%s' "$OS" | tr '[:upper:]' '[:lower:]')}"
is_wsl() { [ "$PLATFORM" = "linux" ] && grep -qi microsoft /proc/version 2>/dev/null; }
has_systemd() { [ -d /run/systemd/system ]; }

LOCAL_BIN="${LOCAL_BIN:-$HOME/.local/bin}"
case ":$PATH:" in *":$LOCAL_BIN:"*) ;; *) export PATH="$LOCAL_BIN:$PATH" ;; esac

# Podman VM memory in MB (macOS only); empty when unknown.
podman_vm_mem_mb() {
  [ "$PLATFORM" = "darwin" ] && have podman || return 0
  podman machine inspect 2>/dev/null | grep -m1 '"Memory"' | tr -dc '0-9'
}
