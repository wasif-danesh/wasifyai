#!/usr/bin/env python3
"""Every URL of the running system, for the mode it is in (`make urls`).

    uv run python scripts/urls.py              # what is up, and how to reach each service
    uv run python scripts/urls.py --markdown   # the README's table (a test keeps them equal)

The SERVICES list is the single source of truth. Two modes: `compose` (make dev, ports published
on localhost) and `kind` (the local cluster: only the web app is published; the rest need a
port-forward)."""

import json
import shutil
import subprocess
import sys
import urllib.request

# name, what it is, compose URL, kind command (port-forward) and its URL, notes
SERVICES = [
    (
        "Web app",
        "the six products, My creations, admin",
        "http://localhost:3000",
        None,
        "http://localhost:3000",
        "both modes publish it",
    ),
    (
        "Admin area",
        "users, models, media backends, safeguards, audit",
        "http://localhost:3000/admin",
        None,
        "http://localhost:3000/admin",
        "needs an admin account",
    ),
    (
        "API docs",
        "Swagger UI for the API",
        "http://localhost:8000/docs",
        "kubectl -n wasifyai port-forward svc/wasifyai-api 8000:8000",
        "http://localhost:8000/docs",
        "/health for liveness",
    ),
    (
        "LiteLLM",
        "the model gateway",
        "http://localhost:4000",
        "kubectl -n wasifyai port-forward svc/wasifyai-litellm 4000:4000",
        "http://localhost:4000",
        "needs LITELLM_API_KEY",
    ),
    (
        "Object storage",
        "S3 API (SeaweedFS)",
        "http://localhost:8333",
        "kubectl -n wasifyai port-forward svc/wasifyai-storage 8333:8333",
        "http://localhost:8333",
        "",
    ),
    (
        "ComfyUI",
        "images (and video on :8189)",
        "http://localhost:8188",
        "kubectl -n wasifyai port-forward svc/wasifyai-comfyui 8188:8188",
        "http://localhost:8188",
        "native in Compose mode; a pod in kind",
    ),
    (
        "Ollama",
        "the language models",
        "http://localhost:11434",
        "kubectl -n wasifyai port-forward svc/wasifyai-ollama 11434:11434",
        "http://localhost:11434",
        "native in Compose mode; a pod in kind",
    ),
    (
        "Postgres",
        "database, checkpoints, usage events",
        "localhost:5432",
        "kubectl -n wasifyai port-forward svc/wasifyai-postgres 5432:5432",
        "localhost:5432",
        "user wasifyai",
    ),
    (
        "Redis",
        "job queue and run events",
        "localhost:6379",
        "kubectl -n wasifyai port-forward svc/wasifyai-redis 6379:6379",
        "localhost:6379",
        "",
    ),
    (
        "Grafana",
        "dashboards and logs",
        None,
        "kubectl -n monitoring port-forward svc/monitoring-grafana 3001:80",
        "http://localhost:3001",
        "user admin; password in the grafana-admin Secret",
    ),
    (
        "Prometheus",
        "metrics and alert rules",
        None,
        "kubectl -n monitoring port-forward svc/monitoring-prometheus 9090:9090",
        "http://localhost:9090",
        "",
    ),
    (
        "Alertmanager",
        "what is firing, where it goes",
        None,
        "kubectl -n monitoring port-forward svc/monitoring-alertmanager 9093:9093",
        "http://localhost:9093",
        "",
    ),
    (
        "Healthchecks.io",
        "the outside heartbeat",
        None,
        None,
        "https://healthchecks.io",
        "your account; shows the last ping",
    ),
]


def markdown() -> str:
    rows = [
        "| Service | What it is | Compose (`make dev`) | kind (`make kind-up`) |",
        "|---|---|---|---|",
    ]
    for name, what, compose, cmd, kind_url, _ in SERVICES:
        c = f"`{compose}`" if compose else "not installed"
        if cmd:
            k = f"`{cmd}`, then `{kind_url}`"
        elif kind_url:
            k = f"`{kind_url}`"
        else:
            k = "not in the cluster"
        rows.append(f"| {name} | {what} | {c} | {k} |")
    return "\n".join(rows)


def up(url: str) -> bool:
    if not url.startswith("http"):
        host, _, port = url.partition(":")
        import socket

        try:
            socket.create_connection((host, int(port)), timeout=1).close()
            return True
        except OSError:
            return False
    try:
        urllib.request.urlopen(url, timeout=2)
        return True
    except urllib.error.HTTPError:
        return True  # it answered
    except Exception:
        return False


def mode() -> str:
    if shutil.which("kubectl"):
        try:
            ctx = subprocess.run(
                ["kubectl", "config", "current-context"], capture_output=True, text=True, timeout=5
            )
            pods = subprocess.run(
                ["kubectl", "-n", "wasifyai", "get", "pods", "-o", "json"],
                capture_output=True,
                text=True,
                timeout=8,
            )
            if (
                ctx.stdout.strip() == "kind-wasifyai"
                and pods.returncode == 0
                and json.loads(pods.stdout)["items"]
            ):
                return "kind"
        except Exception:
            pass
    return "compose"


def main() -> int:
    if "--markdown" in sys.argv:
        print(markdown())
        return 0
    m = mode()
    print(f"System mode: {m}  (kind = the local cluster, compose = make dev)\n")
    for name, what, compose, cmd, kind_url, notes in SERVICES:
        if m == "compose":
            url = compose
            how = ""
        else:
            url = kind_url
            how = f"   run: {cmd}" if cmd else ""
        if not url:
            print(f"  {name:26} not available in this mode")
            continue
        state = "up  " if up(url) else ("fwd " if cmd and m == "kind" else "down")
        print(f"  {name:26} {state}  {url}{how}")
        if notes:
            print(f"  {'':26}        {what}; {notes}")
    print(
        "\n  up = answering now; fwd = reachable after the port-forward shown; down = not running"
    )
    print(
        "More: docs/runbooks/monitoring.md. LangGraph has no UI of its own: it runs inside the API."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
