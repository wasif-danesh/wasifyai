# ADR-0031: Model access: what building it taught us about LiteLLM

- **Status:** Accepted
- **Date:** 2026-10-08
- **Refines:** ADR-0025

## Context

ADR-0025 decided that an admin changes LLM providers at run time through LiteLLM's model-management
API. Building it against the real gateway (`ghcr.io/berriai/litellm:main-stable`, database mode)
showed behaviour the plan did not assume. These are the constraints the implementation follows.

## Decision and findings

- **One alias, one stored entry, one fixed id.** Defaults are seeded as `alias:<name>` and an admin
  edits that same entry. A second entry with the same alias *joins the pool* (calls are shared and
  fall back to each other), and entries from `litellm.yaml` cannot be edited, so `litellm.yaml` and the
  Helm ConfigMap hold settings only. Seeding checks first, because creating a duplicate id returns 500.
- **LiteLLM's tables live in the `litellm` schema of the platform Postgres** (`?schema=litellm` in its
  `DATABASE_URL`); no second database is needed. It applies its own migrations at start.
- **Two calls to update one entry.** `POST /model/update` changes `litellm_params` and ignores
  `model_info`; `PATCH /model/{id}/update` changes `model_info`. Our own metadata (source, provider,
  model, server address, whether a key is saved, who changed it and when) is kept under
  `model_info.wasifyai`, which is replaced as a whole on each change.
- **Updates merge into what is stored, so a key must be overwritten, never omitted.** An update that
  leaves `api_key` out keeps the old key, which LiteLLM would then send to whatever server the alias
  points at after the change (a Gemini key to an arbitrary "server address", for example). Every save
  and every reset therefore writes `api_key` explicitly: the new key, or the literal `none`. A live
  regression test (`test_model_access_live.py`) records the `Authorization` header a server receives
  after each change.
- **Keys are encrypted by LiteLLM**, using `LITELLM_SALT_KEY`, which must be set once and never changed.
  `/model/info` never returns them; our listings, audit entries and logs never contain them.
- **The test and the canary use a temporary candidate.** A candidate entry (`candidate:<alias>:<id>`)
  is created from the proposed binding, used, and deleted in a `finally`; leftovers older than ten
  minutes are removed at the next start. "Test connection" can therefore try a binding before it is saved.
- **Protected aliases (`moderator`) need the product's checks to pass first.** A product registers a
  check for a capability (`registry.add_check`); the platform runs every check for products whose
  capability uses that alias, with the capability pointed at the candidate, and rejects the change
  with the failures. `wasifyai-music` registers a canary of 11 must-refuse and 6 must-allow cases drawn
  from its evaluation set: every must-refuse case has to be refused, and at most one harmless request may
  be refused. On the default model it passes in about 30 seconds; a model that cannot classify (an
  embedding model, a bad key) fails every case and is rejected in under a second.
- **Seeding is the API's job**, in the background at start with retries (LiteLLM may still be starting),
  and idempotent, so several API replicas can run it. `kind-smoke.sh` checks that all six aliases are
  seeded.
- **The set of aliases is fixed by the defaults file.** An admin changes what serves an alias, not
  which aliases exist; products ask for these names.

## Consequences

- Existing `.env` files need `LITELLM_SALT_KEY` (`make setup` adds it); Helm needs it in the Secret
  (`scripts/k8s-secrets.sh` adds it to an existing Secret) and `LITELLM_DATABASE_URL` when Postgres is
  external.
- LiteLLM now depends on Postgres, so it starts after it and takes longer to become ready.
- If LiteLLM's database is lost, the aliases are re-seeded as defaults and saved keys must be entered
  again.
- Media providers (Comfy Cloud, OpenAI-compatible images, ...) are not covered here; they need adapters in
  the media worker and are the next part of ADR-0025.
