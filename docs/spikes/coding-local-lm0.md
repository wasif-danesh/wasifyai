# LM0: the coding agent on the app's own llama-server (2026-11-16 and 17)

The first stage of `docs/coding-local-model-plan.md`. The owner answered "Yes, all three" on 2026-11-16, which
included the GGUF download.

**Where it ran:** an Apple M5 Pro with 64 GB of memory. The app's own `llama-server` was release b11655, Metal,
started through `LlamaServer.ensure_running` with the app's flags (`--jinja`, one slot, `--cache-ram 512`) and a
context of 32,768. The coding engine was the app's, in its sandbox.

**The script:** `docs/spikes/coding-local-lm0.py`. It runs the 36 tasks of `evals/run_eval.py` with the gateway's
local route pointed at that server, and records the server's peak memory.

## Results

| Check | Result |
|---|---|
| **Tool calls through `--jinja`** | **Work.** One chat call with a `read_file` tool returned a correct tool call: 3.4 s on Qwen3 8B, 5.6 s on Qwen 27B. OpenHands' native tool calling ran all 36 tasks without a format error. |
| **Turning thinking off** | **llama-server needs its own switch.** The Ollama route's `reasoning_effort: none` is not read by llama-server. With it, Qwen3 8B thought until the 4,096-token limit on every call. With `chat_template_kwargs: {enable_thinking: false}`, which chat already sends (`desktop_language.thinking_fields`), most calls were 6 to 125 tokens. LM1 has to send this switch for a file run by the app. |
| **Qwen3 8B** (`Qwen3-8B-Q4_K_M.gguf`, from the Model hub's catalogue) | **No-go for coding.** 0 of 2 (`bug-paginate`, `bug-discount`), with no file changed. In one task it repeated itself to the 4,096-token limit three times and ran out of time. Peak memory 9.5 GB. It is the kind of model that gets the "May not manage coding well" note. |
| **Qwen 27B** (`unsloth/Qwen3.8-27B-GGUF`, `UD-Q4_K_M`, 16.6 GB, SHA-256 checked against Hugging Face) | **Go for quality: 32 of 36.** Everything outside the hard group passed, 30 of 30. Hard: 2 of 6 (`hard-bug-hunt` and `hard-cli` passed; `hard-kv-store` and `hard-expr` ran out of time; `hard-refactor` and `hard-conflict` failed their checks). Undo was exact for 36 of 36, and every task was brought back exactly. The same model as MLX on Ollama had 33 of 36 (`coding-c3.md`). |
| **Speed, Qwen 27B** | **About 2.3 times slower than MLX on Ollama.** 87.7 minutes for the 36 tasks, median 106 s a task, against a median of about 45 s on Ollama. Writing is the cost: 42,549 tokens at **11 tokens/s** took 62.7 of the minutes. Reading took 19.4 minutes: 294,688 tokens at 253 tokens/s, over 224 calls. A task's first, long prompt (about 10,000 tokens) is read once, and later calls reuse it (median prompt 242 tokens). |
| **Memory, Qwen 27B at 32k** | Peak 20.8 GB resident. It loaded in 2.0 s once the file had been read. It fits a 32 GB Mac with little room to spare and a 64 GB Mac easily. |

## What it means for LM1 to LM3

1. **The plan stands.** llama.cpp runs the coding agent's tools correctly, and Qwen 27B's quality on it matches
   the MLX run.
2. **LM1 sends llama-server's own thinking switch** for a model run by the app, and Ollama's `think` and
   `reasoning_effort` for a model of a running Ollama, exactly as chat's `thinking_fields` does.
3. **The context is 32,768,** the size measured here, with `max_input_tokens: 24000` and
   `max_output_tokens: 4096` as before.
4. **Speed: LM1 starts the server with `--spec-type draft-mtp,ngram-mod`** for a model that has MTP layers
   (`ngram-mod` alone otherwise). See "Speed check" below: about a fifth less time for the 36 tasks, with the
   same quality.
5. **The catalogue recommendation for coding** is `unsloth/Qwen3.8-27B-GGUF`, file `Qwen3.8-27B-Q4_0.gguf`
   (16.1 GB), on a Mac with 32 GB or more. Smaller models are shown with the note.

## Speed check (2026-11-17)

The owner asked for this before LM1. The script `docs/spikes/coding-local-lm0-speed.py` asks the server for
three kinds of output a session writes, twice each, thinking off: a whole file written again with one change
("edit"), a new module with tests ("write"), and about 300 words on a file ("explain"). The speed is
llama-server's own figure.

| Setup (Qwen 27B, release b11655), tokens/s, two runs | Edit | Write | Explain |
|---|---|---|---|
| `UD-Q4_K_M`, plain (the LM0 run above) | 15.0, 12.8 | 9.9, 10.2 | 11.0, 10.8 |
| `UD-Q4_K_M`, `ngram-mod` | 84.4, 101.3 | 13.0, 10.9 | 9.1, 9.2 |
| `UD-Q4_K_M`, `draft-mtp` | 19.5, 19.4 | 17.5, 17.6 | 13.4, 14.3 |
| `UD-Q4_K_M`, `draft-mtp,ngram-mod` | 81.5, 88.7 | 17.8, 17.2 | 13.2, 12.9 |
| `Q4_0`, plain | 12.0, 12.0 | 12.7, 12.7 | 12.2, 12.1 |
| **`Q4_0`, `draft-mtp,ngram-mod`** | **86.9, 95.4** | **20.8, 21.1** | **15.4, 15.3** |

- **MTP needs no extra file.** The unsloth GGUFs carry the model's own MTP (next-token) layers, and
  `draft-mtp` uses them. The repository's separate `mtp-*.gguf` (1.4 GB) was downloaded and is not needed.
- **`ngram-mod`** reuses text already in the conversation, so it helps most where a session copies a file back
  with small changes. That is the "edit" figure.
- One first start with `ngram-mod` exited with no message. It started on a rerun and by hand, and did not happen
  again in any later run. Not explained.

**The 36 tasks on `Q4_0` with `draft-mtp,ngram-mod`:** **33 of 36** in **69.5 minutes**, median **78 s** a task
(against 32 of 36, 87.7 minutes and a median of 106 s on plain `UD-Q4_K_M`). Undo exact for 36 of 36. Peak
memory 23.6 GB at 32k (the drafting adds about 3 GB). The tool probe took 4.3 s. The hard group changed between
runs (`hard-expr` and `hard-refactor` passed this time, `hard-bug-hunt` failed), so the difference of one task
is noise. MLX on Ollama had a median of about 45 s, so the local model is still slower there, by about 1.7
times instead of 2.3.

The files are at `/Volumes/AI-1TB/wasify-models/gguf/`, outside the app's own models folder.

## LM3: the gate through the app's own route (2026-11-18)

Run on the same Mac with the code of LM1 and LM2, the model chosen the way a person chooses it.

**The 36 tasks:** `run_eval.py --data <throwaway> --model this-computer --gguf Qwen3.8-27B-Q4_0.gguf`, so each
call went through the gateway's `this-computer` route and `LanguageService.session(coding=True)`: one
`llama-server` for the whole run, at 32,768, with `draft-mtp,ngram-mod` (drafts accepted 66 to 96 percent of the
time). **33 of 36** in **87.3 minutes**, median **99 s** a task, the longest 427 s (the time limit). Every group
passed in full except tests (1 of 2: `tests-write` ran out of time) and hard (4 of 6: `hard-kv-store` and
`hard-conflict` ran out of time; `hard-expr` passed although it reached the limit). Undo exact for 36 of 36, and
36 brought back exactly; 32 files changed. Counted cost $0.00.

It was slower than the speed check above (69.5 minutes, median 78 s) on the same file and options. The short
tasks took 10 to 30 percent longer, and three tasks took many more steps (`bug-memo-kwargs` 18 against 3,
`hard-conflict` 41 against 8).

**Why it was slower (looked into 2026-11-18): the computer, not the route.** Both runs used the same
llama-server (b11655), 6 threads, the same file and the same arguments (`-c 32768 -np 1 --jinja --cache-ram 512
--spec-type draft-mtp,ngram-mod`), and drafting was accepted about as often (61 and 57 percent of drafted
tokens). But in LM3 the server itself read and wrote more slowly: 173 against 217 prompt tokens a second, and 19.7
against 27.3 tokens a second written, over the whole run. Drafting cannot slow the reading of a prompt, so the
fair yardstick is a task's first prompt, about 6,730 tokens with nothing cached:

| | A fresh prompt of about 6,700 tokens, tokens/s |
|---|---|
| Speed check (2026-11-17, the server started directly) | 216 to 245 |
| LM3 eval (2026-11-18, through the route) | 152 to 193 (the first one 350) |
| The same server alone on a quiet computer, three fresh prompts | 318 to 376 |
| Eight tasks again through the route on a quiet computer | 199 to 233 |

Through the route on a quiet computer the reading speed is back to the speed check's. The eight tasks (all
passed) took 574 s, against 488 s in the speed check and 578 s in LM3. The seven tasks with the same steps in all
three runs took 444 s, against 401 s and 491 s, so most of LM3's extra time is gone. What is left is within how
much one task's time changes between runs: `bug-flatten` took 62, 92 and 79 s, with three steps each time.

