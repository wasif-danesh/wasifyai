# LongCat-Video-Avatar as a lip sync option (investigation, 2026-11-11)

Status: investigated, then run once locally on this Mac (4-bit, 2026-11-11). Locally it is too slow and loses the
face. The owner's direction: apart from MuseTalk, lip sync choices run in the cloud with the user's own key, so LongCat
is judged as a cloud choice. See "Verdict after the run".

## What it is

LongCat-Video-Avatar (Meituan LongCat team) makes a talking person from a picture, a voice and a short text. It is
built on LongCat-Video, a 13.6-billion-parameter video model (about ten times EchoMimic v3 flash's 1.3B).

| Version | Released | Audio encoder | Steps |
|---|---|---|---|
| 1.0 | 2025-12-16 | wav2vec2 | 50 |
| 1.5 | 2026-05-21 | Whisper-large-v3 | 8 (DMD2 distillation) |

What it is praised for:
- **The body keeps moving during silences.** The model separates "the voice drives the mouth" from "the body moves",
  so pauses do not freeze the person. EchoMimic and InfiniteTalk tend to freeze.
- **Long videos without drift.** It joins its chunks in latent space; the project page shows a 5-minute example.
- **Several speakers in one picture, taking turns.**
- **Less "pasted face".**
- **More languages.** Whisper-large-v3 understands many more languages than the Chinese wav2vec2 that EchoMimic and
  InfiniteTalk use, which fits the multilingual rule.

The project page compares it with InfiniteTalk only through side-by-side videos; it gives no measured scores.

## How it would run on this Mac

There are two routes:

| | Official code (PyTorch) | `longcat-avatar-mlx` (community, MLX) |
|---|---|---|
| Platform | CUDA: torch 2.6 cu124, FlashAttention-2, examples on 2 GPUs | Apple silicon, Python 3.12, `mlx` |
| Mac support | none stated (a code comment only) | built for it |
| Long video (continuation) | yes (`--num_segments`) | not mentioned: one clip only |
| Maturity | the maker's | 13 commits, 8 stars, 70 tests |

The MLX port's weights (`mlx-community/LongCat-Video-Avatar-1.5-*`):

| Variant | Disk |
|---|---|
| bf16 | 46 GB |
| q8, distillation merged | 31 GB |
| q4, distillation merged | 24 GB |

Its peak at 480p in bf16 is about 50 GB. The README calls 64 GB "viable"; this Mac has 64 GB.

Speed, measured by the port's author on an M5 Max with 128 GB, for 29 frames at 256x432 with 8 steps:

| Variant | Time |
|---|---|
| bf16 | ~105 s |
| q4 | ~102 s |
| q8 | ~151 s |

Nothing was published for 480x832, the port's default, or for 93 frames. Our M5 Pro has fewer GPU cores than the M5
Max. A rough guess at 480p is tens of minutes per few seconds of video. That is likely slower than EchoMimic at
768, but it has to be measured.

## Compared with what we have and had

| | EchoMimic v3 flash (now) | MuseTalk 1.5 (before) | InfiniteTalk (2026-10-09 spike) | LongCat Avatar 1.5 |
|---|---|---|---|---|
| Moves | head and face | mouth only | head and body | head, body, hands; keeps moving in silences |
| Size of the model | 1.3B | small | 14B | 13.6B |
| On this Mac | 768 px; ~2.5 min per second of video; 29 GB | 5 s clip in ~30 s; 11.8 GB | 256-320 px only; ~4 min per second of video; ran out of memory in the 2nd window | MLX port only; 480p, ~50 GB bf16; speed unknown |
| Long voice | our own window joining | yes | out of memory after one window on the Mac | official code yes; MLX port no |
| Languages | Chinese wav2vec2 | Whisper | Chinese wav2vec2 | Whisper-large-v3 |

ADR-0044 records that InfiniteTalk *ran* on this Mac but only at 256-320 px, and only for one 3-second window
before it ran out of memory. The owner decided then that it was not a product on the Mac. Bringing it back as a
choice means meeting those limits again. The likely ways to do that are the newer kijai wrapper, a smaller
quantised base, or a CUDA host. ADR-0066 already plans InfiniteTalk as a CUDA-host model.

## Verdict before the run

LongCat Avatar 1.5 is the most promising choice for quality, natural movement and languages. On the Mac it depends
on a young community MLX port that makes one clip at a time. A long voice would need our own chunk joining, as
for EchoMimic, unless the port adds continuation.

It is worth a spike before deciding:
1. Download the q8 merged variant (31 GB). Use bf16 (46 GB) only if q8 looks worse.
2. Run the port as it is, on the owner's picture and a 5 s voice, at 480p, then at 720p if 480p fits in memory.
3. Report time, peak memory and how well it keeps the face, beside EchoMimic at 768.
4. If it is good, check that a second chunk can continue from the first (the official code's `num_segments` idea,
   in MLX).

Adding it needs the owner's yes for the download and for `longcat-avatar-mlx` as a dependency. The app already uses
`mlx` for language training (L1).

## Spike run (2026-11-11, owner chose 4-bit)

The owner chose the 4-bit merged weights (24 GB) over q8, to fit the 64 GB Mac.

Setup:
- `xocialize/longcat-avatar-mlx` cloned with its own `.venv` (mlx 0.31, mlx-arsenal).
- Weights `LongCat-Video-Avatar-1.5-q4-dmd-merged` on AI-1TB, under `wasify-spikes/`.
- Input: the owner's 1024x924 picture and their 16.3 s voice. The picture was cropped to 480x832 (portrait) the
  way the app crops, centred at (0.5, 0.4).
- 93 frames (the port's default), 8 steps, seed 42, a one-line prompt describing the person.
- The picture, voice, prompt and text encoding were passed exactly as the port's own `run_inference.py` passes them.

| | LongCat Avatar 1.5, 4-bit | EchoMimic v3 flash (now) |
|---|---|---|
| Size | 480x832 | 800x720 / 720x1280 |
| Video made | 3.72 s (93 frames) | 16.3 s |
| Work | about 73 min in all, about 1,180 s per second of video | 162 s / 403 s per second of video |
| Peak memory | 58 GB of 64 | 29 GB / 41 GB |
| Face | **not kept**: a different, cartoon-like woman with heavy make-up, orange hair streaks and a frown | kept |
| Long voice | one clip only | joined windows |

What this means:
- **Speed.** At fewer pixels than EchoMimic's portrait size it is about 3 times slower, and about 7 times slower than
  EchoMimic at 720p near-square. The owner's 16 s voice would take about 5 hours, in several clips that the port
  cannot join.
- **Memory.** 58 GB leaves almost nothing for the app and the system. A larger size or q8 would not fit.
- **Face.** The mouth and brows move, but the person is not the owner's picture. Because the inputs match the port's
  own script, this is the 4-bit port's behaviour, not a wiring mistake. q8 might keep the face better, but it would be
  slower (the port author measured q8 1.5 times slower than q4) and heavier.

### Second local run: the 3-second test (2026-11-11, LC0)

The lip sync plan (`docs/lipsync-choices-plan.md`) makes heavy models a 3-second test on this computer. The same
4-bit weights, script and prompt, at the size the app picks for the owner's picture at 480p:

| Size | Frames | Work | Per second of video | Peak memory | Face |
|---|---|---|---|---|---|
| 528x480 | 73 (2.92 s) | 24.8 min (load 3.5 s) | 509 s | 50 GB | **not kept**: the same made-up woman with pink lipstick as the first run |

Both runs, at two sizes and shapes, made the same stranger. Rounding at 4-bit would more likely blur the owner's
face than replace it, so the port's picture conditioning is the more likely fault. Before LC5 builds a local LongCat
test, the port's own sample picture should be run, to see whether it keeps that face. If it does not, the port is
broken for this use and q8 will not help.

## Verdict after the run

**Locally** (on the Mac, through the MLX port) it is not usable: about 1,180 s of work per second of video, 58 GB, and
the face was lost at 4-bit. q8 might keep the face better, but it would be slower and likely would not fit in 64 GB.

**In the cloud** this does not apply. The app is for local and cloud models, and the owner decided (2026-11-11) that
lip sync choices other than MuseTalk use a cloud provider with the user's own key. Hosted LongCat runs the full model
on large GPUs:

| Provider | Endpoint | Price (as listed, 2026-11-11) |
|---|---|---|
| fal.ai | `fal-ai/longcat-single-avatar/image-audio-to-video` (and a multi-person one) | $0.15 per video second at 480p, $0.30 at 720p |
| WaveSpeed | `wavespeed-ai/longcat-avatar`, `longcat-avatar-1.5/multi` | not checked; says about 10-30 s of waiting per video second |

InfiniteTalk is hosted too: WaveSpeed lists $0.15 (480p) and $0.30 (720p) per 5 seconds, up to 10 minutes.

So LongCat is a strong candidate for the cloud dropdown. Its quality, including whether it keeps the face, has to be
judged on a hosted run with the owner's key and picture, not on the 4-bit port.

The local spike files are outside the repo: `/Volumes/AI-1TB/wasify-spikes/longcat-avatar-mlx` (clone, `.venv`,
23 GiB of weights). They can be deleted.

## Sources

- fal.ai: https://fal.ai/models/fal-ai/longcat-single-avatar/image-audio-to-video/api
- WaveSpeed: https://wavespeed.ai/models/wavespeed-ai/longcat-avatar and https://wavespeed.ai/infinitetalk-api

- Project page: https://meigen-ai.github.io/LongCat-Video-Avatar/
- Weights and card (MIT): https://huggingface.co/meituan-longcat/LongCat-Video-Avatar-1.5
- Official code: https://github.com/meituan-longcat/LongCat-Video
- MLX port: https://github.com/xocialize/longcat-avatar-mlx and https://huggingface.co/mlx-community/LongCat-Video-Avatar-1.5-bf16
