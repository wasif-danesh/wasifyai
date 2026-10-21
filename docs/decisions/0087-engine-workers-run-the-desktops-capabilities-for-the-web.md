# ADR-0087: Engine workers run the desktop's capabilities for the web

- **Status:** Accepted for P0 and P1 (2026-10-21, by the owner: "yes, start" to "P0, P1, P2 first, on the Mac"). The later stages
  (P2 onward) and the hosting questions (cloud GPU choice, licences on a public service, shared or personal workers) stay open until
  the owner answers; the plan lists them.
- **Date:** 2026-10-21
- **Depends on:** ADR-0056 (one engine, two shells), ADR-0021 (event log and queue), ADR-0032 (media backends), ADR-0058
  (a runner on a person's desktop), ADR-0066 (speech, music and avatar models; decision 11: what a deployment lists),
  ADR-0077 (Video Builder), ADR-0080 (3D), ADR-0047 (safeguards), ADR-0012 (licences)
- **Plan:** `docs/phase6-web-identical-plan.md`

## Context

The screens are already one set (`packages/ui`) and the product graphs are one set (`products/`). What differs is **where the
heavy work runs**. On the desktop the engine runs it in its own process: ComfyUI, audio.cpp (speech, music, splitting, voice
change, speech edit), the MuseTalk lip sync server, Pixal3D (3D) and the sandboxed browser render (Video Builder). On the web only
ComfyUI (through the media worker) and the hosted speech models have a home, so Music, Lip sync, Voices, Change a voice,
Edit speech, Dub, Audiobook, Split, 3D and Video Builder have none, and the web menu says "Soon" for them. Two stores
(3D, Video Builder) are SQLite only. The model picker (ADR-0086) has no web counterpart.

## Decision

1. **A headless engine worker** runs the desktop's components for the web. It is the engine of the desktop profile without the
   window: the same component code (`audio_runtime`, the lip sync server, `model3d_runtime`, the Video Builder runtime), started
   by a job consumer instead of a route. No capability is written twice.
2. **Jobs, never requests** (rule 6). Each capability that has no web home becomes a job kind next to the image and video ones:
   speech (speak, clone, design, convert, edit, transcribe), music, separate, lipsync, model3d, builder_render. The product code asks
   for the capability; the worker runs it. Files move by presigned URLs (inputs pulled, outputs pushed), as ADR-0058 describes;
   progress and usage use the existing event envelope. One heavy model in memory per worker, as on the desktop.
3. **Two ways to reach a worker, one worker.** (a) **Direct**: the worker reads the queue and storage itself (a worker on the
   same network: the owner's Mac for development and a home lab, a CUDA host for staging and production). (b) **Runner**
   (ADR-0058): a person's desktop connects outbound and serves that person's jobs. Same job contract; only the transport differs.
4. **The same model picker.** On the web `ModelSelect` shows the models the deployment lists for the group (ADR-0066 decision 11:
   only models that allow commercial use are offered on a public service) and the person's own choice; "download" is an
   admin action, not a user one. The desktop keeps its own adapters.
5. **Equal means a gate, not a promise.** Every desktop menu item and action has a web decision (`apps/web/lib/parity.ts`, its
   test, `docs/web-parity-ledger.md`); a release is blocked while a desktop item is "soon" on the web without an owner-accepted
   reason.
6. **What may differ, on purpose:** the window (title bar, Save As box, recents menu), the user downloading models, models whose
   licence does not allow commercial use (desktop only on a public service), and the privacy sentences ("nothing leaves this
   computer" becomes where the work runs; the screens already take a `place`).

## Consequences

- The Linux CUDA build of audio.cpp (open since V1) becomes a requirement for a GPU host; a Mac worker needs none.
- Two SQLite stores (3D, Video Builder) get Postgres adapters; the lip sync and 3D files go through the storage interface.
- The Video Builder render runs untrusted page code: on a shared host it needs the sandbox the desktop already has plus a
  container boundary.
- Quotas and moderation for every new kind go through `caps.safeguards_on()` (ADR-0047); speech usage events (backlog B1)
  become a prerequisite for a public launch.
- Not chosen: proxying the whole desktop engine to the web (ADR-0058's remote UI): it gives one person identical behaviour but is
  not a multi-user service. A cloud-only rewrite of the components: it would duplicate them, against ADR-0056.

## Built (2026-10-21): P0 and P1

- **The queue** (`packages/platform-sdk/.../engine_jobs.py`): Redis streams with a consumer group (`wasifyai:engine:jobs`), the
  outcome of each job in a list the API pops, progress in a key, and live workers in expiring keys with the models they list.
  Files are never in Redis: a job names storage keys under the person's own prefix, and a worker refuses any other key.
- **The wire format of speech jobs** (`speech_wire.py`): one module that both the API and the worker import.
- **The worker** (`services/engine-worker`, `python -m wasifyai_engine_worker`): the speech runtime of the desktop engine
  (`build_local_engine`) behind a job loop; one job at a time; every failure is an outcome with a safe message. `make worker`
  runs it on a Mac in a terminal, `make dev` starts it in the background, `scripts/worker.sh models` lists and fetches models.
- **The API side** (`remote_speech.py`): `RemoteSpeechEngine` is a `SpeechEngine`, so the voice product did not change. It
  offers what live workers list as ready. `VOICE_ENGINE=worker` is the new default (workers plus the hosted models).
- **A compromise, to be revisited:** the voice graph awaits the job inside the run (as it awaited the hosted provider), not with
  the pause-and-resume pattern of the image jobs, because every voice node does more work after the engine call; the run is
  already long-lived and streamed. Consequences: no queue position in the run's events yet, and cancelling a run does not stop
  a job a worker has started.
- **Measured:** a real round trip on this Mac, API engine to Redis to the worker to Kokoro and back through SeaweedFS: 13.8 s for
  one sentence, 11.5 s of it the first model load; no file left behind.