What slowed the computer during LM3 is not known for certain. Another session ran first-run setups (a music
separation model, voice conversion and song analysis) and two engine starts and a window walk in the same
hours, but only for a few minutes each, while the slowdown lasted the whole 87 minutes. No thermal or power
warning was recorded. The lesson for later gates: a timing is only compared with another taken with nothing
else running on the computer.

**The seven walks of the v1 gate** (`docs/spikes/coding-v1-gate.md`), each on a fresh data folder with no key,
so a new session started on "On this computer". `WASIFYAI_AUDIT_LANGUAGE_FILE` chose the file in the Model hub
first, as a person does. **All seven passed:**

| Walk | On Qwen3.8 27B (Q4_0) |
|---|---|
| `code-plan` | Answered in Plan in 72 s, nothing changed; the Files tab, a file found by name, the cost |
| `code-edit` | The change in 57 s; the card for `.env` asked after 6.8 s; the no in 14.7 s; Stop in 0.34 s; Undo and "Bring it back" read back from disk |
| `code-check` | One refusal, one fix, one pass in 26 s; a check of two minutes with the screen live; Stop in 0.22 s; "needs you"; the terminal held by the sandbox; a delete asked first and undone; `git init` |
| `code-build` | The starter, its preview and check; "a to-do web app with a logo" in one turn of 17 min (20 steps, 6 files); the logo made by the picture product after a yes, a 1024 by 1024 PNG, used in the running page. The model's first picture command wrote its log to `/tmp`, which the sandbox closes; the step ended at once and the model asked again without it |
| `code-extensions` | Ours fired (81 s), ours off and Security on (59 s), the person's own skill followed (68 s), its removal |
| `code-scheduled` | Run now on a copy in 171 s, the project byte for byte unchanged, the change applied; the plugin's hook only after approval |
| `code-browser` | The Browser tab's bar and the stay-open switch |

The pictures of these walks in `docs/ui-audit/desktop/` are now the ones on this model.

**The catalogue:** `unsloth/Qwen3.8-27B-GGUF` is on the Model hub's shelf (`hub-shelf.yaml`) and in the chat
list (`CHAT_SHELF`, "advanced", 24 GB of memory, so it does not fit 16 GB, is tight on 32 GB and fits 64 GB).
Its download takes the `Q4_0` file (`quant`), not the usual `Q4_K_M`. It is not the recommended chat model.
