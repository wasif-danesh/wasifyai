#!/usr/bin/env bash
# The web app on this Mac with the models on this Mac: Postgres, Redis, object storage and the gateway in
# containers; the API (which runs audio.cpp on Metal) and the web app natively, so the web screens for music,
# splitting, voice change, speech edit, dubbing, the audiobook and lip sync work without a GPU host.
#
#   scripts/web-local.sh                       # uses the desktop app's data folder
#   WEB_LOCAL_DATA_DIR=/path scripts/web-local.sh
#
# The data folder is where the speech runtime and the models were set up (the desktop app's Models screen
# does that). Quit the desktop app first: both would use the same memory and the same files.
set -euo pipefail
. "$(dirname "$0")/lib.sh"
cd "$ROOT"

[ -f .env ] || { bad "no .env: run make setup first"; exit 1; }
DATA_DIR="${WEB_LOCAL_DATA_DIR:-$HOME/Library/Application Support/ai.wasifyai.desktop}"
[ -d "$DATA_DIR" ] || { bad "no data folder at $DATA_DIR (set WEB_LOCAL_DATA_DIR)"; exit 1; }

set -a
# shellcheck disable=SC1091
. ./.env
set +a

step "Starting the services"
"$CONTAINER_ENGINE" compose up -d postgres redis seaweedfs seaweedfs-init litellm
for _ in $(seq 1 60); do
  "$CONTAINER_ENGINE" compose exec -T postgres pg_isready -U wasifyai -d wasifyai >/dev/null 2>&1 && break
  sleep 1
done
"$CONTAINER_ENGINE" compose exec -T postgres pg_isready -U wasifyai -d wasifyai >/dev/null \
  || { bad "Postgres did not become ready"; exit 1; }

# the services are published on this machine; the containers' own names are for the containers
export DATABASE_URL="postgresql+asyncpg://wasifyai:wasifyai@localhost:5432/wasifyai"
export REDIS_URL="redis://localhost:6379/0"
export LITELLM_BASE_URL="http://localhost:4000"
export STORAGE_ENDPOINT="http://localhost:8333"
export STORAGE_PUBLIC_ENDPOINT="http://localhost:8333"
export AUTH_MODE="${AUTH_MODE:-stub}"
# speech from the models on this Mac, and hosted ones too where the gateway has them (VOICE_ENGINE=both)
export VOICE_ENGINE="${VOICE_ENGINE:-local}"
export DESKTOP_DATA_DIR="$DATA_DIR"

step "Applying migrations"
(cd services/api && uv run alembic upgrade head)

step "Starting the API and the web app"
PIDS=""
cleanup() { for p in $PIDS; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM
(cd services/api && exec uv run uvicorn wasifyai_api.main:app --host 127.0.0.1 --port 8000) &
PIDS="$PIDS $!"
(cd apps/web && API_BASE_URL="http://127.0.0.1:8000" exec pnpm exec next dev --port 3000) &
PIDS="$PIDS $!"

printf '\n%sReady.%s Open %shttp://localhost:3000%s (data folder: %s, speech from: %s)\n' \
  "$GREEN" "$RESET" "$BOLD" "$RESET" "$DATA_DIR" "$VOICE_ENGINE"
printf 'The side menu lists a voice screen when a model for it is ready in that folder. Ctrl-C stops both.\n\n'
wait
