# Roadmap

Build a **walking skeleton** first: the thinnest slice through every layer, deployed to
Kubernetes early. The riskiest assumptions are portability and the delivery pipeline, so
prove them while the code is small.

**ON HOLD (2026-10-19, by the owner): all spikes and new features, until the problems found in the owner's testing are fixed. Exception, lifted 2026-10-20 by the owner: the chat UI on assistant-ui (spike CU0, then CU1).** Specs and ADRs stay as written; nothing new starts. **Current focus (2026-10-18): the desktop app.** Next: `docs/phase4-agent-plan.md` (an MCP server, an MCP client and an
assistant that knows the product; ADR-0068 to ADR-0071, Accepted) and `docs/phase5-agent-training-video-builder-plan.md`
(training, Video Builder; ADR-0073 to ADR-0077; the agent on Hermes, ADR-0072, was dropped by the owner on 2026-10-28). **The chat box gets Attach, Search (DuckDuckGo first), Thinking and Mic (ADR-0083, Accepted, on hold until the owner says start; `docs/composer-options-plan.md`, CO0 spike first).** **The chat UI moves to assistant-ui (ADR-0082, Accepted 2026-10-19; plan `docs/chat-ui-migration-plan.md`, CU0 spike first).** **The design system (ADR-0081): DS0 to DS2 done 2026-10-19: `design/DESIGN.md` is the single source of the look and blue replaces violet; DS3 (catalogue, accessibility checks, content guide) is next.** What is unverified or open on the web side is in
`docs/backlog.md`.

## v1 plan (decided 2026-10-10)

v1 is **not a production launch**. Feature work is frozen; the aim is to prove the whole system deploys and works,
then take it down again. Four stages, each with an exit criterion:

| # | Stage | Done when |
|---|---|---|
| 1 | **End to end on local kind** (`make kind-up`) | All 6 products (music, image, video, text to speech, speech to text, lip sync) work in the cluster, with placeholder media from the worker and the CPU speech servers; a smoke test creates something with each; CI is green. |
| 2 | **Monitoring** (built, ADR-0048 accepted) | Metrics and dashboards for job queues, failures, GPU seconds and request rates, with alerts to Telegram and an outside heartbeat; installed on kind with `make monitoring-up`, fire drill with `make monitoring-drill` (passed 2026-10-10: alert, Telegram notification, resolve). Runbook: `docs/runbooks/monitoring.md`. |
| 3 | **Staging on the 24 GB NVIDIA box, built with OpenTofu** | The box already runs Linux with NVIDIA drivers. One `tofu apply` goes from that to k3s, Argo CD and the chart, running the real models (ComfyUI, Ollama, MuseTalk). Needs a CUDA image for the lip sync server and a ComfyUI image. |
| 4 | **GCP test, then shutdown** | The same OpenTofu against GCP, on one spot GPU, private (no public address), a budget alert, and `tofu destroy` leaves nothing billing. The deployment is then shut down: nothing is promoted to production in v1. |

Decisions: v1 has no safeguards, marks, consent gates, terms or licence data (owner, 2026-10-29, ADR-0094); billing
stays out of v1.

**Stage 1 status (2026-10-10): met, with nothing native.** `make kind-up` (default `KIND_MODE=full`) puts every service
in a pod: Ollama with its models, the CPU speech servers (Kokoro, Whisper), the lip sync server (MuseTalk, CPU) and
ComfyUI, plus the platform. `make kind-test` (27 checks plus 6 that each replacement pod really works) and
`make kind-e2e` (a real creation with each of the 6 products) pass: text to speech 1 s, speech to text 20 s, lip sync
195 s for a 5 second voice on a CPU, and a real ComfyUI graph run by the worker in the ComfyUI pod. `KIND_MODE=light`
(no models) is what CI runs. It needs a Podman VM of about 24 GB (set to 32 GB) and about 20 GB of model downloads on
a first start; a 93 GB VM disk is tight. Found and fixed: no lip sync address or image for the chart, no independent
switch for real speech, nothing that installed the speech models (404 on every speech job, in Compose and in the
cluster), a ComfyUI image and a lip sync image that did not exist, the ComfyUI pod asking for a GPU, and Torch trying
to compile on a CPU image.
Not covered by kind (and left for staging): GPU scheduling and time-slicing, CUDA images for ComfyUI and the lip sync
server (the Containerfiles take a build argument for it), real image, music and video generation (placeholders on
kind). The Indic speech servers do run on kind (`KIND_SPEECH=all`, token from `.env`; Bengali text to speech to
text round trip exact on 2026-10-10). Lip Sync with the safeguards on refuses
photographs, so only illustrations work: a product decision for staging and the GCP test.

Original blockers list (kept for the record): the chart has no `LIPSYNC_SERVER_URL`
(the lip sync server runs natively on a Mac); the worker's `comfyuiMode: stub` also stubs the speech servers, so real
speech in kind needs its own setting; kind publishes `localhost:3000`, so stop the Compose stack first; the Podman VM
needs about 16 GB for kind plus the speech servers; the smoke test checks that pages and APIs answer but does not
create anything with the 6 products.

