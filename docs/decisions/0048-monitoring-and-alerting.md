# ADR-0048: Monitoring and alerting

- **Status:** Accepted
- **Date:** 2026-10-10

## Context

Stage 2 of the v1 plan (`docs/roadmap.md`) adds monitoring once the system works end to end on local kind.
What exists today: structured JSON logs with request, trace, tenant and product ids, health endpoints, usage
events in Postgres (billing input, not monitoring), and the convention in `CLAUDE.md` to instrument with
OpenTelemetry, which is not done. There is no metrics endpoint, no dashboard and no alert.

The constraints that decide the design:

- **One operator, a few environments.** Local kind, a private staging box (a 24 GB NVIDIA GPU, reached over
  Tailscale) and a short-lived GCP test that is shut down afterwards. There is no on-call rota; one person must
  hear about a real failure on a phone.
- **Cloud-neutral and open source first** (rules 11 and 12): no Cloud Monitoring, Datadog or other managed or
  proprietary service in platform code.
- **Same images and charts everywhere** (rule 1): environments differ by values only.
- **The things that fail here are specific:** a GPU job that never finishes, a model server that is up but
  answers errors, a queue that stops draining, a volume full of models, a moderation model that is unreachable
  (the run then fails closed, ADR-0047).
- **Private staging cannot be probed from the internet**, and a monitor that lives inside the cluster is blind
  to the cluster itself being down.

## Decision

