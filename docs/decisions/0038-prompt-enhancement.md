# ADR-0038: Prompt enhancement for every product

- **Status:** Accepted
- **Superseded in part:** by ADR-0094 (2026-10-29): the Enhance guard is removed.
- **Date:** 2026-10-08

## Context

People write prompts badly for the models: too short ("a cat"), not in the style the model likes, or not in
English. Image and video models are trained on English descriptions, and many of our users are not native English
speakers. A button that rewrites the user's text into a good prompt helps every product: a clear scene for the
image model, a single detailed paragraph with the action and the camera for the video model (LTX), a fuller
idea for the song. The platform already has a creative text model behind LiteLLM (Gemma 4, ADR-0018) and a
fail-closed guardrail (ADR-0022, ADR-0036), so this needs little new machinery.

Image to video has a particular problem found in the video tests (ADR-0037): LTX needs a prompt that
**describes the picture**, otherwise the prompt and the picture fight. A text-only enhancer cannot see the picture
and could make this worse.

## Decision

- **One endpoint per product, built from one platform helper.** `POST /products/{product_id}/prompt/enhance`
  with `{"kind": "...", "prompt": "...", "upload_id": null | "..."}`; it returns `{"prompt": "...",
  "changed": true|false}`. The product mounts it as one of its own routes (ADR-0023) using a helper in the
  platform SDK (`wasifyai_platform_sdk.enhance`), so the platform stays generic and each product decides its kinds, its
  limits and which guardrail runs. Identity is required like every other route.
- **Kinds, set per product in `product.yaml`** (`enhance:`): each kind names a prompt file, the output limit and
  whether it needs the user's picture. First kinds: `wasifyai-image`: `text_to_image`, `edit_image` (picture);
  `wasifyai-video`: `text_to_video`, `image_to_video` (picture); `wasifyai-music`: `song_idea`. An unknown kind is a 422.
- **A new alias, `prompt-enhancer`,** seeded like the others (ADR-0025): Gemma 4, thinking off, temperature
  about 0.7 (a rewrite should vary a little), editable at `/admin/models`. The product binds it with a new
  capability `text.enhance`; graph code never names the model (rule 4). The seed check in `kind-smoke` expects
  seven aliases afterwards.
- **Language.** For images and videos the result is **always English**, whatever language the user wrote in,
  because the models are English-trained; the text box then shows English the user can read and edit. For songs
  the result stays in the user's own language (the lyrics follow it). The enhancer prompts say so plainly.
- **Picture-aware for image to video and edits.** When a kind needs the picture, the request carries the
  `upload_id` of a picture the user already uploaded (ADR-0039). The route reads it from the user's own prefix only,
  asks the `multimodal` alias for a short plain description (new capability `text.describe_image`, bound to that
  alias), and gives description plus the user's instruction to the enhancer, which writes one prompt that matches
  the picture and says what moves or changes. The description is not shown or stored.
- **Safety.** The user's text is data inside a fixed prompt, never instructions. The route first runs the product's
  own guardrail on the **input** (`text.moderate`, and for pictures `text.moderate_image`) and answers `422` with
  the fixed refusal text if it fails, so the platform does not write harmful text on request. The **output** is
  not trusted either: it lands only in the text box, and when the user submits it goes through `check_request` like
  any prompt. The enhancer is told not to add real people's names, brands or sexual or violent detail.
- **Output hygiene.** The reply is stripped of quotes, markdown and preambles ("Here is your prompt"), cut at a
  sentence boundary if it passes the kind's limit, and if it is empty or equals the input the route returns the
  input with `changed: false`.
- **Limits and usage.** 40 enhancements per user per hour (the Redis counter used for uploads, in-memory fallback), a
  20 second timeout and `503` with a friendly message if the model does not answer. Every call writes a usage
  event `prompt.enhanced` with the tokens, so billing can see it (rule 9).
- **UI.** An "Enhance" button with a small sparkle icon beside every prompt box's character count (the
  `EnhanceButton` component shared by the products). It shows a spinner, replaces the text, and an "Undo" link restores the user's original. It is disabled
  while the box is empty, and in picture modes until a picture is chosen. A failure shows a short message and
  leaves the text alone.

## Consequences

- New: the SDK helper, the `prompt-enhancer` alias, two capabilities (`text.enhance`, `text.describe_image`), one
  enhancer prompt file per kind, a route in each product, the `PromptBox` component and tests with a scripted fake
  model. The `kind-smoke` alias count becomes seven; `docs/configuration.md` and each product README gain a line.
- Latency: about 2-5 seconds for text, a few more with a picture (two model calls). When a render is running, the
  model reloads next to ComfyUI and slows the render a little; it fits in memory on the 64 GB Mac and is accepted
  for now.
- The enhancer is another place a model can be wrong. Evaluation cases (a short prompt, a non-English prompt, a
  prompt that tries to instruct the enhancer, an unsafe prompt) go in each product's `evals/` and are run like the
  guardrail evaluation. Quality is a judgement; we do not claim it is measured.
- Moderation runs twice (on the input here and on the final prompt at submit). That is deliberate.

## Not in this version

Streaming the enhanced text as it is written, several suggestions to choose from, remembering a user's style, and
enhancing audio or music style tags separately.