## Phase 0: Foundations

- [ ] Git repo, monorepo layout (see `CLAUDE.md`), `.gitignore`, `.env.example`
- [ ] uv workspace (`services/api`, `services/media-worker`, `packages/*`, `products/*`)
- [ ] pnpm + Turborepo workspace (`apps/web`, generated contracts package)
- [ ] Lint, format, typecheck, test tooling; `Makefile` with `dev`, `test`, `lint`, `contracts`
- [ ] `pydantic-settings` config; structured JSON logging with request IDs
- [ ] First Alembic migration: tenants, users, products, threads, jobs, usage_events (all with
      `tenant_id` / `product_id`)
- [ ] `Containerfile` per service; `compose.yaml`; engine-neutral scripts
- [ ] GitHub Actions: lint, test, Buildah multi-arch build, push to GHCR
- [ ] Update `CLAUDE.md` Commands section

## Phase 1: Walking skeleton on the Mac

- [x] Finalise the [SSE contract](contracts/sse-events.md) as Pydantic models; generate TS types
- [x] FastAPI `/products/{id}/runs` with SSE; stub identity; Postgres checkpointer
- [x] Graph registry; a one-node `hello` graph
- [x] LiteLLM container with an alias pointing at native Ollama
- [x] Next.js page + BFF route handler streaming tokens end to end

## Phase 2: Skeleton on Kubernetes

- [x] Helm chart with `base` / `env` / `cloud` values (`deploy/helm/wasifyai`, ADR-0016)
- [x] Install to `kind` locally (`make kind-up`, `make kind-test`)
- [x] CI smoke test on `kind` (`helm-kind` job gates the image push)
- [x] In-cluster Ollama pulls its model into a PVC (tested on kind with a small model)
- [ ] Home lab: k3s, Argo CD, Tailscale. Manifests and [runbook](runbooks/homelab-k3s.md) are
      written; execute them on the lab (or a stand-in Linux box) and record the result
- [ ] Follow-up: roll out new staging images automatically (pinned tags or Image Updater)

## Phase 3: Platform core

- [x] Capability layer: `litellm`, `comfyui` (stubbed), `fake` providers; product config
      loading and validation (ADR-0017)
- [x] Storage interface (obstore) with an S3-compatible adapter; SeaweedFS replaces MinIO, whose
      community image was withdrawn
- [x] pgvector + RAG helpers (not needed by `wasifyai-music`, but part of the core)
- [x] Usage events written for LLM calls
- [ ] Follow-up (Phase 4): deploy object storage in the Helm chart when the media worker needs it

## Phase 4: Media pipeline

- [x] Redis queue, media worker, job completion that resumes graphs (ADR-0021)
- [x] ComfyUI client (`/prompt` + WebSocket progress), workflow + map loading; verified against
      a fake server and a real local ComfyUI (a real image, `make test-comfyui`)
- [x] Progress over Redis → SSE `job_progress` with queue positions; run events in Redis Streams
      so any API replica can serve or resume a run
- [x] LLM unload before generation; one job at a time per GPU id; retries and idempotent redelivery
- [x] Object storage and the worker in the Helm chart (SeaweedFS); stub mode runs the whole flow
      without a GPU, on kind and in CI
- [ ] GPU Operator with time-slicing on k3s; ComfyUI and Ollama pods: manifests and steps are
      written (`deploy/k8s/gpu-time-slicing.yaml`, `comfyui.*` chart values, runbook) but need
      the GPU host to be tested. Also needs a ComfyUI container image chosen for your GPU

## Phase 5: `wasifyai-music` MVP

Built, and since replaced by the voice product (ADR-0067); its spec was removed with it.

- [x] Song graph: guardrail → lyrics → approve → music job → cover job → done, with per-user
      daily quota, validated and streamed lyrics, `songs` table (migration 0004); tested with a
      scripted fake model and end to end with the real model, Postgres, Redis and a stub worker
- [x] Guardrail evaluation on `gemma4:e4b` (results in ADR-0022)
- [x] ACE-Step 1.5 and FLUX.2 klein 4B workflows + map files, run for real on ComfyUI 0.39 and
      through the UI (results and licences in ADR-0024)
- [x] Auth.js with Google, GitHub, Microsoft; FastAPI validates the token, users table (ADR-0030).
      Verified with a real GitHub login (Google and Microsoft are wired but not tried)
- [x] UI: idea form, live lyric streaming, review and edit, progress with queue position, player,
      cover, downloads, "My songs", song page (see `apps/web/README.md`); verified in a browser against
      the real model; reload and reconnect recovery
- [x] Read API for "My songs" as product-provided routes (ADR-0023)
- [x] Song downloads (ADR-0034): real file downloads, the MP3 with cover art and lyrics in its tag, an MP4
      video of the cover with the song playing
