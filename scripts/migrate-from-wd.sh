#!/usr/bin/env bash
# One-off migration of local dev data from the former project name to wasifyai.
#
# The compose project was renamed, so the stack now uses NEW volumes (wasifyai_*). This script COPIES the
# old ones (wd-ai_*): it never modifies or deletes them. Then, on the copy of the database it renames the
# Postgres role and database and rewrites the product ids and the model-gateway metadata key.
#
# Usage (stack stopped: make down):
#   scripts/migrate-from-wd.sh            # database + object storage volumes (small)
#   scripts/migrate-from-wd.sh --models   # also the downloaded speech/STT model caches (about 11 GB)
# Then: make dev, and run: uv run python scripts/migrate_storage.py
set -euo pipefail
ENGINE="${CONTAINER_ENGINE:-podman}"
OLD="wd-ai"; NEW="wasifyai"
WITH_MODELS=0; [ "${1:-}" = "--models" ] && WITH_MODELS=1
PG_COPIED=0
PG_IMAGE="${PG_IMAGE:-docker.io/pgvector/pgvector:pg16}"

say() { printf '==> %s\n' "$*"; }
exists() { "$ENGINE" volume inspect "$1" >/dev/null 2>&1; }

copy_volume() {  # old new
  if ! exists "$1"; then say "skip $1 (not found)"; return; fi
  if exists "$2"; then say "skip $2 (already exists; refusing to overwrite)"; return; fi
  say "copy $1 -> $2"
  [ "$2" = "${NEW}_pgdata" ] && PG_COPIED=1
  "$ENGINE" volume create "$2" >/dev/null
  "$ENGINE" volume export "$1" | "$ENGINE" volume import "$2" -
}

if "$ENGINE" ps --format '{{.Names}}' | grep -qE "^(${OLD}|${NEW})-"; then
  echo "A stack is running. Stop it first: make down" >&2; exit 1
fi

copy_volume "${OLD}_pgdata" "${NEW}_pgdata"
copy_volume "${OLD}_seaweeddata" "${NEW}_seaweeddata"
if [ "$WITH_MODELS" = 1 ]; then
  for v in speechmodels indicmodels sttmodels; do copy_volume "${OLD}_$v" "${NEW}_$v"; done
else
  say "model caches not copied (add --models, or they are downloaded again on first use)"
fi

if [ "$PG_COPIED" != 1 ]; then
  say "database volume was not copied in this run: leaving it as it is (already migrated)"
  say "done."
  exit 0
fi
say "renaming the Postgres role and database, rewriting product ids (on the copy)"
read -r -d '' SQL <<'SQL' || true
CREATE ROLE tmp_admin SUPERUSER LOGIN;
SQL
read -r -d '' SQL2 <<'SQL' || true
ALTER ROLE wd RENAME TO wasifyai;
ALTER ROLE wasifyai WITH PASSWORD 'wasifyai';
ALTER DATABASE wd RENAME TO wasifyai;
SQL
read -r -d '' SQL3 <<'SQL' || true
DO $$
DECLARE r record; n bigint; total bigint := 0;
BEGIN
  FOR r IN SELECT table_schema, table_name FROM information_schema.columns
           WHERE column_name = 'product_id' AND table_schema = 'public' LOOP
    EXECUTE format($f$UPDATE %I.%I SET product_id = CASE product_id
        WHEN 'wd-music-ai' THEN 'wasifyai-music' WHEN 'wd-image-ai' THEN 'wasifyai-image'
        WHEN 'wd-video-ai' THEN 'wasifyai-video' WHEN 'wd-tts-ai' THEN 'wasifyai-tts'
        WHEN 'wd-stt-ai' THEN 'wasifyai-stt' WHEN 'wd-lipsync-ai' THEN 'wasifyai-lipsync'
        ELSE product_id END
      WHERE product_id LIKE 'wd-%%'$f$, r.table_schema, r.table_name);
    GET DIAGNOSTICS n = ROW_COUNT; total := total + n;
    RAISE NOTICE 'product_id: % rows in %', n, r.table_name;
  END LOOP;
  -- the model gateway keeps our metadata under the key "wd" in model_info (now "wasifyai")
  FOR r IN SELECT table_schema, table_name FROM information_schema.columns
           WHERE column_name = 'model_info' AND data_type = 'jsonb' LOOP
    EXECUTE format($f$UPDATE %I.%I SET model_info = (model_info - 'wd')
        || jsonb_build_object('wasifyai', model_info -> 'wd') WHERE model_info ? 'wd'$f$,
        r.table_schema, r.table_name);
    GET DIAGNOSTICS n = ROW_COUNT;
    RAISE NOTICE 'model_info key: % rows in %.%', n, r.table_schema, r.table_name;
  END LOOP;
END $$;
SQL
# volume import does not keep the data directory's owner and mode; Postgres insists on both
"$ENGINE" run --rm --user root --entrypoint bash -v "${NEW}_pgdata:/var/lib/postgresql/data" \
  "$PG_IMAGE" -c 'chown -R postgres:postgres /var/lib/postgresql/data && chmod 700 /var/lib/postgresql/data'
"$ENGINE" run --rm --user postgres --entrypoint bash \
  -v "${NEW}_pgdata:/var/lib/postgresql/data" -e PGDATA=/var/lib/postgresql/data \
  -e SQL="$SQL" -e SQL2="$SQL2" -e SQL3="$SQL3" "$PG_IMAGE" -c '
set -e
pg_ctl -D "$PGDATA" -o "-c listen_addresses= -c unix_socket_directories=/tmp" -w -l /tmp/pg.log start >/dev/null
P="psql -v ON_ERROR_STOP=1 -h /tmp"
$P -U wd -d postgres -c "$SQL"
$P -U tmp_admin -d postgres -c "$SQL2"
$P -U tmp_admin -d wasifyai -c "$SQL3"
$P -U tmp_admin -d wasifyai -c "REASSIGN OWNED BY tmp_admin TO wasifyai" >/dev/null
$P -U wasifyai -d postgres -c "DROP ROLE tmp_admin"
pg_ctl -D "$PGDATA" -m fast -w stop >/dev/null
'
say "done. Next: make dev, then: uv run python scripts/migrate_storage.py"
