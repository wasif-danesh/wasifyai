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

## Built (2026-10-21): P2 to P4, images and video

- **Lip sync (P2)** is one of the speech kinds of P1 and ran for real; no new code beyond what P1 has.
- **3D (P3):** kinds `model3d.matte` and `model3d.generate`; the worker runs the desktop's `Model3dService` and reports
  its state (`ready`, `problem`, `fit`) in its heartbeat (`EngineWorkerInfo.components`). The product keeps its code: its
  store runs on Postgres too (schema `model3d`; a `pgstore.py` subclass until stage J2 made it one class,
  `Model3dStore.on_postgres`), its files go through one interface with two homes
  (`blobs.py`: folders on the desktop, object storage on the web, where a step works in a temporary `workspace`), and its job
  manager is per person on the web. Cancelling asks the worker (`EngineQueue.cancel`), which kills the 3D process.
- **Video Builder (P4):** kinds `builder.inspect`, `builder.snapshot`, `builder.render`, `builder.lint`. A composition
  travels as its template and slots; the worker rebuilds the page (it has the library and the fonts) so no project files are
  kept on the web. The product's engine calls are unchanged: the API's `RemoteBuilderEngine` hands the product stand-in
  files and reads `slots.json` back. The words are turned into a template by the gateway's `chat` alias. Postgres store in
  the schema `builder`.
- **Images and video (not an engine kind):** the media worker got a native mode (`COMFYUI_MODE=sidecar`) that runs the
  desktop's ComfyUI; checked for real with `scripts/web_media_check.py`.
- **Left in these stages:** moderation of typed words and uploaded pictures for 3D and Video Builder (they refuse while
  safeguards are on, as on the desktop; P6), usage events for GPU seconds, a queue position for 3D and Video Builder jobs.

## Built (2026-10-22): jobs survive an API restart, and P5

- **A restart no longer orphans a long job.** A 3D picture or model and a Video Builder render go out under the id of their
  own row. `EngineQueue` keeps a `seen:{id}` key (6 hours) and `status(id)` says `waiting`, `done` (the outcome is waiting) or
  `lost`. On start the API fails what is older than three hours, then `resume_all` picks up every row still working: it waits
  for the same job (nothing is sent again), a job the queue has lost is failed in words ("It was stopped before it finished.
  Make it again."), and a render that never got past its word check is failed the same way. When the service stops, the engines
  are told `closing`, so the cancelled tasks do not tell the worker to stop and leave their rows working. A late failure cannot
  undo a finished row (`WHERE status = 'working'`). The outcome list now lives 6 hours. Checked for real: the API container was
  restarted during a Video Builder render (it finished and was saved), during a 3D picture cut-out and during a model.
  Not covered: two API replicas that both resume the same job (one gets the outcome, the other waits until its time-out and
  its failure is ignored); speech jobs (the voice graph awaits inside the run, no resume).
- **P5, the picker on the web.** `admin_wire.py`: the job kinds `admin.fetch_model` and `admin.fetch_engine`, which a worker
  runs on itself (`wasifyai_engine_worker/admin.py`: the download of the desktop's own `DownloadManager` with progress, and the
  lip sync engine's installer). The API's admin routes (`admin_workers.py`): `GET /admin/workers`, `POST
  /admin/workers/models/{id}/fetch`, `POST /admin/workers/engines/{name}/fetch`, `GET /admin/workers/jobs/{id}`; a second click
  follows the first job; each start is audited. Admin > Workers lists the workers and offers "Get ... (size)". The screens
  for Voice, Listening, Music and Lip sync get the same "Select ... model" button and panel as the desktop
  (`apps/web/lib/choices.ts`, `WebModelChoices` in the product layout): the choice is remembered in the browser under the key
  the screens already read; a person who is not an admin sees a missing model as "ask an admin". `scripts/worker.sh models`
  still works (it uses the same code).
- **Left:** the licence filter for a public service (a deployment setting that hides and refuses models that do not allow
  commercial use) waits for decision 2 of the plan; a worker does one job at a time, so a big download makes other work
  wait; the picker is not on the Image, Video, Chat and 3D screens on the web (their models are the deployment's).

## Built (2026-10-22): P6 safeguards and usage, P8 the gate

- **P6.** `RouteGuard` (`packages/platform-sdk/.../route_guard.py`) gives features that run from routes (3D, Video Builder) what a
  graph gets from `Capabilities`: whether the safeguards are on, the day's usage events against the product's `quotas:`, and a
  usage event for what was made. Nothing is checked while the safeguards are off (the desktop), but usage is recorded either way.
  **3D:** an uploaded picture goes to the picture moderator (`text.moderate_image`, alias `multimodal`; categories include
  `real_person_photo`, matching the rights statement already on the screen) before it is kept or cut out; it fails closed;
  quotas `pictures_per_user_per_day: 20` and `models_per_user_per_day: 5`; events `model3d.picture` and `model3d.model`.
  **Video Builder:** the old refusal while safeguards were on (ADR-0079 decision 9) is gone. The words a video would show
  (`templates.expected`) go to the text moderator before a render starts, and a draft's description before the model sees it;
  quota `renders_per_user_per_day: 10`; event `builder.render`. Saving a project's words is not moderated (they are only
  drawn on a render, and the preview is shown to its author). **Workers:** every job's time is a usage event
  `engine.seconds` (unit seconds, meta `job` and `worker`) from the three remote engines, whatever the outcome. Speech keeps
  the voice graph's moderation, daily limits and consent screens (they are the product's, so the worker path does not change
  them). A 3D title or prompt is not moderated (they are labels; the model is made from the checked picture).
- **P8.** `PARITY` rows that are not `live` carry `accepted` (who, when, why); the gate is in `apps/web/lib/parity.test.ts`:
  every non-live row is accepted, every action in `docs/contracts/actions.json` names a menu item with a row (or says why it has
  none), and the generated table in `docs/web-parity-ledger.md` is what `parity.ts` says. The CI job `parity`
  (`.github/workflows/desktop.yml`) runs it and writes the ledger to the run's summary; the packaged app waits for it. A browser
  check (`apps/web/e2e/menu-walk.spec.ts`) opens each group of the side menu and visits every item: none may be missing or fail to
  draw.
- **Left:** per-deployment quota numbers are defaults in `product.yaml`; a GPU-seconds quota (the events are there to count);
  the moderators' behaviour on a real gateway was not run here (the tests use a stand-in moderator).
