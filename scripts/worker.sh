#!/usr/bin/env bash
# The workers of this machine (ADR-0087). The web stack runs in containers; the heavy work (the models) runs here,
# natively, because it needs the Apple GPU. Two processes, both using what the desktop app set up (its data folder):
#
#   engine   speech, music, splitting, voice change, speech edit, dubbing, the audiobook and lip sync
#   media    images and video: it starts the desktop app's ComfyUI and drives it, and takes the place of the
#            stack's own media worker (which would only make placeholder pictures)
#
#   scripts/worker.sh start     # both, in the background; make dev does this on a Mac
#   scripts/worker.sh stop
#   scripts/worker.sh run       # the engine worker in this terminal
#   scripts/worker.sh logs      # follow both logs
#   scripts/worker.sh models [id ...]   # list the speech models, or fetch some onto this machine
#                                       # (also: lipsync-engine, MuseTalk's environment)
#
# WORKER_DATA_DIR picks another data folder. Quit the desktop app while a worker runs a job: both would use the same
# memory and the same files.
set -euo pipefail
. "$(dirname "$0")/lib.sh"
cd "$ROOT"

STATE="${TMPDIR:-/tmp}/wasifyai"
DATA_DIR="${WORKER_DATA_DIR:-$HOME/Library/Application Support/ai.wasifyai.desktop}"

# the model folders the desktop app saved (its Models page), read from its settings
saved_folder() { # saved_folder models_dir|extra_dirs
  local db="$DATA_DIR/wasifyai.db"
  [ -f "$db" ] || return 0
  sqlite3 "$db" "select value from system_settings where key='desktop.model_folders'" 2>/dev/null |
    python3 -c "
import json, os, sys
raw = sys.stdin.read().strip()
if raw:
    v = json.loads(raw)
    key = '$1'
    print(v.get(key, '') if key == 'models_dir' else os.pathsep.join(v.get(key) or []))
" 2>/dev/null || true
}

environment() {
  [ -f .env ] || { bad "no .env: run make setup first"; exit 1; }
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
  # the stack's services are published on this machine; the containers' own names are for the containers
  export REDIS_URL="redis://localhost:6379/0"
  export DATABASE_URL="postgresql+asyncpg://wasifyai:wasifyai@localhost:5432/wasifyai"
  export STORAGE_ENDPOINT="http://localhost:8333"
  export OLLAMA_BASE_URL="http://localhost:11434"
  export DESKTOP_DATA_DIR="$DATA_DIR"
  export PRODUCTS_DIR="$ROOT/products"
  local models extra
  models="$(saved_folder models_dir)"
  extra="$(saved_folder extra_dirs)"
  [ -z "$models" ] || export DESKTOP_MODELS_DIR="$models"
  [ -z "$extra" ] || export DESKTOP_EXTRA_MODEL_DIRS="$extra"
}

pidfile() { echo "$STATE-$1.pid"; }
logfile() { echo "$STATE-$1.log"; }
running() { [ -f "$(pidfile "$1")" ] && kill -0 "$(cat "$(pidfile "$1")")" 2>/dev/null; }

launch() { # launch engine|media
  local name="$1"
  if running "$name"; then ok "the $name worker is already running (pid $(cat "$(pidfile "$name")"))"; return 0; fi
  case "$name" in
    engine) WORKER_ID="${WORKER_ID:-$(hostname -s)-mac}" nohup uv run python -m wasifyai_engine_worker >"$(logfile "$name")" 2>&1 & ;;
    media)
      COMFYUI_MODE=sidecar JOB_TIMEOUT_S=3600 METRICS_PORT=0 \
        nohup uv run python -m wasifyai_media_worker >"$(logfile "$name")" 2>&1 & ;;
  esac
  echo $! >"$(pidfile "$name")"
  ok "the $name worker started (pid $!, log: $(logfile "$name"))"
}

halt() { # halt engine|media
  if running "$1"; then
    local pid
    pid="$(cat "$(pidfile "$1")")"
    # the worker answers SIGTERM by finishing its loop and stopping what it started
    pkill -TERM -P "$pid" 2>/dev/null || true
    kill -TERM "$pid" 2>/dev/null || true
    ok "the $1 worker stopped"
  fi
  rm -f "$(pidfile "$1")"
}

case "${1:-run}" in
  run)
    [ -d "$DATA_DIR" ] || { bad "no data folder at $DATA_DIR (open the desktop app once, or set WORKER_DATA_DIR)"; exit 1; }
    environment
    WORKER_ID="${WORKER_ID:-$(hostname -s)-mac}"
    export WORKER_ID
    exec uv run python -m wasifyai_engine_worker
    ;;
  start)
    if [ ! -d "$DATA_DIR" ]; then
      warn "no workers: no data folder at $DATA_DIR (the web offers only the hosted speech models and placeholder pictures until they run)"
      exit 0
    fi
    environment
    launch engine
    launch media
    # the stack's own media worker would take jobs too, and only make placeholders
    "$CONTAINER_ENGINE" compose stop media-worker >/dev/null 2>&1 || true
    ;;
  stop)
    halt engine
    halt media
    ;;
  models)
    environment
    shift
    exec uv run python -m wasifyai_engine_worker.models_cli "$@"
    ;;
  logs)
    exec tail -f "$(logfile engine)" "$(logfile media)"
    ;;
  *)
    echo "usage: $0 start|stop|run|logs|models" >&2
    exit 2
    ;;
esac
