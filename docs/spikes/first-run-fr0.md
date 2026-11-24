# FR0: what each part needs, measured (2026-11-18)

Stage FR0 of [`docs/first-run-plan.md`](../first-run-plan.md) for [ADR-0109](../decisions/0109-first-run-and-one-setup-card-per-group.md).
Measured on the owner's Mac (Apple silicon, 64 GB, darwin-arm64), with the real binaries and model files the app
installed in `~/Library/Application Support/ai.wasifyai.desktop`.

## How

- **New measurements** ran the app's own programs directly, with the arguments the engine gives them, and sampled
  the process tree every 0.3 s with `footprint` (the physical footprint, which counts Metal buffers) and `ps`
  (resident memory). The peak of each is given.
- **Earlier measurements** are taken from the spike that made them, named in the table.
- **Download sizes** are the pins: each file in `products/*/models.yaml` and
  `services/api/.../components/manifests/darwin-arm64.yaml` has its size and SHA-256, and the installer refuses a
  file of any other size. A pin is therefore the real size; no second download was needed to check it.

## The table

| Part | Download | Memory: measured peak | Memory the engine judges by | Source |
|---|---|---|---|---|
| Qwen3 4B (chat) | 2.5 GB | about 4 GB | from the GGUF's shape (`need_of_language`) | `hub-shelf.yaml` note, assistant evaluation |
| Qwen3 8B (chat) | 5.0 GB | about 6.5 GB | from the GGUF's shape | same |
| BGE small (search) | 66 MB | **0.58 GB** footprint, 0.64 GB RSS (32 passages of 512 tokens, 200 times) | 1 GB | new |
| Document reader (Docling) | about 0.42 GB | **3.79 GB** footprint, 2.69 GB RSS (a 4-page scanned PDF, OCR on, 33 s) | none | new |
| Kokoro 82M | 0.19 GB | 0.9 GB | 1 GB | `voice-v0.md` |
| Parakeet TDT 0.6B v3 | 0.92 GB | 2.6 GB | 3 GB | `voice-v0.md` |
| Qwen3-TTS 0.6B (copy a voice) | 1.99 GB | 5.0 GB | 5.0 GB | `voice-v0.md` |
| Qwen3-TTS 1.7B (describe a voice) | 2.82 GB | 6.2 GB | 6 GB | `voice-v0.md` |
| Tone Color VC (change a voice) | 0.07 GB | **0.18 GB** footprint, 0.21 GB RSS (12 s of speech, 2.6 s) | 1 GB | new |
| dots TTS edit (edit speech) | 2.96 GB | 6.5 GB | 7 GB | catalogue `measured` |
| ACE-Step 1.5 Turbo (music) | 6.19 GB | 3.1 GB | 4 GB | catalogue `measured` |
| HTDemucs (split into parts) | 0.06 GB | **0.71 GB** footprint, 0.70 GB RSS (30 s stereo song, 24 s) | 1 GB | new |
| Song analysis (beat-this) | 0.96 GB packages + 8 MB | **0.43 GB** footprint, 0.56 GB RSS (30 s song, 12 s) | none | new |
| Sortformer 4spk v2.1 + ERes2Net | 0.52 GB | about 0.6 GB | 1 GB + 0.2 GB | `meetings-mt0.md` |
| FLUX.2 klein 4B (pictures) | 16.1 GB | 17.6 GB (process), 21.6 GB footprint | 24 GB | `desktop-phase1.md`, `pixal3d-td0.md` |
| LTX-Video 2B (video) | 16.1 GB | about 13 GB | 14 GB | `video-extend-vx0.md`, ADR-0037 |
| MuseTalk 1.5 (lip sync) | 2.1 GB environment + 4.17 GB | 11.8 GB | 12 GB | catalogue `measured` |
| Pixal3D + BiRefNet (3D) | 8.98 GB | 18.8 GB (cut-out 5.6 GB before it) | 19.5 GB | `pixal3d-td0.md` |
| Motion graphics render | about 0.32 GB | 2.3 GB (5 s at 720p) | 4 GB limit | `video-builder-v1.md` |
| llama.cpp, audio.cpp, ComfyUI, coding engine, Node | 12 MB, 42 MB, 13 MB, 375 MB, 53 MB | the model they run | | manifests |

