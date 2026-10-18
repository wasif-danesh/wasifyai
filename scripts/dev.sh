#!/usr/bin/env bash
# Start the stack, wait for Postgres, apply migrations, then follow logs.
set -euo pipefail
. "$(dirname "$0")/lib.sh"
cd "$ROOT"

"$ROOT/scripts/preflight.sh"

step "Starting the stack"
"$CONTAINER_ENGINE" compose up -d --build

step "Waiting for Postgres"
for _ in $(seq 1 60); do
  "$CONTAINER_ENGINE" compose exec -T postgres pg_isready -U wasifyai -d wasifyai >/dev/null 2>&1 && break
  sleep 1
done
"$CONTAINER_ENGINE" compose exec -T postgres pg_isready -U wasifyai -d wasifyai >/dev/null || { bad "Postgres did not become ready"; exit 1; }

step "Applying migrations"
(cd services/api && uv run alembic upgrade head)

printf '\n%sReady.%s Open %shttp://localhost:3000%s   (API: http://localhost:8000/docs)\n' "$GREEN" "$RESET" "$BOLD" "$RESET"
printf 'Following logs (Ctrl-C stops the log view, not the stack). Stop the stack with: make down\n\n'
exec "$CONTAINER_ENGINE" compose logs -f
