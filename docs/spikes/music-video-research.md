# Music video: research notes (ADR-0084)

Date: 2026-10-20. Desk research only: web pages, GitHub and Hugging Face pages, papers. **Nothing was installed, downloaded or
run**, and no model was tried. Every number below is what a page or paper says, not something we measured, unless the row says
"ours". Repository numbers (stars, dates) were read from `api.github.com` and repository pages through a page reader on
2026-10-20; they move daily. Where a source is a vendor's own page, a listicle or a reseller, it is marked **(secondary)**.
Anything I could not confirm is marked **UNVERIFIED**.

The dev machine for "ours" figures is the owner's MacBook Pro, Apple M5 Pro, 64 GB (`docs/spikes/voice-v0.md`).

## 1. Which projects are "Maestro" and "AutoMV"

### 1.1 AutoMV

| | |
|---|---|
| What | A "training-free, multi-agent system" that makes a full-length music video from a song. Research code that accompanies a paper. |
| Paper | *AutoMV: An Automatic Multi-Agent System for Music Video Generation*, arXiv 2512.12196, submitted 13 Dec 2025 (v1; CC BY 4.0). https://arxiv.org/abs/2512.12196, HTML https://arxiv.org/html/2512.12196v1 |
| Authors | Xiaoxuan Tang, Xinping Lei, Chaoran Zhu (equal contribution), Yinghao Ma, Emmanouil Benetos, Yang Liu, Jiaheng Liu and others. M-A-P lab with Queen Mary University of London (C4DM), BUPT, Nanjing University, HKUST, Manchester. |
| Repository | https://github.com/multimodal-art-projection/AutoMV. Created 2025-12-09. **137 stars, 27 forks, 3 open issues, 18 commits.** Last pushed 2026-03-29 ("Remove hardcode key from llm_judge.py"); before that 2026-01-04. **No release, no tag.** Read 2026-10-20. |
| Issues | #1 "Release AutoMV-Bench dataset on Hugging Face" (2025-12-21, by a Hugging Face staff member), #2 "show some demos" (2026-01-05), #3 an unrelated message (2026-06-14). None closed. No question about local models or Mac. |
| Project page | https://m-a-p.ai/AutoMV/ . Demos ("Lazy Song", "Golden Hour", "Believer", "APT."), AutoMV-Bench (the page says 60 songs; the paper says 30). No news section. |
| University news | https://c4dm.eecs.qmul.ac.uk/news/2026-01-06.Reimagining-music-videos-with-AI/ (6 Jan 2026): "the first open-source AI system capable of generating complete music videos directly from full-length songs"; cost "roughly the cost of an API call". |
| Code licence | **Apache-2.0** in the repository and on the project page. **The paper's ethics section says MIT** (a commit of 2025-12-16 is titled "update bibtex and license"). Treat as Apache-2.0; the discrepancy is noted, and it does not matter if we copy no code. |

**Pipeline (four stages; paper and README agree):**

1. *Music preprocessing.* SongFormer (structure: intro, verse, chorus...), htdemucs (vocal and accompaniment stems), Whisper
   (lyrics with times; the paper adds a Gemini pass that corrects them with internet search), Qwen2.5-Omni-7B (music caption:
   genre, mood, instruments, vocalist). Beat tracking via the structure tool.
2. *Screenwriter and Director agents.* Screenwriter (Gemini 2.5) writes the story, scene summaries and a **character bank**;
   Director (Doubao) writes shot-level scripts, camera instructions and keyframe prompts.
3. *Keyframes then clips.* Keyframes by the Doubao image API; clips by the **Doubao video API** (general shots, 3 to 8 s
   sub-clips merged up to 15 s) and, for shots where someone sings, a lip-sync model fed the vocal stem: the paper says
   "Qwen-Wan2.2"; the README names **Wan2.2-S2V-14B** as the optional local lip-sync model and a hosted "jimeng" call otherwise.
4. *Verifier (Gemini 2.5 Pro)* checks physical realism, instruction following and character consistency and asks for reshoots;
   clips are merged by ffmpeg with the original song.