- [x] Studio home "WasifyAI Studio" with a card per product, `/music` area, "Coming soon" pages for image and
      video, sign-in asked when a visitor opens music (ADR-0033)
- [x] Secured upload endpoint for images (ADR-0035): identity required, size/type/pixel limits,
      re-encoded without metadata, hourly limit, swept after 24 hours. Audio uploads are not designed yet
- [x] Image product `wasifyai-image` (ADR-0036): text to image and image to image on FLUX.2 klein 4B, guardrail
      on prompt and picture, My images, downloads, delete. Output screening is not in the first version

- [x] Video product `wasifyai-video` (ADR-0037): text to video and image to video on LTX-Video 2B, 2 or 5
      second clips made in the background, with a header badge and a notice when a clip is ready
- [x] Prompt enhancement on every product (ADR-0038) and a shared picture input: choose, drag and drop, paste
      (ADR-0039)

## Phase 6: Production

- [x] Choose the primary cloud: GCP
- [ ] OpenTofu module for it; add-ons; workload identity; External Secrets
- [ ] vLLM or hosted LLM via LiteLLM; KEDA scale-to-zero GPU workers
- [ ] Promotion flow from staging to prod

## Backlog (not yet scheduled)

- [ ] Long transcripts in search (ADR-0043): index a long transcript in several pieces (a `chunk` column on the index,
      about 1500 characters with overlap, results grouped by item, the exact-word check over every piece), instead of
      only its first 6000 characters. Also helps long lyrics

- [x] Every screen is built from shadcn/ui and Tailwind (ADR-0045); the old hand-written stylesheet is deleted and
      `app/tailwind.css` holds only the tokens, the theme and a few base styles
- [ ] Side panel follow-ups (ADR-0046): pinning and reordering, a shared prompt bar for the creation products (needs its own ADR)

- [x] Text to Speech (ADR-0042): Kokoro in 7 languages and Bengali by Indic Parler-TTS, in My creations and search.
      Known gaps: the other Indic languages, Japanese and Chinese (Speaches cannot make them), no male French voice, Spanish and
      Portuguese voices are graded low, no `/admin/media` entry for the speech server
- [x] Speech to Text, first slice (ADR-0043): upload or record, Whisper with language detection, transcripts in My
      creations and search; IndicConformer (`stt-indic`) for the 22 Indian languages. Next: chunked search for long
      transcripts, a native MLX server, a test on noisy recordings
- [x] Lip Sync (ADR-0044): built (product, uploads, voice from a script or a file, library, search, safeguards switch of
      ADR-0047) and run for real only on the placeholder backend. The spike showed the Mac is far too slow (about 4
      minutes of compute per second of video, out of memory past one window). Next: a CUDA host, then the language,
      guardrail and audio evaluations of the ADR, and the Enhance button for the style hint
- [x] Safeguards switch (ADR-0047): built, then removed with every check, limit and mark (ADR-0094, 2026-10-29)
- [ ] Audio uploads (the image upload endpoint exists; ADR-0035): designed in ADR-0043
- [ ] Evaluate audio input on real recordings, not only synthetic speech (ADR-0020)
- [ ] Pin the SeaweedFS image to a version instead of `:latest`
- [ ] Roll out new staging images automatically (pinned tags or Image Updater)

## Planned and recorded (ADRs proposed, not scheduled)

- [x] Admin foundation (ADR-0025 step 1): `/me`, `require_admin`, audit log (migration 0006), `/admin`
      with users, songs, usage and audit log
- [x] Model access, LLM part (ADR-0025 step 2): aliases seeded into LiteLLM's database, `/admin/models`
      with test connection, save, reset and the moderator canary; keys write-only
- [x] Model access, media part (ADR-0032): backends for the media worker (local ComfyUI, Comfy Cloud /
      Comfy API v2, OpenAI-compatible images) chosen per product capability at `/admin/media`
- [ ] Try the media backends against the real services: a paid Comfy Cloud key (do our ACE-Step and klein
      files exist there, and what does a song cost?) and an image API key
- [x] Semantic search in My creations: multilingual (bge-m3) vectors plus an exact-word check over a per-user index (ADR-0041). Every future creation kind must be indexed (checklist in the ADR)
- [ ] Move the RAG helper to a multilingual embedder (768 to 1024 dimensions, new migration; ADR-0041 known issue 4)
- [ ] Billing and pricing: credits ledger, payment provider, cost on usage events (ADR-0029: Stripe, prepaid credits)
- [ ] SEO and shareable song pages (ADR-0026)
- [ ] First-party analytics: page views, logins, privacy-safe IP handling (ADR-0027)
- [ ] Google Analytics behind a consent banner, off by default (ADR-0028)
- [ ] Legal basics: terms, privacy policy, data deletion, takedown process

## Deferred (seams already in place)

Central OIDC broker, billing provider, observability backends (Grafana stack, Langfuse),
further clouds, video generation.
