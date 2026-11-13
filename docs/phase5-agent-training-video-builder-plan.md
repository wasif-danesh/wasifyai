# Phase 5 plan: training and Video Builder (desktop first)

> **2026-10-28 (owner): the agent was dropped.** This plan first also covered an agent for long tasks on Hermes Agent
> (ADR-0072, stages G0 to G4). Hermes needs a component of about 660 MB, which is not practical in the app, so ADR-0072,
> its spike (`docs/spikes/agent-g0.md`) and the agent's stages were removed from this plan. What remains is as written.

Written 2026-10-18 (all of ADR-0072 to ADR-0077 **Accepted** the same day, see "Decisions"), after the owner approved ADR-0068 to ADR-0071 (`docs/phase4-agent-plan.md`). **Revised the same
day** after the owner's Unsloth Studio screenshot: "decision model" is Unsloth's decision model, training reuses
Unsloth, and the whole system is for non-technical people. Desktop is the top priority. This plan covers three new
things the owner asked for, in six Proposed ADRs:

| Owner's request | ADR |
|---|---|
| Training, **simple for non-technical people**, reusing **Unsloth**: the platform, **language models**, **decision models** ("sorters"), **image LoRA** (upload pictures only; the app writes the captions and suggests the magic word) | ADR-0073 (platform), ADR-0074 (language), ADR-0075 (decision model), ADR-0076 (image LoRA, with full diffusion fine-tuning as a remote-only last section) |
| Something like **HyperFrames** (experimental): videos written as code | ADR-0077 (Video Builder) |
| **Text to motion graphics**, working name Motion graphics (`iart-ai/motion-skills`), added later the same day | ADR-0079 (Accepted) |
| **Text/image to 3D** (`TRELLIS.2`, `Pixal3D`), added later the same day | ADR-0080 (Accepted) |

Nothing here is built. Everything waits for the owner's yes to the ADRs and to the components they install.

## Short answers

1. ~~Can the agent do "explore GitHub for the top starred repo and make a report"?~~ The agent was dropped on
   2026-10-28.
2. **What is the "decision model"?** Your screenshot answered it: it is Unsloth's *Train as > Decision model*, a small
   model that answers typed questions about a text (yes or no, pick a category, a score from 1 to 10) with honest
   probabilities. In the app it is **"Teach it to sort"** (ADR-0075), and it needs only a spreadsheet of examples.
   I had misread it as a diffusion model; that content is now a last section of ADR-0076.
3. **Does Unsloth run on a Mac, and can we reuse its code?** Language-model training: **yes**, Studio has an MLX
   backend for Apple silicon (no continued pre-training, embedding models or LoftQ there). Diffusion LoRA: **no**
   (CUDA, Intel XPU or CPU), so the Mac keeps **mflux** (measured). Reuse: Studio is **AGPL-3.0**, the core is
   Apache-2.0. We run Studio's trainer as a **separate, pinned component** (ADR-0062 level A, ADR-0061), and write our
   own simple screens in `packages/ui`; Studio's React code is a reference, not code we copy. **Ostris AI Toolkit**
   stays an optional engine for NVIDIA and rented GPUs only (it is not a Mac option).
4. **How is it simple?** Four rules (ADR-0073): one "Teach" front door with three cards; three steps (add examples,
   check, train) then "use it"; **the app chooses every setting** (the person sees "Quick" or "Better" and a time);
   everything Studio shows lives in a collapsed "For experts" panel. For images the person **only uploads pictures**:
   the app checks them, writes the descriptions with the multimodal model, and offers three magic-word suggestions.
5. **Hyperframes-like?** Yes, as **Video Builder**, experimental: adopt HyperFrames itself as the render engine behind an
   interface, after two gates: the **GSAP licence** and a **sandbox** for rendering code (a composition is code).

## What the refinement changed

