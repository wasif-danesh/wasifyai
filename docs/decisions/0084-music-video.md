# ADR-0084: Music video: a song in, a plan you can edit, clips, a final cut (our own pipeline on our own parts; Maestro and AutoMV as references, not dependencies)

- **Status:** Proposed (2026-10-20); **the owner answered the nine questions and the four follow-ups on 2026-10-20** and the answers
  are recorded in "Owner's answers" below (the goal is **a fast, honest draft**; research on Maestro and AutoMV is allowed in the spike
  and runs on the Mac only; the lip sync mark is removed everywhere, to be reviewed before release; a revenue-threshold licence such as
  LTX-2.x's may be a default; hosted is a later idea; the feature is Video › Music video, labelled experimental; no Labs switch, owner 2026-10-21). **No question is open.** Nothing
  is built or started. **The roadmap's hold (2026-10-19) on spikes and new features stays:** stage MV0 does not start until bug fixing and the
  simple model picker are done, and **it runs after the WanGP spike W0 (ADR-0085, owner, 2026-10-20)**, which may leave the LTX-2.5 files for MV0 to reuse.
- **Date:** 2026-10-20 (updated the same day, twice, with the owner's answers)
- **Depends on:** ADR-0056 (one engine, two shells), ADR-0059 (ComfyUI image and video engine), ADR-0037 (video product, LTX-Video 2B
  0.9.5), ADR-0044 (lip sync, consent and mark) and ADR-0066 (descriptors, one adapter per runtime, honest states, MuseTalk as the
  lip sync default), ADR-0068 (action catalogue), ADR-0041 (every creation is searchable), ADR-0063 (will it fit), ADR-0077 and
  ADR-0079 (Video Builder, motion graphics: later polish), ADR-0078 (Qwen3.5-9B writes the plan), ADR-0047 (safeguards switch),
  ADR-0061 (how outside code enters), ADR-0081 (design tokens), ADR-0012 (licences).
- **Evidence:** `docs/spikes/music-video-research.md` (sources, dates, what could not be verified). No model was run for this ADR.

## Context

The owner found two GitHub projects, **Maestro** and **AutoMV**, and believes they give the best music videos in 2026. They asked
for the truth about that and a plan to bring the best one into the app. A music video here means: a song (made in the app or added)
goes in, a video of about the song's length comes out, cut to the beat, with the singer's mouth moving where someone sings.
**The owner's goal (2026-10-20) is "a fast, honest draft", not "good enough to show"**: a person should see something quickly,
change it cheaply, and be told truthfully how long each step takes and how good the result is. The design below is weighted for that.

What the research found (details and links in the spike; all read on 2026-10-20):

**AutoMV** (M-A-P with Queen Mary University of London; paper arXiv 2512.12196, December 2025; Apache-2.0 code, 137 stars, 18
commits, last real change 2026-03-29, no release) is a research pipeline: song analysis (structure, vocal stem, timed lyrics, a music
caption), a *screenwriter* and a *director* agent, keyframes, clips, a *verifier* that asks for reshoots, a *character bank*, then
ffmpeg. It is the best-documented open design and the only one with a published human evaluation (30 songs, 12 criteria; human
experts scored it 2.42 out of 5, against 1.06 and 1.45 for two commercial tools and 2.90 for human-made videos; removing timed lyrics,
the character bank or the verifier each lowered the score). **But its working parts are hosted services**: Gemini for the agents and
the verifier, ByteDance's Doubao for images and video, Aliyun storage; the only local option (Wan2.2-S2V-14B lip sync) takes
4 to 5 hours per song on an 80 GB datacentre GPU. It is a script with no review screen. It has been quiet for seven months. The
evaluation was run by the authors, against two baselines, at one date.

**Maestro** (Blizaine/Maestro; 781 stars, 142 forks, 75 open issues, release v3.1.0 on 2026-10-19; a Pinokio app built on Wan2GP)
is a very active local studio whose *Director mode* plans a music video from an audio track (beats, sections, energy, singers), has
an Auto mode and a Manual (review each step) mode, re-runs single clips and rejoins takes. **But its licence is the WanGP
Non-Commercial Evaluation License 1.1**: no integration into another product, no hosted service, no commercial use of the software
(the videos it makes may be used commercially with attribution). **It runs only on NVIDIA GPUs on Windows or Linux**; "macOS is in
development" and the one Mac issue (#149, 2026-09-21) has no maintainer reply. It bundles several non-commercial or
territory-limited models (YuE2, Qwen Image 2.1, MiniMax H3 not usable in the US or EU). I found **no paper, benchmark or independent
review** for it.

**The field.** I found no third open-source song-to-music-video system with human evaluation. A later paper (AgentMV, August 2026)
reports better beat alignment and lower cost than AutoMV on a five-song pilot, with a GPT-4o judge, hosted models and no code
found. Hosted tools (Freebeat, Neural Frames, Kaiber, Revid, OpenArt, HeyGen) are compared only in vendor-written lists. The
video models that take audio are large and CUDA-first: LTX-2.5 (22B; community licence free under USD 10M revenue), Wan2.2-S2V
(Apache-2.0, 80 GB), LongCat-Video-Avatar 1.5 (MIT, two GPUs, singing among its evaluated scenes), Kandinsky 6.0 (MIT, NVIDIA),
MiniMax H3 (territory exclusions). On Apple silicon only LTX-2.x has a port (community MLX, int8 about 75 GB of files for 2.5).

**Our product today** (read for this ADR): the video product makes 2 or 5 second clips with **LTX-Video 2B 0.9.5** (Open RAIL-M, 72 s
and 252 s on the owner's 64 GB Mac, about 13 GB); the voice product makes songs (ACE-Step 1.5 Turbo, MIT, up to about 4 minutes),
separates stems (HTDemucs), writes words down with times (Parakeet), writes lyrics, and does **lip sync with MuseTalk 1.5** (MIT, about
5 s of work per second of video, the head stays still, a visible "AI-generated" mark and the person's consent answers are mandatory;
InfiniteTalk was tried on this Mac and rejected, ADR-0044, and a switch of the default was cancelled by the owner on 2026-10-20);
images use FLUX.2 klein 4B (about 13 s warm); Video Builder (ADR-0077) renders deterministic compositions in under a minute per
minute. Everything is an action (ADR-0068), searchable (ADR-0041), local by default.

## Do the owner's two picks hold up? (plain answer)

- **AutoMV: partly.** It is the best *blueprint* published, with real evidence for which steps matter. It is not the best *output* we
  can have locally, because its quality comes from hosted ByteDance and Google models, it has no review screen, and it is dormant.
  Its score (2.42 of 5) says "best of three automatic tools, clearly below a human-made video", not "excellent".
- **Maestro: no, not to ship.** It is the most active and the most complete local studio, and its Auto/Manual modes are a good user
  interface idea. Its code and bundled models cannot go into the product: a non-commercial licence conflicts with our rule 12 and our
  open-source licences, it needs NVIDIA, and nothing shows its quality is better than its underlying models. **Studying it is fine**:
  its licence allows non-commercial research and evaluation, and the owner confirmed (2026-10-20) that the spike may run and study it.
- **Neither is shown to be "the best in 2026".** No independent test compares them, and no one has compared them with the hosted
  frontier (Seedance 2.5, Veo). The honest statement is: *no open system today turns a song into a good music video on a Mac;
  the best path is to build a thin pipeline on models we can legally and physically run, using AutoMV's design and Maestro's
  interface ideas, and be honest about how good the result is.*

## Options considered

| # | Option | Quality evidence | Control | Length | Speed | Hardware | Licence / commercial | Maturity | Fit for a local-first desktop app |
|---|---|---|---|---|---|---|---|---|---|
| A | **Embed or launch Maestro** | none found | high (Auto/Manual, per-clip redo) | long (60 min planning, 14 s windows) | minutes to hours on a 24 GB NVIDIA card | NVIDIA, Windows/Linux only | **non-commercial (WanGP 1.1)**; bundled YuE2, Qwen Image, MiniMax H3 limits | active, fast moving, 75 open issues | **no**: licence and no Mac |
| B | **Run AutoMV as a sidecar** | best published (paper, 30 songs, human experts) | low (fully automatic script) | full song, shots 3-15 s | ~30 min on hosted APIs; 4-5 h local lip sync on A800 | hosted Gemini, Doubao, Aliyun; local part needs 80 GB CUDA | Apache-2.0 code; hosted terms unread; Qwen-Omni, SongFormer weights **unreviewed** | research code, 18 commits, idle since March | **no**: sends the song and ideas to three companies, a second heavy Python environment (ADR-0062), no review step |
| C | **Our pipeline on our parts, AutoMV as the blueprint (recommended)** | none yet: MV0 must measure it | high: plan and stills reviewed shot by shot | up to the song (we cap at 5 min) | draft: storyboard preview of a whole 3-min song in ~10-15 min and a 30 s excerpt in ~5-10 min; full motion ~1.5-2.5 h; all estimated from measured parts | the Mac we already target; 14 GB peak; one model at a time | all parts already reviewed: MIT, Apache-2.0, Open RAIL-M, CC-BY-4.0 | new code on mature parts | **yes** |
| D | **Hosted only** (Seedance 2.5 API, Freebeat, Neural Frames) | vendor lists only | medium | full song | minutes | none | service terms; per-second cost about USD 0.10-0.30/s of video (resellers; unverified) | mature products | **no as default** (privacy, rule 12); allowed later as an **opt-in provider** |
| E | **Wait for an audio-driven video model** (LTX-2.5 a2v, Kandinsky 6, LongCat Avatar, Wan2.2-S2V) | LTX-2.5 and LongCat have model-card claims, no song benchmark | medium | 5-20 s windows | not measured on a Mac; MLX int8 LTX-2.5 about 9 min per 10 s clip on an M1 Max (README) | 24-80 GB VRAM or 64 GB Mac with 75 GB of files | LTX-2.5 conditional on revenue (may be a default, owner 2026-10-20); others MIT/Apache-2.0 but CUDA | new (Aug-Oct 2026) | **later, as a better clip model inside C**, not as the product |
| F | **Lyric or visualiser video only** (Video Builder) | n/a | high | any | seconds to minutes | CPU | all open | built, experimental | **yes, as the cheapest tier inside C** |

**Research use versus shipping (owner, 2026-10-20).** Options A and B are *rejected as things we ship*; they are not rejected as things
we study. Running Maestro or AutoMV in the throwaway test area of MV0 is allowed (Maestro's licence permits non-commercial research
and evaluation). The line is: **anything we ship (code, a default model, a downloaded file) must have a licence that allows
commercial use, or be badge-only**; nothing from Maestro or AutoMV is copied into the repository, and what is learned enters the product
only as our own design and our own code.

## Decision (proposed; owner's answers applied)

1. **Build option C, in stages, draft first.** The app gets a **Music video** feature that takes a song and produces a video through a
   *reviewable* pipeline: **analyse → plan → stills → (draft) clips → cut**, cheapest step first (decision 4). It uses only models
   already in the app in MV1 to MV3. **We do not ship Maestro or AutoMV as code or as a dependency** (they may be studied in MV0). AutoMV's design (screenwriter and director roles, a character bank, timed
   lyrics driving the shots, a verifier, reshoots) is the blueprint, credited in a `PROVENANCE`-style note (ADR-0061, reference only,
   nothing copied). Maestro is reference for the interface only (Auto and Manual, redo one shot, keep accepted shots when
   re-planning, rejoin takes). The licence of Maestro (for shipping) and the hosted dependencies and idle state of AutoMV are the
   reasons; the quality of neither is shown.
2. **Which product owns it:** the **video product** (`wasifyai-video`) owns the project, plan, shots and final cut, because the
   output is a video. The **voice product** gains one analysis action the video product calls (`music.analyse`: beats, sections,
   energy, timed lyrics from the vocal stem). Products stay thin: the video graph asks for capabilities (`caps.music.analyse`,
   `caps.image.generate`, `caps.video.animate`, `caps.video.lipsync`, `caps.text.*`), never for model names (CLAUDE.md rule 4).
3. **The plan is data the person can read and change** (a JSON document, validated): song facts (length, tempo, sections with start
   and end), a one-paragraph idea, up to six **characters** (name, look, optional reference picture), and a list of **shots**:
   section, start and end second (snapped to beats), what is shown, camera, the lyric line it matches, and a kind:
   *story*, *b-roll*, *performance* (a singer, lip sync) or *words* (lyric text). The chat model (Qwen3.5-9B, ADR-0078) writes it
   in two passes (a screenwriter pass for idea and characters, a director pass per section), as AutoMV does, with the output checked
   by code: shot times must cover the song without gaps, lengths must fit the chosen motion, characters must exist.
4. **Draft first: stills before motion, a short piece before the whole, a low setting before a high one.** Motion is the expensive
   part, so the order of work is the cheapest-first order, and the person can stop after any step:
   - **Storyboard preview (the first pass, whole song).** Each shot gets a **keyframe** (FLUX.2 klein 4B, the person's image model;
     the character's reference picture for consistency where the model supports a reference); the stills are cut on the beats over the
     song with slow camera moves (ffmpeg) into a *preview video*. Estimated about 10 to 15 minutes for a 3-minute song (36 stills at
     about 13 to 27 s each plus the cut; smaller stills may be faster, to be measured). The person reviews it and changes the plan
     before any video model runs.
   - **Draft excerpt.** The person picks one stretch (default: the chorus) of at most 30 seconds and makes it with **draft settings**:
     the small, few-step size the video model already supports (512x320, 15 steps: 13 s for a 25-frame clip, measured), Hold by
     default, Animate only on shots the person marks. Estimated about 5 to 10 minutes. The honest label says "draft".
   - **Make it better.** Chosen shots, or the whole song, are re-made at **final settings** (768x512, 30 steps, 72 s per 2 s clip and
     252 s per 5 s clip, measured), reusing the approved stills; or a Sing shot is added.
   Each shot has one of three **motion levels**, chosen per shot with a default per kind: *Hold* (the still with a slow camera move,
   made by ffmpeg, seconds), *Animate* (image to video with LTX-Video 2B 0.9.5), *Sing* (a performance shot: MuseTalk 1.5 on the
   vocal stem slice and a front-facing character still; about 5 s of work per second). Shots longer than 5 s are split at a beat.
   The time targets above are **targets to verify in MV0**, not promises; the screen shows measured figures once a shot has run.
5. **The cut** is made with ffmpeg (already shipped): cuts on beats, short cross-fades at section changes, the **original song as the
   sound track** (clip sounds are dropped), optional lyric captions from the word times. Opening the cut in Video Builder
   (ADR-0077) to change text and timing is a later stage (MV4). Output H.264 MP4, 720p landscape or 9:16 vertical or square, the shapes
   the video product has.
6. **No new model and no new runtime in MV1 to MV3.** Models: Qwen3.5-9B (plan), FLUX.2 klein 4B (stills), LTX-Video 2B 0.9.5 (animate),
   MuseTalk 1.5 (sing), ACE-Step 1.5 Turbo (a song if the person has none), HTDemucs and Parakeet (stems and timed words), all
   already catalogued with `commercial_use: yes`. **Beat and section analysis** needs a small tool that is not in the app yet; the
   candidates (a librosa-style signal library, a beat tracker such as Beat This!, SongFormer for sections) are **not licence-checked**
   here (SongFormer's weights licence is not stated, so it would be `unreviewed` and never default). **MV0 may install and try any of
   them** (owner, 2026-10-20) in a throwaway environment outside the repository, and reads the licence of everything that could be
   shipped; only a tool chosen for the product comes back to the owner for a yes before it enters the repo's dependencies (CLAUDE.md
   "Ask before").
7. **Better clip models are descriptors, not rewrites (ADR-0066).** **LTX-2.5 (audio-conditioned video) is to be tried in the MV0
   spike** (owner, 2026-10-20). Its licence is recorded as `commercial_use: conditional` (LTX-2.x Community License, 11 Aug 2026: free
   under USD 10M annual entity revenue, affiliates counted; a paid licence above; a derivative rule for fine-tunes). If it is worth it, it
   enters as a `video` descriptor. **The owner decided (2026-10-20) that a model whose licence is free below a revenue threshold may
   be the recommended and shipped default**: "if we can earn enough revenue there is no problem to share", and the rule applies to
   all products (see "A licence policy for revenue-threshold models" below). Moving the clip default from LTX-Video 0.9.5 to LTX-2.x
   would still be an amendment to ADR-0037 (which pinned 0.9.5), made only after the spike shows it works on the Mac. Running it on the Mac needs a new
   runtime adapter (`mlx-video`, a sidecar, community port, 47 to 120 GB of files), which is an amendment to ADR-0066 and the owner's
   approval, not part of this decision. Wan2.2-S2V, LongCat Avatar and InfiniteTalk would be listed "not available here" with the
   reason (80 GB CUDA, two GPUs), as ADR-0066 decision 4 asks, only if a CUDA host is added; MiniMax H3 is not listed (territory
   exclusions).
8. **Local only to start (owner, 2026-10-20).** The song, lyrics, pictures and plan never leave the computer. A hosted provider (a
   Seedance-class video API with the person's own key) is **a later, opt-in idea and in no stage of this plan**; if it is ever taken up
   it is a new `remote` descriptor (ADR-0066 adapter), flagged `leaves_device`, with the cost per second and what is sent shown before
   each run, off until the person turns it on, and it gets its own ADR. The AutoMV-style "Gemini and Doubao" default is rejected.
9. **Honest before big (ADR-0063).** Before **Start** (every step: preview, draft, final) the screen shows, in words: the number of
   shots by motion level, the **time estimate** (from measured speeds per model, as a range with the label "about", corrected from the
   real time after the first shot; "overnight" above 60 minutes), what quality it is ("draft" or "final"), the **disk** used by the project
   and by any model still to download (with sizes), and the **memory fit** per stage (`fits`, `tight`, `too_big`, from `desktop_fit.py`;
   stages run one model at a time, so the peak is the largest stage, about 14 GB today). A stage that cannot fit is not offered. Nothing
   is downloaded without the click that shows size and licence (existing rule).
10. **Long work survives.** The whole video is a **job** with one child job per shot (CLAUDE.md rule 6), kept as the person watches:
    each finished still and clip is saved at once; **cancel keeps finished shots**; restart and **resume** redo only missing shots;
    one music-video job at a time, and it takes the one model slot in turn with the other products (a chat or an image waits or asks).
    Preview, draft and final are the same job with different settings, so a finished still is never made twice.
11. **No automatic judge in v1, then a small one.** MV1 to MV3 rely on the person's review of stills and the final cut plus code checks
    (a clip that fails to decode, is black or frozen, or whose duration is wrong is redone once). MV4 adds a *checker* that uses the
    picture-reading chat model on a keyframe against its prompt ("does this show a woman in a red coat on a rooftop?") and offers a
    redo. This follows AutoMV's ablation (no verifier: 2.42 → 2.08) without inventing a second agent.

## How it fits the product

### Actions (ADR-0068; each with a help file, a `ui` pointer, a row in `docs/contracts/actions.json`, a test through `ActionExecutor`)

| Action | Product | Effect | Flags | `requires` | Notes |
|---|---|---|---|---|---|
| `music.analyse` | voice | `make` | `private` | speech runtime, audio models | song id or file → beats, sections, energy, timed lyrics; stored with the song, not a library item |
| `musicvideo.plan` | video | `make` | `private` | chat model | song + idea + style + shape → a plan (no media made); the person edits it in the screen |
| `musicvideo.make` | video | `make` | `costly`, `needs_consent` only when a *performance* shot uses a face or voice (the ADR-0044 statement) | video engine; lip sync engine only for performance shots | `long=True`; takes an approved plan; makes stills (if not yet), clips and the cut; a handle for `job.status`/`job.cancel` |
| `musicvideo.redo_shot` | video | `make` | `costly` | as above | one shot, one level |
| `musicvideo.edit_plan` | video | `change` | | | apply changes to a plan (assistant and MCP callers); the screen edits the same document |
| `library.delete` (existing) | | `destroy` | | | works on the new kind via `LibraryKind` |

Surfaces: `assistant` and `mcp` for plan/make/redo, so Claude Code or the agent can say "make a music video of this song"; `destroy`
and `needs_consent` always ask a person. UI pointer: **Video › Music video** (new menu item, labelled experimental; no Labs switch).

### The screen and flow for a non-technical person (plain words; shared `packages/ui` screen, tokens from `design/DESIGN.md` only)

1. **Song.** Pick a song from *Your music*, make one, or add a recording. A box shows the words; **Write down the words** fills it from the
   song (and the person can fix them). Pick a shape (landscape, vertical, square).
2. **Idea.** One line ("a lonely robot finds a garden") and a style (chips: Cinematic, Cartoon, Painting, Retro film...). Optional: **Who is
   in it?** None, a character made here, or a picture they add (consent question appears only then).
3. **Plan.** A strip of the song with its sections and cards for each shot (what is shown, how long, which words). The person can
   change a sentence, a length, the motion level, delete, add, or **Try another idea** for one section. Nothing is made yet.
4. **Look.** The stills, a grid. Redo or replace any. This is the cheap place to say "no, not that".
5. **Preview, then draft, then better.** After **Look**, **Preview the whole song** (the storyboard video, about 10 to 15 minutes) is the
   default next button; beside it **Draft a 30 second piece** (the chorus is pre-picked) and, later, **Make it better**. Each shows the
   honest panel (decision 9) first: "42 shots: 30 held, 8 animated, 4 singing. Draft quality. About 8 minutes on this Mac. Uses 600 MB
   of space. Needs the video model (16 GB, not yet downloaded)." **Start**; the person may leave; progress by shot; Cancel keeps what is done.
6. **Result.** The video (labelled Preview, Draft or Final), a strip of shots with **Redo this shot** and **Change the cut**, **Save a
   copy** (to Downloads, as videos do), and **Open in Video Builder** later. A note says plainly that motion is gentle and faces are
   small, because that is what the model does.

Everything is English in v1 (the owner decided v1 is English only) but language-neutral: the song may be in any language the speech-to-text
model knows (25 European ones); the lyrics box is free text; no English assumption in the data.

### Consent and safeguards (faces, voices, songs)

- A **performance shot** (a face that sings) uses the existing ADR-0044 desktop rule: before it is made the person says what the
  picture is (a drawing, themselves, someone who agreed) and whose voice it is (made here, their own, with permission); the answers are
  kept with the video. A character made here from words is an invention and needs no answer; a **picture of a real person** used as a
  character reference (stills or animate) asks the same "who is this" question (ADR-0037 flagged real-person animation for review; this
  reuses its caution). **The consent answers and the safeguards that already apply to lip sync stay unchanged.**
- **No "AI-generated" mark (owner, 2026-10-20): removed everywhere, including lip sync, to be reviewed before release.** This ADR asks
  for no visible mark and no required metadata mark on a music video. Because Accepted ADR-0066 (amendment V5 (a) and (d)) and ADR-0044
  make the lip sync engine draw a visible mark on every frame (`mark: required` in the descriptor, no switch), the owner's decision
  **amends those two**: the amendment, the descriptor change, the server change and their tests are made together, as the first task of
  MV3 or earlier if the owner wants (recorded in the backlog, D13), and ADR-0066 and ADR-0044 get their amendment text at that point,
  not before, so the documents never disagree with the code. Until then Sing shots keep the mark. **The review before release** decides
  whether any marking returns (it is also tied to the terms of service, backlog B4). The consent answers and the safeguards (ADR-0047)
  stay.
- **The song:** the screen says, once, "Only use songs you made here, or that you have the right to use." The video stays on the
  computer; the app shares nothing. No lyric or title of a real artist is added to prompts by the app. ADR-0047 safeguards (text and
  picture moderation, daily limits) apply through `await caps.safeguards_on()` as everywhere (off by default on desktop).
- **Prompt injection from lyrics:** lyrics are data. They reach the chat model inside a plan prompt and cannot call tools; the plan is
  parsed as JSON and validated; an assistant run that planned from lyrics that came from the web carries the taint rule (ADR-0070).

### Searchable creation and library kind (ADR-0041 checklist; part of MV1, not left to the end)

New kind **`music_video`** (the project: song, idea, plan, shots, final cut). Index text: title, idea, characters, each shot's description,
the lyrics (any script). `caps.index_creation("music_video", id, text)` on save and again when the plan or the final cut changes;
`deps.unindex` on delete; an `IndexSource` registered with `registry.add_index_source(...)`; an `ids=` filter on `GET /music-videos`; a card
(poster = the first still, length, shot count) and a filter value in `/creations`; `music_video` added to `CreationKind` and the web types;
a row in `services/api/evals/search/corpus.yaml`. The shots' stills and clips are **not** separate library items; they live inside the
project (so My creations does not fill with fragments); the final MP4 is exportable like a video (`library.export`).

### Deletion

Deleting a music video (`destroy`, always asks) removes the project row, the plan, the stills, the clips, the cut and the poster, and
unindexes it. It asks one question: "Also delete the song?" (default: keep, the song is the person's track). Cancelling a running job keeps
finished shots; **deleting the project while a job runs cancels it first**. Stills uploaded as character references are deleted with the
project unless the person saved them in Pictures.

### Descriptors and runtime adapter

MV1 to MV3 add **no model descriptor and no runtime adapter**. They use the existing `comfyui` (stills, animate), `sidecar` (MuseTalk),
`audiocpp` (music, stems, words) and `llamacpp` (plan) adapters, through capabilities. New code: a `music_video` graph in the video
product (tasks `analyse` call, `plan`, `stills`, `clips`, `cut`), the plan schema in `packages/contracts`, the `MusicVideoStore`
(SQLite on desktop, as `SqliteVideoStore`; Postgres on web later), the estimate function, and the screen. A `video` task descriptor shape
(`task: t2v|i2v|a2v`, `audio_in`, `max_seconds`, `hardware`, `licence`) is **proposed for MV5 only**, when a second clip model exists.

## Licence and commercial-use checks (rule 12)

| Part | Used in | Licence (reviewed) | Commercial use | Default? |
|---|---|---|---|---|
| Qwen3.5-9B | plan, checker | Apache-2.0 (ADR-0078) | yes | yes |
| FLUX.2 klein 4B | stills | Apache-2.0 (ADR-0019) | yes | yes |
| LTX-Video 2B 0.9.5 | animate | Open RAIL-M (ADR-0037); use restrictions pass on to the person (terms, B4 in the backlog) | yes, with restrictions | yes |
| MuseTalk 1.5 and its listed weights | sing | MIT; weights stated free for commercial use (`models.yaml`, reviewed 2026-10-16) | yes | yes (optional download) |
| ACE-Step 1.5 Turbo | a song | MIT | yes | yes |
| HTDemucs, Parakeet | stems, timed words | MIT; CC-BY-4.0 (attribution) | yes | yes |
| ffmpeg (`imageio-ffmpeg`) | cut | as already shipped | yes | yes |
| Beat and section tools | analyse | **not checked** (SongFormer weights: not stated) | **unreviewed** until MV0; MV0 may try them and must read the licence of any it recommends | no |
| LTX-2.5 | **tried in MV0**; optional later | LTX-2.x Community License (11 Aug 2026) | **conditional** (free under USD 10M entity revenue, affiliates counted; derivative rule) | **may be the default** (owner 2026-10-20), subject to the policy below and to the spike showing it works |
| Wan2.2-S2V, LongCat Avatar, Kandinsky 6 | not now | Apache-2.0, MIT, MIT | yes, but CUDA 24-80 GB | not offered on the Mac |
| MiniMax H3 | not offered | territory excludes US, EU, UK, Korea | no for those users | never |
| Maestro code and its bundled models | **studied and run in MV0 as research only** (licence allows non-commercial research and evaluation) | WanGP NC 1.1 | **no** | never shipped; nothing copied |
| AutoMV code | studied and run in MV0 as research; reference for the design | Apache-2.0 (paper says MIT) | yes | nothing copied; credit given |
| Gemini, Doubao | not used | hosted terms (not read) | n/a | off |

### A licence policy for revenue-threshold models (owner, 2026-10-20; applies to all products)

A model whose licence is free below a revenue threshold and needs a paid licence above it (today: LTX-2.x at USD 10M, the Stability
Community Licence) **may be listed, recommended and shipped as a default**. The owner's reasoning: if the project earns enough to
cross the threshold, paying is no problem. What stays the same: models that are **non-commercial** (`no`), **unreviewed**, or limited by
territory or conduct in a way that bars our users (MiniMax H3's exclusion of the US, EU, UK and Korea) are still never the default; the
use restrictions in a licence (LTX-2.x Attachment A, Open RAIL-M) still pass on to the person; a derivative rule (fine-tunes of LTX-2.x
passed to a commercial entity) is checked case by case. What this needs, as follow-up documentation and not in this ADR's scope: the
descriptor field `commercial_use: conditional` gets a second field naming the condition and its threshold, a
revenue-watch note in the backlog (when revenue nears the threshold, buy the licence), and the wording of CLAUDE.md rule 12, ADR-0012
and ADR-0066 decision 4 is updated by the owner's say (backlog D13), because they currently read as "conditional is never chosen".

## Staged plan (each stage ends with tests, a real run on the owner's Mac, docs, `git add`; sizes are working days of one engineer
with Claude)

The order is weighted for the owner's goal, a fast honest draft: the first useful result (a storyboard preview) comes at the end of
MV1, about 7 working days from the start including MV0, and the expensive steps (motion, singing) come after it.

| Stage | What | Size | Done when |
|---|---|---|---|
| **MV0** | **Spike, measured on this Mac, no product code in the repo.** Waits for the roadmap hold to lift (bug fixing and the model picker first). **All installs go in a throwaway area outside the repo** (one folder with its own virtual environments and model folder, e.g. `~/mv0-sandbox`); free disk is checked first. (a) Beat, section and timed-lyric analysis of three songs (one sung in English, one instrumental, one non-English) with candidate tools (librosa, Beat This!, SongFormer, others), reading each licence; (b) Qwen3.5-9B plans the same songs in two passes: JSON validity, coverage of the timeline, a person's read of the shots; (c) FLUX.2 klein stills for 12 shots, the **storyboard preview** timed, and LTX 0.9.5 image-to-video for 6 of them at draft and final settings, timing each and looking at the motion ("little motion" was ADR-0037's note); (d) MuseTalk on a **sung** vocal stem, 20 s; (e) an ffmpeg cut of a 60 s excerpt on beats; (f) **LTX-2.5** via the community MLX port (47 GB or more of files, accepted by the owner): one audio-conditioned 5 s clip, time, memory, whether it sings; (g) **research on Maestro and AutoMV, on this Mac only (owner, 2026-10-20)**: read both sources (Maestro's Director prompts and plan format, AutoMV's `story.json`, character bank and verifier prompts) and watch their demos; run AutoMV's local preprocessing steps (htdemucs, Whisper, SongFormer) where they work on the Mac. Maestro is not run (it needs NVIDIA) and AutoMV is not run end to end (it needs hosted Gemini and Doubao keys), so no keys are used and no money is spent; (h) the owner watches two sample excerpts and says whether this works as a fast honest draft. **At the end the spike deletes its downloads and its environments and reports the disk used** (before, peak, after) in the report | 2 | `docs/spikes/music-video-v0.md` with a measured table (including the preview and draft times against the targets above), licence rows for everything that could ship, what was learned from Maestro and AutoMV, a go / no-go, the disk report, and the owner's verdict. **No-go** ends here and the ADR is amended |
| **MV1** | Analysis action (`music.analyse`), plan schema and `musicvideo.plan`, the screen up to **Look** (song, idea, plan cards, stills), **the storyboard preview of the whole song**, the `music_video` kind with its **search registration and eval row**, help files, catalogue rows | 5 | a song becomes an editable plan, approved stills and a preview video on this Mac within the MV0-measured time; tests with fake caps; `make contracts` clean; the search checklist in full |
| **MV2** | `musicvideo.make`: **draft excerpt** and **final** settings, Hold and Animate, ffmpeg cut, the honest panel with a corrected estimate after the first shot, cancel keeps shots, resume, delete | 6 | a 30-second draft end to end in about the estimated time, then a 60-second final with a real song; killing the app mid-run and resuming redoes only missing shots; the estimate is within 25 % of the real time |
| **MV3** | Sing: performance shots with MuseTalk, consent, the vocal stem slice, the code checks (decode, black, frozen); **first the removal of the lip sync mark** (backlog D13: descriptor, server, tests, ADR-0066 and ADR-0044 amendments), reviewed again before release | 4 | a song with 4 sung close-ups and no mark, consent refused without answers, a safeguards test |
| **MV4** | Polish: lyric captions, picture-reading checker with redo, "Change the cut", open in Video Builder, vertical shape, docs | 5 | the owner makes 3 videos from their own songs and says whether the drafts were fast and honest enough |
| **MV5** | *Optional, after MV0 shows it works:* a better clip model (LTX-2.5 via an `mlx-video` sidecar, `conditional`, allowed as default by the owner), with its ADR amendments (ADR-0066 runtime, ADR-0037 pin). A hosted provider is not a stage (a later idea, own ADR) | 5 | measured gain over MV2 clips on the same shots; the licence text approved |

Total to a usable v1 (MV1 to MV4): about 20 working days. MV0 alone is the cheap way to find out whether it is worth it.

## Consequences

- The app gains a long-form, multi-step creation for the first time in the video product (a project with children), and the first
  feature whose time is measured in hours; the cancel/resume/estimate machinery built for it helps audiobooks and dubbing.
- The result on a Mac will be **gentler than hosted tools**: mostly held stills with camera moves, some short animated shots, sung
  close-ups with a still head. The page and the help file say so. Anything better needs a bigger model (MV5) or, one day, a hosted
  opt-in.
- A new dependency (beat/section analysis) is possible; MV0 tries candidates in a throwaway area and the choice is asked for before it
  enters the repo.
- The owner's two named projects are not shipped as dependencies, but they are studied (MV0). If the owner has an NVIDIA PC and wants
  Maestro for their own use, it can run there independently: ADR-0063 lets the app detect a running tool, but this ADR does not
  integrate it.

## Risks

- **Quality may disappoint.** LTX 0.9.5 image-to-video was "faithful to the picture, little motion"; MuseTalk keeps the head still and
  has never been tested on singing. MV0 exists to find out before 20 days are spent. Mitigation: the goal is an honest draft, the Hold
  level is acceptable on its own for a lyric-style video, and drafts are labelled; the owner judges the sample.
- **The draft times are estimates.** The 10 to 15 minute preview and 5 to 10 minute excerpt come from measured parts (13 s per
  1024 px still, 13 s for a small 25-frame clip) and are not yet measured end to end; MV0 does that.
- **Time.** 1.5 to 2.5 hours per 3-minute song on this Mac, estimated, not measured. Smaller Macs are slower or cannot fit (16 and
  32 GB are unmeasured everywhere in this repo).
- **Character consistency** across shots is the weakest part of image-based pipelines (AutoMV's ablation shows it matters). Mitigation:
  few characters, reference pictures, same seed family, and the person's review of stills.
- **Licence drift:** LTX versions, MiniMax and WanGP change terms; the pin and the `commercial_use` field are the guard. A revenue-threshold default (LTX-2.x) needs someone to watch revenue against the threshold.
- **Real people and songs:** deepfake and copyright risk; consent answers, the safeguards and the local-only rule reduce it (the owner
  removed the visible mark, to be reviewed before release); terms of service are still missing (backlog B4) and block public release of video
  features.
- **Throwaway installs:** the spike downloads 47 GB or more and installs many libraries; a leftover would clutter the Mac. Mitigation: one
  folder outside the repo, deleted at the end, with a disk report.
- **Idle upstream:** if AutoMV or Maestro move fast, the references go stale. Harmless: nothing depends on them.
- **The roadmap hold:** MV0 must wait until bug fixing and the model picker are done.

## Not decided here

A new video model runtime on the Mac (MLX sidecar); a hosted provider (a later, opt-in idea); audio-driven full-body singing or dance; a web version (the
web would need the cloud GPU host, B5); non-English interface text; editing video clips beyond redo-one-shot; selling or sharing videos.

## Owner's answers (2026-10-20)

| # | Question | Answer (decided) | Where it landed |
|---|---|---|---|
| 1 | Which "Maestro"? | **Blizaine/Maestro**, confirmed | Context, spike notes |
| 2 | Good enough to show, or a fast honest draft? | **A fast, honest draft** | Context; decision 4 (preview, draft, better); decision 9; the stage order |
| 3 | May a conditional-licence model be the recommended clip model? | Maestro's non-commercial licence is **not an issue for research**: MV0 may run and study Maestro and AutoMV. **Anything we ship must be commercial-OK or badge-only.** **LTX-2.5 is to be tried in the spike**. Follow-up (same day): **yes, a revenue-threshold model may be the shipped default, for all products** | Options note; decisions 1, 7; licence table; MV0 (f), (g) |
| 4 | Hosted opt-in path? | **Local only to start**; hosted is a later, opt-in idea and in no stage | Decision 8; MV5; Not decided here |
| 5 | A visible "AI-generated" mark on the whole video? | **No mark needed**; the consent and safeguards for faces and voices that already apply to lip sync stay. Follow-up (same day): **the lip sync mark is removed everywhere**, to be reviewed before release | Consent section; MV3; backlog D13 |
| 6 | A download of 47 GB or more for the spike? | **Fine**, because it can be deleted afterwards; the spike deletes its downloads and environments at the end and reports the disk used | MV0 |
| 7 | Does the hold stay? | **Yes**: until the bug-fixing stage and the model picker are done | Status; roadmap; MV0 |
| 8 | Menu name and place | **Video › Music video**, labelled experimental | Actions; screen section |
| 9 | May the spike install beat/section libraries? | **Yes, anything it needs**, with free disk; check the licence of anything that could be shipped; installs in a throwaway environment outside the repo | Decision 6; MV0 |

## Follow-up answers (owner, 2026-10-20)

| # | Question | Answer (decided) | Where it landed |
|---|---|---|---|
| F1 | The mark on sung shots | **Removed everywhere** (lip sync too); reviewed before release | Consent section; MV3; backlog D13 |
| F2 | What the research run may use | **Only the Mac**: no NVIDIA machine, no hosted keys, no spend | MV0 (g) |
| F3 | May a conditional model ever be the shipped default? | **Yes.** "If we can earn enough revenue there is no problem to share." **It applies to all products** | Decision 7; the licence policy section; backlog D13 |
| F4 | Is "draft" defined right? | **Yes**: storyboard preview of the whole song, a 30 s excerpt at draft settings, then "make it better" | Decision 4 |

## Open questions for the owner

None. What the spike will decide with measurements (not owner questions): the draft times, whether LTX 0.9.5 motion and MuseTalk singing
are acceptable, which beat and section tool to use, and whether LTX-2.5 on the Mac is worth a new runtime adapter.
