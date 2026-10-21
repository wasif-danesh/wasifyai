#!/usr/bin/env bash
# The engine worker on this machine (ADR-0087, stage P0): the desktop engine's speech runtime without the window, taking
# jobs from the stack's queue so the web app can offer Music, Voices, Change a voice, Edit speech, Dub, Audiobook,
# Split and Lip sync. It uses the models the desktop app downloaded (the app's data folder).
#
#   scripts/worker.sh start     # in the background; make dev does this on a Mac
#   scripts/worker.sh stop
#   scripts/worker.sh run       # in this terminal
#   scripts/worker.sh logs
#   scripts/worker.sh models [id ...]   # list the speech models, or fetch some onto this machine
#
# WORKER_DATA_DIR picks another data folder. Quit the desktop app while the worker runs a job: both would use the
# same memory and the same files.
set -euo pipefail
. "$(dirname "$0")/lib.sh"
cd "$ROOT"

STATE="${TMPDIR:-/tmp}/wasifyai-engine-worker"
PIDFILE="$STATE.pid"
LOGFILE="$STATE.log"
DATA_DIR="${WORKER_DATA_DIR:-$HOME/Library/Application Support/ai.wasifyai.desktop}"

environment() {
  [ -f .env ] || { bad "no .env: run make setup first"; exit 1; }
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
  # the stack's services are published on this machine; the containers' own names are for the containers
  export REDIS_URL="redis://localhost:6379/0"
  export STORAGE_ENDPOINT="http://localhost:8333"
  export DESKTOP_DATA_DIR="$DATA_DIR"
  export PRODUCTS_DIR="$ROOT/products"
  export WORKER_ID="${WORKER_ID:-$(hostname -s)-mac}"
}

running() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

case "${1:-run}" in
  run)
    [ -d "$DATA_DIR" ] || { bad "no data folder at $DATA_DIR (open the desktop app once, or set WORKER_DATA_DIR)"; exit 1; }
    environment
    exec uv run python -m wasifyai_engine_worker
    ;;
  start)
    if running; then ok "the engine worker is already running (pid $(cat "$PIDFILE"))"; exit 0; fi
    if [ ! -d "$DATA_DIR" ]; then
      warn "no engine worker: no data folder at $DATA_DIR (the web offers only the hosted speech models until one runs)"
      exit 0
    fi
    environment
    nohup uv run python -m wasifyai_engine_worker >"$LOGFILE" 2>&1 &
    echo $! >"$PIDFILE"
    ok "engine worker started (pid $!, log: $LOGFILE)"
    ;;
  stop)
    if running; then
      pid="$(cat "$PIDFILE")"
      # the worker answers SIGTERM by finishing its job loop and leaving the list of workers
      pkill -TERM -P "$pid" 2>/dev/null || true
      kill -TERM "$pid" 2>/dev/null || true
      rm -f "$PIDFILE"
      ok "engine worker stopped"
    else
      rm -f "$PIDFILE"
    fi
    ;;
  models)
    environment
    shift
    exec uv run python -m wasifyai_engine_worker.models_cli "$@"
    ;;
  logs)
    exec tail -f "$LOGFILE"
    ;;
  *)
    echo "usage: $0 start|stop|run|logs|models" >&2
    exit 2
    ;;
esac
