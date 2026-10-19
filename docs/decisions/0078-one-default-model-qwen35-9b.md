# ADR-0078: One default model for the app: Qwen3.5-9B

- **Status:** Accepted (2026-10-18, by the owner). **The switch of each alias waits for the checks below**; until a
  check passes, that alias stays as ADR-0018 left it.
- **Date:** 2026-10-18
- **Supersedes:** the default-model decision of ADR-0018 (Gemma 4 E4B for every chat alias), and the Gemma 4 E4B
  routing of the `multimodal` alias in ADR-0020 and the default text alias note in ADR-0060, once the checks pass.
- **Depends on:** ADR-0072 (the agent needs a large context), ADR-0071 (assistant evaluation), ADR-0022 (guardrail
  evidence), ADR-0056 (managed llama.cpp, the one slot), ADR-0012 (licences), ADR-0074 (fine-tuning base).

## Context

The owner's direction: the agent should run on **Qwen3.5-9B**, which offers more context than our current default,
and it should **replace Gemma as the app's default so the app keeps one model** (one download, one slot, one thing
to evaluate and to fine-tune).

What is known (Hugging Face, read 2026-10-18):

- `Qwen/Qwen3.5-9B`: **Apache-2.0**, 9.65 B parameters, architecture `qwen3_5`, task *image-text-to-text* (so it
  takes images, which the `multimodal` alias needs; **audio input is not claimed**). GGUF builds (Unsloth,
  bartowski, LM Studio) and MLX 4-bit and 8-bit builds exist, so both our runtimes can load it.
- `Cloudflare/clef-flash`, a decision model, is a post-train of Qwen3.5-9B (ADR-0075): the same backbone family
  serves chat, the agent and the sorter.
- Gemma 4 E4B (ADR-0018) is Apache-2.0, text and image, 128K context claimed, and runs in about 8 GB of RAM.

Not known and not to be assumed: the **context length and memory use of Qwen3.5-9B on our runtimes** (the 64,000
tokens Hermes needs, with the cache, on a 32 and a 64 GB Mac), its **speed** on the owner's Mac, whether it
**thinks by default** (Gemma did, ADR-0018), its **tool-calling** and **JSON** reliability, and whether it still
passes the **guardrail** cases. A 9B model is roughly twice Gemma E4B in weights: a 16 GB Mac is tight, an 8 GB
machine cannot run it.

## Decision

1. **Qwen3.5-9B becomes the default for the aliases that use a local chat model** (`default-chat`, `lyrics-writer`,
   `moderator`, `multimodal`, `prompt-enhancer`, the assistant and the agent), **one alias at a time**, each after
   its check passes:

   | Alias | Check before the switch | Evidence it must beat or match |
   |---|---|---|
   | `moderator` | The 70-case guardrail set, 3 repeats | ADR-0022: Gemma E4B was sufficient |
   | `default-chat`, assistant | The assistant's 11 tool cases and the guide cases of ADR-0071 | the current pass rate |
   | `lyrics-writer`, `prompt-enhancer` | The 8-idea JSON and tag test, thinking off | ADR-0018's table |
   | `multimodal` (captions, picture checks, ADR-0076) | A set of described pictures, including faces and mascots | Gemma E4B's descriptions |
   | agent | 64,000 tokens of context on 32 and 64 GB, one real task (G0), the agent evaluation (G3) | the hosted-model result |

2. **Thinking** is off by default for these aliases, as for Gemma (ADR-0018), unless the check shows a gain; the
   agent may turn it on.
3. **Memory.** The setup and the docs say the minimum is now what the measurement says (to be written by the first
   check), not 8 GB. On a machine that cannot run it, the app **keeps Gemma 4 E4B as the low-memory choice** (or a
   smaller Qwen3.5 if one exists and passes the same checks), with the agent shown as "needs a hosted model" through
   the `agent-ready` mark (ADR-0072). The owner's wish for one model holds on machines that can run it.
4. **Fine-tuning** (ADR-0074) uses Qwen3.5-9B as the recommended base on machines with the memory for it, and the
   chat-template round-trip test applies to its template.
5. **The model stays behind aliases** (ADR-0005, ADR-0010): the switch is a change in `model_defaults.yaml` and in the
   desktop recommended-model list, not in code, and can be undone by one line.
6. **The licence is re-read from the model files**, not only from the Hugging Face tag, when the model is added to
   the recommended list (ADR-0012).

## Consequences

- One local model to download, evaluate, fine-tune, serve and explain, and a context large enough for the agent
  without a second model.
- A bigger first download and more memory; small machines get a fallback and a clear message.
- ADR-0018's evidence (the guardrail and the lyrics test) is re-run, not assumed, so the switch is visible and
  reversible.
- Docs that name Gemma (ADR-0018, ADR-0020, ADR-0022, ADR-0038, ADR-0060, the setup guide) are updated as each alias
  switches, not before.

## Alternatives considered

- **Keep Gemma 4 E4B and add Qwen3.5-9B for the agent only.** Two local models, two downloads, two slots swapping;
  the opposite of the owner's wish.
- **Gemma 4 12B for everything.** Larger context is not shown for it either; no reason to pick it over the model the
  agent and the sorter already share.
- **Hosted model only for the agent.** Kept as the path for small machines (Hugging Face and GitHub first, ADR-0072).

## Open questions

1. Qwen3.5-9B's real context, memory and speed on 16, 32 and 64 GB Macs in our llama.cpp and in MLX (G0).
2. Whether the Ollama library has a build (the desktop uses managed llama.cpp, ADR-0056, so this only matters for the
   web and Compose stack).
3. Whether a smaller Qwen3.5 exists to serve 8 GB machines.
4. Audio input (Gemma's was never confirmed either): not required.

## Amendment after spike G0 (2026-10-19; `docs/spikes/agent-g0.md`)

- **Open question 1 is answered for the owner's Mac (M5 Pro, 64 GB, llama.cpp Metal, Q4_K_M):** a 62,038-token prompt ran;
  two of two hidden-fact lookups at 62,056 tokens were exact; **about 8 GB of memory in total at 64k**. Prompt reading
  1,080 / 858 / 686 tokens/s at 8k / 32k / 62k; writing 39.3 / 37.4 / 28.5 tokens/s.
- **Thinking is on by default** and is switched off with `--reasoning off` (server) or
  `chat_template_kwargs {"enable_thinking": false}` (request): this ADR's decision 2 holds.
- **Tool calling:** 10 of 10 small cases, with thinking on and off. The assistant's 11 cases and the guardrail set
  (decision 1's checks) are still to run.
- **Still not measured:** 16 and 32 GB Macs. The minimum-RAM line in decision 3 is **not written yet** and waits for
  those measurements.
