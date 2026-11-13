# ADR-0098: Teaching writing on Windows and Linux: PEFT + TRL on CUDA PyTorch, mlx-lm stays on the Mac

- **Status:** Proposed
- **Date:** 2026-11-08
- **Supersedes, if accepted:** ADR-0074 decision 3 **for NVIDIA only** ("on NVIDIA its CUDA path", the Unsloth component). The Mac part of
  decision 3 is unchanged, as built (`mlx-lm`, the ADR's own named fallback, L1 to L3).
- **Depends on:** ADR-0074 (the writing card), ADR-0073 (training platform), ADR-0075 amendment of 2026-11-08 (the decision trainer's CUDA
  locks), ADR-0056 (one slot; llama.cpp managed), `docs/train-web-plan.md` (the web's Linux CUDA host, P7).
- **Spike:** `docs/spikes/writing-peft-wp0.md` (WP0, 2026-11-08).

## Context

The owner wants training to be cross-platform (2026-11-07: "the aim is cross-platform, not speed"). Pictures and video are taught with AI
Toolkit and diffusers on PyTorch, which run on Apple silicon and NVIDIA alike; deciding (Laya) now has CUDA locks. **Writing is the one
card that only runs on a Mac**: `mlx-lm` exists only for Apple silicon. ADR-0074 named Unsloth's CUDA path for NVIDIA, but the app never
adopted the Unsloth component (the Mac uses `mlx-lm` directly), so following decision 3 on NVIDIA would add a second, large engine for one
card. The web's Linux CUDA worker (train-web plan, P7) has the same gap: "mflux and mlx-lm do not" run on CUDA.

Spike WP0 taught the same fixture with PEFT + TRL on PyTorch, on this Mac (no NVIDIA machine is here), with the app's exact recipe:

| Base | mlx-lm (4-bit) | PEFT + TRL on MPS (bf16) |
|---|---|---|
| Qwen3 0.6B | 7.6 s, 1.42 GB, held-out loss to 2.85 | 16.4 s, 3.61 GB, to **2.71**, 11 of 11 in style |
| Qwen3 1.7B | 12.7 s, 2.0 GB, to 2.51 | 18.5 s, 6.34 GB, to **2.15**, 11 of 11 |
| Qwen3 4B | 19.4 s, 3.8 GB, to 2.27 | 29.8 s, 12.17 GB, to **2.24**, 11 of 11 |

It learns the same manner, with no stray thinking tags, and its adapter went through the app's own GGUF writer and llama-server (4B, served on
the Q4_K_M chat copy: 11 of 11 in style). On the Mac it is slower and needs about three times the memory (full-precision weights; 4-bit
bitsandbytes has no Mac build), so it is not the better Mac engine.

## Decision

1. **Two engines behind the one writing trainer.** On a Mac with Apple silicon: `mlx-lm`, as built. On Windows and Linux with an NVIDIA card:
   **PEFT + TRL on CUDA PyTorch**, as a second trainer class beside `MlxLmTrainer`, chosen by `make_language_trainer` by platform (the same
   `apple_or_nvidia()` rule as pictures and deciding). The product, the screen, the job (`LanguageJob` in, `LanguageResult` out), the split,
   the steps ("Quick" and "Better"), the report and the action do not change.
2. **The same recipe on both.** LoRA rank 16, alpha 16, all seven projections, learning rate 2e-4 constant, batch 2, answer-only loss
   (TRL's prompt and completion form), the chat template with thinking off, seed 3407. A runner script of ours (like `language_train.py`)
   runs in the trainer's own Python and writes one JSON line per event, so the engine reads both trainers the same way.
3. **LoRA on bf16 weights first.** This is the measured path. 4-bit QLoRA through bitsandbytes on NVIDIA is a later option, taken only after it
   is measured on an NVIDIA machine (memory on 8 to 12 GB cards is the reason it may be wanted).
4. **The same way to use the result.** The adapter is PEFT's standard file; `gguf_lora.py` gains a PEFT reader (a rename and a transpose,
   the reverse of T0's `mlx2peft.py`), and the chat copies and llama-server's `--lora` stay as they are.
5. **Set up in the app like every trainer.** A hashed lock per platform (`writing-requirements-<target>.lock`, torch 2.11.0+cu128, transformers,
   peft, trl, accelerate, datasets; **2.84 GB on Windows, about 4.1 GB on Linux** by the indexes' sizes), installed with
   `--torch-backend cu128`, and the bases in Hugging Face form, pinned by size and SHA-256 (Qwen3 0.6B 1.5 GB, 1.7B 4.1 GB, 4B 8.0 GB: larger
   than the Mac's 4-bit copies), each fetched on request with the size shown.
6. **The web's Linux CUDA worker uses the same trainer**, through the existing `train.writing` job: no new route.

## Consequences

- Every training card runs on Windows and Linux with an NVIDIA card; the Mac keeps its faster, lighter path.
- Two writing engines to keep in step: one recipe module and one test that both build the same training text guard it.
- Downloads on Windows and Linux are large (CUDA PyTorch plus full-precision bases). If the decision trainer and the writing trainer share one
  CUDA PyTorch environment (open question 1), the second costs about 50 MB instead of about 3 GB.
- Nothing is measured on NVIDIA until a machine is available: speed, memory, Windows paths. The screen's "Measured here" sentences must say
  "estimated" there until it is.

## Alternatives considered

- **Unsloth's CUDA path (ADR-0074 decision 3 as written).** Likely faster and lighter on NVIDIA, but it is a large component of its own that
  patches transformers and moves with its own versions, the app does not use it anywhere else, and it could not be measured here either.
  Kept as the next option if PEFT + TRL is too slow on NVIDIA.
- **PEFT + TRL on the Mac too (one engine everywhere).** Simpler code, but 1.4 to 2.7 times slower and about 3 times the memory measured: 4B
  would not fit a 16 GB Mac. Rejected for now; it remains a fallback.
- **Leave writing Mac-only.** Contradicts the owner's aim.

## Open questions (the owner's)

1. One CUDA PyTorch environment shared by the decision and writing trainers (about 3 GB saved, one lock), or one each (as on the Mac)?
2. Accept that Windows and Linux start without measured numbers, or wait for an NVIDIA machine before offering the card there?
3. Should 4-bit QLoRA (bitsandbytes) be measured and offered on NVIDIA as part of this, or later?

## Docs to update if accepted

ADR-0074 (decision 3 marked superseded for NVIDIA, pointing here), `docs/desktop/` training page and `docs/desktop-profile.md`,
`docs/train-web-plan.md` (P7: the writing trainer on CUDA), `docs/backlog.md` (D34), the component manifests (`trainer-writing` on
`linux-*` and `windows-x64`).