Every new figure is below what the engine already judges by, so nothing in the catalogue had to be raised. The
reader and song analysis have no figure in the engine; they are small next to every cut-off and are counted at
their measured peak (3.8 GB and 0.5 GB).

## The cut-offs, against the engine's own fit check

ADR-0109 asks for three thresholds. The engine already has two of them in `desktop_fit.py` (on Apple silicon,
**capacity** is 90 % of the memory, and the **budget** is 75 %), so the cards use the same rules rather than new
numbers:

| Rule | ADR-0109 | Engine (`limits`) | Used by the card |
|---|---|---|---|
| Part included in the group's download | under three quarters of the memory | budget 75 % | need ≤ 75 % of the memory |
| "Download instead" still offered | the computer can still run it | capacity 90 % | need ≤ 90 % |
| Key is the main button (only where a key covers the whole group) | more than half the memory | — | need > 50 % |

The card judges the computer, not this moment: it uses the total memory, not what is free now. The model button's
"tight" warning still speaks about the moment when a model is started.

## What each Mac gets

Memory figures are the ones the engine judges by (fourth column above: the catalogue's `approx_ram_gb`, which the model button's fit check also uses, so the card and the button never disagree). "Key first" means the main button is the
key and "Download instead" is the second; "key only" means the model is too big to run (it is never offered for
download, as today).

| Group | 8 GB | 16 GB | 24 GB | 32 GB | 64 GB |
|---|---|---|---|---|---|
| Chat (Qwen3 4B, about 4 GB) | key first (ADR-0109 decision 3) | download | download | download | download |
| Voice | 6 of 7 items: Edit speech (7) left out; describing a voice (6) is in, at the limit | all | all | all | all |
| Music (4 + 1) | all | all | all | all | all |
| Meetings (3 + 1.2 + Notebook's) | all | all | all | all | all |
| Lip sync (12) | key only | key first | download | download | download |
| Images (24) | key only | key only | **key only** | key first | download |
| Video (14) | key only | key first | key first | download | download |
| 3D model (19.5) | key only | key only | key first | key first | download |
| Creative Studio | its own parts, Voice as above, Video by key | same, Video key first | same | all | all |

One answer differs from the mockup: **Images on a 24 GB Mac is key only**, not key first. The engine judges
FLUX.2 klein 4B at 24 GB, more than a 24 GB Mac's capacity of 21.6 GB, so the model button already refuses it
there today. The measured peaks (17.6 GB of process memory, 21.6 GB of footprint) sit right at that capacity. This
is the engine's existing figure, not one of ADR-0109's cut-offs, so the cards follow it and the mockup is
corrected. Lowering the figure needs a run on a real 24 GB Mac, which was not available.

## Checked in code

`services/api/tests/test_setup_groups.py` runs these rules on the real catalogues for 8, 16, 24 and 64 GB, and the
route `GET /desktop/setup/groups` was called on a real engine with a fresh data folder on this Mac (stage FR1):
Voice 8.98 GB, Music 6.29 GB, Lip sync 6.33 GB, 3D 8.98 GB, Meetings 3.01 GB, Notebook 1.53 GB, Code 0.43 GB.
Images and Video are 20.4 GB each on a fresh computer, not 16.1 GB: ComfyUI's own environment (PyTorch and its
packages) is 4.3 GB, which the manifest's 13 MB archive does not count. The mockup's figures are corrected.

## Not measured

- A 8, 16, 24 or 32 GB Mac: the cut-offs are computed from this Mac's measurements, not run on those Macs.
- Kokoro, Parakeet, ACE-Step and the voice models were not measured again; their figures are from `voice-v0.md`
  and the catalogue.
- The meetings models are not on this Mac; their figure is MT0's.
- The Indian-language models: 2.9 and 3.0 GB from the catalogue.
