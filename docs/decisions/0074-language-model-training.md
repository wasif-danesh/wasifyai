# ADR-0074: Teach my assistant to write like me: language-model fine-tuning for non-technical people

- **Status:** Accepted (2026-10-18, by the owner), together with the components it names. **Revised the same day** after the owner's
  Unsloth screenshot (see ADR-0073): Unsloth Studio does train on Apple silicon, through an MLX backend.
- **Date:** 2026-10-18
- **Depends on:** ADR-0073 (training platform and the simplicity rules), ADR-0056 (one slot; llama.cpp managed),
  ADR-0063/0064 (models the person has, and the hub), ADR-0071 (the assistant's evaluation and its fine-tune gate),
  ADR-0072 (agent models), ADR-0065 (notebooks), ADR-0047.
- **Plan:** `docs/phase5-agent-training-video-builder-plan.md`, stage T2.

## Context

The owner wants to train a language model in the app, as simply as possible, reusing Unsloth.

**What fine-tuning is for.** It changes **how** a model answers (tone, format, a persona, a structured output, a
tool-calling habit, a field's vocabulary) far better than it teaches **new facts**. For "answer from my documents"
retrieval is the right tool and the app has it (notebooks, ADR-0065); fine-tuning on documents to make a model
remember them is slow, forgets other things and still invents. The assistant's fine-tune gate (ADR-0071 decision 9)
names one precise use: if a model tier cannot call our actions reliably, a small fine-tune on **synthetic examples
written from the action catalogue** may fix it.

**What Unsloth Studio gives us** (ADR-0073 has the table): language-model training of text and vision models with
**QLoRA, LoRA, Full and CPT**, LoRA variants (rslora, loftq, dora), datasets from files or Hugging Face in alpaca,
chatml, sharegpt or raw format, an **MLX backend for Apple silicon** (text and vision; no CPT, embedding models,
LoftQ or dataset streaming there), GGUF and adapter export, and a Train page with about 30 settings. The owner's
Mac showed Gemma 4 E2B with QLoRA, 30 steps, context 2,048, learning rate 2e-4 as the defaults.

**The audience.** Someone who wants "my assistant should sound like me" or "answer in this exact format". They have
a handful to a few hundred examples, not a Hugging Face dataset, and have never heard of QLoRA.

## Decision

1. **One card, "Teach my assistant to write like me", and three steps** (ADR-0073 decision 5):
   1. **Add examples.** Four ways, in plain words: **Type some** (a two-column grid: "What someone asks" and "How I
      would answer", with an Add row button and paste from a spreadsheet); **From my chats** (a list of my
      conversations, tick the good ones; the assistant's replies I edited are marked); **From a document or my
      writing** (the app drafts a question for each passage with a model and the person reviews a sample; for
      style, not for facts); **A spreadsheet** (two columns).
   2. **Check.** The app shows what it will use: the count, five sample rows, warnings in words ("Only 12
      examples: the result will mostly copy them. 50 or more is better", "3 answers are very long", "2 look like
      personal data: emails or phone numbers"), the model it chose and why ("Qwen3 4B: small, quick, already on this
      computer"), and one sentence of estimate ("about 20 minutes; chat and image making pause").
   3. **Train.** One button. A progress bar and, every few minutes, **"how it answers now"**: the same three test
      questions answered by the model so far, so the person sees it learn. Stop and resume.
   Then **Use it**: "Use in chat" (a toggle in the assistant's model picker, "My style"), "Compare" (side by side with
   the original), "Save a copy as a file", "Delete".
2. **Everything else is chosen by the app.** Method: **QLoRA** (4-bit base, small adapter) by default, **LoRA**
   when memory allows and the model is small; rank 16, learning rate and steps from the measured preset for this
   machine ("Quick", "Better"; the person sees only these two words, plus the time); context length from the examples'
   longest item; the dataset format from our own builder (always the base model's chat template). Studio's other
   options (Full, CPT, LoftQ, rslora, dora, packing, offload, W&B) live in **Advanced** (ADR-0073) and Full and CPT
   only on NVIDIA.
3. **Engine.** The **Unsloth component** (ADR-0073 decision 2): on Apple silicon its **MLX backend**, on NVIDIA
   its CUDA path. Fallback if the component is too heavy on the Mac: Apple's `mlx-lm` (MIT) directly for LoRA and
   QLoRA. Both write a standard adapter. Spike T0 measures both on 16, 32 and 64 GB Macs.
4. **Base models.** Only models that are **already on the computer or recommended by the app**, with **trainable
   weights** (Hugging Face format or an MLX conversion), a **licence that allows commercial use** (ADR-0012) and
   **no sign-in needed** where possible. The app shows the memory the run needs and the time **from measurements**;
   a model that will not fit is listed with the reason and a smaller suggestion. About 8B on a 64 GB Mac is the
   expected ceiling for v1.
5. **Data hygiene (ours, before any run):** remove duplicates, flag items over the context length, empty turns and
   likely personal data (a warning, not a block), split a validation set (10 percent, at least 20 records, fixed seed),
   format every record with **the base model's own chat template**, the same code path the server uses to serve it. A
   test trains for two steps on a fixture and checks that the served prompt equals the training prompt token for
   token; a mismatch refuses to start. Under 50 examples: the warning above.
6. **Serving.** A finished adapter becomes a **GGUF LoRA** (llama.cpp's converter) loaded with the base by the
   language server, switchable per conversation, or a **merged, quantised GGUF** if the person asks for one file. The
   adapter's card names its base so the pair cannot be separated; a mismatched adapter is refused.
7. **Evaluation, in words.** At the end: validation loss (in Advanced), **ten answers side by side with the
   original on held-out prompts**, and **our regression cases** (the assistant's 11 tool cases and, once they exist,
   the guide and action cases of ADR-0071) run on the adapted model. A fine-tune that breaks tool calling or safety
   refusals is marked "did not pass: it stopped using tools correctly". The person can still keep it.
8. **The slot and the time.** Training unloads the chat model first and needs most of the memory; the screen says
   so and refuses a run that would swap. Runs are resumable.
9. **Privacy.** Data and adapters stay on the computer. Chats and notebook text are read only after the person ticks
   them. A remote tier shows what is sent. An adapter can memorise its training data: v1 has no sharing, and "Save a
   copy" carries a warning.
10. **Starting points, so the screen is never blank:** "Sound like me" (from chats or examples), "Always answer in this
    format" (a structured output such as JSON), "Use our company's words" (a glossary), and a hidden one for the
    assistant's tool-calling gate (ADR-0071). Each fills the builder and the preset.

## Consequences

- A person can adapt a small local model privately in three steps, and the assistant has a documented fix if a model
  tier cannot use our tools.
- Two engines support one result format; GGUF LoRA conversion must be tested per architecture the hub offers; the
  descriptor lists the supported ones and the rest are not offered.
- The template test and the regression suite make "my fine-tuned model is worse" visible instead of silent.
- Memory pressure on small Macs is real: many people will see "this model does not fit here", and the honest answer
  is a smaller model or a rented GPU.

## Alternatives considered

- **Show Studio's Train page.** Rejected (ADR-0073): it is the screenshot the owner asked us to simplify.
- **Train facts into the model.** Rejected as the main use: retrieval is better and exists.
- **Full fine-tuning on the simple path.** Memory and forgetting; Advanced on NVIDIA only.
- **Hosted fine-tuning APIs** (a provider's). Possible as a tier later; they send data away and tie the model to one
  provider.

## Open questions

1. Which model families convert cleanly to a GGUF LoRA today: the T1 spike fills the descriptor.
2. Whether "from a document" produces good style data without a human check; the sample review is the guard.
3. The size at which MLX QLoRA stops being comfortable on 16 GB.
4. Whether "My models" can serve the agent (ADR-0072): it needs 64,000 tokens of context, which a small fine-tune does
   not change.
5. Studio's MLX trainer for vision models: a later card ("teach it to read my receipts").

## Not in v1

Preference tuning; continued pre-training and full fine-tuning on the simple path; embedding, audio or vision language
models; merging several adapters; sharing adapters; training on a schedule from new chats.

## Amendment after spike T0 (2026-10-19; `docs/spikes/training-t0.md`)

- **Verdict: T2 Go for small models; conditional for 9B.** Qwen3-0.6B and Qwen3.5-0.8B train in under 30 s, learn the
  style (0 of 12 held-out replies carried the sign-off before, 12 of 12 after), convert to a GGUF LoRA and serve.
- **Engine (decision 3):** Unsloth is the default engine and `mlx-lm` the fallback for small Qwen3 models.
  Unsloth was lighter on Qwen3.5 (1.76 GB against 6.33 GB for mlx-lm on the 0.8B), so the 9B on a 16 GB Mac may need
  Unsloth's chunked loss: **measure before promising it**.
- **Chat template (decision 5):** formatted text equals the model's own template (44 of 44), but the served prompt
  equals the training prompt **only with thinking switched off** (44 of 44; 0 of 44 with thinking on, for Qwen3 and
  Qwen3.5). Training and serving both disable thinking, and the round-trip test enforces it.
- **GGUF LoRA (decision 6):** llama.cpp's converter works for Qwen3 and Qwen3.5 and `llama-server --lora` applies the
  result. Unsloth's own PEFT export refuses Qwen3.5 adapters; a 30-line converter of ours fixes it (identical to
  Unsloth's output on Qwen3).
- **Not measured:** Qwen3.5-9B (ADR-0078's recommended base), the 16 and 32 GB tiers.
