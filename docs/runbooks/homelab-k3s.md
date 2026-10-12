# Runbook: staging on k3s with Argo CD

Works on the real home lab and on any Linux box standing in for it (for example a laptop
running Debian, Ubuntu or Kali). Phase 2 needs no GPU: the model runs on CPU.

Status: written and reviewed, **not yet executed** against a real k3s node. The chart itself
is tested on kind (`make kind-up && make kind-test`). Record anything that differs here.

## 0. Prerequisites

| Need | Notes |
|---|---|
| Linux host, amd64 or arm64 | 8 GB RAM minimum, 16 GB recommended, for `gemma4:e4b` on CPU; 25+ GB free disk |
| Internet access | To pull images from GHCR and Docker Hub, the model from the Ollama registry, and the chart from GitHub. A fully offline lab needs a registry mirror and a local Git server first |
| `cgroup2` | `stat -fc %T /sys/fs/cgroup` should print `cgroup2fs` |
| CI has pushed images | The `images` job on `main` publishes `ghcr.io/wasif-danesh/wasifyai/{api,web,media-worker}:latest` |
| GHCR packages public | GitHub → profile → Packages → each package → Settings → Change visibility. Or create an image pull secret and set `image.pullSecrets` |

## 1. Install k3s

```bash
curl -sfL https://get.k3s.io | sh -
sudo kubectl get nodes          # wait for Ready
mkdir -p ~/.kube && sudo cat /etc/rancher/k3s/k3s.yaml > ~/.kube/config && chmod 600 ~/.kube/config
```

k3s bundles Traefik (ingress), a local-path storage provisioner and a service load balancer.
Do not expose ports 6443 or 10250 beyond your LAN or tailnet.

## 2. Install Argo CD

```bash
kubectl create namespace argocd
kubectl apply -n argocd --server-side -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl -n argocd rollout status deploy/argocd-server
```

UI (optional): `kubectl -n argocd port-forward svc/argocd-server 8080:443`, then open
https://localhost:8080. The initial admin password is in the
`argocd-initial-admin-secret` Secret (`kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d`).
Change it and delete that Secret.

## 3. Create the application Secret

Secrets are not in Git. From a checkout of this repo, with kubectl pointing at k3s:

```bash
scripts/k8s-secrets.sh wasifyai
```

This creates `wasifyai/wasifyai-secrets` with random `LITELLM_API_KEY` and `POSTGRES_PASSWORD`,
without printing them. It leaves an existing Secret unchanged.

## 4. Point Argo CD at the chart

Edit `ingress.host` in `deploy/helm/wasifyai/values/cloud/homelab.yaml` (see step 6), commit and
push, then:

```bash
kubectl apply -f deploy/argocd/application-staging.yaml
kubectl -n argocd get application wasifyai-staging -w
```

Argo CD syncs `deploy/helm/wasifyai` with `values/staging.yaml` and `values/cloud/homelab.yaml`,
then runs the migration Job as a PostSync hook.

## 5. Wait for the model

The Ollama pod downloads `gemma4:e4b` (about 10 GB) on first start and is not Ready until it
finishes. The model lives on a PVC, so this happens once.

```bash
kubectl -n wasifyai logs deploy/wasifyai-ollama -f
kubectl -n wasifyai get pods
```

To use a smaller model, change it in the admin area (`/admin/models`) or in
`services/api/src/wasifyai_api/model_defaults.yaml`, update `ollama.models` in values to match, and lower
`ollama.resources`.

## 5b. GPU and real media generation (Phase 4)

Status: written, **not yet run on a GPU node**. Without these steps the stack still works: the
media worker runs in `stub` mode and returns placeholder files.

1. Install the NVIDIA driver on the host, then the GPU Operator (Helm chart `nvidia/gpu-operator`)
   on k3s. Confirm with `kubectl describe node | grep nvidia.com/gpu`.
2. Share the card between Ollama and ComfyUI with time-slicing: apply
   `deploy/k8s/gpu-time-slicing.yaml`, then point the operator's device plugin at it
   (`kubectl patch clusterpolicies.nvidia.com/cluster-policy --type merge -p '{"spec":{"devicePlugin":{"config":{"name":"time-slicing-config","default":"any"}}}}'`).
   The worker serialises generation per GPU and unloads LLMs before each job, so the two
   workloads do not need VRAM together.
3. Choose a ComfyUI container image for your GPU (none is chosen for you), put the models on its
   volume, and set in your values: `comfyui.enabled: true`, `comfyui.image: <your image>`,
   `mediaWorker.comfyuiMode: real`, and `ollama.gpuResources: { nvidia.com/gpu: 1 }`.
4. Verify with the `media-demo` product (adjust `products/media-demo/workflows/` to models you
   have): a run should show `job_progress` events with live progress and finish with an image URL.

## 6. Reach the app

Install Tailscale on the node (`curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up`)
and on your devices. Set `ingress.host` to the node's MagicDNS name
(`<machine>.<tailnet>.ts.net`). Traefik serves port 80 on the node, so
`http://<machine>.<tailnet>.ts.net` reaches the web app. Nothing is forwarded from the
internet.

Without Tailscale: `kubectl -n wasifyai port-forward svc/wasifyai-web 3000:3000`.

## 7. Verify

```bash
kubectl -n wasifyai get pods                                   # all Running; migrate Completed
kubectl -n wasifyai port-forward svc/wasifyai-web 3000:3000 &
curl -N -X POST localhost:3000/api/products/hello/runs \
  -H 'content-type: application/json' -d '{"input":{"message":"Say hi"}}'
```

Expect `node`, `token`... and `done` events.

## Known limitations

- Staging uses the `latest` tag, so a new image does not trigger a rollout by itself. After CI
  pushes new images, restart the workloads: `kubectl -n wasifyai rollout restart deploy`.
- In-cluster Postgres is a single replica, suitable for staging only.
- GPU support (GPU Operator, time-slicing) arrives in Phase 4.

## Troubleshooting

| Symptom | Check |
|---|---|
| `ImagePullBackOff` on api/web/worker | GHCR package visibility, or a pull secret |
| Ollama pod never Ready | `kubectl -n wasifyai logs deploy/wasifyai-ollama`; disk space; internet access |
| Pods `Pending` | `kubectl -n wasifyai describe pod <name>`; usually memory requests exceed the node |
| Argo CD `OutOfSync` on the PVC | Expected to be ignored; the chart marks it `resource-policy: keep` |
| SSE stream cut off | Ingress timeouts or buffering; Traefik needs no change, nginx needs buffering off |
