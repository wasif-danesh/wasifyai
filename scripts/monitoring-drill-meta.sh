#!/usr/bin/env bash
# Second fire drill (ADR-0048): the monitoring itself goes down. Stops Prometheus (and the operator that would
# restart it), so the Watchdog heartbeat to Healthchecks.io stops; Healthchecks.io then messages you from outside
# the cluster. Starts it again and the "up" message follows. Check your phone. Wait time: DRILL_WAIT_MIN (default 12,
# the check's period plus grace must be shorter than this).
set -uo pipefail
. "$(dirname "$0")/lib.sh"
NOTIFY="${ALERT_NOTIFICATIONS:-$(env_value ALERT_NOTIFICATIONS || true)}"
[ "$NOTIFY" = "on" ] || { bad "ALERT_NOTIFICATIONS is not on, so no heartbeat is sent and there is nothing to test"; exit 1; }
MON=monitoring; WAIT="${DRILL_WAIT_MIN:-12}"
restore() {
  kubectl -n $MON scale deploy/monitoring-operator --replicas=1 >/dev/null 2>&1
  kubectl -n $MON scale sts/prometheus-monitoring-prometheus --replicas=1 >/dev/null 2>&1
}
trap restore EXIT
step "Fire drill: Prometheus down"
kubectl -n $MON scale deploy/monitoring-operator --replicas=0 >/dev/null
kubectl -n $MON scale sts/prometheus-monitoring-prometheus --replicas=0 >/dev/null
ok "Prometheus stopped; the heartbeat stops now. Waiting $WAIT minutes for Healthchecks.io to notice"
sleep $((WAIT * 60))
restore
ok "Prometheus started again; waiting for it to be ready"
kubectl -n $MON rollout status sts/prometheus-monitoring-prometheus --timeout=5m
printf '\n%sDrill done.%s Healthchecks.io should have sent a "down" message, then an "up" message after the heartbeat came back.\n' "$GREEN" "$RESET"
