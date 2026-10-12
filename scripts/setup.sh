#!/usr/bin/env bash
# One-shot, idempotent setup for a fresh clone on macOS, Linux and Windows (inside WSL2).
# Installs missing tools, starts the container engine and Ollama, pulls the models, creates
# .env and installs dependencies. Every install or large download asks first.
#
#   scripts/setup.sh [-y] [--k8s]
#     -y     accept every prompt
#     --k8s  also install kind, helm and kubectl (for `make kind-up`)
#
# Environment knobs (mainly for CI): SETUP_TOOLS_ONLY=1 installs tools and dependencies only
# (no engine, Ollama or model steps).
set -euo pipefail
. "$(dirname "$0")/lib.sh"
. "$(dirname "$0")/install-tools.sh"

ASSUME_YES="${ASSUME_YES:-0}"
K8S=0
for arg in "$@"; do
  case "$arg" in
    -y) ASSUME_YES=1 ;;
    --k8s) K8S=1 ;;
    *) echo "usage: setup.sh [-y] [--k8s]"; exit 2 ;;
  esac
done
TOOLS_ONLY="${SETUP_TOOLS_ONLY:-0}"

confirm() {
  [ "$ASSUME_YES" = "1" ] && return 0
  [ -t 0 ] || { bad "Not a terminal; re-run with -y to accept: $1"; return 1; }
  printf '%s [y/N] ' "$1"; read -r reply; [ "$reply" = "y" ] || [ "$reply" = "Y" ]
}

step "Detected $OS / $ARCH$(is_wsl && echo ' (WSL2)')"
case "$PLATFORM" in darwin|linux) ;; *) bad "Unsupported OS: $OS. On Windows, run this inside WSL2 (docs/windows.md)."; exit 1 ;; esac
if is_wsl && ! has_systemd; then
  warn "systemd is not enabled in this WSL distro. Podman and Ollama still work, but enabling it is smoother:"
  warn "  add '[boot]' and 'systemd=true' to /etc/wsl.conf, then run 'wsl --shutdown' from Windows."
fi

# ---- package manager (Linux) ------------------------------------------------------------
PM=""
if [ "$PLATFORM" = "linux" ]; then
  if have apt-get; then PM=apt; elif have dnf; then PM=dnf; elif have pacman; then PM=pacman; fi
fi
pm_install() {
  case "$PM" in
    apt) sudo apt-get update -qq && sudo apt-get install -y "$@" ;;
    dnf) sudo dnf install -y "$@" ;;
    pacman) sudo pacman -S --noconfirm --needed "$@" ;;
    *) bad "No supported package manager (apt, dnf, pacman). Install manually: $*"; return 1 ;;
  esac
}

# ---- 1. Tools ----------------------------------------------------------------------------
step "Checking tools"
tools="$CONTAINER_ENGINE uv pnpm node ollama curl git make openssl"
[ "$K8S" = "1" ] && tools="$tools kind helm kubectl"
missing=""
for t in $tools; do
  have "$t" && ok "$t" || { bad "$t missing"; missing="$missing $t"; }
done
node_old=0
if have node; then
  nm="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
  [ "$nm" -ge 22 ] || { warn "Node $nm found; Node 22+ is required"; node_old=1; }
fi
compose_ok=1
if have "$CONTAINER_ENGINE" && ! "$CONTAINER_ENGINE" compose version >/dev/null 2>&1; then
  bad "compose provider missing"; compose_ok=0
fi

