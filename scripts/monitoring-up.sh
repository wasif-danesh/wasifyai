#!/usr/bin/env bash
# Install the monitoring stack (ADR-0048): Prometheus, Alertmanager and Grafana, Loki and Promtail, in the
# `monitoring` namespace of the current cluster, alerting to Telegram with an outside heartbeat.
# Only production sends: with ALERT_NOTIFICATIONS=on it reads TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID and
# HEALTHCHECKS_PING_URL from .env (values are never printed). Without it (the default) alerts still fire and show in
# Alertmanager and Grafana, but nothing is sent and no token is stored in the cluster.
#
# Usage: scripts/monitoring-up.sh                          # no notifications
#        ALERT_NOTIFICATIONS=on scripts/monitoring-up.sh    # production, or a drill on kind
set -euo pipefail
. "$(dirname "$0")/lib.sh"
cd "$ROOT"
NS=monitoring; APP_NS="${APP_NS:-wasifyai}"
KPS_VERSION=92.3.0; LOKI_VERSION=2.10.3

NOTIFY="${ALERT_NOTIFICATIONS:-$(env_value ALERT_NOTIFICATIONS || true)}"
step "Checking the settings"
if [ "$NOTIFY" = "on" ]; then
  missing=0
  for k in TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID HEALTHCHECKS_PING_URL; do
    v="$(env_value "$k" || true)"
    if [ -n "$v" ]; then ok "$k is set"; else bad "$k is empty in .env"; missing=1; fi
  done
  [ "$missing" -eq 0 ] || exit 1
  ok "ALERT_NOTIFICATIONS=on: alerts go to Telegram and the heartbeat is sent"
else
  warn "ALERT_NOTIFICATIONS is not on: alerts are shown in Alertmanager and Grafana but nothing is sent"
fi
have helm && have kubectl || { bad "helm and kubectl are needed"; exit 1; }

step "Secrets"
kubectl get ns "$NS" >/dev/null 2>&1 || kubectl create ns "$NS" >/dev/null
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
if [ "$NOTIFY" = "on" ]; then
  env_value TELEGRAM_BOT_TOKEN | tr -d '\n' >"$tmp/telegram-token"
  env_value HEALTHCHECKS_PING_URL | tr -d '\n' >"$tmp/heartbeat-url"
  chat="$(env_value TELEGRAM_CHAT_ID | tr -d '\n ')"
  case "$chat" in ''|*[!0-9-]*) bad "TELEGRAM_CHAT_ID must be a number"; exit 1 ;; esac
  sed "s/__CHAT_ID__/$chat/" deploy/monitoring/alertmanager.yaml.tmpl >"$tmp/alertmanager.yaml"
else
  # Alertmanager mounts this Secret, so it exists, but holds nothing real
  : >"$tmp/telegram-token"; : >"$tmp/heartbeat-url"
  cp deploy/monitoring/alertmanager.off.yaml "$tmp/alertmanager.yaml"
fi
kubectl -n "$NS" create secret generic alert-secrets --from-file="$tmp/telegram-token" \
  --from-file="$tmp/heartbeat-url" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl -n "$NS" create secret generic alertmanager-wasifyai-config --from-file="$tmp/alertmanager.yaml" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
if ! kubectl -n "$NS" get secret grafana-admin >/dev/null 2>&1; then
  kubectl -n "$NS" create secret generic grafana-admin --from-literal=admin-user=admin \
    --from-literal=admin-password="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 20)" >/dev/null
fi
ok "secrets stored in the cluster (values not shown)"

step "Installing Prometheus, Alertmanager and Grafana"
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
helm repo add grafana https://grafana.github.io/helm-charts >/dev/null 2>&1 || true
helm repo update >/dev/null 2>&1 || true
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack -n "$NS" \
  --version "$KPS_VERSION" -f deploy/monitoring/kube-prometheus-stack.values.yaml \
  ${MONITORING_VALUES:+-f "$MONITORING_VALUES"} --wait --timeout 15m

step "Installing Loki and Promtail"
helm upgrade --install loki grafana/loki-stack -n "$NS" --version "$LOKI_VERSION" \
  -f deploy/monitoring/loki-stack.values.yaml --wait --timeout 10m

# The application chart creates its scrape target, alerts and dashboard only once the CRDs exist.
if helm status wasifyai -n "$APP_NS" >/dev/null 2>&1; then
  step "Telling the application chart the stack is there"
  helm upgrade wasifyai deploy/helm/wasifyai -n "$APP_NS" --reset-then-reuse-values --wait --timeout 10m >/dev/null
  ok "scrape target, alert rules and dashboard created"
fi

printf '\n%sMonitoring is up.%s Grafana: kubectl -n %s port-forward svc/monitoring-grafana 3001:80  (user admin; password:\n' "$GREEN" "$RESET" "$NS"
printf '  kubectl -n %s get secret grafana-admin -o jsonpath={.data.admin-password} | base64 -d)\n' "$NS"
[ "$NOTIFY" = "on" ] && printf 'Test the alerts with: make monitoring-drill\n' || printf 'Notifications are off. To test sending: ALERT_NOTIFICATIONS=on make monitoring-up, then make monitoring-drill\n'
