# ADR-0044: Lip Sync

- **Status:** Accepted (built 2026-10-09; the engine is MuseTalk, see "Engine change"; InfiniteTalk was removed)
- **Update (2026-10-18):** superseded in part by ADR-0067: the lip sync product was removed and replaced by the voice product (ADR-0066).
- **Date:** 2026-10-09

## Context

The studio's home page has a "Lip Sync" card marked Coming soon. A user supplies a **character image** and
a **voice, a song or a script**, and gets a video of the character speaking or singing in sync. It builds on the
other two speech ADRs and on the video product:

- the character image uses the picture upload and component (ADR-0035, ADR-0039);
- a **script** becomes speech with Text to Speech (ADR-0042, which also covers Bengali and the other Indic
  languages);
- an **uploaded or recorded voice or song** uses the audio upload and recorder (ADR-0043);
- the clip is made as a long background job with a "being made" row, a badge and a notice (ADR-0037).

It is also the riskiest product in the studio: a realistic video of a real person saying words they never said is
exactly what a deepfake is. The design starts from that, not from the model.

**The engine is InfiniteTalk** (MeiGen-AI), chosen by the owner. What was checked on 2026-10-09:

| Part | Notes |
|---|---|
| InfiniteTalk weights and code | Audio-driven video generation. Two modes: video to video (dubbing) and **image to video**, which is what this product uses. A song works as audio. |
| Base model Wan2.1-I2V-14B-480P | A 14-billion-parameter video model; InfiniteTalk adds its audio conditioning on top of it |
| Audio encoder `chinese-wav2vec2-base` | Turns the audio into features for the video model |
| ComfyUI workflow (`ComfyUI-WanVideoWrapper`, kijai) | The route that fits our worker, which already drives ComfyUI |

What the project documents, and what it does **not** say:

- It makes 480P or 720P video. Image to video gives good results for up to about one minute (colour drift after
  that); the default maximum is 40 seconds. It offers an int8 quantised model, and a community low-memory
  runner (Wan2GP) exists.
- The reference setup assumes **NVIDIA CUDA** (a CUDA build of PyTorch and flash-attention). Nothing in what was
  read says it runs on Apple silicon, and **our own result with a neighbouring model is a warning**: Wan 2.2 5B
  image to video produced noise on this Mac (ADR-0037). Memory and time for the 14B model are not verified.
- The card's languages are English and Chinese, and the audio encoder was trained on Chinese. **How well the lips
  follow Bengali, Hindi, Spanish, Arabic or any other language is unverified.** Because the project must be
  multilingual, that is an acceptance test, not an assumption.
- The same team has released a newer avatar model (LongCat-Video-Avatar 1.5) that replaces the Wav2Vec2 encoder
  with Whisper-Large for more accurate audio understanding. It is noted here as the likely successor if
  InfiniteTalk's language coverage falls short; it is not part of this decision.

## Decision

- **A new product, `wasifyai-lipsync`,** built like the video product: a row with `status = working`, the user can
  leave, the same badge and notice, a "Lip syncs" kind in My creations. Web area `/lip-sync` and
  `/lip-sync/creations/{id}`. The Coming-soon card and page stay until it is accepted and built.
- **Inputs.** (1) A character image (PNG, JPEG or WebP, up to 10 MB, one face). (2) A voice, in one of three ways:
  *Script*: text, a language and a male or female voice, made into speech by ADR-0042 first; *Upload*: an audio
  file (or the audio of a video) through the ADR-0043 upload; *Record*: the ADR-0043 recorder. A song is just
  audio. (3) An optional short style hint ("calm, smiling"), with the Enhance button (ADR-0038) as for video.
- **Output.** An MP4 with the audio mixed in and a poster, like a video clip, **480P** (720P only if the
  evaluation shows it is affordable). The length equals the audio's; **at most 15 seconds in this version**
  (the model supports far more; the limit is for cost and is raised only from measured speed). One working lip
  sync per user.
