# Runbook: carry local dev data over after the rename from `wd-*`

The stack now runs as compose project `wasifyai` with new volumes. Nothing in the old `wd-ai_*` volumes is
modified or deleted by these steps.

1. `make down` (the stack must be stopped).
2. `scripts/migrate-from-wd.sh` copies the database and object-storage volumes (about 115 MB), renames the
   Postgres role and database to `wasifyai`, rewrites `product_id` in every table that has one, and moves the
   model gateway's `wd` metadata key to `wasifyai`. Add `--models` to also copy the downloaded speech, STT and
   Indic model caches (about 11 GB); otherwise they download again on first use.
3. `make dev`.
4. `uv run python scripts/migrate_storage.py` copies files from bucket `wd-ai` to `wasifyai`, rewriting the
   product segment of every key. Re-running it is safe (existing objects are skipped). `--dry-run` shows the count.
5. Check My creations in the web app. When satisfied, the old volumes can be removed:
   `podman volume rm wd-ai_pgdata wd-ai_seaweeddata wd-ai_speechmodels wd-ai_indicmodels wd-ai_sttmodels`.

Also update, outside the repository: the GitHub repository name and `git remote set-url origin ...`,
registry paths, and any Argo CD / External Secrets entries.
