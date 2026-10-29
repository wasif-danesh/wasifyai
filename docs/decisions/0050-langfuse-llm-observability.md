# ADR-0050: LLM observability, analytics and cost tracking with Langfuse

- **Status:** Accepted
- **Date:** 2026-10-10

## Context

ADR-0048 gives us system health: metrics, logs and alerts. It does not tell us how the models behave. We cannot
yet answer: which prompts are slow or expensive, what a graph did step by step for one run, how many tokens or
how much money each product used this week, which moderation calls refused and why, or whether a model change made
things better or worse. What exists:

- `usage_events` in Postgres: tokens and counts per call, the input to billing, not an analysis tool.
- LiteLLM computes per-request cost and keeps basic spend logs; that is its own small view.
- Prometheus: per-product run and job counters, no prompts, no per-call cost.

The owner wants monitoring, analytics and cost tracking for LLM use, self-hosted.

Facts (checked 2026-10-10):

- **Langfuse** is open source (its `ee` folders, enterprise features, are not needed).
  It provides traces, prompt management, evaluations, datasets and a playground, and is self-hostable. It has
  official Helm charts.
- Self-hosting needs **Postgres, ClickHouse, Redis (or Valkey) and S3-compatible storage**, plus its web and worker
  containers. **ClickHouse is a new datastore for this project** and CLAUDE.md requires an ADR for that.
- **LiteLLM** (our model gateway) sends every call to Langfuse with `success_callback: ["langfuse"]`, including
  cost and token usage, and can turn message logging off (`turn_off_message_logging`) or redact key and user
  identity (`redact_user_api_key_info`).
- Graph-level traces come from Langfuse's LangChain callback handler, which LangGraph accepts as a run callback
  (to be confirmed in the spike below).
- The calls contain user content. Where that data lives and who can open it is the main design question.

## Decision

1. **Langfuse, self-hosted, in the cluster**, installed from its official Helm chart in an `observability`
   namespace, next to the monitoring stack. The `ee` features are not used. It is **not** used for
   alerting (Alertmanager stays the only place alerts come from) and it does **not** replace `usage_events`
   (billing's source of truth) or Prometheus.
2. **New datastore: ClickHouse**, owned by Langfuse and used by nothing else. Postgres, Redis and object storage
   are Langfuse's own instances or databases (a separate database and bucket, not shared tables). Sizes are set in
   chart values per environment.
3. **Two ingestion paths:**
   - **The gateway:** LiteLLM logs every model call to Langfuse (model, tokens, latency, cost). Our capability
     layer already passes the product id and run id; they become the call's metadata, which makes cost and latency
     filterable by product.
   - **The graphs:** the API attaches Langfuse's callback to each run, so a trace shows the run's nodes and the
     calls inside them. Media jobs (GPU seconds, queue time) are added as observations, since they are not LLM
     calls.
4. **Privacy is configuration, per environment, decided by the owner:** `LANGFUSE_CAPTURE_CONTENT` (prompts and
   outputs stored or only metadata and cost). The proposal: on in development and staging, **off in the GCP test
   and in production** until a privacy review. User ids sent to Langfuse are a one-way hash. Sign-up is disabled
   and access is by port-forward or Tailscale, never an ingress. Retention 30 days.
5. **Cost for local models.** Ollama calls cost nothing in dollars, so Langfuse would show zero. We define model
   prices in Langfuse (an internal price per 1,000 tokens, derived from GPU time) so product and model
   comparisons mean something; the media GPU seconds already in `usage_events` are shown next to it in Grafana.
6. **Scope in v1:** an optional install in kind (`KIND_LANGFUSE=1`, off by default: ClickHouse needs a few GB),
   on in staging and in the GCP test. Langfuse's evaluation and prompt features are not adopted yet.

## Evaluation (exit criteria)

1. After a run in kind, its trace is visible with a span per node and the model calls under them, with tokens,
   latency and cost, filterable by product.
2. With content capture off, no prompt or output text is stored (a test reads a trace through the API).
3. A user id in Langfuse is a hash, and no e-mail address appears anywhere in it.
4. The dashboard answers: cost per product per day, slowest prompts, refusal count by product.
5. ClickHouse stays within its memory limit under the six-product run.

## Consequences

- A fifth datastore (ClickHouse) and six more pods; the largest addition so far. About 3 to 4 GB of memory.
- Prompt and output text is a new place user content lives; the capture switch and the retention are the controls.
- Costs for local models are estimates by design; the real cost on a cloud model is exact.
- If Langfuse is down, runs are unaffected: both ingestion paths are asynchronous and best-effort.

## Alternatives considered

- **LangSmith:** the natural pair for LangGraph, but proprietary and cloud-hosted; against rule 12 and data
  residency.
- **Arize Phoenix:** open source and lighter; no cost
  analytics comparable to Langfuse.
- **OpenTelemetry traces into Grafana Tempo:** fits the existing stack, but no prompt or cost views, and we would
  build them.
- **LiteLLM's built-in spend UI only:** zero new components, gateway-level only; stays as the fallback.
- **Do nothing; query `usage_events`:** enough for billing, not for debugging model behaviour.

## Questions for the owner

1. ClickHouse as a new datastore: acceptable?
2. Prompt and output text captured in staging: yes? In the GCP test and production: off until a privacy review?
3. Who may open Langfuse (just you, or others), and is "port-forward or Tailscale only" right?
4. 30 days retention, or longer for cost history?

## Owner's answers (2026-10-10)

Yes to all four: ClickHouse as a new datastore; prompt and output text captured in staging and off in the GCP
test and production until a privacy review; access by port-forward or Tailscale only; 30 days retention.

## Built (2026-10-29, stage O1)

- **The graphs:** `wasifyai_api/run_tracing.py` gives each run Langfuse's LangChain callback (the `langfuse`
  Python SDK 5.0.4) when `LANGFUSE_BASE_URL`, `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set. With
  `LANGFUSE_CAPTURE_CONTENT` off (the default) every input and output is replaced by "[not captured]" before it
  leaves; the person is a one-way hash of tenant and user; the product is a tag. Langfuse has a tracer provider
  of its own, so its prompts never reach Tempo, and its traces share the run's trace id.
- **The gateway:** with `langfuse.baseUrl` set, the chart turns on LiteLLM's `langfuse` callback, with
  `turn_off_message_logging` unless content is captured and `redact_user_api_key_info`.
- **The install:** `scripts/langfuse-up.sh` (chart 2.1.5, `deploy/monitoring/langfuse.values.yaml`) with sign-up
  off, the first person, project and key pair made from a Secret, and the keys copied into the app's Secret.
  Chart 2.x needs the ClickHouse operator and cert-manager first. Staging's values turn it on with content
  captured; production leaves it off.
- **Not verified:** nothing has run against a real Langfuse yet (no cluster with ClickHouse here); the acceptance
  "a prompt and its cost show in Langfuse on staging" waits for staging. Media jobs are not yet observations in
  Langfuse (they are spans in Tempo). Model prices for local models (decision 5) are not set.

## Docs to update

`docs/architecture.md`, `docs/environments.md`, `docs/configuration.md`, `docs/runbooks/` (a Langfuse runbook),
`CLAUDE.md` (the datastore list), `scripts/urls.py` and the README table, and the chart values for LiteLLM.
