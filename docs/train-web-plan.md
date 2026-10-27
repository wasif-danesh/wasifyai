# Train on the web: the plan (2026-10-27)

Owner, 2026-10-27: "Do the Train work for web. It should be identical to desktop." Answers to the three questions asked first:
**all four cards, one at a time** (Video, Image, Decision, Writing, each checked for real before the next); **"Use in chat" for a writing model works on the
web** (a worker serves the adapter, a per-person alias points chat at it); **every signed-in person may train**, with the desktop's rules while safeguards are
on (3 runs and 200 pictures a day, one job per person, pictures moderated).

"Identical" means the same screens (`packages/ui` `Train`), the same routes (`/products/wasifyai-training/train/...`), the same managers, plans, checks and
cards. Only the three seams below change, as ADR-0087 did for speech, 3D and Video Builder. Where the web must differ it is listed in `docs/web-parity-ledger.md`.

## The three seams

1. **Rows: `PostgresTrainingStore`** (schema `training`), a subclass of `TrainingStore` that runs the same SQL on a Postgres pool (the 3D store's pattern,
   `wasifyai_model3d/pgstore.py`). Datasets, items, runs, models, writing sets, decision sets. A service restart does not turn a run into "stopped when the app
   closed": runs left `working` are failed with a plain sentence and their worker job is cancelled (resuming a one-hour run is a later step, see "Not in the first stage").
2. **Files: `StorageFiles` (`wasifyai_training/files.py`).** The product's code works with folders (`item_folder`, `run_folder`, `model_folder`). On the desktop they are the
   truth. On the web the truth is **object storage** under the person's own prefix (`tenant/product/user/train/<kind>/<id>/<name>`, rules 7 and 10) and a folder is a **cache on
   the API's disk**: `folder_ready` fetches it when it has no `.synced` mark, `folder_saved` puts what was written back, `folder_gone` removes it from both. Pictures, thumbnails,
   clips, samples, adapters, cards and the looks a run published (`looks/<run>/<name>`) are all kept this way, so any API replica can serve them after a restart.
3. **The engine: `Remote*Trainer` (`remote_train.py`).** The managers call an engine object (`problem`, `ready`, `fit`, `preflight`, `train`, `publish`, `unpublish`, `stop`). On
   the web that object queues an **engine job** (`train.video`, later `train.image`, `train.decision`, `train.writing`) and a worker that has the component runs the **same desktop
   engine class** (`LtxTrainer`, ...) on its own data folder, as `Model3dService` already does. The API uploads the dataset's files as the job's inputs (named `m0.png`, `m1.mp4`, ...),
   the worker writes the adapter to the job's outputs, the API reads it back and the managers go on as on the desktop. `stop()` cancels the worker's job, which ends its process.

## Using a result

