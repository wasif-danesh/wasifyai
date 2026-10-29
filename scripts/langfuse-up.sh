#!/usr/bin/env bash
# Install Langfuse for LLM traces (ADR-0050) in the `observability` namespace of the current cluster, and give the
# application chart its keys. The first run makes the organisation, the project, its key pair and a sign-in for
# LANGFUSE_ADMIN_EMAIL (from .env), all random and stored only in the cluster (values are never printed).
# ClickHouse needs a few GB of memory: on kind this is off unless you run it.
#
# Usage: scripts/langfuse-up.sh       then: helm upgrade wasifyai ... --set langfuse.baseUrl=http://langfuse-web.observability:3000
set -euo pipefail
. "$(dirname "$0")/lib.sh"
cd "$ROOT"
NS=observability; APP_NS="${APP_NS:-wasifyai}"; APP_SECRET="${APP_SECRET:-wasifyai-secrets}"
LANGFUSE_VERSION=2.1.5
have helm && have kubectl || { bad "helm and kubectl are needed"; exit 1; }
email="${LANGFUSE_ADMIN_EMAIL:-$(env_value LANGFUSE_ADMIN_EMAIL || true)}"
[ -n "$email" ] || { bad "LANGFUSE_ADMIN_EMAIL is empty in .env (the person who signs in to Langfuse)"; exit 1; }

rand() { LC_ALL=C tr -dc 'a-f0-9' </dev/urandom | head -c "$1"; }

# chart 2.x runs ClickHouse through its operator, which needs cert-manager; both are installed apart
if ! kubectl get crd clickhouseclusters.clickhouse.com >/dev/null 2>&1; then
  bad "the ClickHouse operator is not installed (with cert-manager): see the Prerequisites of the langfuse chart's README"
  exit 1
fi

step "Keys"
kubectl get ns "$NS" >/dev/null 2>&1 || kubectl create ns "$NS" >/dev/null
if ! kubectl -n "$NS" get secret langfuse-init >/dev/null 2>&1; then
  kubectl -n "$NS" create secret generic langfuse-init \
    --from-literal=LANGFUSE_INIT_ORG_ID=wasifyai --from-literal=LANGFUSE_INIT_ORG_NAME="Wasify AI" \
    --from-literal=LANGFUSE_INIT_PROJECT_ID=wasifyai --from-literal=LANGFUSE_INIT_PROJECT_NAME="Wasify AI" \
    --from-literal=LANGFUSE_INIT_PROJECT_PUBLIC_KEY="pk-lf-$(rand 32)" \
    --from-literal=LANGFUSE_INIT_PROJECT_SECRET_KEY="sk-lf-$(rand 32)" \
    --from-literal=LANGFUSE_INIT_USER_EMAIL="$email" --from-literal=LANGFUSE_INIT_USER_NAME=admin \
    --from-literal=LANGFUSE_INIT_USER_PASSWORD="$(rand 24)" >/dev/null
fi
ok "langfuse-init stored in the cluster (values not shown)"

step "Installing Langfuse"
helm repo add langfuse https://langfuse.github.io/langfuse-k8s >/dev/null 2>&1 || true
helm repo update >/dev/null 2>&1 || true
helm upgrade --install langfuse langfuse/langfuse -n "$NS" --version "$LANGFUSE_VERSION" \
  -f deploy/monitoring/langfuse.values.yaml ${LANGFUSE_VALUES:+-f "$LANGFUSE_VALUES"} --wait --timeout 20m

step "Giving the application its keys"
get() { kubectl -n "$NS" get secret langfuse-init -o "jsonpath={.data.$1}"; }
kubectl -n "$APP_NS" patch secret "$APP_SECRET" --type merge -p \
  "{\"data\":{\"LANGFUSE_PUBLIC_KEY\":\"$(get LANGFUSE_INIT_PROJECT_PUBLIC_KEY)\",\"LANGFUSE_SECRET_KEY\":\"$(get LANGFUSE_INIT_PROJECT_SECRET_KEY)\"}}" >/dev/null
ok "LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY added to $APP_SECRET"

printf '\n%sLangfuse is up.%s Open it: kubectl -n %s port-forward svc/langfuse-web 3002:3000  (user %s; password:\n' "$GREEN" "$RESET" "$NS" "$email"
printf '  kubectl -n %s get secret langfuse-init -o jsonpath={.data.LANGFUSE_INIT_USER_PASSWORD} | base64 -d)\n' "$NS"
printf 'Turn it on for the app: langfuse.baseUrl=http://langfuse-web.%s:3000 (set in values/staging.yaml). Set the\n' "$NS"
printf "project's data retention to 30 days in Langfuse's settings (ADR-0050).\n"
