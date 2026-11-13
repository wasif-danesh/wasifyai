# Lip sync choices: a model dropdown, on this computer or with a key (plan, 2026-11-11)

Status: **accepted by the owner 2026-11-11** with every recommended answer (see "Decisions for the owner"). LC0 in progress.

## What the owner asked (2026-11-11)

- A dropdown on the lip sync screen to choose the model: **EchoMimic v3 flash** (today's only one), **MuseTalk**,
  **InfiniteTalk** and **LongCat Avatar**.
- The app is for local **and** cloud models. Apart from MuseTalk, the lip sync models also run in the cloud with the
  person's own key.
- The desktop must not stop anyone from trying a heavy model on their own computer. A heavy model may be limited to
  a short test of 2 or 3 seconds.
- MuseTalk, InfiniteTalk and LongCat Avatar must work on the Mac, and be built so they can work on Linux and Windows
  (tested later).
- With a key saved, a lip sync video must be made through the provider.

## Where each model runs

| Model | On this computer (Mac) | On this computer (Linux, Windows) | With a key |
|---|---|---|---|
| EchoMimic v3 flash (default) | yes, any length: ~2.5 min per s at 720p, 29-41 GB | PyTorch CUDA, same code | no provider found; local only for now |
| MuseTalk 1.5 | yes, any length: ~6 s per s, 11.8 GB (ADR-0044) | PyTorch CUDA, same code | **no** (fal.ai's MuseTalk needs a video, not a picture; owner: local only) |
| InfiniteTalk | ~~test only, up to 3 s~~ (no forced length since 2026-11-12): one 81-frame window at 320 px, ~4 min per s, ~30 GB (ADR-0044 spike) | PyTorch CUDA, the kijai ComfyUI wrapper or the official code; full length on a big GPU | fal.ai `fal-ai/infinitalk` (picture + voice), listed $0.20 per video second |
| LongCat Avatar 1.5 | ~~test only, up to 3 s~~ (no forced length since 2026-11-12): MLX port, ~20 min per s, up to 58 GB at 480x832 (spike, 2026-11-11) | official PyTorch CUDA code | fal.ai `fal-ai/longcat-single-avatar/image-audio-to-video`, $0.15 (480p) or $0.30 (720p) per video second, up to ~50 s |

**Cloud models added 2026-11-12 (owner):** on fal.ai, VEED Fabric 1.0 Fast, Kling Avatar v2 Standard, OmniHuman 1.5
(turbo, 720p) and InfiniteTalk (acceleration high, 480p by default), timed in `docs/spikes/lipsync-cloud-race.md`.
Each says its price and measured time per video second in the picker and on the screen. LongCat was taken off the
cloud list (fal.ai and WaveSpeed) the same day: a black video on fal.ai. This computer's models are
unchanged.

**Lip sync is fal.ai only (owner, 2026-11-12): no WaveSpeed or other provider.** (Kept for the record:) WaveSpeed hosts both InfiniteTalk and LongCat too. ADR-0095 says fal.ai first and other providers later, so WaveSpeed
is a later step with its own runner.

## How it works

### 1. The dropdown

- Every lip sync model is a catalogue entry in `products/wasifyai-voice/models.yaml` with `tasks: [lipsync]`. The
  model picker (ADR-0086) and the lip sync screen list them; EchoMimic stays the default.
- Each entry says where it can run. A row shows one of:
  - "On this computer"
  - "On this computer · test, up to 3 s"
  - "With your key · fal.ai"
- When a model can run both ways, the person chooses with a "Where" choice beside the dropdown: **On this
  computer** or **With my key**. That choice is offered only once a lip sync key is saved.
- A model whose files or engine are not set up on this computer shows "Set up" (size first, as today), and
  can still be used with a key without setting anything up.

### 2. The short test on this computer

**Replaced 2026-11-12 (owner): "Don't force 3 seconds testing only. Indicate time per second and leave it to user to
decide."** No length is forced on any model, here or in the cloud. The screen says, before Make, how long the voice
should take and (in the cloud) what it should cost, from each model's measured time per video second and its listed
price; the person decides. The text below is the old plan, kept for the record.


- New catalogue field `lipsync.local_test_s` (3 for InfiniteTalk and LongCat; absent for EchoMimic and MuseTalk).
- With a heavy model on this computer, the screen says "On this computer this model makes a 3-second test from the
  start of your voice. With your key it makes the whole video." The voice is cut to its first 3 seconds. Nothing is
  refused.
- The sizes for a test are the small ones the Mac can hold. InfiniteTalk is 320 px on the short side (it ran out of
  memory above that). LongCat is 480p. The shape choices stay the same.
- The time and memory estimate on the screen uses each model's own measured numbers (`speed_pixels`, `measured`),
  as for EchoMimic today.
- On Linux and Windows with a CUDA GPU the test limit can be lifted per platform later (`local_test_s` by platform),
  once measured.

### 3. One engine per model on this computer

Today there is one lip sync sidecar (EchoMimic). The four models need different packages (MuseTalk's old torch lock,
EchoMimic's, InfiniteTalk's transformers 4.57 / diffusers 0.35, LongCat's `mlx` on the Mac), so:

- **One environment per model family**, each with its own pinned source, hashed lock and platforms in the component
  manifest (`lipsync.echomimic`, `lipsync.musetalk`, `lipsync.infinitetalk`, `lipsync.longcat`). Platforms:
  `darwin-arm64`, `linux-x86_64-cuda`, `windows-x86_64-cuda`. LongCat uses a different lock on the Mac (MLX port)
  from the one on Linux and Windows (official PyTorch code).
- **One server contract** for all of them, the one EchoMimic uses now: `POST /generate` with the picture, the voice,
  `fps`, `width` and `height`, answering an MP4. Each family has its own `engine.py` behind it.
- **Only one lip sync engine runs at a time.** Starting another one stops the first and gives the memory back, using
  the same slot manager and 10-minute idle stop as now.
- The installer already handles `Scripts/python.exe` on Windows and reports `mps`, `cuda` or `cpu`. Each engine
  chooses its device from that.

Where the code comes from:
- **MuseTalk:** the engine, lock and server from before commit `acadeeed` (git history), and the working copy still in
  `.lipsync/musetalk` (5 GB). Its weights were in the catalogue; they are fetched again (4.2 GB; old files were
  trashed).
- **InfiniteTalk:** the ADR-0044 spike route. On the Mac that means ComfyUI-WanVideoWrapper with the MPS patch
  (float64 to float32, a bf16 base). The plan is to run its pipeline directly in our own sidecar instead of a second
  ComfyUI, if the spike shows that works.
- **LongCat:** `xocialize/longcat-avatar-mlx` on the Mac (the spike setup); the official `LongCat-Video` code on
  CUDA.

### 4. Lip sync with a key

- **A lip sync row in Settings > Your keys** (`keys.lipsync`), provider fal.ai, with "Use the same key as Voice" as
  for the other products (ADR-0095: one key per product). Test asks about a request that does not exist, so
  nothing is charged.
- `KeyedLipSync` in `own_keys_engines.py`, beside `KeyedSpeechEngine`:
  - it sends the picture (already cropped to the chosen shape and size) and the voice to the model's endpoint
    through `FalQueue`;
  - it follows the job and fetches the MP4;
  - the result is saved like a local lip sync, with the provider named in usage (seconds).
- The fal.ai pages show only links for `image_url` and `audio_url`. The picture and voice either go inline as data
  URIs, if fal.ai accepts them, or are uploaded to fal.ai's storage with the same key first. Stage LC0 finds out
  which.
- Sizes with a key: LongCat 480p or 720p (fal.ai's own choice); InfiniteTalk 480p or 720p.
- Length with a key: LongCat up to about 50 s per video (10 segments); longer voices are made in pieces and
  joined, as EchoMimic does locally. InfiniteTalk's limit is read from its page in LC0.
- Errors are passed on in fal.ai's words (ADR-0095 decision 8).
- **The web:** a new row in Admin › Media, **Voice · Lip sync**, either "Engine workers" or fal.ai, as K5 did for
  Speak and 3D. People see the admin's choice on the model button.

## Stages

Each stage ends with tests, a real run on the owner's Mac, docs and a `git add` line.

| Stage | What | Done when |
|---|---|---|
| LC0 | **Spike.** (a) With the owner's fal.ai key, one 5 s LongCat clip and one 5 s InfiniteTalk clip from the owner's picture and voice (about $2 in all). Record: whether data URIs work or storage upload is needed, wait time, and whether the face is kept. (b) On the Mac: a 3 s LongCat test at 480p and 75 frames on the q4 weights already downloaded; a 3 s InfiniteTalk test at 320 px (downloads first, see the decisions below); MuseTalk started from `.lipsync/musetalk`. | the table of time, memory, face and cost is written down, and the owner has watched the clips |
| LC1 | The catalogue fields (`where`: local, key or both; `local_test_s`; per-model sizes), the per-family components and the one-engine-at-a-time slot. EchoMimic moves onto the new layout without changing what it does. | EchoMimic works exactly as now; tests cover two families |
| LC2 | MuseTalk back as a choice on this computer (Mac; CUDA lock written, not run) | a MuseTalk video from the screen, any length |
| LC3 | Lip sync with a key: Your keys row, `KeyedLipSync`, LongCat and InfiniteTalk on fal.ai, long voices in pieces, the web's Admin row | a full-length LongCat and InfiniteTalk video made with the owner's key from the screen |
| LC4 | InfiniteTalk on this computer: a 3 s test on the Mac; the CUDA path written | a 3 s InfiniteTalk test from the screen |
| LC5 | LongCat on this computer: a 3 s test on the Mac (MLX); the CUDA path written | a 3 s LongCat test from the screen |
| LC6 | The screen and the dropdown seen in the real window; help, search index (ADR-0041), contracts, README, `docs/desktop/voice.md` | walked in the real app window |

Linux and Windows are written into every stage (locks, platform keys, device choice) and are **not run** until the
owner tests them, as asked.

## ADR changes this needs

- **ADR-0066 (Accepted): an amendment, "Lip sync choices".** It covers several lip sync models chosen per job, one
  engine environment per family, and the 3-second local test for heavy models. It reverses nothing: answer 3 and
  the 2026-11-10 amendment made EchoMimic the engine; it stays the default.
- **ADR-0095 (Proposed): change K4's "Lip sync is not on a key".** That line was true for MuseTalk on fal.ai, which
  needs a video. LongCat and InfiniteTalk on fal.ai start from a picture, so lip sync goes on a key with those two.
- **ADR-0044:** a pointer only. InfiniteTalk comes back as a choice; its Mac limits are why it is a 3-second test.

## Decisions for the owner

LC0 progress (2026-11-11):
- LongCat 3 s test on the Mac: 25 min, 50 GB, and the face is not kept (`docs/spikes/lipsync-longcat-avatar.md`).
- The cloud half waits for the owner's fal.ai key. The code for it was built as stage F4 of
  `docs/own-keys-fal-everywhere-plan.md`, which is this plan's LC3.

Answered 2026-11-11 (owner): "Yes, as recommended". A separate Lip sync key row; a 3 s local test; each download
asked for before it starts; about $2 of fal.ai for LC0; EchoMimic local only.

1. **The key:** a separate Lip sync key row (with "Use the same key as Voice"), or simply use the Voice key? The
   plan says a separate row, because ADR-0095 is one key per product and Voice's row is set to Kokoro.
2. **The test length:** 3 seconds for InfiniteTalk and LongCat on this computer, cut from the start of the voice?
   For time: a 3 s LongCat test is roughly an hour on this Mac, InfiniteTalk roughly 12 minutes.
3. **Downloads for LC0 and later**, each asked for separately before it starts:
   - MuseTalk weights: 4.2 GB.
   - InfiniteTalk on the Mac: the Wan2.1 I2V 14B base converted to bf16 (~33 GB), plus InfiniteTalk's own weights
     and the audio encoder (several GB).
   - LongCat: the q4 weights are already on AI-1TB. q8 (31 GB) only if the face is lost again.
4. **The fal.ai spend for LC0:** about $2 on your key (two 5 s clips, LongCat at 720p, InfiniteTalk at $0.20 a second).
5. **EchoMimic with a key:** no hosted EchoMimic v3 was found, so it stays local only. Agreed?

## Sources

- fal.ai LongCat: https://fal.ai/models/fal-ai/longcat-single-avatar/image-audio-to-video/api
- fal.ai InfiniteTalk: https://fal.ai/models/fal-ai/infinitalk
- WaveSpeed: https://wavespeed.ai/models/wavespeed-ai/longcat-avatar, https://wavespeed.ai/infinitetalk-api
- Our own: ADR-0044 (InfiniteTalk and MuseTalk on the Mac), ADR-0066, ADR-0095, `docs/spikes/lipsync-longcat-avatar.md`
