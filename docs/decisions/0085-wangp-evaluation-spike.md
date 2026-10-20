# ADR-0085: WanGP evaluation spike: can it make basic images, video and audio on the Mac better than what we run now?

- **Status:** Proposed (2026-10-20); **the owner answered the five questions on 2026-10-20** (see "Owner's answers"). A **spike ADR**: it decides
  how to find out, not whether to adopt. Nothing is installed, downloaded or run for this ADR. **The roadmap's hold (2026-10-19) on spikes
  and new features applies**: stage W0 starts when the owner lifts it, and runs **before** the music video spike (ADR-0084 MV0). No question is open.
- **Date:** 2026-10-20 (updated the same day with the owner's answers)
- **Depends on:** ADR-0056 (one engine, two shells), ADR-0059 (ComfyUI as the image and video engine), ADR-0037 (video product),
  ADR-0062 (engines chosen by measurement; no second heavy Python environment), ADR-0066 (descriptors, one adapter per runtime, honest
  states, audio.cpp as the audio engine, `sidecar` for on-demand environments), ADR-0061 (how outside code enters), ADR-0063 (will it
  fit, models already on the computer), ADR-0012 (licences; rule 12), ADR-0084 (music video: its research found WanGP's licence).
- **Evidence read for this ADR:** the WanGP repository, licence, changelog, model list and issues on 2026-10-20 (links in "Sources");
  our own measured numbers in the repository. Anything not confirmed is marked **UNVERIFIED**.

## Context

The owner wants to know whether **WanGP** (github.com/deepbeepmeep/WanGP, "a fast AI video generator for the GPU poor") can generate
images, audio and video well enough on our Mac to be the engine for **basic** generation, and asks for a comparison with our current
performance. The owner's frame: **ComfyUI stays for image and video *workflows* only** (the custom graphs: style chains, remix,
editing, training outputs); WanGP would be the candidate for the plain "type a prompt, get a result" generation of images, clips and
audio. And the owner said WanGP works on the Mac.

**What WanGP is** (README, v18.19 dated 18 October 2026; 10.8k stars, 1.7k forks, 1,300 open issues, pushed 2026-10-19): a Python
application (a Gradio web UI plus a command line and a Python API) around many open models, with its own memory manager (`mmgp`)
that streams weights so big models run on small GPUs. It lists video (Wan 2.1/2.2, LTX-2.x and LTX-Video 0.9.8, MiniMax H3, Kandinsky
5/6, HunyuanVideo 1.5, LongCat, InfiniteTalk, MultiTalk, Ovi), image (Flux 1 and 2 including Klein 4B and 9B, Qwen Image, Z-Image,
Krea 2, HiDream, Ideogram) and **audio** (Qwen3-TTS Base, Custom Voice and Voice Design, ACE-Step 1.5 Turbo and XL Turbo, IndexTTS 2,
Chatterbox, KugelAudio, YuE2, HeartMuLa, Stable Audio 3, MiniMax Music 3). Install: one-click scripts (`.bat`, `.sh`), Pinokio, Docker
(NVIDIA), manual conda. Headless use: `python wgp.py --process queue.zip`, and a Python API (`shared/api.py`: `init()`, a session with
`submit_task(settings)` and an event stream, `cancel()`, model persistence between requests; read only in mirrors and a wiki summary,
**UNVERIFIED against the current source**).

**Does it work on a Mac? Partly, and the newest versions have open Mac bugs.**

- Official "early support" arrived in **v11.66 (12 May 2026)**. The changelog says it "wont be fast nor very optimized" and that not all models will be
  supported; a Pinokio post adds that **Macs cannot compute int8 and FP8**, so the person must switch precision to FP16. After that date the changelog
  mentions Macs nowhere. The manual installation guide covers Windows and Linux only.
- **Issue #2496 (opened 2026-10-19, open, no maintainer reply):** on an M4 Max with 128 GB, since v17 **LTX-2.5 image-to-video degrades to blocky noise and
  Qwen Image Edit gives wrong output**, because the memory manager's staging copy is not waited for on Apple's GPU (v16 was clean). The reporter proposes
  a patch and notes that on Metal the transformer is re-streamed every step unless `--preload` is used (an 8-step Qwen edit went from 21 min 46 s to
  14 min 40 s with it).
- **Issue #2014 (opened 2026-07-18, open):** a Metal crash ("commit an already committed command buffer") at the first step with LTX-2 distilled and Wan 2.2
  14B on M1 Pro, M1 Max and M4 Max; a community patch is unmerged.
- A community timing in a neighbouring project (Maestro issue #149, 2026-09-21, Wan 2.2 TI2V-5B 8-bit on an M5 with 32 GB, 704x1280, 49 frames) was 27 min 20 s
  for about 2 s of video. That used a different stack (MLX); it is not a WanGP number.

So the honest reading today: **WanGP runs on Apple silicon with caveats; whether it runs well on the latest version, and faster than our
engines, is exactly what the spike measures.**

**Licence: the decisive gate, found in the research for ADR-0084.** WanGP is not OSI open source. Its own licence is the
**WanGP Community License 2.0** (LICENSE.txt, read 2026-10-20; I am not a lawyer):

- *Free Use* covers personal, hobby, research, educational and evaluation use **and internal company or business use**, studio and client work.
- *Restricted Commercialization* (needs a separate licence from the author) includes selling, sublicensing, renting, licensing for a fee or "otherwise
  monetizing access to the Software", and **paid API, SaaS, hosted or managed access**. Private use through an API, local service or automation is allowed.
- **Redistribution is limited to Free Use**, with the licence text and notices kept and changes stated. **Free, non-monetized integrations are allowed if they
  disclose the use of WanGP and keep all notices.**
- Outputs may be used, sold and licensed for any lawful purpose; credit ("Made with WanGP") is required only when the output itself is what is sold.
- Models and libraries keep their own licences (WanGP's model list states none).
- (Maestro, built on WanGP, still carries the older "WanGP Non-Commercial Evaluation License 1.1" with no commercial use at all; the two differ, so the
  licence of the exact version we test must be read again.)

For us: the desktop app is free and open source today (owner, 2026-10-18), so an integration that **discloses WanGP and does not charge for access to it** looks
allowed; **a paid app, a paid or hosted web twin, or bundling WanGP's code inside our Apache-2.0 / AGPL-3.0 packages is not** without a licence from the author.
That makes WanGP a **conditional, source-available component**, never code we copy. CLAUDE.md rule 12 ("open source first; ask before adding a proprietary
dependency") applies. **The owner decided (2026-10-20) to experiment first and decide the licence stance afterwards**: W0 does not wait for a ruling, and
neither the web twin question nor a letter to the author is settled before the numbers exist.

**What conflicts with Accepted decisions, so any adoption must go through new ADRs (nothing here changes them):**

- ADR-0062 rule 2: *no second heavy Python environment*. WanGP is one (PyTorch and a stack of model libraries). ADR-0066 allows it only as an **optional
  `sidecar` component installed on a click**, with its own owner of the one model slot.
- ADR-0066 and ADR-0062 name **audio.cpp** as the audio engine and ADR-0059 names **ComfyUI** as the image and video engine. If WanGP wins a comparison, those
  decisions are amended by a new ADR; they are not contradicted by running a spike.

## Our current performance (the numbers WanGP must beat), measured on the owner's M5 Pro, 64 GB

| Task | Engine and model | Measured | Source |
|---|---|---|---|
| Image, 1024x1024, 4 steps | ComfyUI, FLUX.2 klein 4B (Apache-2.0) | **~13 s warm with a new prompt**; ~14 s cold direct, ~30 s through the engine including ComfyUI starting; ~24 GB listed memory (bf16) | ADR-0059 erratum, `docs/desktop-profile.md` |
| Video, text to video, 768x512, 30 steps | ComfyUI, LTX-Video 2B 0.9.5 (Open RAIL-M) | **72 s for 2 s (49 frames); 252 s for 5 s (121 frames)**; ~13 GB peak; 512x320, 25 frames, 15 steps: 13 s | ADR-0037 amendment, desktop profile "Video (V8)" |
| Video, image to video | same | 2 s clip 58 s through the app; "faithful to the picture, little motion" | ADR-0037, desktop profile |
| Video, other model | ComfyUI, Wan 2.2 TI2V 5B, 640x352, 33 frames, 10 steps | 85 to 108 s | ADR-0059 context |
| Speech | audio.cpp (Metal), Kokoro 82M | 8.6x realtime, 0.9 GB | `docs/spikes/voice-v0.md` |
| Speech with clone or design | audio.cpp, Qwen3-TTS 0.6B Base / 1.7B VoiceDesign | 3.5x / 2.9x realtime; 5.0 / 6.2 GB | voice-v0 |
| Music | audio.cpp, ACE-Step 1.5 Turbo (MIT) | ~1.6x realtime (a 3-minute song in ~2 minutes), 3.1 GB, songs up to ~4 minutes | `products/wasifyai-voice/models.yaml` |
| Switching the resident model | audio.cpp one process, `max_loaded_models: 1` | 2 to 4 s | voice-v0 |

Fixed lessons for how to measure: use **a new prompt each run** (ADR-0059's erratum: same-prompt runs overstated ComfyUI's speed by a third), count **cold and
warm**, report **peak resident memory**, never take file size for memory (ADR-0066 V0), and test with other apps closed.

## Decision

1. **Run a bounded comparison spike (W0), measured on this Mac, before any integration work.** Nothing is adopted by this ADR. After W0 the owner decides, and a
   follow-up ADR (W1) records the outcome per task.
2. **Scope: "basic" generation only.** Text to image; text to video and image to video (one clip); text to speech (built-in voice; clone and design if the model
   offers them); music from a style and lyrics. **Out of scope** (stay as they are): ComfyUI workflows (LoRA chain, remix, edit, inpaint, LoRA training outputs), speech
   to text, stem separation, voice conversion, lip sync, dubbing, audiobook, the assistant's language model.
3. **Like with like first, then the extra reach.** The comparison uses the **same model, size, steps, seed and prompt** wherever both engines have it, so the
   difference is the engine, not the model:

   | Task | Our side (baseline) | WanGP side (same model) | Extra, where WanGP offers what we cannot run |
   |---|---|---|---|
   | Image | ComfyUI, FLUX.2 klein 4B | WanGP, Flux 2 Klein 4B | Z-Image Turbo, Qwen Image 2512 (only after their licences are read) |
   | Video | ComfyUI, Wan 2.2 TI2V 5B (same weights) and LTX-Video 2B 0.9.5 (our default; WanGP lists only 0.9.8 13B, a different model under the later LTX licence, so no like-with-like) | WanGP, Wan 2.2 TI2V 5B | **LTX-2.5 Distilled** (conditional licence), Kandinsky 6 Lite (MIT, probably NVIDIA only: UNVERIFIED on Mac), LongCat |
   | Speech | audio.cpp, Qwen3-TTS 0.6B Base and 1.7B VoiceDesign | WanGP, Qwen3 TTS Base and Voice Design | Chatterbox, IndexTTS 2 (licences read first) |
   | Music | audio.cpp, ACE-Step 1.5 Turbo | WanGP, ACE-Step 1.5 Turbo | ACE-Step XL Turbo, HeartMuLa, Stable Audio 3 (licences read first) |

   Models our side already has on disk are **reused in place where WanGP can read the file**, otherwise the duplicate and its size are shown first (ADR-0062 rule 3).
4. **What is measured (every cell has a number or a "failed" with the reason):** wall time cold and warm; peak resident memory and the Metal allocation; disk used by
   the install and by each model; install time; first output after "Start" (including process start); runs that fail, crash, give noise or a blank (10 runs per cell);
   cancel (does it stop within 10 s and free memory?); unload (does the model leave memory when asked, so the one-slot rule holds?); progress events available to a
   caller; whether the **API/headless route** can run all of it without opening the web UI; what the process sends over the network while generating (a packet capture
   or a local firewall log; WanGP's changelog mentions optional remote assistant, MCP and notification features, so the claim "offline" is checked, not assumed).
5. **Quality is judged by a person, blind, plus simple automatic checks.** Per task, 12 pairs (same prompt and seed, engines hidden) shown to the owner; for speech, the
   clip is also transcribed back by Parakeet and compared (as in voice-v0); for video, a frame check for noise and frozen frames (issue #2496 is exactly a noise failure);
   for music, a listen. A result that is "faster but visibly worse" is a loss.
6. **Version discipline.** Test **v18.19 as shipped**, and the **last version before the Mac regression (v16.x, per issue #2496)**, to learn whether the bugs
   are in the latest only. The version, commit and `mmgp` and `torch` versions are recorded. Precision FP16/BF16 only (no int8 or FP8 on a Mac). The owner left this choice to me (2026-10-20): **both versions are tested and reported, and the Mac bugs are not patched by us.** Known Mac bugs are
   *recorded*, not patched; if a published patch is the only way to get correct output, that is a finding ("works only with a local patch"), not a pass.
7. **Throwaway environment (same rules as the owner set for ADR-0084's spike).** Everything installs in one folder **outside the repository**, with its own virtual
   environment and model folder; free disk is checked first; downloads are listed with size and licence and **need the owner's yes before they start** (CLAUDE.md "Ask
   before"); at the end the spike **deletes its downloads and environments and reports the disk used** (before, peak, after), **except the files the music video spike
   (ADR-0084 MV0) will reuse (LTX-2.5), which are named in the W0 report and deleted at the end of MV0**. The overall download ceiling is **100 GB**
   (owner, 2026-10-20), still with a listed size and licence and a yes before each download. No Pinokio, no third-party launcher: the
   official repository only (its README warns about look-alike sites). No account, token or key is used.
8. **Decision rule ("better"), fixed before the numbers are known.** WanGP wins a task if **all** hold:
   - *Performance:* with the same model and settings, warm time at least **20 % shorter** or peak memory at least **20 % lower**, with no quality loss; **or** it makes
     usable (no noise, no crash in 9 of 10 runs) a model or size we cannot run today with a licence that allows it (for example LTX-2.5 Distilled);
   - *Stability:* at least 9 of 10 runs per cell are good on the version we would pin; cancel and unload work;
   - *Integration:* a headless/API route drives it without the web UI, reports progress, and can be put behind our slot manager as one more owner of the model slot;
   - *Licence:* WanGP's licence permits what we would do (below) **and** every model we would make default has `commercial_use: yes` (or `conditional` on a revenue
     threshold, which the owner accepted on 2026-10-20 for all products; never non-commercial, unreviewed or territory-barred);
   - *Cost:* the extra install (WanGP's environment and duplicate models) is shown and the owner accepts it.
   Otherwise the answer is "keep the current engine for that task", which is a fine result. A tie goes to the current engine (no new heavy environment).
9. **If WanGP wins a task, the integration shape is already chosen so the follow-up is small** (W1): an `engine: wangp` **`sidecar` adapter** (ADR-0066 decision 2): a
   separate process the app installs **on a click from the official repository at a pinned commit** (we do not redistribute or copy its code; the install shows its size,
   source and licence; the notices and the "uses WanGP" disclosure appear in the screen's about text and the credits), driven through the API/headless route, one owner of
   the single-slot rule, descriptors per model with measured speed and memory, honest states ("needs the WanGP component", "not available here" with the reason). ComfyUI keeps
   every workflow; the model picker shows which engine a model runs on. Graphs still ask for capabilities, never for model names (CLAUDE.md rule 4). **Out of reach of this
   spike and of W1: the web twin**, because WanGP's licence needs a separate licence for hosted or paid access.
10. **Actions, search, deletion:** no new action and no new creation kind. Image, video, speech and music actions keep their ids (ADR-0068) and gain a model choice through
    the existing descriptors; creations stay searchable (ADR-0041) because they are the same kinds; deleting works as today. The help files gain one sentence about the engine
    only if W1 is built.
11. **Privacy:** local only. If W0 finds that WanGP contacts a service while generating (telemetry, update checks, remote assistant), that is listed and judged; a component
    that cannot be run with all of it off does not pass.

## Staged plan

| Stage | What | Size | Done when |
|---|---|---|---|
| **W0** | **Runs before the music video spike (ADR-0084 MV0).** The comparison spike in decisions 3 to 8, in a throwaway folder, on this Mac. Order: (a) install v18.19 and run one image to see it work; (b) the like-with-like image cells; (c) speech and music cells; (d) the video cells (Wan 2.2 5B both engines, then LTX-2.5 Distilled); (e) the same cells on v16.x; (f) API/headless route, cancel, unload, network log; (g) the licence rows and a blind quality session with the owner; (h) delete everything and report disk | 3 days (video cells are long runs: leave them in the background) | `docs/spikes/wangp-w0.md`: the tables (our baseline against WanGP, per task, cold and warm, memory, failures), the licence table per model, the network log, the disk report, a verdict per task against decision 8 |
| **W1** | Only for tasks that won: an ADR (amending ADR-0059 / ADR-0062 / ADR-0066 as needed) and the `wangp` sidecar adapter plus descriptors | decided after W0 | the ADR Accepted by the owner; for the built part, a real run on this Mac for each won task, tests with a fake adapter, the single-slot test, the credits text |
| **W2** | Optional: Windows and Linux (NVIDIA) numbers, where WanGP is strongest | decided after W1 | measured on those machines before anything is promised |

## Licence and commercial-use checks (rule 12) to complete in W0

| Part | Licence as read | Commercial use | Status |
|---|---|---|---|
| WanGP code (v18.x) | WanGP Community License 2.0: free incl. internal business use; paid or hosted access and redistribution beyond Free Use restricted; disclosure required | **conditional** (free local/internal and free non-monetised integration; a paid or hosted use needs a licence from the author) | read 2026-10-20; **re-read for the exact version tested; ask the author (deepbeepmeep@yahoo.com) if the owner wishes** |
| `mmgp` (its memory manager) | **UNVERIFIED** | unreviewed | read in W0 |
| FLUX.2 klein 4B | Apache-2.0 (ADR-0019) | yes | known |
| FLUX.2 klein 9B | non-commercial (ADR-0019) | no | never default |
| Wan 2.2 TI2V 5B | Apache-2.0 (HF tag of the family) | yes | verify the 5B card in W0 |
| LTX-2.5 | LTX-2.x Community License (free under USD 10M entity revenue; derivative rule) | conditional; allowed as default by the owner (2026-10-20) | known (ADR-0084) |
| LTX-Video 0.9.8 13B | later LTX licence (ADR-0037) | conditional | not tested |
| Kandinsky 6 Lite | MIT (GitHub link; secondary sites agree) | yes | verify in W0 |
| Qwen3-TTS (Base, VoiceDesign) | Apache-2.0 (voice-v0) | yes | known |
| ACE-Step 1.5 Turbo / XL Turbo | MIT (Turbo, models.yaml); XL **UNVERIFIED** | yes / unreviewed | verify in W0 |
| Qwen Image 2512 / 2.1, Z-Image, Krea 2, HiDream, Ideogram 4 | **UNVERIFIED** (Maestro's README says Qwen Image 2.1 is research/evaluation only) | unreviewed | read before any is run beyond a test |
| Chatterbox, IndexTTS 2, HeartMuLa, Stable Audio 3, YuE2, OmniVoice | **UNVERIFIED** here; ADR-0066 notes OmniVoice non-commercial, Stable Audio conditional; Maestro's README notes YuE2 non-commercial and IndexTTS2 under a bilibili licence | mostly unreviewed | read before any is run beyond a test |
| MiniMax H3 | territory excludes US, EU, UK, Korea (ADR-0084 notes) | no for those users | not tested |

## Consequences

- If nothing wins, we learn it for the cost of three days, with the disk freed; if one task wins, the follow-up is a small adapter, not a rewrite.
- WanGP's strongest case is **reach**: bigger models streamed through limited memory (LTX-2.5, Wan, Kandinsky). Its weakest case on this machine is **maturity**: the
  Mac path is five months old and the newest version has an open correctness bug. The spike is designed so a shiny model list cannot win without clean output.
- It fits ADR-0084's music video: a better clip model chosen here feeds that plan's stage MV5. W0 runs first (owner, 2026-10-20), so its LTX-2.5 files and
  environment can serve MV0 and are deleted when MV0 ends.

## Risks

- **Licence drift or misreading.** The licence changed between versions (Maestro still ships 1.1). Mitigation: read the tested version's text; ask the author before shipping; keep
  WanGP an installed component, never copied code; the web twin excluded.
- **A second heavy environment** (ADR-0062 rule 2): accepted only as an optional sidecar, and only if it wins.
- **Duplicate model files.** WanGP keeps its own checkpoint folder; a Qwen-sized model can be tens of gigabytes. Mitigation: reuse in place where it can read the file; show sizes.
- **Speed on Metal may be poor by design:** the memory manager re-streams weights each step unless `--preload` is used (issue #2496 measured a 33 % gain); `--preload` has its own
  over-commit risk. The spike records the best safe setting, not just the default.
- **Moving target:** 1,300 open issues and weekly releases. The pin protects us; the spike measures one version.
- **Privacy surface:** optional remote assistant accounts, MCP servers and notifications exist in the changelog; they must be off and silent. Checked, not assumed.

## Not decided here

Replacing ComfyUI or audio.cpp for anything; WanGP on Windows/Linux or in the web twin; WanGP's own assistant (Deepy), plugins, MCP and 3D features; Pinokio or
third-party launchers; any change to Accepted ADRs.

## Owner's answers (2026-10-20)

| # | Question | Answer (decided) | Where it landed |
|---|---|---|---|
| 1 | Is "ComfyUI for image and video workflows only" read right (ComfyUI keeps the workflows; WanGP, if it wins, does only basic generation of images, clips and audio; the comparison includes audio.cpp for speech and music)? | **Yes, the assumption is correct** | Context; decisions 2, 3, 9 |
| 2 | A download ceiling of about 100 GB, deleted afterwards? | **Yes** | Decision 7 |
| 3 | Keep the web twin out of any WanGP plan, and ask the author before anything ships? | **First experiment, then decide** | Context (licence); risks. The web twin stays out of the spike's scope; the stance is decided after W0 |
| 4 | Version pin: test v18.19 and v16.x and report, rather than patch the Mac bugs? | **My decision**: test both and report; do not patch | Decision 6 |
| 5 | Before or after the music video spike? | **Before** it | Status; W0; the shared LTX-2.5 files in decision 7 |

## Open questions for the owner

None. The spike itself will answer: whether WanGP is faster or lighter than ComfyUI and audio.cpp on the same models, whether its output is clean on the Mac,
and which tasks (if any) pass the decision rule. The licence stance (including the web twin and asking the author) is decided after those numbers.

## Sources (read 2026-10-20)

WanGP repository https://github.com/deepbeepmeep/WanGP (API data: 10,799 stars, 1,735 forks, 1,300 open issues, pushed 2026-10-19; README v18.19); licence
https://raw.githubusercontent.com/deepbeepmeep/WanGP/main/LICENSE.txt ; model list https://raw.githubusercontent.com/deepbeepmeep/WanGP/main/docs/MODELS.md ; changelog
https://raw.githubusercontent.com/deepbeepmeep/WanGP/main/docs/CHANGELOG.md (v11.66, 12 May 2026) ; installation guide
https://raw.githubusercontent.com/deepbeepmeep/WanGP/main/docs/INSTALLATION.md (Windows and Linux only) ; Mac post https://pinokio.co/posts/01kt8rp3rz968ss4zf1k1h9pf9 (third-party) ;
issues https://github.com/deepbeepmeep/WanGP/issues/2496 , https://github.com/deepbeepmeep/WanGP/issues/2014 , https://github.com/deepbeepmeep/WanGP/issues/672 ; API and CLI docs
(mirrors, **UNVERIFIED**) https://deepwiki.com/deepbeepmeep/Wan2GP/4.2-command-line-interface ; Maestro licence and issue #149 (see `docs/spikes/music-video-research.md`).
Our numbers: `docs/decisions/0059-comfyui-managed-sidecar-image-engine.md`, `0037-video-product.md`, `docs/desktop-profile.md`, `docs/spikes/voice-v0.md`,
`products/wasifyai-voice/models.yaml`.
