# S1: making EchoMimic v3 flash faster on this Mac (2026-11-10)

**Question.** S0 (`lipsync-echomimic-v3-s0.md`) found EchoMimic v3 flash running at 36 to 38 s of work per second
of video at 512, against MuseTalk's 6 and the bar of 30. Which settings make it faster, what do they cost in
quality, and can the face drift between windows be held?

**Answer.** Two settings together more than halve the time: **TeaCache at 0.2 with only the first 2 steps forced**
(the project's script forces 5 of 8), and **448 px** (464x416 for the photo). On the full 9.3-second voice that is
**16.6 s per second of video for the photo and 18.3 for the drawing**, under the bar and about **three times
MuseTalk**. Colour matching each frame to the picture keeps the skin tone across windows and costs nothing
measurable. Skin detail still smooths out by the third window. The fast clips look as good frame by frame, but the
mouth opens a little less. Fewer steps, skipping guidance in later steps, fp16 and longer windows did not help.

## How it was measured

- The same code, weights, environment and inputs as S0. A bench script loads the model once and runs every variant
  in one process: [`lipsync-em3-s1/bench.py`](lipsync-em3-s1/bench.py). It reuses S0's Mac fixes from `run_spike.py`
  and times the transformer's passes and the VAE decode separately.
- "One window" is the first 81 frames (3.24 s) of the 5.7 s voice on the photo; "10 s" is the 9.3 s voice in three
  windows. The times are work only; loading takes 66 to 69 s once.
- A rough lip score, [`lipsync-em3-s1/lipscore.py`](lipsync-em3-s1/lipscore.py), correlates the mouth's opening
  (face landmarks) with the voice's loudness frame by frame. It came out 0.06 to 0.21 for every clip, MuseTalk
  included. That is too noisy to rank variants (two runs doing identical work scored 0.06 and 0.11), so lip timing
  is judged by watching.

## A quirk in their pipeline that matters for speed

The pipeline runs the model twice per step: with the voice, and without it (audio guidance). It never tells the
model which pass is which, so TeaCache compares the two passes of the same step, finds them alike, and **reuses the
with-voice result for the without-voice pass**. That makes the later steps cost one pass instead of two, but it
also fades the audio guidance out after the first steps. Their own `run_flash.sh` does this on CUDA too, so S0's
clips are what the project ships. Telling the model which pass is which (`fix_cond`) makes TeaCache at 0.1 reuse
nothing, and the run costs the same as with TeaCache off (173 s against 174 s). The speed-ups below keep their
behaviour.

## Results

One window, photo, bf16 unless stated:

| Variant | Size | Work | Per second of video | Denoising | Decode | Passes (reused) |
|---|---|---|---|---|---|---|
| S0 settings (TeaCache 0.1, 5 forced steps) | 528x480 | 119.9 s | 37.0 | 98.5 s | 13.5 s | 16 (3) |
| TeaCache off | 528x480 | 173.7 s | 53.6 | 152.4 s | 13.4 s | 16 (0) |
| Model told which pass is which | 528x480 | 173.1 s | 53.4 | 151.2 s | 13.9 s | 16 (0) |
| **TeaCache 0.2, 2 forced steps** | 528x480 | **74.3 s** | **22.9** | 49.8 s | 16.1 s | 16 (9) |
| TeaCache 0.3, 2 forced steps | 528x480 | 69.8 s | 21.6 | 47.1 s | 14.6 s | 16 (9) |
| No guidance in the last half of the steps | 528x480 | 124.6 s | 38.5 | 98.8 s | 16.5 s | 12 (2) |
| No audio guidance at all | 528x480 | 105.5 s | 32.6 | 81.5 s | 15.2 s | 8 (0) |
| 6 steps | 528x480 | 123.8 s | 38.2 | 100.5 s | 14.6 s | 12 (0) |
| **448** | 464x416 | **94.1 s** | **29.0** | 76.0 s | 11.1 s | 16 (3) |
| **448 + TeaCache 0.2, 2 forced steps** | 464x416 | **44.0 s** | **13.6** | 27.9 s | 10.2 s | 16 (9) |
| S0 settings in fp16 | 528x480 | 132.5 s | 40.9 | 107.3 s | 15.3 s | 16 (3) |
| TeaCache 0.2 in fp16 | 528x480 | 80.5 s | 24.9 | 55.8 s | 15.5 s | 16 (9) |

Full 9.3 s voice, three windows:

| Variant | Picture | Size | Work | Per second of video |
|---|---|---|---|---|
| S0 settings (from S0) | photo | 528x480 | 337.2 s | 36.2 |
| TeaCache 0.2 | photo | 528x480 | 221.9 s | 23.8 |
| TeaCache 0.2 + colour matching | photo | 528x480 | 212.1 s | 22.8 |
| TeaCache 0.2, windows of 113 frames | photo | 528x480 | 259.2 s | 27.8 |
| TeaCache 0.2 | drawing | 512x512 | 245.2 s | 26.3 |
| **448 + TeaCache 0.2 + colour matching** | photo | 464x416 | **154.6 s** | **16.6** |
| **448 + TeaCache 0.2 + colour matching** | drawing | 448x448 | **170.3 s** | **18.3** |
| MuseTalk 1.5 (from S0) | photo / drawing | 768 long side | 57.8 / 56.6 s | 6.1 / 6.0 |

- One real pass costs about 9.5 s at 528x480 and about 6 s at 464x416. Decoding the 81 frames costs 10 to 16 s
  per window, about a fifth of the fast setting's time.
- Fewer steps, or dropping guidance in later steps, saves nothing: the passes they remove are the ones TeaCache
  was already reusing.
- fp16 is about 10% slower than bf16 on this Mac.
- Windows of 113 frames cost more per frame than 81 (attention's cost grows faster than the length) and still drift.
- With the text encoder freed after the prompts, the GPU holds 19.7 GB after loading. The process peaked at 36 to
  37 GB, set during loading.
- **A one-minute voice** at the fast setting: about 17 minutes of work plus a minute of loading (MuseTalk: about 6).

## Quality

- **Fast setting against S0, same frames**
  ([`faces-compare.png`](lipsync-em3-s1/faces-compare.png); rows: S0, TeaCache 0.2, 448): no faults or melting.
  TeaCache 0.2 is a little softer and the mouth opens a little less; 448 looks like S0, only smaller.
- **Drift** ([`drift-compare.png`](lipsync-em3-s1/drift-compare.png); frames 5, 120, 200, 225; rows: TeaCache 0.2,
  with colour matching, 113-frame windows): without matching, the face goes pale by the third window. With it, the
  skin tone holds. In all three, skin detail smooths out over the windows; one eye half closes at the end with
  113-frame windows.
- **The fast clips**: [photo](lipsync-em3-s1/sheet-photo-fast.png), [drawing](lipsync-em3-s1/sheet-drawing-fast.png).
  The head moves, the eyes blink and the drawing keeps its style. Side by side with MuseTalk (left), with the voice:
  [photo](lipsync-em3-s1/side-by-side-photo-fast.mp4), [drawing](lipsync-em3-s1/side-by-side-drawing-fast.mp4).

## What this means for the swap

- The speed bar of the proposal is met: 16.6 to 18.3 s per second of video. It is still about three times slower
  than MuseTalk and needs a 64 GB Mac (36 to 37 GB for the process).
- If you choose EchoMimic, the settings for the build would be: 448 px, 8 steps, UniPC, TeaCache 0.2 with 2 forced
  steps, bf16, 81-frame windows each starting from the last frame, every frame colour-matched to the picture, the
  text encoder freed after the prompts. Their pipeline's pass quirk is kept as it is.
- Still open: lip timing, judged by watching; drift on voices longer than 10 s (each window smooths a little more),
  which might need a fresh start from the picture now and then; 448 px is a small video (upscaling would be a
  separate step); and a 16 or 32 GB Mac can't run it.

Nothing in the app was changed by the spike itself.

## The app's own run (2026-11-10, after the swap)

The swap was built (ADR-0066 amendment "Lip sync model") and run end to end through the app's code, not the
spike's: `LipSyncInstaller` set up the environment from the pinned tarball and the hashed lock into a throwaway
data folder (50 seconds, 1.25 GB on disk, MPS found), then `LipSyncSidecar` laid out the seven catalogue files,
started the server and made two clips. The prompts came from the shipped `echomimic_prompts.safetensors`; the text
encoder was never loaded.

| Clip | Voice | Video | Load | Work | Work per second of video |
|---|---|---|---|---|---|
| Photo | 9.45 s | 464x416, 236 frames | 30 s | 130 s | 13.7 s |
| Drawing | 5.7 s | 448x448, 142 frames | warm | 110 s | 19.2 s |

The process's footprint, sampled every 10 seconds, was 13 to 15 GB (it was 37 GB in S0, with the text encoder).
A short voice costs more per second because its last window is padded to the model's frame count. The first run
showed that the old window rule dropped up to 7 frames at the end and ffmpeg's `-shortest` then cut the voice;
the last window is now rounded up, padded with the last voice frame, and only the frames needed are written.


## Size and the face (2026-11-10, after the first clips in the app)

The owner's first clip in the app (a 1024x924 portrait, 16 s voice) changed the face: slimmer, smoother and
younger, already by the end of the first window, more in later ones. EchoMimic's own flash script makes one
81-frame window at 768x768 with TeaCache 0.1 after five steps; ours used 448 and TeaCache 0.2 after two. Each
setting was run on that picture for one window (the picture is not kept in the repository):

| Setting | Size | One window (3.24 s) | Work per second of video | The face at the window's end |
|---|---|---|---|---|
| ours | 464x416 | 47 s | 15 s | changed |
| 448, their TeaCache | 464x416 | 85 s | 26 s | changed |
| 640, their TeaCache | 672x592 | 301 s | 93 s | kept |
| 768, their TeaCache (theirs) | 800x720 | 526 s | 162 s | kept, the most detail |

The size is the cause: at 448 the face is about 120 pixels wide, too few for the model to keep it. At 768, three
windows chained from the last frame (9.6 s) kept the face; also taking the CLIP picture from the original for
every window looked the same, so the chaining is left as EchoMimic does it. Peak footprint at 768 was 29 GB.
The owner chose quality over speed: the app now uses 768 with TeaCache 0.1 after five steps, about 2.5 minutes of
work per second of video, and waits up to 400 seconds per second of voice.

## Shape and size (2026-11-11, owner)

The owner asked for common sizes and portrait or landscape on the Lip sync screen. The screen now offers:
- **shapes:** as the picture, 9:16, 16:9, 1:1 and 4:5. Another shape crops the picture centred across and 40% down,
  where a face usually is.
- **sizes:** 480p and 720p on the short side, from the model's `lipsync.sizes`.

720p from a near-square picture is the 800x720 measured above. The largest size, 720p portrait (720x1280), was run
on the same picture for one window, with the same settings:

| Size | One window (3.24 s) | Work per second of video | Peak footprint | The face |
|---|---|---|---|---|
| 720x1280 | 1306 s | 403 s | 41 GB | kept |

Fitted on 672x592, 800x720 and 720x1280, the work grows with about the 1.8th power of the pixels. The screen's
estimate uses that power, measured from `speed_pixels` (576,000). The wait is now 800 seconds per second of voice.
The 480p sizes were not run. By the same power, 480p portrait (480x848) is about 1.4 minutes of work per second of
video.