if [ -n "$missing" ] || [ "$compose_ok" = "0" ] || [ "$node_old" = "1" ]; then
  confirm "Install what is missing:${missing:- (compose/node)}?" || { bad "Cannot continue without:$missing"; exit 1; }

  if [ "$PLATFORM" = "darwin" ]; then
    # macOS: Homebrew for engine/CLI tools; the rest from checksum-verified binaries.
    have brew || { bad "Homebrew is required on macOS. Install it from https://brew.sh, then re-run."; exit 1; }
    pkgs=""
    for t in $missing; do
      case "$t" in
        podman|uv|pnpm|node|ollama|git|kind|helm) pkgs="$pkgs $t" ;;
        kubectl) pkgs="$pkgs kubernetes-cli" ;;
      esac
    done
    [ "$node_old" = "1" ] && pkgs="$pkgs node"
    [ "$compose_ok" = "0" ] && pkgs="$pkgs docker-compose"
    # shellcheck disable=SC2086
    [ -z "$pkgs" ] || brew install $pkgs
  else
    # Linux and WSL2: distro packages for system tools, official verified binaries for the rest.
    syspk=""
    for t in $missing; do
      case "$t" in podman|curl|git|make|openssl) syspk="$syspk $t" ;; esac
    done
    [ "$compose_ok" = "0" ] && syspk="$syspk podman-compose"
    # shellcheck disable=SC2086
    [ -z "$syspk" ] || pm_install $syspk ca-certificates
    for t in $missing; do
      case "$t" in
        node) install_node ;;
        uv) curl -LsSf https://astral.sh/uv/install.sh | sh ;;
        ollama) curl -fsSL https://ollama.com/install.sh | sh ;;
        kind) install_kind ;;
        helm) install_helm ;;
        kubectl) install_kubectl ;;
      esac
    done
    [ "$node_old" = "1" ] && install_node
    # pnpm is provided by corepack, which ships with Node.
    case "$missing" in *pnpm*) have corepack || install_node; install_pnpm ;; esac
    hash -r
  fi
fi

nm="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
[ "$nm" -ge 22 ] && ok "node $nm" || warn "Node $nm found; Node 22+ is required"
case ":$PATH:" in *":$LOCAL_BIN:"*) ;; *) warn "Add $LOCAL_BIN to your PATH (e.g. in ~/.profile)";; esac

# ---- 2. Container engine -----------------------------------------------------------------
if [ "$TOOLS_ONLY" != "1" ]; then
  step "Container engine"
  if [ "$CONTAINER_ENGINE" = "podman" ] && [ "$PLATFORM" = "darwin" ]; then
    if ! podman machine list --format '{{.Name}}' 2>/dev/null | grep -q .; then
      echo "Creating the Podman VM (4 CPUs, 6 GB RAM)..."
      podman machine init --cpus 4 --memory 6144
    fi
    podman info >/dev/null 2>&1 || podman machine start
    # The stack needs ~4 GB; running it on kind needs ~6 GB.
    want=4096; [ "$K8S" = "1" ] && want=6144
    mem="$(podman_vm_mem_mb)"
    if [ -n "$mem" ] && [ "$mem" -lt "$want" ]; then
      warn "The Podman VM has ${mem} MB RAM; ${want} MB is recommended."
      if confirm "Resize it to 6144 MB now? (restarts the VM and any running containers)"; then
        podman machine stop && podman machine set --memory 6144 && podman machine start
      fi
    fi
  fi
  "$CONTAINER_ENGINE" info >/dev/null 2>&1 && ok "$CONTAINER_ENGINE is running" \
    || { bad "$CONTAINER_ENGINE is not running (on Linux, rootless Podman needs no daemon; check 'podman info')"; exit 1; }

  # ---- 3. Ollama and models ----------------------------------------------------------------
  step "Ollama"
  if ! ollama_up; then
    echo "Starting Ollama..."
    if [ "$PLATFORM" = "darwin" ] && have brew && brew list ollama >/dev/null 2>&1; then
      brew services start ollama >/dev/null
    elif has_systemd && systemctl list-unit-files 2>/dev/null | grep -q '^ollama'; then
      sudo systemctl start ollama
    else
      nohup ollama serve >/tmp/ollama.log 2>&1 &
    fi
    for _ in $(seq 1 30); do ollama_up && break; sleep 1; done
  fi
  ollama_up && ok "Ollama reachable at $OLLAMA_URL" || { bad "Ollama did not start"; exit 1; }

  # Linux/WSL: containers reach the host through host.containers.internal, but Ollama listens
  # on loopback only by default. Test it, and offer a fix if the containers cannot connect.
  if [ "$PLATFORM" = "linux" ]; then
    if "$CONTAINER_ENGINE" run --rm docker.io/curlimages/curl:8.10.1 -fsS -m 8 \
         http://host.containers.internal:11434/api/tags >/dev/null 2>&1; then
      ok "containers can reach Ollama"
    else
      warn "Containers cannot reach Ollama at host.containers.internal:11434."
      warn "Ollama has no authentication; listening on all interfaces exposes it to your network."
      warn "Use a host firewall to limit port 11434 to this machine and your container network."
      if confirm "Make Ollama listen on 0.0.0.0?"; then
        if has_systemd && systemctl list-unit-files 2>/dev/null | grep -q '^ollama'; then
          sudo mkdir -p /etc/systemd/system/ollama.service.d
          printf '[Service]\nEnvironment="OLLAMA_HOST=0.0.0.0"\n' | sudo tee /etc/systemd/system/ollama.service.d/wasifyai.conf >/dev/null
          sudo systemctl daemon-reload && sudo systemctl restart ollama
        else
          pkill -f "ollama serve" 2>/dev/null || true; sleep 1
          OLLAMA_HOST=0.0.0.0 nohup ollama serve >/tmp/ollama.log 2>&1 &
          warn "Started Ollama manually. Re-export OLLAMA_HOST=0.0.0.0 whenever you start it yourself."
        fi
        for _ in $(seq 1 30); do ollama_up && break; sleep 1; done
      fi
    fi
  fi

  # RAM / disk heads-up for the default 20B model.
  if [ "$PLATFORM" = "darwin" ]; then mem_gb=$(( $(sysctl -n hw.memsize) / 1073741824 ))
  else mem_gb=$(( $(awk '/MemTotal/{print $2}' /proc/meminfo) / 1048576 )); fi
  free_gb=$(df -Pk "$HOME" | awk 'NR==2{print int($4/1048576)}')
  [ "$mem_gb" -ge 8 ] || warn "Only ${mem_gb} GB RAM: the default model (gemma4:e4b) needs about 8 GB and may be very slow or fail. Change the model in services/api/src/wasifyai_api/model_defaults.yaml (or in the admin area once running) to use a smaller one."
  [ "$PLATFORM" = "darwin" ] && [ "$ARCH" = "x86_64" ] && warn "Intel Mac: Ollama runs CPU-only, so replies will be slow."

  for m in $(required_models); do
    if ollama_has_model "$m"; then ok "model $m already pulled"; continue; fi
    [ "$free_gb" -ge 15 ] || warn "Only ${free_gb} GB free disk; models need roughly 10 GB in total."
    confirm "Download model $m now (gemma4:e4b is about 10 GB; embeddings about 0.3 GB)?" \
      && ollama pull "$m" || { bad "Model $m not pulled"; exit 1; }
  done