- **Looks and styles.** A published model on the desktop is a file in the shared `loras` folder. On the web it stays in storage and is **never shared**: a
  generation request names the person's models (`loras: [{name, weight}]`, `name` the model's published name), the video graph asks `person_looks` (the API) for the storage key of
  **that person's** look by that name (or refuses: "not yours"), and the media job carries `lora_files`; the media worker checks that each key is under that person's looks prefix,
  fetches it into `<loras>/wasify-user/<hash>/<job>-<name>` (a folder ComfyUI reads: `MEDIA_LORAS_DIR`, else the models folder's `loras`), renames it in the graph and removes it
  after the job. The Video **My looks** section is the shared one; the web gives it the person's own models.
- **Decision models** (Try it, Sort a list): the model's folder is in storage; `train.decision.ask` and `train.decision.sort` run on a worker that fetches it
  and keeps it for a few minutes.
- **Writing models** ("Ask both", "Use in chat"): `train.writing.ask` is a worker job; "Use in chat" starts the worker's chat engine on the base model with the
  adapter and registers a per-person chat alias (`mine-<id>`) in the gateway; "Back to my chat model" removes it. It holds the worker's one big-model slot while
  it is in use, and the screen says so.

## Components on a worker

The trainers are components, like lip sync: an admin sets them up from **Admin > Workers** (sizes first, the same consent card), and the worker lists
`train.video`, `train.image`, `train.decision`, `train.writing` with ready, problem and fit in its heartbeat. A person who is not an admin sees "ask an admin"
where the desktop shows a download. The base models each trainer needs (the picture model, the Qwen models, Laya) are fetched onto the worker by the same
admin action; the video model is the one the media worker already holds.

**The trainers in the repository are Mac trainers** (PyTorch MPS, mflux, mlx-lm). On the Mac worker the web is identical. A Linux CUDA host (P7) needs a CUDA
build of each trainer: `diffusers` and `peft` already run on CUDA (the video and decision trainers), mflux and mlx-lm do not (the picture and writing
trainers would need another engine there). That is P7 work, noted in the ledger, not hidden.

## Stages (each ends with a real run on the Mac worker through the web)

| Stage | What | Exit |
|---|---|---|
| **WT0 Base** | `TrainingFiles`, `PostgresTrainingStore`, the job `scope`, `train_wire`, the web mount, the Train page and its BFF, the worker's component slot, admin install of a trainer | the Train page opens on the web, a set can be made, a picture added and checked, descriptions written |
| **WT1 Video** | `RemoteVideoTrainer`, `train.video`, the video component on the worker, the media job's `lora_files`, **My looks** on the web Video screens | a video look taught and used from the web |
| **WT2 Image** | `train.image`, the picture trainer on the worker, Styles on the web image screens, Check it and Try it | a style taught and used from the web |
| **WT3 Decision** | `train.decision`, ask and sort jobs, the decision trainer on the worker | a decision model taught and asked from the web |
| **WT4 Writing** | `train.writing`, ask both, Use in chat with a per-person alias | a writing model taught, asked and used in chat from the web |
| **WT5 Gate** | `train` row in `parity.ts` turned to live, ledger, ADR, checklist run in Playwright, quotas and usage events checked | the parity gate passes without an accepted reason |

## Not in the first stage

Resuming a run after an API restart (the run is failed with a sentence and the job cancelled); a pause that survives a worker restart; the Linux CUDA trainers
(P7); a per-person disk quota for datasets (a limit on pictures and sets exists; a byte quota is a follow-up).

## Status 2026-10-27: WT0 and WT1 built

Built: the Postgres store (`pgstore.py`, the same SQL as the desktop's, found two portability bugs by running both), `StorageFiles`, the remote video trainer, the job `train.video`, the
worker's `TrainComponents` (each trainer is a component with `ready`, `problem`, `fit`, `preflight`), the admin set-up job `video-trainer` (Admin > Workers > Trainers), the web mount in
`main.py` (the other three families are `UnservedTrainer`s: they say a worker is needed), the web Train page (`/train`, the shared screen), the media job's `lora_files`, **My looks** on the web Video screens.
Checked: `services/api/tests/integration/test_training_web.py` (real Postgres and Redis: pictures, a clip, descriptions, a run through a worker, the model, the look in storage, another person
sees nothing, delete removes every file, Stop reaches the worker's process) and the real run in the section below.

Known limits (not hidden): **one run at a time for the whole service** (the managers refuse a second: "A model is being taught"; a queue per person is D26 work); any worker takes any job (a
worker without the trainer fails the job: kind routing is P7 work); a job a worker took more than 45 minutes ago is offered to another (`RECLAIM_AFTER_MS`; long runs need the limit raised
before more than one worker runs); a run is failed, not resumed, when the API restarts; the Playwright menu walk was not run for `/train`.

### The real run of WT1 (2026-10-27): Ena, taught and used through the web stack

On this Mac, native, against the compose stack's Postgres, Redis and SeaweedFS: the API (`DEPLOYMENT_PROFILE=web`), the engine worker and the media worker (sidecar mode, the app's installed ComfyUI), a
scratch data folder for the worker. **The video trainer was set up by the admin API** (`POST /admin/workers/engines/video-trainer/fetch`, followed by `GET /admin/workers/jobs/<id>`: 182.5 MB, 26 s). Then,
as a signed-in person: 12 Ena pictures and 3 four-second clips uploaded to the API (files in SeaweedFS, rows in Postgres), their captions, the magic word, **the run: 2,761 s, the same 1,260 steps, peak 12.0 GB,
training loss 1.1616 to 0.5002, to four decimals the numbers of the desktop run** (same data, same seed, same trainer). The look was kept in storage under that person's prefix; **a second signed-in person saw no
models and got 404 for the file**; and asking for the look as that second person is refused in words ("One of those looks is not yours any more."), before any work.
The first person then made a video with it (`POST /products/wasifyai-video/runs` with `loras`): the graph found the look's storage key, the media worker fetched it into the loras folder for that one job and
removed it, ComfyUI applied it (no "lora key not loaded"), and a real 768x512, 5 s clip came back through the API's download route. Frames: `docs/spikes/video-training-tv0/built-ena-on-the-web.jpg`.

## Status 2026-10-27 (later): WT2, WT3 and WT4 built, and checked for real

All four cards run on the web the way the video one does: **image** (`RemoteImageTrainer`; the samples appear as the worker makes them; the magic word is checked by the picture model's own tokenizer on the worker; Styles
on the web image screens), **decision** (`RemoteDecisionTrainer`; the 850 MB model goes from the worker into the person's part of storage and is moved there inside storage; Try it and Sort a list are worker jobs that fetch the model from
storage into a small cache), **writing** (`RemoteWritingTrainer`; the adapter, tens of MB, comes back through the API; Ask both is a worker job). Each trainer is a component on the worker, set up by an admin
(`POST /admin/workers/engines/<name>/fetch`: `video-trainer`, `image-trainer`, `decision-trainer`, `writing-trainer`), listed by Admin > Workers > Trainers with its size.

Checked for real through the web stack (API in the web profile, Postgres, Redis, SeaweedFS, the engine worker, the media worker, the app's ComfyUI): the **decision** model (128 examples, **43 s, 11.0 GB**, 23 of 23 right, asked in 4 to 6 s,
100 texts sorted in 3 s, another person gets 404), the **writing** model (50 examples, **12 s**, answers before and after side by side, another person gets 404), the **video** look (above). The picture style is run below.

**Not built:** *Use in chat* for a writing model on the web (the status says `can_chat: false` and the screen shows nothing for it): it needs the worker to serve the base with the adapter (the desktop's llama server on a worker), a per-person alias in the
gateway and the assistant taking a per-person model; **Pause and carry on** (a worker job has no checkpoint to pick up: the Pause button is hidden where the status says so); a queue of runs (one at a time for the whole service);
the pictures-and-clips transfer is through the API twice (up to the worker's inputs).

### The real runs of WT2 to WT4 (2026-10-27)

- **Picture style** (12 Ena pictures, 200 steps at 512): **1,071 s, peak 24.0 GB**, through the web API. The magic-word suggestions were checked by the picture model's tokenizer **on the worker**; the sample pictures appeared in the run as the worker
  made them (stored as they appeared, served from storage); the style was kept in storage under that person's prefix; a second person saw no models and was refused ("One of those styles is not yours any more.") before any work. The first person drew
  with it through `POST /products/wasifyai-image/runs` with `loras`: the same prompt and seed gives a young woman without the style and a woman with Ena's age, complexion and face with it (left, middle; the right is one of the training pictures):
  `docs/spikes/video-training-tv0/built-ena-style-on-the-web.jpg`.
- **Decision model** (128 examples): 43 s, 11.0 GB, 23 of 23 right on texts kept back; asked in 4 to 6 s (the worker fetched the 846 MB model from storage once and kept it), 100 texts sorted in 3 s; another person gets 404.
- **Writing model** (50 examples): 12 s, answers before and after side by side, an answer from the taught model in 3 s; another person gets 404.

Two bugs found only by running it for real: the picture trainer reports a sample from a thread of its own, so the worker's upload had to be thread-safe (the integration test's stand-in now reports from a thread too); and tokenizer jobs need a valid key
prefix (the suggestions silently fell back to the plain list until a test said so).
