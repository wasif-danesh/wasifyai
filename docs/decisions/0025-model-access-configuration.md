# ADR-0025: Model access configuration (local by default, admin-configurable)

- **Status:** Accepted (2026-10-08). The LiteLLM mechanism in decision 2 is subject to a spike; see Follow-ups
- **Superseded in part:** by ADR-0094 (2026-10-29): the product checks (canaries) before an alias changes, and the protected aliases, are removed.
- **Date:** 2026-10-08
- **Replaces:** the earlier draft "Hosted inference: no GPU in the cloud or home lab" (never accepted)

## Context

Every environment (dev, staging, production) should default to local models. An admin should be able
to change, from a UI, how LLMs and media models are reached: hosted LLM providers (Gemini, Groq,
Cerebras, OpenRouter, or any other LiteLLM-supported one) and media providers (local ComfyUI,
Comfy Cloud, OpenRouter, or others). Graphs already ask for capabilities and LiteLLM aliases
(rules 4 and 5), and the media worker already owns generation (rule 6), so graph and product code
should not change.

## Research (2026-10-08, vendor pages and search results; re-verify before building)

- **Comfy Cloud API:** runs API-format workflows at `https://cloud.comfy.org` with an `X-API-Key`
  header. Needs a paid subscription. Credits are charged for active GPU time. v1 is deprecated in
  favour of Comfy API v2. Inputs and outputs are kept 24 hours, so results must be copied to our
  storage at once. Unconfirmed: that it has our exact model files, credits per song, concurrency
  limits.
- **Free LLM tiers:** Gemini's free tier may use prompts to improve Google products and cannot serve
  users in the EEA, Switzerland or the UK. Groq and Cerebras free tiers are for prototyping
  (about 30 requests per minute).

## Decision (proposed)

1. **Local by default where hardware exists** (dev machines, home lab). On a cloud cluster with no
   GPU the platform starts "not configured": health checks say so and runs fail with a clear,
   typed error until an admin binds a provider.
2. **Aliases stay the contract.** The admin maps each LiteLLM alias (`default-chat`,
   `lyrics-writer`, `moderator`, `multimodal`, `embedder`) to a provider and model. The UI drives
   LiteLLM's model-management API, so "any provider" needs no code of our own.
3. **Media adapters.** One small interface per capability (`image.generate`, `music.generate`).
   Adapters: local ComfyUI, Comfy Cloud (reuses our workflows and map files), and a generic
   OpenAI-compatible images adapter. Each other provider needs its own adapter that translates
   our request (prompt, size, seed, duration) to that provider's parameters. Jobs carry the
   capability, not the provider; the worker resolves the active provider at run time and records
   which one it used in the usage event.
4. **Config storage.** Env vars and Helm values seed the defaults; admin overrides live in Postgres
   (tenant- and product-scoped, rule 7). An export and import as YAML makes drift from Git visible.
   This **amends rule 13** ("config only from env vars") for provider bindings only.
5. **API keys** are stored encrypted with a master key from the secrets manager or env, are
   write-only (never returned by the API, never logged), and are shown only as "set / not set".
6. **Moderation is protected.** A new or changed `moderator` binding goes live only after a canary
   set of must-refuse and must-allow cases passes (ADR-0022 evaluation cases). Fail closed stays.
7. **Provider metadata** on each binding: whether the provider trains on data (the UI warns about
   free tiers and blocks them in production), price per token or job (feeds `cost_usd` on usage
   events and billing), fallback order, and a budget limit with a circuit breaker.
8. **Admin access** uses the role from ADR-0030, an audit log of every change (who, what, when; no
   secrets), and a "test connection" action per binding. Every admin API route sits under `/admin`
   behind one `require_admin` dependency (403 for other users); the web app's `/admin` pages call
   it server-side and show an "Admins only" notice to non-admins. A `GET /me` route reports the caller's id,
   email, name and role so the UI can show or hide the admin link.
8a. **First admin release** (two steps): (1) foundation: the guard, the audit log, `/admin` shell,
   a read-only users list, and recent runs and usage; (2) model access: LLM and media provider
   configuration. Billing, Stripe and the credits ledger (ADR-0029) come last.
8b. **Becoming admin with GitHub.** Sign-in now asks GitHub for the primary email and its verified
   flag (`/user/emails`, scope already requested). Only a primary, verified address counts as
   verified, so `ADMIN_EMAILS` and account linking work for GitHub as well as Google. Any failure
   leaves the email unverified.
2a. **LLM runtime config** goes through LiteLLM's model-management API (`store_model_in_db`), so
   any LiteLLM-supported provider works without code. LiteLLM then needs its own database, a
   separate database on the existing Postgres. The alias names stay fixed in `litellm.yaml`
   defaults; the admin overrides which provider and model each alias routes to.
9. **Provider approval** (rule 12): Comfy Cloud and hosted LLM providers are proprietary services;
   this ADR records the approval once accepted.
10. **GPU on k3s (Phase 4)** stays valid for the home lab; it is no longer required for the cloud.

## Follow-ups

- **Spike result (decision 2a), 2026-10-08, LiteLLM `main-stable` with `STORE_MODEL_IN_DB`, a
  separate database on the existing Postgres:** it starts cleanly and applies its own migrations.
  `POST /model/new` adds a model that works at once and survives a restart; `/model/update` changes
  it live; `/model/delete` removes it; `/model/info` returns the cost per token. Stored provider
  keys are encrypted by LiteLLM (so we do not add our own key vault for LLM keys; set
  `LITELLM_SALT_KEY` once and never change it) and `/model/info` never returns them. Two things
  differ from the plan:
  1. A DB model with the same alias as one in `litellm.yaml` **joins the pool** (calls are shared
     and fall back between both); it does not replace it, and models defined in `litellm.yaml`
     cannot be edited or deleted through the API. So **the default aliases move out of
     `litellm.yaml` into the database**: a seed step creates them idempotently (fixed model ids such
     as `default:moderator`) from a defaults file in the repo, and the admin edits those entries.
     `litellm.yaml` keeps only settings (`drop_params`, and so on).
  2. LiteLLM must be seeded before the API serves requests, so the seed runs at API start (with
     retry) and in the Helm post-install job.
- Do Comfy Cloud's models match our workflows? Test with a paid key.
- Which hosted LLM first, after the guardrail evaluation (suggested: paid Gemini)?

## Consequences

- No product or graph code changes; the work is the admin UI, config store, adapters and canary.
- Runtime config is not in Git, so staging and production state needs the YAML export and an audit log.
- User ideas and lyrics reach third parties when hosted providers are used; the privacy policy must say so.
