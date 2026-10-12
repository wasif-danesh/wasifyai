#!/usr/bin/env bash
# Fire drill for the monitoring (ADR-0048): stop the media worker, wait for the critical alert to fire and be
# sent to Telegram, start it again and wait for it to resolve. Prints what Alertmanager did; check your phone.
set -uo pipefail
. "$(dirname "$0")/lib.sh"
NS=wasifyai; MON=monitoring
NOTIFY="${ALERT_NOTIFICATIONS:-$(env_value ALERT_NOTIFICATIONS || true)}"
[ "$NOTIFY" = "on" ] || warn "ALERT_NOTIFICATIONS is not on: this checks that the alert fires and resolves, nothing is sent"
step "Fire drill: the media worker"
kubectl -n $MON port-forward svc/monitoring-alertmanager 9093:9093 >/dev/null 2>&1 &
pf=$!; trap 'kill $pf 2>/dev/null; kubectl -n $NS scale deploy/wasifyai-media-worker --replicas=1 >/dev/null 2>&1' EXIT
sleep 4
sent() { curl -fsS -m 5 localhost:9093/metrics | awk '/^alertmanager_notifications_total\{integration="telegram"/ {s+=$2} END {print s+0}'; }
before="$(sent)"
firing() { curl -fsS -m 5 localhost:9093/api/v2/alerts 2>/dev/null | python3 -c "
import json,sys
a=json.load(sys.stdin)
print(any(x['labels'].get('alertname')=='MediaWorkerDown' and x['status']['state']=='active' for x in a))"; }
kubectl -n $NS scale deploy/wasifyai-media-worker --replicas=0 >/dev/null
ok "worker stopped; waiting for MediaWorkerDown (about 3 to 4 minutes)"
for _ in $(seq 1 60); do [ "$(firing)" = "True" ] && break; sleep 10; done
[ "$(firing)" = "True" ] && ok "MediaWorkerDown is firing in Alertmanager" || { bad "the alert never fired"; exit 1; }
if [ "$NOTIFY" = "on" ]; then
  for _ in $(seq 1 12); do [ "$(sent)" -gt "$before" ] && break; sleep 10; done
  [ "$(sent)" -gt "$before" ] && ok "Alertmanager sent a Telegram notification (check your phone)" || { bad "no Telegram notification was sent"; exit 1; }
fi
kubectl -n $NS scale deploy/wasifyai-media-worker --replicas=1 >/dev/null
ok "worker started again; waiting for the alert to resolve"
for _ in $(seq 1 60); do [ "$(firing)" = "False" ] && break; sleep 10; done
[ "$(firing)" = "False" ] && ok "resolved" || { bad "still firing"; exit 1; }
printf '\n%sDrill passed.%s You should have received an ALERT and a RESOLVED message.\n' "$GREEN" "$RESET"
