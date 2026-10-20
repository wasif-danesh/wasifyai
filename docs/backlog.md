# Backlog: what is not verified, and what is left open

Kept so nothing said in a status report is lost. Each item says what is true now, why it matters, and what
finishing it takes. When one is done, move it to "Closed" with the date and how it was checked. Written
2026-10-18, after the web parity work (`docs/phase3-web-parity-plan.md`) and ADR-0067.

The desktop app is the top priority from 2026-10-18 (`docs/phase4-agent-plan.md`); these items are the web
and deployment side and wait for it unless marked **blocks release**.

## A. Not verified (built, with tests that use fakes or mocks, never tried for real)

| # | Item | Why it is not verified | What closes it |
|---|---|---|---|
| A1 | The web screens for music, splitting, voice change, speech edit, dubbing, the audiobook and lip sync, through the web app on a Mac with the local models | The data folder on the dev machine had no speech runtime set up; the checks use a fake engine and mocked responses | Set up the speech runtime and models in the desktop app, run `scripts/web-local.sh`, make one of each through `http://localhost:3000`, and note what failed here |
| A2 | `scripts/web-local.sh` itself | Never run | Run it from a clean shell with Podman up; fix what breaks; add a line to the runbook with the time it takes |
| A3 | The text and picture moderators, the daily limits and the canaries of the voice product against real models | Tests script the moderator replies | Bind `moderator` and `multimodal` in the admin Models page, press the test (it runs the voice canaries), then try a refused text, a photograph of a person for lip sync, and each limit with `SAFEGUARDS_FORCE_ON=true` |
| A4 | The hosted speech provider (`HostedSpeechEngine`, aliases `voice-speak`, `voice-transcribe`) | Tested against a mocked gateway | Bind the two aliases to a real provider (OpenRouter or similar), run the alias test in the admin Models page, speak and transcribe once; check the provider's terms allow commercial use |
| A5 | The Helm chart on a cluster (`notebooks`, `voice` values, the notebooks worker Deployment) | Only `helm lint` and `helm template` were run | `make kind-up` with `notebooks.enabled=true` and `voice.enabled=true`, add a source to a notebook, speak a sentence |
| A6 | The notebooks worker image on amd64, and the worker against a real database and object storage | Built on arm64 only (3.0 GB); the reader check passed in the build | Build in CI (it is in the image list), run the worker with `DATABASE_URL` and storage set, add a PDF |
| A7 | Migration 0019 on a database that has real old rows | Verified on a scratch database with one row | Run it on a copy of any database that has old songs, speeches, transcripts or lip syncs |
| A8 | `scripts/purge_older_products.py --yes` | Run as a dry run only, against an empty bucket | Run against a bucket with files under the four old product prefixes |
| A9 | The kind scripts and compose after the speech and lip sync services were removed | Syntax-checked (`bash -n`, YAML load) only | `make kind-up` and `make kind-test`; `podman compose up` |
| A10 | Playwright after the second deletion round (services, SDK providers) | Not re-run; only unit, type and lint checks | `pnpm --filter web test:e2e` |

## B. Left open (not built)

| # | Item | Notes |
|---|---|---|
| B1 | Usage events and quotas for hosted speech seconds | The gateway's spend log has the cost; the platform writes no usage event for speech seconds. Needed before the web is public |
| B2 | Accessibility pass on the web (focus order, labels, contrast in both themes) | No axe or similar tool is installed (a new dependency, ask first). Folded into the design system, ADR-0081 decision 9 and stage DS3 |
| B3 | Load and quota tests (many people, long dubs and audiobooks) | None exist |
| B4 | **Blocks release:** the terms of service the OpenRAIL and consent rules require before the public sees video and voice cloning | Needs the owner and a lawyer; the consent text exists in the app |
| B5 | The cloud GPU host | ComfyUI music on a GPU host is gone from the web (ADR-0067). To run ACE-Step on a host, run the voice product's local engine there (`VOICE_ENGINE=local`); needs a CUDA build of audio.cpp with its own pinned lock (open since V1) |
| B6 | The assistant on the web: tool results that open a creation only know images and videos (a track or a notebook has no web page for them); no per-person token quota for the chat model | Superseded in part by the assistant work in `docs/phase4-agent-plan.md` |
| B7 | Image styles (LoRAs) on the web | The list an admin curates has no route yet, so the panel is hidden |
| B8 | The per-resource BFF route files the shared screens no longer need | The catch-all route covers them; only `speeches`, `transcripts`, `voices`, `images`, `videos`, `uploads`, `prompt` remain and are used |
| B9 | Dubbing and the audiobook: no cap on long inputs besides the daily limits | A 200,000 character audiobook is a long job; no per-run ceiling in time |
| B10 | In-flight runs of a deleted product do not resume | Not applicable once the products are gone; listed because a deployment that still has paused runs of them would see errors |
| B11 | Old object storage keys and usage events of the deleted products | Usage events are kept on purpose (billing); files are removed by A8 |
| B12 | The development Postgres is a second database | The Podman container `wasifyai-pg` is not the compose stack's Postgres; `make migrate` may touch the wrong one. Pick one and say so in `docs/environments.md` |

