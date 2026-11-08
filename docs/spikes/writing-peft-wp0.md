# Spike WP0: teaching writing with PEFT + TRL on PyTorch (for Windows and Linux)

Date: 2026-11-08. Machine: MacBook Pro M5 Pro, 64 GB (the owner's). Question: the writing trainer ("Teach my assistant to write like
me", ADR-0074) runs on `mlx-lm`, which only exists on Apple silicon. What should teach writing on Windows and Linux with an NVIDIA card,
and does it give the same result as the Mac's? Asked by the owner on 2026-11-08 ("make training cross-platform"); the owner approved
downloading Qwen3 0.6B, 1.7B and 4B in Hugging Face form for it (about 13 GB, kept on AI-1TB under `wasify-models/huggingface/hub`).

Scratch folder (outside the repo): `~/Projects/wasifyai-spikes/w-peft/` (`peft_run.py`, `peft2mlx.py`, the split data, logs, adapters).

## Answers in short

| # | Question | Answer (measured unless marked) |
|---|---|---|
| 1 | Does PEFT + TRL learn the style with the app's settings? | **Yes, on every size: 11 of 11 answers in the taught style and signed after teaching, 0 of 11 before, 0 stray thinking tags**, the held-out loss falls as far as or further than with mlx-lm. |
| 2 | Same recipe as the Mac? | Yes, with no change: the app's split (45 to learn from, 5 kept back), 69 steps ("Quick"), batch 2, learning rate 2e-4 constant, LoRA rank 16 and alpha 16 on all seven projections, loss on the answer only, the chat template with **thinking off**, seed 3407. The training text equals the template's own, checked row by row. |
| 3 | How fast and heavy on this Mac (PyTorch on the graphics chip, bf16)? | **About 1.4 to 2.7 times slower a step and 2.5 to 3.2 times the memory of mlx-lm** (12.2 GB against 3.8 GB on 4B), because mlx-lm teaches a 4-bit copy and PyTorch here a full bf16 one (bitsandbytes 4-bit has no Mac build). Table below. |
| 4 | Can the result be served the way the app serves writing now? | **Yes.** The 4B PEFT adapter, renamed and transposed into mlx-lm's layout (`peft2mlx.py`), went through the app's own `gguf_lora.convert` (504 tensors, 132 MB) and was served by the app's llama-server (b11655) on the Qwen3-4B Q4_K_M chat copy the app uses: **11 of 11 answers in style, 0 stray tags**, thinking off through `chat_template_kwargs`. Taught on bf16, served on 4-bit K-quant: the style holds. |
| 5 | What would it install on Windows and Linux? | torch 2.11.0+cu128, transformers 5.22.2, peft 0.21.2, trl 1.17.1 (+ accelerate, datasets): **2.84 GB on Windows, about 4.1 GB on Linux x86-64** by the indexes' file sizes (nothing downloaded); almost all of it is CUDA PyTorch, the same build the decision trainer now installs there (ADR-0075 amendment of 2026-11-08). On the Mac the same set is 922 MB on disk. |
| 6 | Not measured | An NVIDIA machine (none here): the speed and memory there, 4-bit QLoRA through bitsandbytes, Windows paths. Unsloth's CUDA path (ADR-0074 decision 3) was not run for the same reason. |

## Same fixture, both engines, this Mac

The T0 fixture (`t0/data/all.jsonl`, 50 questions with short answers signed "- Wasi"), split by the app's own `language.split`
(45 and 5; the questions kept back are the ones the app asks before and after). mlx-lm numbers: 0.6B re-run today with the app's exact
config (`config_for`, through `language_train.py`, thinking off); 1.7B and 4B are the L3 numbers of 2026-10-26 (ADR-0074, same fixture and
steps, through the app's routes; their 4-bit MLX copies were in a deleted throwaway folder). "Closer" is how much the held-out loss fell, the
number the screen shows as "closer to how you write".

| Base | Engine | Weights taught | Training (69 steps) | A step, warm | Peak memory footprint | Held-out loss | Closer | In style after |
|---|---|---|---|---|---|---|---|---|
| Qwen3 0.6B | mlx-lm 0.31 | 4-bit | **7.6 s** | **0.071 s** | **1.42 GB** | 5.52 to 2.85 | 48 % | (L1: 4 of 4) |
| Qwen3 0.6B | PEFT + TRL, MPS | bf16 | 16.4 s | 0.195 s | 3.61 GB | 4.79 to **2.71** | 43 % | **11 of 11** |
| Qwen3 1.7B | mlx-lm (L3) | 4-bit | **12.7 s** | **0.184 s** | **2.0 GB** | 7.58 to 2.51 | 67 % | (4 of 4 in chat) |
| Qwen3 1.7B | PEFT + TRL, MPS | bf16 | 18.5 s | 0.255 s | 6.34 GB | 7.30 to **2.15** | **71 %** | **11 of 11** |
| Qwen3 4B | mlx-lm (L3) | 4-bit | **19.4 s** | **0.281 s** | **3.8 GB** | 7.98 to 2.27 | 72 % | (4 of 4 in chat) |
| Qwen3 4B | PEFT + TRL, MPS | bf16 | 29.8 s | 0.414 s | 12.17 GB | 7.42 to **2.24** | 70 % | **11 of 11** (and 11 of 11 served as GGUF) |

Reading:

- **It learns the same thing.** Every PEFT run signed all 11 answers (5 kept back, 6 new questions the fixture never had), with no stray
  `</think>`: the thinking-off template carries over unchanged. What they say is invented, as with mlx-lm ("Open Settings, choose Update"):
  the fixture teaches a manner, not facts.
- **The held-out loss ends lower with PEFT**, from a lower start: the bf16 base reads the answers better than the 4-bit copy before any
  teaching (4.79 against 5.52 on 0.6B). The two are not the same experiment on the base, so "closer" is not comparable to the percent; the
  final loss is the fairer number, and PEFT is as good or better there.
- **The Mac should keep mlx-lm.** PyTorch on the Mac teaches the full-precision weights and needs 2.5 to 3.2 times the memory, so on 16 GB Macs
  4B would not fit where mlx-lm's 4-bit copy does. PEFT works on the Mac as a fallback, not as the better engine.
- **On NVIDIA the picture changes** (not measured here): bitsandbytes gives 4-bit QLoRA there, and CUDA kernels are fast; the memory and time
  rows above are the Mac's only.

## Notes from the runs

- TRL's prompt-and-completion form with `completion_only_loss` is exactly mlx-lm's `mask_prompt`; the completion ends with the tokenizer's
  `<|im_end|>`, which TRL would otherwise add itself.
- PEFT keeps the adapter in fp32 while the base is bf16 (its default); no NaN in any run.
- The adapter is PEFT's standard `adapter_model.safetensors` (40.4 MB for 0.6B, 69.8 MB for 1.7B, 132 MB for 4B, the same sizes as mlx-lm's), which
  llama.cpp's own converter reads; the app's writer `gguf_lora.py` reads mlx-lm's layout, so it needs a PEFT branch (a rename and a
  transpose, the reverse of T0's `mlx2peft.py`).
- Downloads: 0.6B (1.5 GB) in about a minute, 1.7B (4.1 GB) in about three; 4B (8.0 GB) in about 15 minutes. Versions: torch 2.15.0, transformers 5.22.2, peft 0.21.2, trl 1.17.1, accelerate 1.15.0, datasets 5.1.0 (Mac; the Windows and Linux lock would have torch 2.11.0+cu128).
