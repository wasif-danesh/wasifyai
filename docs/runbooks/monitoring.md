# Runbook: monitoring and alerting (ADR-0048)

## What runs

In the `monitoring` namespace of each cluster: Prometheus, Alertmanager, Grafana, Loki (7 days of logs) and Promtail.
The application chart adds the scrape target (API and worker, port 9464, not reachable from outside the cluster), 10
alert rules plus the always-firing `Watchdog`, and a Grafana dashboard ("wd-ai overview").

Install: `make monitoring-up` (also part of `make kind-up` in full mode). **Only production sends:** without
`ALERT_NOTIFICATIONS=on` alerts fire and show in Alertmanager and Grafana, but nothing is sent and no token is stored.
With it on, the script reads `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` and `HEALTHCHECKS_PING_URL` from `.env` and
stores them in Secrets; nothing is written to a file in the repository. For the drills on kind:
`ALERT_NOTIFICATIONS=on make monitoring-up`. To mute production temporarily, create a silence in Alertmanager
(`kubectl -n monitoring port-forward svc/monitoring-alertmanager 9093:9093`, Silences, New silence). Remove with `helm uninstall loki monitoring -n monitoring`.

## Where to look

| Need | How |
|---|---|
| Dashboards and logs | `kubectl -n monitoring port-forward svc/monitoring-grafana 3001:80`, user `admin`, password: `kubectl -n monitoring get secret grafana-admin -o jsonpath={.data.admin-password} \| base64 -d`. Logs: Explore, data source Loki, `{namespace="wd-ai"}`. |
| What is firing | `kubectl -n monitoring port-forward svc/monitoring-alertmanager 9093:9093`, then http://localhost:9093 |
| Raw metrics, queries | `kubectl -n monitoring port-forward svc/monitoring-prometheus 9090:9090`, then http://localhost:9090 |

There is no public ingress for any of these. On staging reach them over Tailscale or with the port-forward.

## The alerts

Critical (notified at once): `ApiDown`, `MediaWorkerDown` (2 minutes), `JobQueueStuck` (jobs waiting, none finished
for 10 minutes), `JobFailureRateHigh` (over half for 10 minutes), `VolumeAlmostFull` (over 90%), `PodNotReady` (10
minutes). Warning (grouped, every 12 hours at most): `JobFailureRateElevated`, `ModerationUnavailable`,
`RunErrorsSpike`, `ApiServerErrors`. Every alert carries a `runbook` line with the first command to run. The
thresholds are chart values (`metrics.alerts.*`).

## Fire drills (run them after any change to this setup)

1. **Worker down:** `make monitoring-drill`. It stops the media worker, waits for `MediaWorkerDown`, checks that
   Alertmanager sent a Telegram notification, starts the worker and waits for the alert to resolve. You should
   get an ALERT and then a RESOLVED message.
2. **Whole cluster or monitoring dead:** `make monitoring-drill-meta`. It stops Prometheus (and the operator that
   would restart it), which ends the Watchdog and so the heartbeat, waits `DRILL_WAIT_MIN` minutes (default 12)
   and starts it again. Healthchecks.io messages Telegram from outside the cluster that the heartbeat stopped, and
   again when it is back.

## Rules for metrics

Labels are bounded values only: a product id, a capability, an outcome, an error or refusal code, an HTTP route
template. Never a user id, an email, a prompt or any content (a test checks this). New metrics go in
`services/api/src/wd_api/metrics.py` or `services/media-worker/src/wd_media_worker/metrics.py`.

## Known limits

Loki runs from the `loki-stack` chart, which upstream marks deprecated; Loki with Alloy replaces it without changing
the dashboards. Alerts for certificates and backups are added when those exist.