**Inputs and outputs.** In: `result/<name>/<name>.mp3` or `.wav` (name: English letters, digits, underscore). Run
`python -m picture_generate.main` (prompts and first frames) then `python generate_pipeline.py`. Out: `mv_<name>.mp4`, `story.json`
(the storyboard), `label.json` (character bank), per-clip files. **No review step, no UI**: it is a script run. No stated maximum
song length ("full-length"); shots are 3 to 15 s. Lyrics are found by Whisper; a lyrics file is not an input.

**Hardware and services (what it really needs).** The README gives no general requirements. Environment variables name
`GEMINI_API_KEY`, `DOUBAO_API_KEY`, Aliyun OSS keys (bucket) and Huoshan (Volcano Engine) keys, so the **default path is hosted
APIs** from Google and ByteDance plus Alibaba cloud storage. The paper ran "a single node with eight NVIDIA A800 80 GB GPUs".
The optional local lip-sync path (Wan2.2-S2V-14B) is documented as **4 to 5 hours per song on an A800** and needs a separate conda
environment (Python 3.10). Nothing says it runs on Apple silicon; the stack (SongFormer tested on Ubuntu 22.04 and an NVIDIA L40,
Wan2.2-S2V single-GPU command wanting 80 GB) is CUDA. The README names no image model for keyframes (the paper says Doubao).