fi

# ---- 4. .env -----------------------------------------------------------------------------
step "Environment file"
[ -f "$ROOT/.env" ] || { cp "$ROOT/.env.example" "$ROOT/.env"; ok "created .env from .env.example"; }
# Upgrades: add keys introduced since .env was created (values come from .env.example).
while IFS= read -r line; do
  key="${line%%=*}"
  case "$line" in ""|\#*) continue ;; esac
  grep -qE "^$key=" "$ROOT/.env" || { echo "$line" >> "$ROOT/.env"; ok "added new setting $key to .env"; }
done < "$ROOT/.env.example"
set_secret() { # set_secret KEY PLACEHOLDER PREFIX: replace a placeholder with a random value
  cur="$(env_value "$1")"
  if [ -z "$cur" ] || [ "$cur" = "$2" ]; then
    val="$3$(openssl rand -hex 24)"
    sed -i.bak "s|^$1=.*|$1=$val|" "$ROOT/.env" && rm -f "$ROOT/.env.bak"
    ok "generated $1 (not printed)"
  else ok "$1 already set"; fi
}
set_secret LITELLM_API_KEY sk-dev-change-me sk-
set_secret AUTH_SECRET change-me ""
set_secret API_AUTH_SECRET change-me-with-at-least-32-characters ""
set_secret LITELLM_SALT_KEY change-me ""
# A Fernet key: 32 random bytes, URL-safe base64 (used to encrypt media provider keys).
cur="$(env_value MEDIA_SECRETS_KEY)"
if [ -z "$cur" ] || [ "$cur" = "change-me" ]; then
  val="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n')"
  sed -i.bak "s|^MEDIA_SECRETS_KEY=.*|MEDIA_SECRETS_KEY=$val|" "$ROOT/.env" && rm -f "$ROOT/.env.bak"
  ok "generated MEDIA_SECRETS_KEY (not printed)"
else ok "MEDIA_SECRETS_KEY already set"; fi
set_secret STORAGE_SECRET_KEY change-me ""

# ---- 5. Dependencies ---------------------------------------------------------------------
step "Dependencies"
(cd "$ROOT" && uv sync --all-packages)
(cd "$ROOT" && CI=true pnpm install)

printf '\n%sSetup complete.%s Next: %smake dev%s  (starts the stack, runs migrations, opens on http://localhost:3000)\n' \
  "$GREEN" "$RESET" "$BOLD" "$RESET"