| The idea | What it became, and why |
|---|---|
| Train language, decision and image models | **One platform** (datasets, runs, model cards, where it runs), **three simple cards** ("write like me", "sort things", "my character or style"), engines as descriptors with measured numbers, and **three tiers**: this computer, my other machine, a rented GPU. Each result is a **model with a card** (provenance, licence, consent, evaluation) in **My models** |
| Reuse Unsloth, simplify the UI | Unsloth's trainer as a component; our screens; a mapping from every Studio option to *show / hide / fix* (next section) |
| Image: upload only, make descriptions, suggest a trigger word | Our own **auto-captioning** (a multimodal model; the trainers skip uncaptioned pictures), **three magic-word suggestions** checked against the model's own tokenizer, picture checks on arrival, a with-and-without result grid |
| Ostris AI Toolkit first | Kept as an engine for NVIDIA and rented GPUs; on the Mac mflux (measured) and Unsloth's MLX backend (language) are what run |
| Hyperframes | Adopt the engine, own the product around it: assets, speech, captions, music, templates, and authoring by the assistant through our actions |

## The simple screens: every Unsloth Studio option, shown, hidden or fixed

Read from the owner's screenshot of Studio's Train page and from the reference clone. The rule: **a non-technical
person sees only what they can answer.**

| Studio option | In our app |
|---|---|
| Model (a Hugging Face id picker) | **Hidden.** The app picks one already on the computer or recommended; "Why this one" in one line; changeable in Advanced |
| Method (QLoRA / LoRA / Full / CPT) | **Fixed to QLoRA** (LoRA when memory allows); the rest in Advanced; Full and CPT only on NVIDIA |
| Hugging Face token | **Hidden** unless the chosen model needs it; then asked once, with a reason, kept in the keychain |
| Train as (Language / Decision) | **Two separate cards** with plain names: "Teach my assistant to write like me", "Teach it to sort" |
| Dataset (Hugging Face / upload / S3) and Subset, Splits, format | **Replaced** by "Add examples": type some, my chats, a document, a spreadsheet; the app builds the format with the model's own chat template and splits off a check set |
| Max steps | **Hidden.** "Quick" or "Better" sets it from a measured preset and shows the time |
| Context length | **Hidden.** Chosen from the longest example |
| Learning rate, rank, alpha, dropout, scheduler, packing, offload, W&B | **Advanced** only |
| Advanced panel | Kept as **"For experts"**, collapsed, with the engine and every setting, a saved configuration (YAML), and the loss curve |
| Start training | **One button**, with the estimate beside it and a refusal in words if it would not fit |
| Image captions (a sidecar file per picture) | **Written by the app.** The person sees a grid of pictures with text and can edit |
| Trigger word | **"Magic word"**, three suggestions, one selected; "trigger word" only in Advanced |
| Decision questions, layouts (Laya / Clef / LLM head) | **Hidden.** The person picks "category / yes or no / score" and drops a spreadsheet; the app picks the model |
| Export (GGUF, adapter, merged) | **"Use it"**, "Save a copy as a file" |

## The picture

```
 window:  Teach screens · Video Builder screen · assistant cards
              │                  │               │
              ▼                  ▼               ▼
        ACTION CATALOGUE + EXECUTOR  (ADR-0068; approvals in the window, audit, limits)
              │                  │
   ┌──────────┘                  └───────────┐
   ▼                                         ▼
 Training runners                      VideoBuilderEngine
 (ADR-0073)                            (ADR-0077)
   ├ this computer: Unsloth component  │ HyperFrames + Node +
   │   (MLX on the Mac), mflux (image) │ Chrome for Testing,
   ├ my other machine (runner,         │ sandboxed render
   │   ADR-0058)                       │ FFmpeg (the app's)
   └ rented GPU: Unsloth, AI Toolkit   │
                our MCP server (ADR-0069) ◄──────── Claude Code and other agents author here
```

## Hardware reality (this sets the defaults)

