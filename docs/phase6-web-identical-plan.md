# Phase 6: the web app does what the desktop app does (plan)

Status: **Proposed 2026-10-21; P0 and P1 accepted to start the same day (owner: "yes, start")** (owner: "No functionalities for music and voice. We need a proper plan for the web. How can we make it
identical to desktop?"). Design: ADR-0087 (Proposed). Builds on ADR-0056 (one engine, two shells), `docs/phase3-web-parity-plan.md`
(W1 to W8: the look, notebooks, hosted speech, the switches removed) and `docs/web-parity-ledger.md`.

## What "identical" means

Same screens, same abilities, same results, for every item of the desktop menu and every action of the catalogue (ADR-0068). Allowed
differences, because a browser or a public service is not a window on one computer: the window chrome (title bar, Save As box,
recents menu), the person downloading models themselves, models whose licence forbids commercial use (ADR-0066 decision 11: desktop
only on a public service), and the sentences about privacy (they say where the work runs).

## Why the web is not there

The screens and the product graphs are shared. The **compute** is not. Today:

| Capability | Desktop runs it with | Web today | Missing on the web |
|---|---|---|---|
| Chat, assistant, notebooks answers | llama.cpp (or another local tool) | LiteLLM to Ollama or a hosted model | nothing (the gateway serves the model) |
| Images (Create, Edit, Inpaint, Reference) | ComfyUI sidecar | media worker to ComfyUI | a GPU host with the models (real mode); pages exist |
| Video (Create, Animate, Extend) | ComfyUI sidecar, ffmpeg | media worker to ComfyUI; ffmpeg in the API image | a GPU host; Extend never run on the web |
| Speak, Transcribe | audio.cpp | hosted models through the gateway | provider aliases bound |
| Voices, Change a voice, Edit speech, Dub, Audiobook, Music, Lyrics, Split | audio.cpp and its models | **nothing** | a runtime and models on a worker |
| Lip sync | MuseTalk server (its own environment) | **nothing** | a worker with the sidecar; files and consent through storage |
| 3D models | Pixal3D component, SQLite store | **nothing** | a worker; a Postgres store |
| Video Builder | sandboxed browser render, SQLite store | **nothing** | a worker with the sandbox; a Postgres store |
| Model picker, Models page | local adapters | none | a web adapter (admin-managed list) |
| Safeguards, usage, quotas | off on the desktop | on (ADR-0047) but not written for speech seconds | usage events for every new kind (backlog B1) |

So the gap is five components and two stores, not a rewrite of the screens.

## The design (ADR-0087)

A **headless engine worker**: the desktop profile's engine without the window, started by a job consumer. The product asks for a
capability; the job goes to a queue; a worker with the component runs it, pulls inputs and pushes outputs through presigned URLs,
and reports progress with the event envelope the media worker already uses. The same worker runs in three places:

1. **The owner's Mac**, for development and a home lab: the models and runtimes that already work in the desktop app. No cloud.
2. **A Linux CUDA host**, for staging and production (a rented GPU; the plan's decision D3).
3. **A person's own desktop** as a runner (ADR-0058): outbound connection, that person's jobs only.

Why not the alternatives: running audio.cpp in the API container on CPU (too slow for music and lip sync, and the web has no way to
download models); proxying the whole desktop engine through a tunnel (one person only, not a service); writing cloud versions of the
components (two copies of each, against ADR-0056).

## Stages

Each stage ships on its own and ends with its rows in `apps/web/lib/parity.ts` turned to "live" and a run of the desktop checklist
(`docs/testing/desktop-window-checklist.md`) on the web for that area.

| Stage | What | Size | Exit |
|---|---|---|---|
| **P0 Worker core** (built 2026-10-21) | the job contract for engine kinds (inputs, presigned file in and out, progress, cancel, usage, one heavy model at a time); the `engine-worker` service and its image; a Mac mode (`make worker`, native, Metal) that reads the compose stack's queue and storage; fake components for tests | M | a fake job runs end to end in `make dev`; the Mac worker takes it |
| **P1 Speech family** (built 2026-10-21; models still to fetch) | `RemoteSpeechEngine` for the voice product (the voice engine interface, queueing instead of calling in-process); speak, clone, design, convert, edit, transcribe, music, separate, dub, audiobook on the worker; the web offers a screen when a worker lists a ready model | L | Voices, Change a voice, Edit speech, Dub, Audiobook, Music, Lyrics, Split open and work on the web with the Mac worker |
| **P2 Lip sync** (built with P1, checked for real 2026-10-21) | the MuseTalk server as a worker component; picture and recording through storage; the consent and the visible mark kept | M | Lip sync on the web |
| **P3 3D models** (built 2026-10-21) | Postgres store and files in storage for `wasifyai-model3d`; the Pixal3D component as a job kind | M | 3D on the web |
| **P4 Video Builder** (built 2026-10-21) | Postgres store for projects and drafts; the sandboxed render as a job kind (browser sandbox plus a container boundary on a shared host) | L | Video Builder on the web |
| **P5 The picker on the web** (built 2026-10-22) | `ModelSelect` on the web: the deployment's listed models and the person's choice; admin actions for adding a model to a worker; licence filter | M | "Select … model" on every web screen; the Models page for admins |
| **P6 Safeguards and usage** | usage events and quotas for every new kind (backlog B1); moderation of text and uploads; consent screens kept; the voice-cloning policy of 2026-10-18 | M | a public deployment can turn safeguards on without gaps |
| **P7 GPU host** | audio.cpp Linux CUDA lock (open since V1); the worker image for CUDA; Helm `engineWorker` with a GPU node selector; runbook; CI builds the image | L | staging runs the same screens as the Mac worker |
| **P8 The gate** | CI fails when a desktop menu item or action has no "live" web row without an accepted reason; the desktop checklist runs on the web in Playwright for the shared screens; the ledger is the release page | S | releases are blocked on parity |

P0 and P1 give the owner everything in the web menu on the Mac within the plan's first two stages; P7 is what a public launch needs.

## Decisions for the owner

1. **GPUs.** The plan needs two: the Mac as a worker now (recommended, no cost), and a rented CUDA host for staging and production.
   Which hosting, and when (backlog D3)?
2. **Public web and licences.** "Identical" stops at licence. Models that do not allow commercial use stay desktop only on a public
   service. Is the web first a home-lab service for you (everything on, including those models) or public from the start?
3. **Where a worker is shared or personal.** One shared worker for all web users, or each person's own desktop as a runner
   (ADR-0058), or both? Voice cloning and lip sync need the person's consent either way.
4. **Order.** Recommended: P0, P1, P2, then P3 and P4 (experimental on the desktop too), then P5 to P8. The alternative is P5 first
   (the picker), which is visible but changes nothing for Music and Voice.

## Risks

- One heavy model per worker: a person waiting behind another's music job. A queue position is shown (the media worker does this
  already); more workers help.
- Files are large (a lip sync video, a 3D model): presigned transfer, size limits, and a clean-up on every exit path.
- The Video Builder runs untrusted page code: the desktop sandbox is necessary but not enough on a shared host.
- The Mac sleeps or is closed: the worker must say it is away, and a job waits or fails plainly.
- Cost on a rented GPU: idle time; start and stop on demand is a later stage.

## Not in this plan

Training (ADR-0073 and onwards), the music video (ADR-0084), the assistant's agent system (ADR-0072): each says what it does on the
web in its own ADR; the gate in P8 applies to them when they reach the menu.

## Status 2026-10-21: P0 and P1 built

Built and checked: the queue, the wire format, the worker, `RemoteSpeechEngine`, `VOICE_ENGINE=worker` as the default, `make worker`,
`make dev` starting the worker on a Mac, `scripts/worker.sh models`. Real run: the API's engine, Redis, SeaweedFS and the worker on this
Mac made a spoken sentence with Kokoro. The API container lists every model the worker lists.

**Checked for real (2026-10-21, `scripts/worker_smoke.py`, this Mac, models fetched with `scripts/worker.sh models`):** all ten
capabilities went API engine, Redis, worker, model, SeaweedFS and back: Text to speech (Kokoro, 14 s with the first load), Speech to
text (Parakeet, 2.3 s, heard the sentence back exactly), Change a voice (Tone Color VC, 0.9 s), Edit speech (dots.tts Edit, 51 s),
Split (HTDemucs, four stems, 9.8 s), Music (ACE-Step, 15 s of song in 135 s) and its repaint (90 s), Voices design and clone
(VoxCPM2, 7 s and 2 s), Lip sync (MuseTalk, a 9 s video at 768x768 in 70 s). The API lists every model, so the web offers every Voice
and Music screen. Not run through the web page itself (it needs a signed-in browser session): the API route and the engine path are.

Two bugs found by running it for real: (1) the first runs of Change a voice and Split failed because the smoke script gave the
engine recordings at the wrong sample rate; the product prepares them (`audio_input.at_rate`), the script now does the same; (2) **Lip
sync fails on a Mac whose data folder has a space in its path** ("Application Support"): torch compiled the face finder with a C++
build that does not quote the folder. Fixed by turning torch's compile off for the lip sync server (`TORCHDYNAMO_DISABLE=1`); this
also repairs Lip sync in the desktop app on a normal Mac. The worker now closes the lip sync server when it stops.

**Still to do:** the admin screen to fetch models from the web (P5), a queue position and cancel for speech jobs, a worker on a Linux
GPU host (P7). Lip sync's consent and picture handling are the product's own and unchanged, so P2 is mostly done: what remains is a
real run through the web page with a signed-in session.

## Status 2026-10-21 (later): P2, P3, P4 built, and images and video on the web

The web menu has no "Soon" item left except Train (not built on either app). Real runs on this Mac: all seven image and
video modes (`scripts/web_media_check.py`), every speech capability (`scripts/worker_smoke.py`). 3D (`scripts/web_model3d_check.py`: a picture cut out in 36 s, a model made in 551 s, a 34 MB GLB read back through the API) and Video Builder (`scripts/web_builder_check.py`: the words checked in 1.1 s, a still, a real MP4 in 15 s). What is left of the plan is P5
(the picker and fetching models from the web), P6 (usage, quotas, moderation of every new kind), P7 (a cloud GPU) and P8 (the gate).

## Status 2026-10-22: restart-safe jobs and P5 built

A restart of the API during a 3D picture, a 3D model or a Video Builder render no longer loses the job (checked for real; ADR-0087
has the mechanism). P5 is built: **Admin > Workers** lists the workers and their models and has a worker fetch a model (with its
size shown, progress followed, files checked by the worker) or set up the lip sync engine; the Voice, Listening, Music and Lip sync
screens have the desktop's "Select ... model" button and panel, and a person who is not an admin sees a missing model as "ask an
admin". Left of the plan: the licence filter for a public service (decision 2), P6 (usage, quotas, moderation), P7 (a cloud GPU) and
P8 (the gate).