## D. Open items from Phase 5 (answered by the owner 2026-10-18; what is left)

| # | Item | Where |
|---|---|---|
| D1 | Read the licence files of Laya and Clef-flash (Hugging Face lists both Apache-2.0) and Unsloth Studio's AGPL terms for redistribution | ADR-0075, ADR-0073, stage T0 |
| D2 | Hosted models for the agent: Hugging Face and GitHub only to start; check that GitHub Models' limits allow 64,000 tokens of context | ADR-0072, stage G0 |
| D3 | Rented GPUs: the person's own account on desktop; ours on web (to confirm with the web hosting); first provider chosen in T0 | ADR-0073 |
| D4 | GSAP: fine on the open-source free desktop; ask GSAP again before any paid or hosted Video Builder | ADR-0077 |
| D5 | Qwen3.5-9B as the one default model: run the checks per alias, measure context, memory and speed, write the minimum-memory line, decide the low-memory fallback | ADR-0078 |
| D6 | Not verified, to measure in T0: Unsloth's MLX backend memory and time on 16, 32 and 64 GB Macs; whether its trainer can be driven headless; Laya training on the Mac; automatic caption quality; GGUF LoRA conversion per model family | ADR-0073 to ADR-0076 |
| D7 | 3D (ADR-0080): the DINOv3 redistribution position and the weights-bundle licence; `pixal3d.cpp` NOTICE and vendored code; speed and memory on the owner's Mac; the owner accepts Meta's DINOv3 licence on Hugging Face and approves the TD0 download | ADR-0080, stage TD0 |
| D8 | Motion graphics (ADR-0079): MG0 evaluation of the adapted skills; HyperFrames transparent-video check | ADR-0079 |
| D9 | ~~Approve a 3D viewer dependency~~ approved 2026-10-18 (`<model-viewer>`, ADR-0080) | ADR-0080 decision 7 |
| D10 | Spikes done 2026-10-19 (G0, T0, V0, TD0). Open decisions: DINOv3 route; `pixal3d.cpp` face-target patch; CI build of the pinned commit; AGPL reading by counsel; Qwen3.5-9B bf16 and Clef-flash downloads; Laya licence enquiry; V1 sandbox path and fonts | `docs/phase5-agent-training-video-builder-plan.md`, "Spike results" |
| D11 | Not measured by the spikes: 16 and 32 GB Macs (9B training, 64k agent, 3D), Windows and Linux, rented NVIDIA GPUs, Q8_0 against original Pixal3D, model quality half of MG0, hosted agent run | the four spike reports |
| D12 | Music video (ADR-0084, **Proposed** 2026-10-20): all owner questions are answered (2026-10-20), none open. Stage MV0 (a throwaway-environment spike on this Mac only: analysis tools and their licences, plan quality, LTX 0.9.5 and LTX-2.5 motion, MuseTalk on a sung voice, a study of Maestro and AutoMV by reading; deletes its downloads and reports the disk used) waits for the hold on new features to lift | ADR-0084, `docs/spikes/music-video-research.md` |
| D13 | Two owner decisions of 2026-10-20 that touch Accepted documents and wait for code or the owner's wording: (a) **remove the "AI-generated" mark from lip sync everywhere** (descriptor `mark: required`, the server's drawing, tests; amend ADR-0066 V5 (a)(d) and ADR-0044; review again before release, with B4); (b) **a model free below a revenue threshold may be a shipped default, for all products** (CLAUDE.md rule 12, ADR-0012 and ADR-0066 decision 4 wording; a field naming the condition and threshold on the descriptor; a revenue-watch note; LTX-2.x USD 10M, Stability Community) | ADR-0084 |

## C. Closed

| Date | Item | How it was checked |
|---|---|---|
| 2026-10-18 | The older music, text to speech, speech to text and lip sync products, their services and providers, tables and files | ADR-0067; 1529 Python tests, 193 web tests, helm-lint; `purge_older_products.py` dry run found 0 files; migration 0019 applied |