| Thing | Runs where | Evidence |
|---|---|---|
| Image LoRA, klein 4B or Z-Image | **Mac**, mflux | 7.5 s/step measured on the M5 Pro for klein; Z-Image to be measured (T0) |
| Image LoRA, families Unsloth lists (SDXL, FLUX.1, Qwen-Image, Z-Image, Krea 2, FLUX.2) | NVIDIA (own or rented), Unsloth's diffusion trainer; AI Toolkit as an alternative | Studio's trainer picks CUDA, then XPU, then CPU: no Mac path |
| Language LoRA or QLoRA up to about 8B | **Mac**, Unsloth's MLX backend (fallback `mlx-lm`), memory by size | Studio documents the MLX backend; figures to measure in T0 |
| Language Full or CPT, bigger models | NVIDIA, Unsloth | not on the MLX backend |
| Decision model, Laya | Any computer (about 0.7 to 0.85 GB); Mac path to verify | licence and Mac training to verify in T0 |
| Decision model, Clef or LLM head | NVIDIA or rented GPU only | Clef is 9B or 27B |
| Diffusion full fine-tune | **remote only**, last | memory and compute; not verified for any engine |
| Video Builder render | CPU, any Mac | speed to be measured (V0) |
| Motion graphics (template path) | any computer; the model only fills slots | ADR-0079; the custom path needs a capable model |
| Text/image to 3D (Pixal3D; TRELLIS.2 not in v1) | **Mac (Metal)**, NVIDIA, AMD or any Vulkan card, through the native `pixal3d.cpp` binary; the original code needs NVIDIA 24 GB | author figures: M5 24 GB 9 min 21 s at 512 with 5.6 GB; RTX 4090 about 3 min; to be measured on the owner's Mac (TD0) |

## Stages

Sizes: S under a week, M one to two weeks, L two to four. Each ends with something a person can use.

### Training (ADR-0073 to ADR-0076)

| Stage | What | Size | Done when |
|---|---|---|---|
| **T0** | **Done 2026-10-19, Go.** Spikes: **how to drive the Unsloth trainer as a component** (its API or CLI, headless, from our adapter; AGPL redistribution read with the licence check); its **MLX backend on 16, 32 and 64 GB Macs** (memory and time by model size) against `mlx-lm`; the **chat-template round trip**; **GGUF LoRA conversion** for the models in the hub; the **Laya and Clef licences** and whether Laya trains and serves on the Mac; Z-Image LoRA with mflux (recipe, time, memory); **auto-caption quality** and the magic-word tokenizer check on the mascot set; Unsloth's diffusion trainer and AI Toolkit on a **rented NVIDIA GPU** from a generated config | M | A descriptor file per engine and family with measured numbers, and a go or no-go on each licence |
| **T1** | The platform and the simple screens: datasets (check, consent, moderation), runs, progress with samples, model cards, **My models**, publishing, the `train.*` actions, the "Teach" front door with three cards and the "For experts" panel | L | A fixture run of each engine through the same screens with fake trainers in CI |
| **T2** | **Teach my assistant to write like me** (language): the four example sources, data checks, Quick and Better, evaluation with our regression cases, GGUF LoRA, "My style" in the model picker | L | A style adapter loads in the language server and passes the regression cases |
| **T3** | **Make my character or style** on the Mac with mflux: picture checks, automatic captions, three magic-word suggestions, evaluation grid, magic-word and memorisation tests, publish to ComfyUI with the key rename | M | A mascot LoRA made in the app from uploaded pictures only, in under an hour, and used in Create image |
| **T3b** | The same card on an NVIDIA machine or a rented GPU through Unsloth's diffusion trainer (AI Toolkit if the spike says it is better) | M | The same screen drives it; the cost cap works |
| **T5** | **Teach it to sort** (decision model): spreadsheet in, data checks in words, Laya by default, report with a baseline, `decision.decide` action, "sort a folder or spreadsheet" | M | A sorter trained from a spreadsheet beats the embeddings baseline and is callable from the assistant |
| **T5b** | A "that was wrong" button that feeds corrections back and offers a retrain | S | Optional |
| **T4** | **Diffusion full fine-tune**, remote only, behind the questionnaire (ADR-0076, last section) | M | Optional; dropped without cost if unwanted |

### Video Builder (ADR-0077)

| Stage | What | Size | Done when |
|---|---|---|---|
| **V0** | **Done 2026-10-19, Go (sandbox first).** Spikes: HyperFrames render speed and memory on the Mac (720p30, 1080p30, a 60-second composition); **the GSAP licence read and a decision**; the sandbox (request interception, profile, limits) against hostile compositions; whether WKWebView can render deterministically; Chrome for Testing size and signing | S | Go or no-go, with numbers |
| **V1** | The component (Node, browser, HyperFrames), `VideoBuilderEngine`, project folders, preview, render with progress and cancel, the experimental screen | M | A template renders in the app and in a hostile-composition test nothing escapes |
| **V2** | Assets from the library, speech and captions with word times, music with ducking, five templates, the `video_builder.*` actions, creations kinds | M | A 60-second explainer with voice and captions made from a script |
| **V3** | Authoring by the assistant, a generated skill for Claude Code, "turn this report into a video" | M | A report becomes a video from one request |

