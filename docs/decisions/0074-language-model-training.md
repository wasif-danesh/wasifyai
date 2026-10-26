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

## Built (2026-10-26): stage L1, "Teach my assistant to write like me" on the desktop

Built and run for real on the owner's Mac (M5 Pro, 64 GB) with the real model, through the real screen. What is true:

- **Engine: `mlx-lm` first, as the amendment of 2026-10-19 allowed.** `services/api/src/wasifyai_api/desktop_language_training.py` runs
  `mlx_lm.lora` as a separate process (LoRA rank 16 on every projection, answer-only loss, learning rate 2e-4, a held-out loss before and after,
  a checkpoint every 25 steps) and `language_answer.py` asks the same environment how a model answers, greedy and with thinking off. It holds the
  one big-model slot, kills the process group on stop, and samples memory. Unsloth's MLX backend stays the other engine: both write a standard
  adapter, and the base descriptor is where an engine is chosen. Reason for `mlx-lm` first: measured 0.06 s a step and 0.98 GB on Qwen3-0.6B
  against 0.31 s and 1.19 GB, MIT instead of a 2.1 GB AGPL environment; it holds 6.3 GB on Qwen3.5 0.8B (Unsloth 1.8 GB), which is why only the
  measured Qwen3 0.6B is offered.
- **Measured on the real model** (the T0 fixture, 50 questions with a sign-off style; Qwen3-0.6B 4-bit): 69 steps in **8 to 13 s**, **1.27 GB**
  peak, held-out loss **5.28 to 2.56** (52 percent closer), the sign-off in **4 of 4** new answers against 0 of 4 before; a whole run through the
  routes (before answers, training, after answers, the card) takes **16 s**. The answers are in the person's style but a model this small can say
  something wrong ("The picture shows a copy of the model's style…"): the descriptor says "it picks up a style or a format, not new facts" and
  the Check step shows that sentence.
- **Product (`products/wasifyai-training`):** `language.py` (clean, checks in words, split, chat records, steps, test questions: at least 10
  examples, a warning under 50, long answers and personal data warned about and never refused, a tenth kept back with a fixed seed, at least 2 and
  at most 20), `writing.py` (the run manager: asks the test questions, teaches, asks again, keeps the adapter as a model with its card: the
  answers before and after, the held-out loss, a mark **passed when the held-out loss falls by 20 percent**, the statement of rights),
  `writing_routes.py` (`/train/writing/status|sets|sets/{id}|sets/{id}/examples|sets/{id}/runs|models/{id}/ask`), store tables `writing_sets` and
  `examples`, and the runs and models tables as they were (`settings.family = "language"`, model `kind = "writing"`). One run at a time across
  pictures and writing; "busy" means teaching, not the usage record or the search index after it (a real run found that a question asked right
  after a run was refused while the index was slow).
- **The choice (D30):** `bases.py` has a second descriptor, Qwen3 0.6B 4-bit, engine mlx-lm, default method QLoRA (the weights are 4-bit, so LoRA
  is listed with that reason; full fine-tuning is listed with "needs an NVIDIA graphics card"); `GET .../writing/status` carries the rows.
