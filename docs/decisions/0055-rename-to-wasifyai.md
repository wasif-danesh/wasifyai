# ADR-0055: Rename the project and every product from `wd-*` to `wasifyai`

- **Status:** Proposed
- **Date:** 2026-10-13

## Context

"WD" is a registered trademark of Western Digital for hardware and software, so it cannot be used in this
project's names. The owner has registered `wasifyai.com`; products will live on subdomains of it
(`art.wasifyai.com`, and so on). The project and its products were named with the `wd-` prefix and a
trailing `-ai`.

## Decision

- **Project:** `wd-ai` becomes `wasifyai` (repository folder, Helm chart, compose project, container images,
  bucket, Postgres role and database).
- **Products:** `wd-<x>-ai` becomes `wasifyai-<x>` for music, image, video, tts, stt and lipsync. The trailing
  `-ai` is dropped because the prefix already says it.
- **Code:** Python packages `wd_*` become `wasifyai_*` (`wasifyai_platform_sdk`, `wasifyai_api`,
  `wasifyai_media_worker`, `wasifyai_contracts`, `wasifyai_<x>`); the TypeScript scope `@wd/contracts` becomes
  `@wasifyai/contracts`; the product entry-point group `wd_ai.products` becomes `wasifyai.products`;
  environment prefixes `WD_<X>_AI__` become `WASIFYAI_<X>__`; Redis key prefix `wd:` becomes `wasifyai:`;
  the model-gateway metadata key `wd` becomes `wasifyai`; the session claim `wd` becomes `wasifyai`.
- **Product ids are data.** They are stored in tables (`product_id`) and in object keys
  (`{tenant}/{product}/{user}/...`). Dev data is carried over by `scripts/migrate-from-wd.sh` (copies volumes,
  renames the role and database, rewrites `product_id` and the gateway key on the copy) and
  `scripts/migrate_storage.py` (copies objects to the new bucket with the product segment rewritten).
  Old volumes are never modified. See `docs/runbooks/rename-from-wd.md`.
- Accepted ADRs were edited mechanically for the names only (no decision text changed); this ADR is the record.

## Consequences

- A new compose project name means new volumes (`wasifyai_*`); the old `wd-ai_*` volumes remain until removed.
- Existing sessions are signed out (the session claim changed); API tokens issued before are invalid.
- Anything outside the repository that uses the old names must be changed by the owner: the GitHub repository
  name and remote URL, container registry paths (`ghcr.io/<owner>/<repo>/...`, derived from the repository name),
  Argo CD applications, External Secrets entries and DNS.
- Screenshots in `docs/images/` still show the old brand text and are regenerated separately.
- The architecture picture (`wd-ai-system-architecture.jpeg`) is not text and was not changed.
