# The coding agent's local model on the app's own language engine (plan, 2026-11-16)

**Status:** plan; the owner answered "Yes, all three" on 2026-11-16 (the recommended answer to each question
at the end of this page). **LM0 done 2026-11-17** (`docs/spikes/coding-local-lm0.md`): tool calls work through
`--jinja`; llama-server needs its own thinking switch; Qwen 27B (GGUF) passed 32 of 36 but writes at 11 tokens/s,
about 2.3 times slower than MLX on Ollama; Qwen3 8B is a no-go. **Speed check done 2026-11-17:** the `Q4_0` file
with `--spec-type draft-mtp,ngram-mod` (no extra file) passed 33 of 36 in 69.5 minutes, median 78 s a task
(edits 87 to 95 tokens/s, new code about 21), 23.6 GB. LM1 starts the server with those options; LM3 recommends
that file. **LM1 built 2026-11-17** (`docs/desktop/coding.md`, "The model on this computer"): the gateway's
`this-computer` entry runs the Model hub's choice through `LanguageService.session(coding=True)`;
`qwen-27b-ollama` and `CODING_OLLAMA_URL` are gone; the evaluation runner takes `--model this-computer`
with the Model hub's choice or `--gguf`, which is LM3's runner part. Checked for real on the `Q4_0` file through
the route: 3 of 3 tasks (`bug-paginate`, `bug-discount`, `hard-cli`) in 244 s, the server at 32,768 with drafting
accepted 44 to 84 percent of the time. **LM2 built 2026-11-17** (mockup
`docs/spikes/coding-local-lm2-mockup.html`; `docs/desktop/coding.md`, "The model button"): the row is the
Model hub's model by name, with why it cannot run and a button to the place that fixes it, "May not manage
coding well" on the models LM0 found too small, and a line in a session when the model changes. **LM3 done
2026-11-18** (`docs/spikes/coding-local-lm0.md`, "LM3"): Qwen3.8 27B (`Q4_0`) is on the Model hub's shelf; through
the route it passed 33 of 36 (87.3 minutes, median 99 s) and all seven walks of the v1 gate. The plan is complete.

## Why

On the desktop, chat and writing run on the language model chosen in the Model hub. That is a GGUF file in
the app's own `llama-server` (`llama_server.py`), or a model of a running Ollama or LM Studio that the engine
found (`desktop_language.py`, `select_server`).

The coding agent does not use that model. Its only local entry is `qwen-27b-ollama` in `coding_models.yaml`.
That entry was added in stage C1b so the gates could run a second time on a local model through the
developer's own Ollama. Its address comes from `CODING_OLLAMA_URL`, which the app never sets. The C1b notes
(`docs/spikes/coding-c1b.md`, decision 7) say the model picker that exists "takes the list over with the
screens", and ADR-0101 decision 7 says other models "follow the picker that exists". That handover was never
built.

On 2026-11-16 the owner chose "Qwen 27B on this computer (Ollama)" for a coding session, and the session
stopped with "could not be reached". The entry was listed even though no address was set. That listing is
fixed: the entry is now offered only when `CODING_OLLAMA_URL` is set (staged with H4). This plan replaces the
entry itself.

## What it becomes

There is one local entry in the coding model list: **the language model chosen in the Model hub**, shown by its
own name ("Qwen3 8B on this computer"). The person chooses or changes it in the Model hub, the same as for chat.
Coding gets no picker of its own and no Ollama setting.

- **A file:** the gateway sends the call to the app's own `llama-server`, started for that file through
  `LanguageService`.
- **A model of a running Ollama or LM Studio:** the call goes to that program, the same as chat.
- **Nothing chosen:** the entry is listed but not ready, with the words "Choose a language model in the Model
  hub first". The other models are unchanged.

Claude Code and Codex sessions (ADR-0107) are not affected. They run on the person's own plan.

## What has to be solved