1. **The monitoring stack runs in the cluster it watches**, in its own `monitoring` namespace, installed from the
   `kube-prometheus-stack` chart: Prometheus (metrics), Alertmanager (routing) and Grafana (dashboards), plus
   Loki for logs, **in every environment including kind** (the owner's decision). It is cloud-neutral and the same
   chart serves kind, staging and GCP. Defaults: 15 days of metrics, 7 days of logs, small volumes.
2. **Applications expose metrics.** The API and the media worker serve `/metrics` (Prometheus text format, on
   a separate port for the worker). Metric names are stable and low-cardinality: labels are the product, the
   capability, the outcome and the HTTP route template, **never a user id, a prompt or any content**.
   Initial set:
   - requests: count and latency by route template and status;
   - runs: started and finished by product and outcome (`done`, `refused`, `failed`), refusals by category;
   - jobs: queue depth, jobs by capability and status, duration, GPU seconds, retries;
   - uploads accepted and refused; quota refusals; moderation unavailable (fails closed).
3. **Infrastructure metrics come from standard exporters:** kube-state-metrics and node-exporter (in the chart),
   the NVIDIA DCGM exporter on the GPU host, and Postgres and Redis exporters. Pod and volume usage from the
   kubelet.
4. **Alerts start with about ten rules, each with a runbook line.** Critical (a message at once): API or web
   down; media worker down or the job queue not draining for 10 minutes; Postgres or Redis down; a persistent
   volume above 90%; job failure ratio above 50% for 10 minutes; the language-model gateway unreachable.
   Warning (grouped, not urgent): failure ratio above 20%; a job slower than twice its usual duration; GPU memory
   near full; moderation or quota refusals spiking; certificate or backup problems when those exist.
   More rules are added only when something real is missed.
5. **Notifications go to Telegram** through Alertmanager's native receiver (a bot created with BotFather). The
   bot token is a Kubernetes Secret, never in values or the repository. Critical alerts notify immediately;
   warnings are grouped. WhatsApp (no free official API for alerts, unofficial gateways get banned) and Messenger
   are not used.
6. **One check from outside the cluster.** Prometheus's built-in `Watchdog` alert fires forever by design;
   Alertmanager sends it to an external heartbeat service every minute (Healthchecks.io free tier, or a "push"
   monitor in Uptime Kuma run on another machine). When the heartbeats stop, that service messages Telegram: the
   only way to learn that the whole cluster, or its monitoring, is dead. This works for private staging because
   the cluster pushes out and nothing reaches in.
7. **Not in v1:** Uptime Kuma as a primary monitor, cron-job.org (it needs a public URL, cannot receive
   heartbeats, and mostly emails), distributed tracing (OpenTelemetry traces), PagerDuty-style escalation, SLO
   dashboards, and log-based alerting. The first three can be added without changing this design.
8. **Access.** Grafana, Prometheus and Alertmanager have no public ingress. On staging they are reached over
   Tailscale or `kubectl port-forward`; the Grafana admin password comes from a Secret.
9. **Environment differences are values only:** `deploy/helm/monitoring/` holds a base values file and one per
   environment (kind, staging, gcp-test). The application chart gets a `metrics.enabled` switch and the
   `ServiceMonitor` objects.

## Amendment (2026-10-29, owner): traces

Decision 7 excluded distributed tracing from v1. The owner approved it for stage O1 of the 2026-10-27 plan:

- **OpenTelemetry** (`opentelemetry-api`, `-sdk`, `-exporter-otlp-proto-http`) in the API, the media
  worker, the engine workers and the action executor: one span per request, per run stretch, per graph node,
  per action and per engine or media job. The trace context travels in the job (`EngineJob.trace`,
  `JobRequest.trace`) and arrives from the web app's BFF as a `traceparent` header, so a run is one trace from
  the BFF to the worker. The helper is `wasifyai_platform_sdk/tracing.py`.
- **Where they go:** OTLP over HTTP to **Tempo** in the `monitoring` namespace (`scripts/monitoring-up.sh`,
  `deploy/monitoring/tempo.values.yaml`, 7 days), read in Grafana; the Helm value `tracing.otlpEndpoint` turns it
  on (staging all traces, production one in ten). On the desktop the engine writes one JSON line per span to
  `<data>/logs/traces.jsonl` (20 MB, then one older file).
- **What a span carries** follows decision 5's rule for labels, loosened only for ids: a product, a node, an
  action, a job kind, an outcome, an error code, a route template, the run's or job's id. Never a user id, an
  e-mail address, a prompt or content; `tracing.span` drops any other attribute and records an exception by its
  type only. Metric labels are unchanged.
- **Not yet:** the BFF exports no spans of its own; it starts or continues the trace id and sends it on (a Next.js
  OpenTelemetry setup is a later step and needs its own packages).

## Evaluation (the exit criterion for stage 2)

1. On kind, the dashboards show real numbers while `make kind-e2e` runs: runs per product, job durations, queue
   depth.
2. A fire drill on kind: stop the media worker; within 10 minutes the Telegram chat receives the critical alert,
   and it resolves when the worker is back. A log line for the same run can be found in Grafana by its request id.
3. A second drill: stop Prometheus; within 5 minutes the external heartbeat service messages the same chat.
4. No metric label carries a user id or content (a test scrapes `/metrics` after a run and checks).

## Consequences

- About 1 to 2 GB of memory and a few GB of disk per cluster for the stack; kind in full mode needs it on top
  of the models.
- Two new things to look after: the Telegram bot token (a Secret, rotated by editing it) and the external
  heartbeat account.
- Metrics discipline: any new label must pass the "no user data, bounded values" rule in review.
- Alert fatigue is the failure mode of this design; hence a small rule set that grows from real misses.
- The GCP test gets the same stack from the same values, then everything is removed by `tofu destroy`.

## Alternatives considered

- **Uptime Kuma only:** easy and good for "is it up", but blind to queues, failures and GPU; kept as an optional
  external probe.
- **A managed service (Cloud Monitoring, Datadog, Grafana Cloud):** breaks the cloud-neutral and open-source
  rules, or adds a vendor for a one-person system.
- **VictoriaMetrics or another lighter store:** viable and smaller, but the Prometheus ecosystem (exporters,
  rule examples, the chart) is the common denominator; revisit if memory on staging becomes a problem.
- **Alerts by email only:** too slow for a one-person on-call; Telegram reaches a phone.

## Owner's answers (2026-10-10)

1. **Telegram is the only channel.** The owner's Telegram user id is the destination (kept in `.env` as
   `TELEGRAM_CHAT_ID`, not in the repository). The bot token comes from BotFather and is kept in `.env` as
   `TELEGRAM_BOT_TOKEN`; the owner must press Start on the bot once before it can send.
2. **Healthchecks.io's free tier** is the outside heartbeat. Its ping URL is a secret (`HEALTHCHECKS_PING_URL`).
3. **Loki for logs everywhere**, including kind.
4. **Grafana, Prometheus and Alertmanager are private:** no public ingress, reached over Tailscale or
   `kubectl port-forward`.

## Secrets this needs

`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `HEALTHCHECKS_PING_URL` and the Grafana admin password. They live in
`.env` locally and in a Kubernetes Secret (External Secrets later); none is in a values file or the repository.

## Docs to update if accepted

`docs/roadmap.md` (stage 2 with this design), `docs/architecture.md` (an observability section),
`docs/environments.md`, `docs/configuration.md` (metrics settings), `CLAUDE.md` (the metrics label rule),
a runbook with the fire drills, and the chart READMEs.