**Cost and time (authors' figures):** USD 10 to 20 per song and about 30 minutes or more (on the 8 x A800 node, mostly API).

**Quality evidence (all from the authors, on their own benchmark):**

- AutoMV-Bench: 30 professionally released songs (English, Chinese, Japanese, Korean), 12 criteria in 4 groups (Technical 20 %,
  Post-production 20 %, Content 30 %, Art 30 %), scored 1 to 5 by Gemini-class judges and by human experts (musicians and
  music-industry people).
- Human expert overall: **AutoMV 2.42**, Revid.ai-base 1.06, OpenArt story mode 1.45, **human-made music videos 2.90**.
  Beat/audio-visual alignment (ImageBind score): AutoMV 24.4, Revid 19.9, OpenArt 18.5, humans 24.1.
- Ablations (human overall): no lyrics and timestamps 1.81, no character bank 1.84, no verifier 2.08, full 2.42. This is the
  most useful finding for us: **timed lyrics, a character bank and a verifier each matter.**
- Honest limits the authors list: physically implausible motion, off-beat dancing, distorted on-screen text, lip-sync mismatch
  without source separation; LLM judges do not replace experts; character consistency over longer sequences is future work.
  Sub-scores for AutoMV from human experts: Technical 2.94, Post 2.05, Content 2.62, Art 2.12 (out of 5), so **"best" means best
  of three automatic systems, and still below a 3 out of 5**.
- The two baselines are commercial products at one date (late 2025). No open-source system was compared. The project page's
  quality line ("2.9/5 human baselines to 2.4/5") is garbled in places; use the paper's table.
- The authors' benchmark release is URLs of the original videos only (no audio), and issue #1 asks for the dataset to be put on
  Hugging Face; the repository's `evaluate` and `result` folders are excluded from the repo.

**A later challenger.** *AgentMV* (arXiv 2605.10723v2, 16 Aug 2026, Sichuan University; https://arxiv.org/html/2605.10723):
five agents sharing a "Structured Persistent State"; Whisper, SongFormer, Qwen3-Omni, Qwen-Plus, Seedream images, Seedance video;
5-second clips at 1080p. On a **five-song pilot** it reports beat alignment 0.67 against AutoMV 0.10, cost USD 2.19 against 3.25
per song, and a GPT-4o judge; AutoMV keeps the higher CLIP score. **No code or licence mentioned; no human study; hosted
backends.** Treat as a signal that AutoMV is not unchallenged, not as proof.

### 1.2 Maestro

"Maestro" is **ambiguous**; two repositories with that name exist and no paper called Maestro for music video was found.

| | Blizaine/Maestro (the original) | fgilde/Maestro (a fork) |
|---|---|---|
| What | "A local, all-in-one studio for AI video, image, and music generation"; **Director mode** plans music videos and short films. Built on the WanGP pipeline (Wan2GP, by deepbeepmeep) and installed through **Pinokio**. | A fork of the original |
| Stars, forks | **781 stars, 142 forks, 75 open issues** (and ~19 PRs), 347 commits | 4 stars, 1 fork |
| Created, last push | created 2026-07-08; **last pushed 2026-10-20** | |
| Latest release | **v3.1.0, 2026-10-19** (MOSS Image 5B, H3 community checkpoint, Viggle fixes) | v1.6.5 (2026-08-08) shown |
| Licence | **"Maestro License Notice" = WanGP Non-Commercial Evaluation License 1.1** (GitHub shows "Other"/NOASSERTION). https://raw.githubusercontent.com/Blizaine/Maestro/main/LICENSE | same |

Blizaine/Maestro is the one the owner means (https://github.com/Blizaine/Maestro); **confirmed by the owner on 2026-10-20**.

**Licence terms (quoted from the notice, summarised):** free for non-commercial use, copying, modification and redistribution
(personal projects, research, education, evaluation). **Not allowed:** selling or sublicensing Maestro or derivatives, offering
them as a paid product, hosted service, API, headless deployment or integration, or providing cloud, backend, embedded or
automated services that end users access, invoke or pay for. Any commercial use of the software needs a separate licence from
the WanGP licensor (deepbeepmeep@yahoo.com). **Outputs** (images, video, audio) may be used for any purpose including selling,
if made with a properly licensed copy and with a notice that WanGP was used and a link. Models and libraries carry their own
licences. The README flags: Qwen Image 2.1 research/evaluation only; **YuE2 non-commercial**; seed-vc **GPL-3.0**; IndexTTS2
under a bilibili licence; **MiniMax H3 weights subject to MiniMax terms "plus any authorization or waiver needed for your
location"**. Many other bundled models are not mentioned (unreviewed).

**Director mode (README):** input an audio track *or* a written story. A local LLM (Gemma 4 4B by default, or Qwen3.6 27B; external
OpenAI/Anthropic-compatible endpoints "experimental") reads BPM, sections and energy, plans shots on downbeats, can transcribe
and diarize singers. **Auto mode** runs everything (analyse, plan, images, clips, combine); **Manual mode** lets you review each
step. Director v2: three passes (screenplay, shot breakdown, per-model prompt polish). "Use lyrics to guide visuals" is **off by
default** for new projects. Lip-sync assignment is on in both settings (LongCat Avatar windows of ~5.8 s with 13 frames overlap).
Pipeline dashboard can re-run one clip; "rejoin current takes" makes a new final cut and keeps earlier ones; repairs keep accepted
shots. Models named: video MiniMax H3 (several), LTX-2.3/2.5, Wan 2.1/2.2, Hunyuan, SCAIL-2, LongCat, Viggle; image Flux 2/3 Klein,
Krea 2, MOSS Image 5B, Qwen Image; audio MiniMax-Music3, ACE-Step, YuE2, Kugelaudio, Qwen3 TTS, MMAudio. H3 clips up to 14.4 s per
window (30 s experimental); long-form planning up to 60 minutes.

**Hardware:** Windows 10/11 or Linux with an NVIDIA GPU. README: "AMD GPUs and macOS are not currently supported", because the
pipeline "depends on CUDA and several NVIDIA-only kernels"; "MacOS support is in development". Minimum NVIDIA 6 GB VRAM, 16 GB
RAM, 150 GB disk; recommended RTX 3090/4090/5090 24 GB+; downloads 50 to 100 GB typical, over 300 GB for everything. Tested:
8 GB VRAM + 32 GB RAM gives about 10 s clips at 720p.

**Mac status (issue #149, opened 2026-09-21, still open, no maintainer reply):** a user points out that MLX ports of LTX-2,
MiniMax H3 and Wan 2.2 now exist, so the work is a backend abstraction; the installer (`torch.js`) refuses non-Windows/Linux. The
same user measured **Wan 2.2 TI2V-5B, 8-bit, on an M5 with 32 GB: 704x1280, 49 frames (about 2 s), 40 steps = 27 min 20 s**, peak
26.3 GB (about 13 minutes of compute per second of footage); an M1 Max GGUF Wan 2.2 run took about 82 minutes for 2 s. MiniMax H3
"needs 128 GB or more" on a Mac in the issue's table.

**Quality evidence for Maestro: none found.** No paper, benchmark, human study or independent review; only the README, release
notes and a Pinokio catalogue page. Its quality is the quality of the models it drives (H3, LTX, Wan) and of a local 4B LLM
planner. (I did not watch its demos.)

## 2. The wider field (2026)

### 2.1 Open music-video pipelines and papers

| Project | What | Evidence | Code / licence | Notes |
|---|---|---|---|---|
| AutoMV | see above | Own 30-song benchmark, human experts | Apache-2.0 (repo) | hosted APIs by default |
| AgentMV (arXiv 2605.10723) | agents with shared state, budget-aware, motif reuse | 5-song pilot, GPT-4o judge | **none found** | hosted Seedance/Seedream |
| Maestro Director | see above | none | NC licence | CUDA only |
| Video-to-music papers (MuVi, VidMusician, V2M-Zero, JenBridge) | the reverse direction (video in, music out) | papers | various | not music video; ignore |
| Encore (arXiv 2609.04249, SIGGRAPH Asia 2026) | "infinite-length" joint audio-video, audio-to-video chunks | paper | code link github.com/shaohua-pan/Encore; weights/licence **UNVERIFIED** | music/singing not mentioned |

I found **no third open-source song-to-music-video system** with a human evaluation. The hosted products are listed in 2.3.

### 2.2 Open video models that take audio (the "backbones")

| Model | Size / date | Audio use | Licence (as read) | Hardware | Mac? |
|---|---|---|---|---|---|
| **LTX-2.5** (Lightricks; LTX-2 paper arXiv 2601.03233) | 22B transformer + Gemma 4 12B text encoder; HF card created 2026-07-23, updated 2026-10-11 | joint audio and video generation; `A2VidPipelineTwoStage` "audio-to-video conditioned on an input audio file"; DubIt pipeline | **LTX-2.x Community License (11 Aug 2026)**: free commercial use for entities under **USD 10M** annual revenue (affiliates counted); at or above it, paid licence; commercial-entity free use only for non-revenue purposes; derivatives (fine-tunes) passed to a commercial entity need a paid licence; outputs belong to the user; hosting for third parties allowed with use restrictions passed on. https://raw.githubusercontent.com/Lightricks/LTX-2/main/LICENSE-2_x ; HF card https://huggingface.co/Lightricks/LTX-2.5 (gated) | CUDA reference; no VRAM figure; ~66 GiB of downloads for the distilled set | **Community MLX port** `dgrauet/ltx-2-mlx` (MIT; 133 stars; supports 2.3 and 2.5; **a2v works on the dev model + CFG, distilled a2v experimental**). Packs: 2.5 bf16 ~120 GB, int8 ~75 GB, int4 ~47 GB; int8 wants 32 GB+ (16 GB with a low-RAM flag), 8 s clips want 64 GB+. One timing: M1 Max, 2.5 int8 distilled i2v 576x1024x241 frames (10 s) 563 s. |
| LTX-2.3 | 22B; March 2026 | same | LTX-2 Community License (5 Jan 2026), same revenue rule | | MLX ports (several community) |
| **Wan2.2-S2V-14B** | 16.3B; Sept 2025 | audio-driven (speech/song) image+audio to video, 480P/720P | **Apache-2.0** (HF tag) | official single GPU **80 GB VRAM**; AMD MI300X tutorial; AutoMV: 4 to 5 h per song on A800 | no (our own result: a neighbouring Wan 2.2 5B was broken on MPS in 2025, ADR-0037; community now reports Wan 2.2 TI2V-5B working in MLX at 13 min per second) |
| **InfiniteTalk** (MeiGen) | on Wan2.1 14B | audio-driven talking/singing video, image or video in, up to ~1 min | Apache-2.0 (ADR-0044, read 2026-10-09) | CUDA; **we measured it on the Mac: ~4 min of compute per second of video, 256 px, out of memory beyond one window; removed** (ADR-0044) | no |
| **LongCat-Video-Avatar 1.5** (Meituan; arXiv 2605.26486) | 2026-05 | audio-driven avatar, single and multi stream, Whisper-Large encoder, 8-step distilled; **singing is one of six evaluated scenarios**; human study 508 pairs, 770 raters, 13,240 ratings (scores only in a figure) | **MIT** (HF card) | CUDA 12.4 + FlashAttention 2; examples on **2 GPUs**; unverified ~75 GB | no |
| Kandinsky 6.0 Video (Sber/Kandinsky Lab) | Lite 3B, Pro 29B; open 2026-10-06 | joint 44 kHz audio and lip-sync; text/image conditioning only (no audio-conditioned mode seen) | **MIT** (GitHub licence link; secondary sites agree) | NVIDIA GPU (RTX 4090 to H100 in its table) | no (not mentioned) |
| **MiniMax H3** | 33B; weights 2026-08 | joint audio-video, reference-to-audio-video, audio-to-audio-video tags | **MiniMax community licence: territory excludes the EU, UK, South Korea and the US**; free for organisations under USD 20M; name must be displayed; may not be used to improve other models (secondary: https://rits.shanghai.nyu.edu/ai/minimax-ships-h3-weights-with-the-us-and-eu-excluded/ ; **UNVERIFIED against the model card**, which says only `license: other`) | big; "128 GB+" on a Mac per Maestro issue #149 | MLX port exists |
| Wan 2.5/2.6/2.7/3.0 | | | **No open weights found**; sites claiming "Wan 2.7 Apache-2.0" appear to be SEO pages (https://howaiworks.ai/blog/alibaba-wan-open-weights-stopped-at-2-2 , secondary). Last open: Wan 2.2 (Apache-2.0). | | |
| HunyuanVideo 1.5 / SkyReels-V3 | | listed as audio-driven (secondary) | **UNVERIFIED** (Tencent's licence has territory limits in earlier versions) | | |
| **LTX-Video 2B 0.9.5** (ours) | 2B; March 2025 | none | Open RAIL-M, commercial use allowed with use restrictions passed on | **ours: runs on the Mac**, 5 s clip 252 s, 2 s 72 s, ~13 GB peak | yes |
| **MuseTalk 1.5** (ours) | | mouth redraw from audio on a still face | MIT, weights free for commercial use | **ours: 5 s of work per second of video, 11.8 GB**; head and eyes stay still; trained on speech, singing **not tested** | yes |

Music side (already in the product): ACE-Step 1.5 Turbo (MIT) makes songs up to ~4 minutes; MiniMax-Music3 and YuE2 are named
by Maestro (YuE2 non-commercial); HTDemucs, Parakeet, Kokoro exist in the product.

### 2.3 Hosted tools (all secondary evidence)

| Tool | Claim | Source |
|---|---|---|
| Freebeat | song-to-video, dance/lyric/performance modes, uses Seedance and Veo; "lip-sync accuracy about 90 %" (its own blog) | https://www.unite.ai/best-ai-music-video-generators/ (updated 2026-07-17), https://freebeat.ai/articles/ (vendor) |
| Neural Frames | deepest audio reactivity, 8-stem analysis, many third-party video models; free to USD 199 a month | unite.ai |
| Kaiber | stylised, Beat Sync (not on cheapest plan), short clips | unite.ai |
| Revid, OpenArt story, HeyGen, One More Shot, TwoShot, Plazmapunk | various; Revid and OpenArt are AutoMV's two baselines | unite.ai, AutoMV paper |
| Seedance 2.5 (ByteDance) API | accepts reference audio (up to 10 files, 30 s combined, per one source); about **USD 0.10 per second at 480p and 0.23 at 720p** (BytePlus), resellers USD 0.13 to 0.47 | https://openrouter.ai/bytedance/seedance-2.5 and https://apiframe.ai/models/seedance-2.5/pricing (resellers, **UNVERIFIED** against ByteDance's price page) |
| Veo 3.x | no price or music-video evidence found | |

**Independent comparison of these tools: none found.** Every ranking I saw is a listicle, several by Freebeat itself.

## 3. Licence and commercial-use table for what the two projects pull in

(Our rule: open source first; commercial use must be allowed before a model is added; non-commercial = badge only, never default.)

| Component | Used by | Licence as read | Commercial use | Evidence |
|---|---|---|---|---|
| Maestro code | Maestro | WanGP Non-Commercial Evaluation License 1.1 | **no** (no integration, no hosted use; outputs OK with attribution) | LICENSE above |
| Wan2GP / WanGP | Maestro's base | same family | **no** without separate licence | same |
| AutoMV code | AutoMV | Apache-2.0 (repo); MIT (paper) | yes | repo, paper |
| SongFormer | both-ish (AutoMV, AgentMV) | code CC-BY-4.0; **weights licence not stated** | **unreviewed** | https://github.com/ASLP-lab/SongFormer |
| htdemucs | AutoMV; ours (HTDemucs in the app) | MIT | yes | `docs/desktop-profile.md` V4 |
| Whisper | AutoMV | MIT | yes | |
| Qwen2.5-Omni-7B | AutoMV | **UNVERIFIED** (believed Apache-2.0) | unreviewed | |
| Gemini (agents, verifier, judge) | AutoMV | hosted service, Google terms (not read) | service terms | |
| Doubao image/video (ByteDance) | AutoMV | hosted service, ByteDance terms (not read) | service terms | |
| Aliyun OSS, Huoshan | AutoMV | hosted | service terms | |
| Wan2.2-S2V-14B | AutoMV (local lip sync) | Apache-2.0 | yes | HF tag |
| ImageBind | AutoMV (metric only) | not checked | | |
| MiniMax H3 | Maestro | MiniMax community licence, territory excludes US/EU/UK/KR | **conditional, and not for the owner's likely users** | secondary + Maestro README |
| LTX-2.3 / 2.5 | Maestro, AutoMV-like use | LTX-2.x Community License | **conditional** (under USD 10M entity revenue; derivative rule) | licence file |
| Qwen Image 2.1 | Maestro | research/evaluation | no | Maestro README |
| YuE2 | Maestro | non-commercial | no | Maestro README |
| seed-vc | Maestro | GPL-3.0 | copyleft, cloned at install | Maestro README |
| ACE-Step | Maestro; ours | MIT (ours: reviewed 2026-10-16) | yes | `products/wasifyai-voice/models.yaml` |
| LongCat Avatar | Maestro | MIT | yes | HF card |

## 4. Our measured numbers that matter (from the repo)

- LTX-Video 2B 0.9.5, M-series 64 GB, half precision: 2 s clip (49 frames, 768x512, 30 steps) **72 s**; 5 s clip (121 frames) **252 s**;
  peak ~13 GB (`docs/desktop-profile.md`, "Video (stage V8)"; ADR-0037 amendment). Image to video was timed at 2 s only (58 s through
  the app, model load included); ADR-0037 found "faithful to the picture, little motion" and needs image strength 1.0.
- MuseTalk 1.5: ~5 s of work per second of video, 11.8 GB peak, head still, 5 minute voice limit, visible mark mandatory.
- FLUX.2 klein 4B (Apache-2.0): ~13 s warm, ~27 s cold, per 1024x1024 image at 4 steps (`docs/decisions/0059`).
- ACE-Step 1.5 Turbo on audio.cpp/Metal: songs up to about 4 minutes (`docs/desktop-profile.md`, Music).
- Video Builder render (HyperFrames): 60 s composition at 720p30 in 41 to 49 s, byte-identical output (`docs/spikes/video-builder-v0.md`).
- Switching the one resident model costs 2 to 4 s for audio models; image/video models load in seconds to a minute.

A rough, **not measured** cost model for a 3-minute song with 36 shots of 5 s: all shots animated by LTX 0.9.5 = 36 x ~250 s = **~2.5 h**;
12 animated + 24 held stills with camera moves = ~50 min of clips; keyframes 36 x ~15 s = ~10 min; 4 sung close-ups of 20 s with MuseTalk
= ~7 min; cut with ffmpeg = a few minutes. Overnight for the full-motion version; under 1.5 h for the "mostly stills" version.

## 5. Not verified / could not read

- Maestro's demos and any independent quality opinion; its issue list beyond #149; whether it has a Mac port in a branch.
- AutoMV's actual output quality (I did not run or watch it); Qwen2.5-Omni-7B licence; whether the repo runs without Doubao/Gemini keys
  (nothing says it does); ImageBind licence.
- Licence text of MiniMax H3 from the model card (gated or summarised); HunyuanVideo-Avatar and SkyReels-V3 licences; Encore weights.
- Any speed of LTX-2.5 on this Mac (the one number is an M1 Max, int8 distilled, 10 s clip, 563 s, from a README).
- Seedance 2.5 prices from ByteDance directly; Freebeat/Neural Frames quality; Veo.
- Whether MuseTalk lip sync is acceptable on sung vocals (we have only tested speech).
- Whether the star counts and dates came through the page reader correctly (they were read through a summarising tool, not by hand).

## 6. Owner's answers (2026-10-20) and what they change for research

Recorded in full in ADR-0084 ("Owner's answers"). For these notes:

- **Research versus shipping.** The owner confirmed Maestro's non-commercial licence is not an obstacle to *studying* it in the MV0 spike
  (the WanGP notice allows non-commercial research and evaluation; I read it as covering a spike whose output is a report, which the owner
  has now decided). The rule for anything that could be **shipped** (code, a default model, a downloaded file) is unchanged: commercial
  use allowed, or badge-only. So the licence tables above stay as they are; they describe what can ship.
- **What the spike may run (follow-up answer: the Mac only).** Maestro needs an NVIDIA GPU (Windows or Linux), so it is only read and its
  demos watched; no NVIDIA machine is used. AutoMV end to end needs Gemini and Doubao API keys (about USD 10 to 20 per song, per its
  authors); no keys are used and no money spent; its local preprocessing (htdemucs, Whisper, SongFormer) may run on the Mac. LTX-2.5 through the community MLX port is to be tried (47 GB or more
  of files accepted). Anything else may be installed if disk allows, in a throwaway environment outside the repo, deleted at the end with a
  disk report.
- **Goal.** A fast, honest draft: the research above is re-read for speed. Relevant figures for the draft design: FLUX.2 klein 4B about 13 s
  warm per 1024 px still; LTX 0.9.5 small clip (512x320, 15 steps, 25 frames) 13 s, full size 2 s clip 72 s and 5 s clip 252 s; AutoMV's own
  runtime is about 30 minutes on hosted APIs; Maestro's Auto mode runs the whole chain (hours on a 24 GB NVIDIA card, not measured by us).
- **Hosted:** local only to start; the Seedance 2.5 price notes in section 2.3 stay as background for a possible later opt-in idea.
- **No visible "AI-generated" mark:** removed everywhere including lip sync (follow-up answer), to be reviewed before release; it amends
  ADR-0066/0044 when the code changes (backlog D13).
- **Licences with a revenue threshold** (LTX-2.x at USD 10M, Stability Community) may be shipped defaults, for all products (follow-up
  answer). Section 3's "conditional" rows read accordingly; non-commercial, unreviewed and territory-barred models are still never defaults.

## 7. Sources

AutoMV paper https://arxiv.org/abs/2512.12196 , https://arxiv.org/html/2512.12196v1 ; repo https://github.com/multimodal-art-projection/AutoMV
(API read 2026-10-20) ; issues https://github.com/multimodal-art-projection/AutoMV/issues ; project page https://m-a-p.ai/AutoMV/ ;
news https://c4dm.eecs.qmul.ac.uk/news/2026-01-06.Reimagining-music-videos-with-AI/ ; AgentMV https://arxiv.org/html/2605.10723 ;
Maestro https://github.com/Blizaine/Maestro , LICENSE https://raw.githubusercontent.com/Blizaine/Maestro/main/LICENSE , README
https://raw.githubusercontent.com/Blizaine/Maestro/main/README.md , issue https://github.com/Blizaine/Maestro/issues/149 , fork
https://github.com/fgilde/Maestro ; LTX-2 https://github.com/Lightricks/LTX-2 , https://huggingface.co/Lightricks/LTX-2.5 , licence
https://raw.githubusercontent.com/Lightricks/LTX-2/main/LICENSE-2_x ; MLX port https://github.com/dgrauet/ltx-2-mlx , https://github.com/Blaizzy/mlx-video ;
Wan2.2-S2V https://huggingface.co/Wan-AI/Wan2.2-S2V-14B ; LongCat https://huggingface.co/meituan-longcat/LongCat-Video-Avatar-1.5 , arXiv 2605.26486 ;
Kandinsky https://github.com/kandinskylab/kandinsky-6 ; MiniMax H3 https://huggingface.co/MiniMaxAI/MiniMax-H3 ; Wan weights status
https://howaiworks.ai/blog/alibaba-wan-open-weights-stopped-at-2-2 ; SongFormer https://github.com/ASLP-lab/SongFormer ; Encore
https://arxiv.org/abs/2609.04249 ; hosted tools https://www.unite.ai/best-ai-music-video-generators/ ; Seedance pricing
https://openrouter.ai/bytedance/seedance-2.5 .