| | The question | What is known now |
|---|---|---|
| 1 | **Tool calls.** OpenHands calls tools natively (`native_tool_calling: true`). | `llama-server` is started with `--jinja`, which applies the GGUF's own chat template, including its tools. Whether Qwen's GGUF templates give tool calls OpenHands can read is to be measured (LM0). |
| 2 | **Context.** The OpenHands prompt and the tools are about 10,000 tokens before any file is read. The Ollama entry used `max_input_tokens: 24000`. | Chat starts the server at 8,192 by default (`DEFAULT_CONTEXT`), which is too small for coding. Coding asks for at least 32,768. To avoid a restart each time chat and coding take turns, `ensure_running` takes "at least this context" and keeps a larger server that is already running. Whether it fits is checked with `desktop_fit` at the larger context. |
| 3 | **One model at a time.** There is one `llama-server`, and it holds the `chat` slot. | A coding call holds the `chat` slot while it runs, the same as a chat answer, so an image job waits and the image model is unloaded first. The slot is held per call, not per session, so a session left idle does not block images. |
| 4 | **The model name.** The gateway lets through only the session's `provider_model`. | The local route takes its name from the selection: the file's name for `llama-server`, which ignores it, and the program's model name for Ollama or LM Studio. A change in the Model hub while a session is open: the session keeps working on the new model, and its title says so. Choosing per new session, as the owner decided on 2026-11-15, applies only to the cloud models. |
| 5 | **Quality.** Small models do poorly at coding. | The tested local result is Qwen 27B (MLX, through Ollama): 33 of 36 evaluation tasks (`coding-c3.md`) and all seven walks (`coding-v1-gate.md`). The Model hub's catalogue offers only Qwen3 0.6B, 4B and 8B. These are not measured for coding. Ollama's `qwen3.8:27b-mlx` is MLX, which llama.cpp cannot run, so a GGUF of the same model would be a new download. |
| 6 | **The gates and the evaluation.** They use `CODING_OLLAMA_URL` today. | The runner (`evals/run_eval.py`) and the walks choose the local model the way a person does: through the Model hub selection in their data folder, a file or the developer's Ollama. The Ollama entry leaves `coding_models.yaml`. |

## Stages

| Stage | What | Done when |
|---|---|---|
| **LM0** spike | Run the 36 evaluation tasks through the app's `llama-server` with a Qwen 27B-class GGUF, and with Qwen3 8B from the catalogue. Measure: tool calls, the context a session needs, memory at that context (this Mac has 64 GB), speed against the MLX model on Ollama, tasks passed. | `docs/spikes/coding-local-lm0.md` with the numbers and a go or no-go per model |
| **LM1** gateway | A local route kind in `coding_gateway.py`: listed from `LanguageService.selected`; its upstream and name resolved per call through `LanguageService.session()`, holding the slot for the call; `ready()` says why not (nothing chosen, does not fit at 32k, the engine is not set up). `ensure_running(..., at_least=...)` in `llama_server.py`. Remove `qwen-27b-ollama` from the file and `coding_ollama_url` from the settings. | Gateway and session tests on a fake `llama-server` and a fake Ollama; `make test` green |
| **LM2** window | The Code model button shows the chosen model as one row, "On this computer", with its name, and the not-ready words with a link to the Model hub (`apps/desktop/src/choices/code-choices.ts`). Mockup first. | Mockup approved, then the UI tests and a walk |
| **LM3** gates | The runner and `ui-audit.sh` walks choose the local model through the Model hub selection. Rerun the 36 tasks and the seven walks on the chosen GGUF. | Results in the LM0 note; ADR-0101 gets a "Built" line; `docs/desktop/coding.md` updated |

The web is not affected: it runs only cloud models (ADR-0099), and the coding agent is desktop only.

## The owner's answers needed

1. **The local model is the Model hub's choice (recommended), or a separate choice for coding?** One choice
   means one model in memory and nothing new to learn. A separate choice would let chat stay small while
   coding uses a large model, but the two would take turns on the one server and reload it each time.
2. **May LM0 download a Qwen 27B-class GGUF** (about 17 GB, from Hugging Face, Q4)? Only after a yes. If it
   passes, should it be added to the Model hub catalogue as the recommended model for coding on computers with
   enough memory? That is adding a model, so it needs a yes too.
3. **A model that is too small for coding** (less than 32k context, or failing LM0): show it with a note
   ("May not manage coding well"), or not list it at all? Recommended: show it with the note. It is the
   person's choice, and nothing is refused.