- **Engine: InfiniteTalk, in its image-to-video mode, as a ComfyUI workflow** (`infinitetalk-i2v.json` and its map
  file, with a wav2vec2 audio-encoder node), bound to a new capability `video.lipsync` in `product.yaml` like the
  video workflows (ADR-0037). The audio goes to the worker the way a picture does: the worker reads it from the
  user's `uploads/` prefix and puts it where the workflow's audio-loading node reads it. Where it runs is decided
  by the spike below: on a CUDA machine if the Mac cannot run it, reached as a ComfyUI backend (ADR-0032), so the
  product code is the same either way. The workflow must be run for real before it is accepted, and the weights
  (the 14B base, the audio encoder and InfiniteTalk's own: tens of gigabytes together) are downloaded only when you
  say so.
- **Graph.** `check_request` (inputs, quota, guardrails below), then for a script a `speech.synthesize` job
  (ADR-0042) and `await_job`, then the lip-sync job and `await_job`, then `finalise`: store the MP4, make the poster,
  write the row, delete the uploaded image and audio, write a usage event `lipsync.created` (seconds). Failures
  mark the row `failed` with a plain message.
- **The safety policy. Update 2026-10-09: by the owner's decision (ADR-0047) every safeguard below (the real-person-photo refusal, audio and script checks, MP4 marking, the daily limit) is behind one Admin switch: off on local and staging, forced on in production. The text below describes what runs when the switch is on.**
  1. **No photographs of real people in this version.** A multimodal check of the image (the existing
     `multimodal` alias, like the picture guardrail of ADR-0036) classifies it as `real_person_photo` or not;
     photographs of people are refused with a fixed message. Illustrations, cartoons, 3D renders, paintings,
     mascots and animals are allowed. A classifier is not perfect and a realistic AI-generated face may pass,
     so the check is evaluated on a labelled set (like the image guardrail) and fails closed.
  2. **What is said is checked.** For a script, `text.moderate` on the text. For an uploaded or recorded voice,
     the audio is transcribed with ADR-0043's `speech.transcribe` and the transcript is moderated, in any
     language. Songs are checked the same way (their lyrics).
  3. **No voice cloning,** and the voices for scripts are the preset ones of ADR-0042.
  4. **Marked as AI-generated:** the MP4 metadata says so, and an optional visible mark can be switched on in
     configuration (`LIPSYNC_VISIBLE_MARK`, off by default).
  5. **Limits and records:** 3 per user per day, one working at a time, usage events for every one, and no
     sharing or public gallery in this version.
  Loosening any of this (allowing photographs, for example with a consent step) is a separate ADR.
- **Quota.** 3 lip syncs per user per day.
- **Search (ADR-0041 rule).** A lip sync is searchable: kind `lipsync`, indexed text = the script, or the
  transcript of the voice, plus the style hint. Needs an `IndexSource` (finished ones only), `caps.index_creation`,
  `deps.unindex`, an `ids=` filter, a library card (poster, words) and an evaluation row.

## Evaluation before this is accepted

`services/api/evals/lipsync/` with the results written into this ADR. Nothing in the product is built before
step 1 answers where InfiniteTalk can run.

1. **The feasibility spike (decides where it runs).** Run the InfiniteTalk ComfyUI workflow with a 5 and a 15
   second audio on (a) the development Mac, in the half and full precisions the video work needed (ADR-0037 found
   that fp16 and bf16 gave noise for Wan and fp32 was needed), with and without the int8 model and the
   speed-up LoRA the project mentions; and (b) a CUDA GPU if one can be used. Report seconds of compute per second
   of output, peak memory, and whether the output is a face that moves rather than noise. If the Mac cannot run
   it, this ADR records that and the product targets a GPU host.
2. **Languages.** The same character with speech in Bengali, Hindi, English, Spanish, Arabic, German, Japanese,
   Chinese and Russian, and a sung line. Lip alignment is scored with a lip-sync confidence measure (a SyncNet
   style distance and confidence) and by a person
   who speaks the language; the table lists which languages are good, weak or not usable. A language that fails
   is shown as limited on the page, and the Whisper-encoder successor is tried for it.
3. **The image guardrail:** a labelled set of photographs, illustrations, cartoons, 3D renders and AI-generated
   faces: how many real-person photographs are refused (must be all of the clear photographs), how many
   harmless drawings are refused (a few at most), and an honest note on realistic AI faces. Photographs of
   people in the set are synthetic or used with permission; no real person's photograph is generated or kept.
4. **The audio check:** a script, a spoken file and a song in several languages each reach the moderator through
   the right path.

## Feasibility spike on the Mac (2026-10-09)

Run on the 64 GB Apple Silicon Mac in a separate ComfyUI (port 8190) with ComfyUI-WanVideoWrapper (commit
`088128b`), InfiniteTalk single, Wan2.1-I2V-14B-480P, the lightx2v step-distill LoRA (4 steps, cfg 1), a
synthetic portrait and English speech. Scripts and the wrapper patch are in `~/ComfyUI-LipSync`
(`spike_run.py`, `wrapper-mps-patch.diff`).

| Question | Answer |
|---|---|
| Does it run on MPS? | **Yes, with changes**: the fp8 base file cannot be merged with the LoRA on MPS, so the base is converted to **bf16** (33 GB); the wrapper's RoPE and scheduler code needs float64 replaced by float32 (MPS has no float64); `transformers` 4.57 and `diffusers` 0.35 (newer ones break the wrapper). |
| Is the output noise? | **No.** bf16 gives a clean face that moves and opens its mouth with the speech (unlike Wan 2.2 5B). Checked at 256x256, 1 step. |
| Speed | 256x256, 1 step, 5 s of audio: 306 s in total (**about 60 s of compute per second of output**, including loading). 320x320, 4 steps: **about 200 s per step for one 81-frame window** (3.2 s of video), so about **13 minutes per 3 seconds of output**: roughly 4 minutes per second of video. A 15 s clip would take over an hour. |
| Peak memory | 29-31 GB resident for the process, plus MPS allocations that grow with every window: **the second window ran out of memory at 320x320** (88 GB allowed). 448x448 ran out of memory in the first window (attention asks for a 20 GB block). So the Mac is limited to about 256-320 px and under one window. |
| Languages | Not tested yet (English only so far). Bengali and the other Indic languages are still unverified. |

**Verdict: the Mac cannot be the production host for Lip Sync.** It proves the engine and the workflow work, and is
good for a small demo, but 4 minutes per second of video, small pictures and memory growth are not a product.
Lip Sync needs a CUDA host (the home lab GPU or a cloud GPU) with the same workflow; there the fp8 base, the
LoRA and `sageattn` apply and the speed is expected to be one to a few times real time (to be measured on that host).

Consequence for the build: the product (graph, routes, upload, search, UI) can be built now against the worker
contract and the stub backend, and switched to the real workflow when a CUDA host exists. One extra file was
needed besides the list above: `clip_vision_h.safetensors` (1.26 GB, Comfy-Org repack of Wan 2.1).

## Consequences

- New: the `video.lipsync` capability and InfiniteTalk workflow, the product and graph, migration 0016
  (`lipsyncs`), the web area, the library card and the index source, the image classification prompt and its
  evaluation, the visible-mark option, and tens of gigabytes of weights on whatever machine runs it (the 14B base alone is about 28 GB in 16-bit
  precision).
- Depends on ADR-0042 and ADR-0043 being built first; the ADRs are written so the pieces they share are built
  once.
- **Real risk to the plan:** if InfiniteTalk cannot run on the Mac, development of the product (the page, the
  jobs, the guardrail, the library) continues against a placeholder backend, as the media worker already has a
  stub mode, but real clips need a CUDA host. That is a cost and operations decision for you, not a code one.
- The output length (15 s) and the cost per clip are limited by the model; the first version may be slow. The
  page says how long it takes, as video does.
- InfiniteTalk's language coverage is unproven for the project's languages (see above); the evaluation table is
  part of the product's documentation and an unsupported language is listed, not hidden.
- Not allowing photographs of real people removes a popular use (a photo of a relative speaking). That is a
  deliberate trade for safety, to be revisited with consent design, not by loosening the classifier.

## Not in this version

Photographs of real people, voice cloning, several characters in one image (the multi-person variant exists in the
model), full-body animation, changing the words on an existing video (the dubbing mode), clips longer than 15
seconds, sharing or a public gallery, and translating a voice into another language.

## What was built (2026-10-09)

Built as designed, with these differences, all small and recorded here:

- The product is `wasifyai-lipsync`; the table is `lipsyncs` (migration 0016: 0015 became the system settings table of ADR-0047).
- It takes the **voice as a script or as an audio file or recording** and a **style hint**; the **Enhance button is not
  built** for the hint (it is short and optional).
- **Safeguards follow the owner's switch** (ADR-0047): off on local and staging, forced on in production. This covers the
  picture check, the moderation of words and of the transcript of an uploaded voice, the AI-generated mark and the daily
  limit of 3. The visible mark (`LIPSYNC_VISIBLE_MARK`) is not built; the metadata mark is.
- The words of an uploaded voice are transcribed only while the safeguards are on, so with them off an uploaded voice is
  searchable only by its style hint.
- The workflow is the one run in the spike, with the core `CreateVideo` and `SaveVideo` nodes to mix the voice into an
  MP4 (the example's `VHS_VideoCombine` is not needed). It has been run for real only on the Mac, at 256x256 and one
  step, not at the product's size; the product config sets 640x640 and 4 steps for a CUDA host.
- The worker now uploads a job's **voice** (`audio_key`) as well as a picture, and the stub backend returns a real
  test-pattern MP4 for a video output.
- Still to do from the evaluation: languages (step 2), the picture guardrail on a labelled set (step 3, only three
  fixtures exist now), the audio check on songs (step 4), and speed on a CUDA host.

## Engine change: MuseTalk (2026-10-09)

A first run of InfiniteTalk on the Mac, at the only size it could manage (256x256, 2 steps), looked poor, and
the owner decided that a prototype must run on the development machine. **The default engine is now MuseTalk
v1.5** (TMElyralab; checked 2026-10-09). InfiniteTalk stays as
the option for a big GPU (`PRODUCT_ENV=infinitetalk`, `product.infinitetalk.yaml`, the workflow files and the
ComfyUI route are kept).

| | MuseTalk v1.5 | InfiniteTalk (spike) |
|---|---|---|
| Runs on the Mac (MPS) | **Yes**, fp32, no patches to the model code | Only at 256x256, bf16, patched |
| Memory (peak, MPS) | 11.8 GB | 29 to 45 GB |
| Compute per second of video | about 6 s (15 s for the network plus 12 s of blending, for 5 s) | 60 s to over 200 s |
| What it makes | The mouth area redrawn, **the head and eyes stay still** | A whole moving video |
| Picture | Best on real, front-facing faces; weak on cartoons (not tested yet) | Works on drawings |
| Size | The picture as given, scaled to at most 768 px on the long side | 256 on the Mac |

How it is built: `services/lipsync-musetalk` is a small server (`POST /v1/lipsync`, picture and voice in, MP4 out)
run natively (`scripts/lipsync-server.sh`, set up by `services/lipsync-musetalk/setup.sh`, about 4 GB) because a
container on a Mac cannot reach the GPU; a CUDA container is the same code. The product's `video.lipsync`
capability uses a new `lipsync` provider; the worker's `LipSyncRunner` (set by `LIPSYNC_SERVER_URL`) sends the
picture and voice to it. MuseTalk's own code needs mmpose, which does not install without CUDA; the server takes the
68 face landmarks from the `face-alignment` package instead, with the same crop rule. Weights:
MuseTalk v1.5, sd-vae-ft-mse, whisper-tiny, the BiSeNet face parser and ResNet18 (the project's
own links), face-alignment's S3FD and 2DFAN4. A real run through the stack (script, Kokoro speech,
768x768 clip, cold start included) took 39 seconds for 1.8 seconds of video.

**Length.** The 15 second limit of the InfiniteTalk design is gone: with MuseTalk a clip costs about 5 seconds of
compute per second of video (a 52 second voice took 254 seconds, warm), so the limit is **5 minutes**, enough for a
song (about 20 minutes of work for 4 minutes). The worker allows a lip sync job 90 minutes (`LIPSYNC_TIMEOUT_S`,
reclaimed after 91), a row is marked failed only after 100, and a script may be 1000 characters. The InfiniteTalk
overlay keeps 15 seconds.

Consequences: a still picture gives a head that does not move, and the safeguard that refuses photographs of real
people (ADR-0047 switch) refuses the very pictures this engine works best on, so with the safeguards on the
product needs either an illustration that MuseTalk handles (to test) or a consent design (a separate ADR).

## InfiniteTalk removed (2026-10-09)

The owner asked for the InfiniteTalk code and its models to be removed. The workflow and its map, the
`infinitetalk` product overlay, the worker's ComfyUI address for lip sync (`COMFYUI_LIPSYNC_BASE_URL`), and the
ability to hand a voice to a ComfyUI workflow were deleted, and the 62 GB of models, the ComfyUI environment and the
spike scripts were removed from the Mac. The spike section above stays as the record of what was measured and why
it was dropped. If a CUDA host and a need for whole-body motion appear, InfiniteTalk can be added back
as another provider, from this ADR and the git history (the commits of 2026-10-09).

## The desktop (2026-10-16)

The desktop app makes lip sync inside the voice product (ADR-0066, stage V5), with the same engine, MuseTalk. It does
not use the classifier that refuses photographs of real people, because the app has no model for it and the picture
never leaves the computer; instead the person **says what the picture is and whose voice it is** before anything is
made (a drawing, themselves, or someone who agreed), the answer is kept with the video, and **every video carries
a visible "AI-generated" mark that cannot be turned off**. The web product keeps the ADR-0047 switch as before.