- **Set up in the app (`language_setup.py`):** the same shape as the picture trainer's: `mlx-lm` 0.31.3 from a committed hashed lock
  (`scripts/lock-language-trainer.sh`; 34 packages, no torch; **64.3 MB** of wheels by PyPI's own metadata) and the model's 9 files pinned by size
  and SHA-256 (`mlx-community/Qwen3-0.6B-4bit` at revision `73e3e38d`, Apache-2.0, **351.4 MB**), `/desktop/language-setup`, a consent card with
  the size repeated on the button, resumable, removable; the bundle script copies the lock. **Run for real (2026-10-26, owner's yes for the 416 MB):** on a clean data folder the screen offered
  415,683,618 bytes, the button downloaded and set it up in under a minute (the environment 342 MB on disk, the model 335 MiB, every file checked
  against its pin; `mlx_lm 0.31.3`, `mlx 0.32.3` start from it), and a run with only what the app had installed trained 69 steps in **9.9 s** at
  **1.0 GB**, held-out loss **5.27 to 3.02** (43 percent closer, passed), in the taught style and with invented facts ("press Share" for
  working offline), as the descriptor says a model this size does. The older figures above are from the spike's own conversion of the model.
- **The screen (`packages/ui/src/training/Writing.tsx`, `use-writing.ts`):** the language card is live; Start opens a list of sets; the set is a grid
  of "What someone asks" and "How I would answer" (saved as it is typed, pasted from two spreadsheet columns), the check in words, whose they are,
  Quick or Better, **Teach it**, a progress bar with Cancel, then the same questions before and after side by side, a mark, and "Ask both something new".
  A trained writing model appears under My models with "See what it learnt". Walked in a real browser against the real engine and model.
- **The action:** `train.start` takes `set_id` (a set of examples) instead of `dataset_id` (the catalogue has a guard of 50 actions, ADR-0068, and a
  second action would have been the 51st); its help file has a section for it. Searchable like every trained model (name and kind).
- **Not built (next stages):** (L2) **use it in chat**: a GGUF LoRA (llama.cpp's converter plus our Qwen3.5 fix, ADR-0074 decision 6) and "My style"
  in the model picker; the served prompt must equal the trained one with thinking off (a round-trip test); (L3) more base models (Qwen3 1.7B, 4B, 8B)
  measured on this Mac, each a descriptor and a consented download; (L4) the other example sources (from my chats, from a document), the regression
  cases of ADR-0071 (a fine-tune that breaks tool calling is marked "did not pass"), pause and resume, "Better" measured against "Quick" on a
  real set; (L5) the web; Windows and Linux (NVIDIA, Unsloth). A real person's writing is not yet measured: the only data so far is the fixture.

## Built (2026-10-26, later): stage L2, chat with a taught writing model

Run for real on the owner's Mac: trained through the screen, converted, served by the app's own `llama-server` and asked through the assistant.

- **A fault found by serving it, and fixed at the root.** The first adapters made by the product started some chat answers with a stray `</think>`
  (a 30-step adapter: 6 of 6; the product's 69-step one: 1 of 6; the untaught base: 0 of 6). Cause: `mlx-lm` renders the training text with the
  chat template's default, which is thinking on, so the template's empty `<think></think>` block sits in the *answer* and is learnt as something to
  write; chat serves with thinking off, which puts that block in the *prompt*, and the adapter wrote it again. (ADR-0074's thinking-off rule was
  right but the trainer did not follow it: `mlx-lm`'s tokenizer wrapper asks for thinking whenever a model has the tokens for it.)
  **Fix:** `language_train.py` runs `mlx_lm lora` with `TokenizerWrapper.has_thinking` false, so the block is in the masked prompt and the loss
  covers only the answer, which is what is served. Measured through llama-server on the same data: **0 of 6 stray and 6 of 6 in the taught style at
  30 steps, 69 steps and 69 steps at half the learning rate** (before: 6/6 stray and 0/6 signed at 30 steps).
- **GGUF LoRA (`gguf_lora.py`, decision 6):** the mlx-lm adapter is turned into the file `llama-server --lora` loads by a small writer of our own, no
  new dependency (a GGUF file is a header, key values, tensor infos and aligned data): the tensors are moved into PEFT's layout under llama.cpp's
  names, with `alpha = scale x rank`. Checked against llama.cpp's own converter on the spike's adapter (the same 392 tensors and shapes, largest
  difference 1.5e-5, half-precision rounding) and by serving it in the app's `llama-server` b11655 (6 of 6 in the taught style). Qwen3 only; any
  other architecture is refused in words. (Qwen3.5 needs the layout of its fused tensors: with L3.)
- **The chat copy (`language_chat_pins.json`):** a taught adapter is served on a GGUF of the same base, `Qwen/Qwen3-0.6B-GGUF` Q8_0 (**639 MB**,
  Apache-2.0, revision and SHA-256 pinned), fetched once through the same checked, resumable downloader, asked for only when a taught model is first
  used in chat, with its size shown before anything is fetched. Its pins are a file of their own so that asking for it never makes the installed
  trainer look out of date. **Run for real with the owner's yes (2026-10-26):** through the screen (the consent card showed
  "639 MB, Apache-2.0, from huggingface.co" and nothing moved until the button), **38 seconds**, the file exactly the pinned 639,446,688 bytes and its
  SHA-256 the pinned one; a model taught on the 4-bit base then answered through the assistant on this Q8 file with the adapter on top: all three
  questions in the taught style, signed, no stray tag (the earlier real test used the spike's f16 file).
- **Chat (`desktop_language.py`):** the chat selection can carry an adapter (`lora`, `style`): the engine starts `llama-server` with `--lora`, thinking
  is always off for it (the window's switch cannot turn it on), what was chosen before is kept (`previous`, saved, so it survives a restart) and
  `end_style` gives it back; choosing another model replaces a taught one for good; deleting the taught model, or its adapter file disappearing,
  gives chat its earlier model back instead of a server that will not start.
- **The screen:** under the result of a run and under My models, "Chat with it": Use in chat (or, first, the consent card with the size), "Back to my
  chat model", and a line that says it keeps the style and can still get facts wrong. Routes: `POST .../writing/models/{id}/use`,
  `DELETE .../writing/use`, `GET|POST /desktop/language-setup/chat-copy[/install|/cancel]`. The chat's model name shows "My style: ...".
- **Measured through the assistant** (the T0 fixture, Qwen3-0.6B f16 + the adapter): three questions through `wasifyai-assistant`'s own run, all three
  answered in the taught style and signed, no stray tag. A 0.6B model inside the assistant's long prompt still says wrong things (it is for style).
- **Not built:** the "My style" row in the model picker itself (the button on the card is the way to it for now); Qwen3.5 and bigger bases (L3); the other example sources and regression cases (L4); the web and other computers (L5).

## Built (2026-10-26, later still): stage L3, more base models, measured on this Mac

The owner approved downloading Qwen3 1.7B and 4B (about 7.6 GB with their chat copies). Built and run for real through the app's own downloader.

- **Several bases, fetched on request.** `language_more_bases.json` pins, for each extra base, the MLX weights (`mlx-community/Qwen3-1.7B-4bit` and `-4B-4bit`, Apache-2.0, 9 files each with size and SHA-256,
  revision fixed) and the chat copy its adapters are served on (`Qwen/Qwen3-1.7B-GGUF` Q8_0, 1.83 GB; `Qwen3-4B-GGUF` Q4_K_M, 2.50 GB, SHA-256 from the hub's LFS record). The first base
  stays set up with the trainer; the others are asked for one part at a time (its weights, or the chat form of it), with the size shown and repeated on the button, resumable, checked, and removed with the
  component. `language_setup.py` has a catalogue (`BaseSpec`), per-base finders (`find_model`, `find_chat_copy`), `fetch_start|cancel` and `/desktop/language-setup/bases[...]`; the single chat-copy
  route of L2 became the per-base one (a development file named by `WASIFYAI_LANGUAGE_CHAT_COPY` is only for the first base).
- **Measured on the owner's M5 Pro (64 GB), the T0 fixture (50 questions), Quick (69 steps), through the real routes:**

  | base | training | memory | whole run | held-out loss | closer to how you write |
  |---|---|---|---|---|---|
  | Qwen3 0.6B | 7.8 s (0.113 s a step) | 1.3 GB | 14.1 s | 5.53 to 2.94 | 47 percent |
  | Qwen3 1.7B | 12.7 s (0.184 s a step) | 2.0 GB | 20.7 s | 7.58 to 2.51 | 67 percent |
  | Qwen3 4B | 19.4 s (0.281 s a step) | 3.8 GB | 29.7 s | 7.98 to 2.27 | 72 percent |

  Time grows with size far less than the parameters do (6.7 times the parameters, 2.5 times the time), memory by about 1 GB per 1.5 GB of weights; **a larger base fits the held-out answers
  better** (the final loss falls 2.94, 2.51, 2.27). Each descriptor in `bases.py` carries its measured seconds a step, the overhead of a run (loading, asking before and after: 6.3, 8.0 and 10.3 s),
  the memory it held and the sentence the screen shows ("Measured here: ..."); the estimate on the Check step is `steps x seconds a step + overhead`. One fixture on one Mac: how it behaves on real
  writing, and on 16 and 32 GB Macs, is not measured. **8B was not downloaded** (not approved; the next step if wanted: 4.6 GB + 5.0 GB).
- **Chat with each, for real:** the chat copies were fetched through the screen's own routes (1.7B Q8_0, 1.83 GB, 2,980 s; 4B Q4_K_M, 2.50 GB, 4,088 s, on a connection that gave about 0.45 MB/s;
  both whole and checked), each taught model was used in chat and asked four questions through the assistant: **4 of 4 in the taught style and signed, 0 of 4 with a stray tag, for both**
  (4 answers in 8 s on either). A model taught on the 4-bit weights and served on an 8-bit (1.7B) or a 4-bit K-quant (4B) chat copy keeps its style. What they say is still invented
  ("press Crop or resize", "choose Update") as it must be: the fixture teaches a way of answering, not the app.
- **Downloads on this connection:** 1.7B's 984 MB took 66 s; 4B's 2.28 GB was interrupted once (the downloader said so and continued from where it stopped on the second try) and took 56 minutes in all;
  the connection later gave 0.45 MB/s, so the chat copies take long: the screen's progress bar and Stop matter.
- **The screen:** the Check step has "Which model?": the models with what each is good for and "Measured here: ...", the recommended one marked; one that is not on this computer is chosen like the
  others and has "Get it (size)" next to its name; Teach it waits (and says why) until it has arrived, then the plan is read again. "Chat with it" asks for the chat copy of the model's own base.
  A refusal for a missing base says which and what to do.
- **Not built:** 8B and Qwen3.5 (its fused tensors need their own GGUF layout, and a thinking-off check of its own); the "My style" row in the model picker.