### Motion graphics (ADR-0079)

| Stage | What | Size | Done when |
|---|---|---|---|
| **MG0** | Spike after V1: adapt five skills (kinetic typography, chart animation, explainer, lower thirds, web/GSAP) to HyperFrames; run about 20 requests with and without a skill on three model tiers; test transparent video (HyperFrames, else the lower-thirds route) | S | A table of which skills raise the score, and the alpha answer |
| **MG1** | Template path: five vetted templates with slots, exact-text check, `motion.make`, the plain-words loop with three-still previews | M | "Lower third for Maya Chen" and "chart from my CSV" work from the screen and from chat |
| **MG2** | Custom path: skill catalogue lookup, model-written compositions in the sandbox, the look-and-fix check | M | Passes the evaluation on a capable model; off on small ones |
| **MG3** | Transparent outputs (WebM alpha, ProRes), more skills that earned their place | S | Optional |

### 3D (ADR-0080)

| Stage | What | Size | Done when |
|---|---|---|---|
| **TD0** | **Done 2026-10-19, Go.** **Pixal3D-only spike** (owner's priority): run the pinned `pixal3d.cpp` Metal binary with the Pixal3D single-view and multi-view models on the owner's Mac at 1024 and 1536 (time, memory, failures); 20 inputs; Q8_0 against original quality; the **DINOv3** redistribution read and the weights-bundle licence; `pixal3d.cpp` NOTICE and vendored code read; build the same commit in CI; one run on a rented GPU. No TRELLIS.2 work | S to M | Descriptors with measured numbers, a default resolution, a go or no-go on the DINOv3 position |
| **TD1 (built 2026-10-21)** | Platform: the `model3d` component (installer, `trellis-server`, slot owner), creation kind (search, card, filter), `model3d.*` actions, the viewer (`<model-viewer>`, dependency approval first), tiers 2 and 3 through the runner | M | A GLB from a fixture engine in CI, shown and searchable |
| **TD2 (built 2026-10-21)** | The screen: from a picture, from words through four candidate pictures, input checks, cut-out preview, plain-words result | M | A mascot photo becomes a model on the Mac from one screen |
| **TD3** | Multi-view input; turntable video as a Video Builder template (WebGL in headless Chrome to verify) | S | Optional |
| **TD4** | Our own GPU host for the web, once it exists (backlog B5) | L | Not scheduled |

### Design system (ADR-0081)

| Stage | What | Size | Done when |
|---|---|---|---|
| **DS0** | **Done 2026-10-19.** Write `design/DESIGN.md` from today's tokens (still violet), the generator `scripts/design/build-tokens.mjs`, generated CSS and types, the CI "generated files are current" check | S | Screenshots of every screen are unchanged |
| **DS1** | **Done 2026-10-19.** The token lint (no raw colours, sizes, radii), contrast, gamut, completeness and reduced-motion validation; replace the hard-coded values the lint finds | S to M | `pnpm design:check` passes in CI |
| **DS2** | **Done 2026-10-19.** The blue template (`design/themes/blue.md`) as the default: visual review of the recommended blue and two alternatives, neutrals and accents, chart palette; the token-swap test | S | Web and desktop look blue, AA contrast holds in both schemes, layout checks pass |
| **DS3** | Component catalogue (states, light and dark, density), content guide and state patterns, axe checks (dependency approval first) | M | Every component and state is visible in one place and checked |
| **DS4** | Screen patterns for Teach, Video Builder, Motion graphics and 3D, written before they are built; usability tests of the flows as they land | ongoing | Each Phase 5 screen is built against the system |

## Spike results (2026-10-19)

The spikes ran on the owner's M5 Pro (64 GB) and are written up in `docs/spikes/`. Each ADR carries an amendment with
the details; this is the summary.

| Spike | Report | Verdict | What changed |
|---|---|---|---|
| **T0** training | `training-t0.md` | **T1 Go; T2 Go for small models** | Unsloth's trainer runs headless on the Mac; GGUF LoRA works for Qwen3 and Qwen3.5 (our converter for Qwen3.5); thinking must be off for the template round trip; Laya trains on the Mac; Z-Image trains at 9 to 12 s/step; **licence headers are mixed (AGPL inside the "Apache" package), counsel must read them**; Laya has no licence file |
| **V0** Video Builder | `video-builder-v0.md` | **V1 Go (sandbox first); MG1 Go (templates)** | Render is about real time and byte-identical; **stock HyperFrames is not sandboxed**, so V1 starts with our own locked launch; alpha video works; WKWebView can render GSAP deterministically |
| **TD0** 3D | `pixal3d-td0.md` | **TD1 Go, TD2 Go** | 198 to 1361 s per picture at 1024 (median about 11.6 min), about 18 GB; single view 1024 only; 1M-triangle GLB, not watertight; server has no progress or cancel; prebuilt Metal binary lacks the tensor API, so build in CI; DINOv3 handling recommended |

### Decisions waiting for the owner after the spikes

1. DINOv3 route for 3D (the TD0 recommendation is to download the bundle, show the Meta agreement and "Built with DINOv3", record `conditional`, never mirror).
2. Patch `pixal3d.cpp` for 50k and 200k face targets, or offer only the 1M mesh in v1.
3. Build the pinned `pixal3d.cpp` commit in CI with a current SDK (and test on a macOS 26 Mac).
4. Have someone qualified read the Unsloth AGPL section (mixed headers) before shipping the training component.
5. Approve the optional follow-up downloads: Qwen3.5-9B bf16 (about 19 GB, for 9B training memory) and Clef-flash (about 19 GB).
6. Ask Convai Innovations about Laya's licence file and training data.
8. V1 sandbox path: our own launch (preferred) or an OS-profile wrapper; whether the installed Chrome is offered at all; the open fonts to ship.

## Suggested order (Phase 4 first, then these)

`Phase 4: S1, S3 → A1 (catalogue) → A2 ‖ M1 (card and MCP server) → A3` is already decided and is the base:
training and Video Builder are actions in the catalogue.

Then, in parallel sessions where files do not overlap:

0. **DS0 to DS2 (the design system, ADR-0081) is top priority as soon as the four spikes finish**, before any Phase 5 screen is built.

1. **T0, V0** (spikes, one week): they decide go and no-go and cost nothing in product code.
2. **T1 then T3 then T2** (the platform with its simple screens, the Mac image LoRA, the language card): the nearest to
   done, with a measured path for images, and the owner's Mac is the test machine.
3. ~~G1 then G2 (the agent)~~ Dropped 2026-10-28.
4. **T5** (sorters) once the T0 licence answers are in: the smallest training feature and the easiest for a
   non-technical person to understand.
5. **V1 then V2** (Video Builder): needs the V0 licence and sandbox answers.
6. ~~G3 (the agent evaluation)~~ Dropped 2026-10-28.
7. **MG0 then MG1** after V1, and **TD0** (a week of reading and running on the owner's Mac) in
   parallel with the other spikes; **TD1 and TD2** only if the gates pass.
8. **V3, T3b, T5b, T4, MG2, MG3, TD3, TD4** last.

## Rules these stages follow

- Everything is an action in the catalogue (ADR-0068) and approvals appear in the window (ADR-0069).
- Components are installed on request, pinned and hashed, with the size shown; none is needed by the rest of the app.
- The Unsloth component keeps its AGPL-3.0 licence and notice; our code stays Apache-2.0 and talks to it as a
  separate process.
- Data leaves the computer only through a tier or a provider the person chose, with the destination shown.
- A trained model is never offered without its card and its evaluation; a real person's likeness needs their word.
- **Simplicity is a requirement, tested:** a first-time run of each Teach card needs no more than the three steps, uses
  no word from the experts list ("LoRA", "QLoRA", "epoch", "rank", "learning rate", "trigger word") outside Advanced,
  and is checked in a screen test.
- No number is guessed: estimates come from a measurement on a comparable machine.
- Code that a model wrote (a composition, an agent's file) runs only in a sandbox, and after untrusted content only
  after a click.
- English only in v1; user text in any language works.

## Risks

| Risk | Control |
|---|---|
| Training on the Mac fights the one slot | Slot-aware start card, overnight option, resumable runs |
| Unsloth Studio is AGPL-3.0 | Separate pinned component with its notice; no linking into the Apache-2.0 core; the redistribution read is a T0 gate (ADR-0061, ADR-0062) |
| Studio changes quickly; its trainer may not be easy to drive headless | Descriptor per engine and an adapter; `mlx-lm` as the language fallback on the Mac; T0 decides |
| Laya or Clef licences forbid commercial use | Checked in T0; the sorter falls back to an embeddings classifier |
| Automatic captions are wrong for faces or unusual mascots | The caption grid is editable; quality measured in T0; "Describe again" |
| A trained LoRA of a real person | Consent statement, card, moderation when safeguards are on, no sharing in v1 |
| Licences: FLUX.1-dev non-commercial; GSAP; Remotion; base models | Descriptors carry `commercial_use`; the GSAP gate in V0 |
| Video Builder runs model-written code | Sandbox, request interception, resource limits, notice on untrusted sources |
| AI Toolkit and Unsloth's diffusion trainer need CUDA | They are only ever run on NVIDIA or rented hosts |
| The original 3D code carries non-commercial pieces (nvdiffrast, nvdiffrec, RMBG-2.0); the encoder DINOv3 is gated and conditional | The native engine avoids the first three; DINOv3 conditions shown in About and the model card; TD0 reads the redistribution terms |
| The 3D engine is young (two months, one maintainer) | Pinned commit and hash, built in CI, descriptor seam with alternates, regression set on every pin change |
| Third-party skills are instructions a model obeys | Imported as reviewed, pinned, adapted files; never fetched at run time (ADR-0079) |
| Scope: large features | Spikes first; each stage ships alone; T4 and T5b can be dropped |

## Decisions (answered by the owner, 2026-10-18)

| # | Question | Answer |
|---|---|---|
| 1 | Accept ADR-0072 to ADR-0077 | **Accepted**, with the components they name (Hermes Agent, Unsloth Studio trainer as a separate AGPL component, `mlx-lm`, mflux, AI Toolkit as an optional engine, HyperFrames, Node.js, Chrome for Testing). Components are still installed only on request, with the size shown |
| 2 | "Decision model" | Unsloth's decision model (ADR-0075) |
| 3 | Licence reads | Approved (reading only). Done: Laya and Clef-flash are listed **Apache-2.0** on Hugging Face (ADR-0075). Still to read in T0: the licence files and Studio's AGPL terms |
| 4 | Models for the agent | **Qwen3.5-9B**, also the app's one default model, replacing Gemma alias by alias after checks (**ADR-0078**). Hosted providers first: **Hugging Face and GitHub** only |
| 5 | Rented GPUs | The person's own account on the desktop; ours on the web (to confirm) |
| 6 | GSAP | The desktop is open source and free, so it is not an issue there; ask again before any paid or hosted Video Builder |
| 7 | Order | Unchanged: spikes, then the training platform with the Mac image LoRA (the agent after it was dropped on 2026-10-28) |
| 8 | Optional last items (T4, T5b) | Unchanged: last, droppable |
| 10 | Design system (ADR-0081): `design/DESIGN.md` as the single source, blue replaces violet, build-time swap only, no Figma | **Accepted 2026-10-19.** Still needs your approval later for the axe-core dependency (MPL-2.0) |
| 9 | Motion graphics and 3D ADRs (0079, 0080) | **Accepted 2026-10-18**, including the `<model-viewer>` dependency. Still needed from you: accept Meta's DINOv3 licence on Hugging Face (by hand) and say yes to the TD0 download (the pinned `pixal3d.cpp` Metal build and Pixal3D weights, sizes shown first) |

New work this created: **the model switch (ADR-0078)** needs the guardrail, assistant, lyrics and caption checks before
each alias moves, and the Qwen3.5-9B context and memory numbers from G0.

## What I would not do

- Give an agent a shell on the person's computer, or let it turn its own approvals off.
- Train a person's likeness without their word, or offer FLUX.1-dev LoRAs as if they were commercial.
- Show Unsloth Studio's Train page to a non-technical person, or ask them to write a caption, pick a learning rate or
  name a dataset format.
- Link AGPL code into the Apache-2.0 core, or run AI Toolkit on a Mac and call it supported.
- Guess training times; or ship a trained model without its evaluation.
- Let a composition reach the network or the person's files.
- Switch on agent learning by default.
