# ADR-0049: Redis and Postgres viewers in every environment

- **Status:** Accepted
- **Date:** 2026-10-10

## Context

When a job seems stuck or a run ends oddly, the answer is in two places: the Redis streams (`wasifyai:jobs`,
`wasifyai:done`, the per-run event streams, consumer groups and their pending entries) and the Postgres tables
(LangGraph checkpoints, `runs`, `jobs`, `usage_events`, the product tables). Until now the only way in was
`redis-cli` and `psql` through a port-forward. The owner wants a graphical Redis viewer and a Postgres viewer in
**development, staging and production**.

Facts (checked 2026-10-10):

- **RedisInsight** (the official viewer) is licensed **SSPL**, not an OSI open-source licence, and has no login
  of its own. As a *desktop application* it runs on the operator's machine and connects to any Redis it can
  reach, including one behind `kubectl port-forward` or Tailscale. Nothing needs to be hosted for it.
- **Redis Commander** (MIT) is the hosted alternative, with weak stream support and no consumer-group view.
- Postgres viewers: **Adminer** (Apache-2.0 or GPL-2.0, one small container), **pgAdmin** (PostgreSQL licence,
  own users, heavier), **CloudBeaver** (Apache-2.0, heavier).
- The database holds user content and e-mail addresses. A viewer reads all of it, so in production that is a
  privacy decision, not only a convenience.

## Decision

1. **Redis: RedisInsight desktop only.** Nothing is hosted for Redis in any environment. The operator connects
   through `kubectl port-forward` (kind, GCP) or Tailscale (staging). No SSPL software is shipped, built into an
   image or run in a cluster by this project. A hosted viewer (Redis Commander) is added only if the desktop route
   proves not to work for staging or production.
2. **Postgres: Adminer in the cluster**, one chart component `tools.postgresViewer`, off by default and switched
   on per environment by values only (rule 1). `ClusterIP` only, **no ingress in any environment**. A patched
   version is pinned. It connects with a dedicated **read-only role** `wasifyai_viewer` (`SELECT` only, created by a
   migration). A write attempt fails in the database, not in the viewer. The same read-only role also works from a
   desktop SQL client over a port-forward, so Adminer is a convenience, not the only way.
3. **Production is on demand.** Adminer is installed but at **zero replicas**. `make tools-up` scales it to one
   for a session and `make tools-down` back to zero; the cloud audit log records who did it. Reading production
   data is break-glass: allowed, short and written down.
4. **Development:** a Compose profile (`--profile tools`) starts Adminer on localhost with the same role.
   `make urls` lists it, and the Redis entry names the port-forward command for RedisInsight.
5. **No `/admin/queue` page for now.** RedisInsight shows streams and consumer groups; the page was only needed
   to compensate for Redis Commander. It can be added later without a decision.

## Evaluation

1. RedisInsight desktop, through a port-forward to the kind Redis, shows `wasifyai:jobs`, its consumer group and pending
   entries while a job runs. The same procedure is written for staging (Tailscale) and the GCP test.
2. On kind with the tools on: Adminer shows the tables, a write is refused, and nothing answers without
   credentials.
3. A Helm test asserts that no tool has an ingress and that the production values keep Adminer at zero replicas.

## Consequences

- One small image to patch (Adminer); it is off the product path, so an outage affects no user.
- Redis access depends on the operator's desktop and network route. Its steps live in the runbook.
- The read-only role can read user content; the on-demand rule is the control, not the role.

## Alternatives considered

- **Host RedisInsight:** best stream tool, but SSPL and no login. Not needed, because the desktop app covers it.
- **Redis Commander (MIT, hosted):** works without a desktop, but weak on streams; the fallback if desktop access
  fails.
- **pgAdmin or CloudBeaver instead of Adminer:** per-person accounts, heavier; revisit when more than one operator
  needs the database.
- **Only `psql`:** what we had; correct but slow for the common questions.

## Owner's answers (2026-10-10)

1. "If I can monitor staging/live using RedisInsight desktop, then don't need it, otherwise yes." → Desktop
   RedisInsight over a port-forward or Tailscale; a hosted Redis viewer only if that fails (decision 1).
2. Postgres viewer and production access: not answered separately; the proposal above (Adminer, read-only role,
   production at zero replicas) stands until changed.

## Docs to update

`docs/environments.md`, `docs/configuration.md`, `README.md` and `scripts/urls.py` (the URL table; add the Redis
desktop route), `docs/runbooks/monitoring.md` (a link), a migration for the `wasifyai_viewer` role, and a short
runbook "Looking inside Redis and Postgres".
