#!/bin/bash
# Pictures of every screen of the real desktop window for docs/ui-audit (docs/ui-audit-2026-10-27.md).
#
# Starts the engine the way the Tauri shell does (the desktop profile, this computer's app data, a token
# signed with a secret made for this run), serves the window with Vite on :1420, and drives it with the
# Playwright that apps/web already has. The shell itself is not started: a small polyfill in
# ui-audit-pictures.mjs answers the window's few shell commands. Everything is stopped at the end, by PID.
#
#   apps/desktop/scripts/ui-audit.sh            # writes docs/ui-audit/desktop/*.png
#
# Needs the checkout's .venv (make setup) and pnpm install. Quit the desktop app first: both would use the
# same database. With a throwaway DESKTOP_DATA_DIR the app may stay open if the window is served on another
# port than the app's own 1420: WASIFYAI_AUDIT_WINDOW_PORT=1431 (and another WASIFYAI_AUDIT_PORT).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
RUN=$(mktemp -d)
PORT=${WASIFYAI_AUDIT_PORT:-8765}
WINDOW_PORT=${WASIFYAI_AUDIT_WINDOW_PORT:-1420}
DATA="${DESKTOP_DATA_DIR:-$HOME/Library/Application Support/ai.wasifyai.desktop}"
SECRET=$("$ROOT/.venv/bin/python" -c "import secrets; print(secrets.token_urlsafe(36))")

cleanup() {
  [ -n "${ENGINE_PID:-}" ] && kill "$ENGINE_PID" 2>/dev/null || true
  [ -n "${VITE_PID:-}" ] && kill "$VITE_PID" 2>/dev/null || true
  rm -rf "$RUN"
}
trap cleanup EXIT

# the engine, from the data folder (never the checkout: its .env must not reach it); `exec` so the PID kept
# for cleanup is the process itself, not a subshell
(cd "$DATA" && exec env DEPLOYMENT_PROFILE=desktop DESKTOP_DATA_DIR="$DATA" DESKTOP_IMAGE_ENGINE=auto \
  API_AUTH_SECRET="$SECRET" AUTH_MODE=jwt PRODUCTS_DIR="$ROOT/products" WASIFYAI_PORT="$PORT" \
  DESKTOP_ALLOWED_ORIGINS="http://localhost:$WINDOW_PORT" \
  PYTHONUNBUFFERED=1 PYTHONUTF8=1 "$ROOT/.venv/bin/python" -m wasifyai_api.desktop >"$RUN/engine.log" 2>&1) &
ENGINE_PID=$!
for _ in $(seq 1 120); do
  curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
  sleep 1
done
curl -sf "http://127.0.0.1:$PORT/health" >/dev/null || { echo "the engine did not start; see $RUN/engine.log"; cat "$RUN/engine.log" | tail -20; exit 1; }

# the token the shell would sign for the window (session.rs: the same claims)
TOKEN=$("$ROOT/.venv/bin/python" - "$SECRET" <<'PY'
import sys, time, jwt
now = int(time.time())
print(jwt.encode({"iss": "wasifyai-web", "aud": "wasifyai-api", "sub": "desktop:local", "iat": now, "exp": now + 3600}, sys.argv[1], algorithm="HS256"))
PY
)

(cd "$ROOT/apps/desktop" && exec node ./node_modules/vite/bin/vite.js --port "$WINDOW_PORT" --strictPort >"$RUN/vite.log" 2>&1) &
VITE_PID=$!
for _ in $(seq 1 60); do
  curl -sf "http://localhost:$WINDOW_PORT/" >/dev/null 2>&1 && break
  sleep 1
done

WASIFYAI_AUDIT_BASE="http://127.0.0.1:$PORT" WASIFYAI_AUDIT_TOKEN="$TOKEN" \
  WASIFYAI_AUDIT_WINDOW="http://localhost:$WINDOW_PORT" \
  node "$ROOT/apps/desktop/scripts/ui-audit-pictures.mjs" "$@"
