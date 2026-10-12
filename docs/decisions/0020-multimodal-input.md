# ADR-0020: Multimodal input in the capability layer

- **Status:** Accepted
- **Date:** 2026-10-08

## Context

The default model, Gemma 4 E4B (ADR-0018), accepts text, images and audio, but the capability
layer only passed strings. Testing showed LiteLLM's native Ollama route (`ollama_chat/`) handles
images but rejects audio parts (HTTP 500), while Ollama's OpenAI-compatible API (`/v1`) accepts
text, image, audio and combinations. On that route Gemma "thinks" by default and ignores the
`think` switch; `reasoning_effort: none` turns it off reliably.

## Decision

- **API:** a prompt is a string or a list of parts: strings, `Image` and `Audio`
  (`wasifyai_platform_sdk.parts`). `caps.text.stream/complete(name, system, prompt)` accepts either, so
  existing graphs are unchanged. Limits: images up to 10 MB (png, jpeg, webp, gif), audio up to
  25 MB (wav, mp3). Messages with only text stay plain strings.
- **Declared modalities:** each binding lists the inputs its model accepts (`inputs: [text, image,
  audio]`, default `[text]`). Passing anything else raises `UnsupportedInput` before any call.
- **Routing:** a new LiteLLM alias `multimodal` runs `gemma4:e4b` through Ollama's `/v1` endpoint
  (`openai/` provider in LiteLLM, still behind the gateway per rule 5) with
  `reasoning_effort: none`. Capabilities that take image or audio bind `model: multimodal`; text-only
  capabilities keep their existing aliases. The Helm chart marks such entries with
  `backend: ollama-openai`, which selects the `/v1` base URL and makes the Ollama pod pull the model.
- **Files stay in storage:** graph state holds only storage keys (rules 7 and 10). A graph loads
  the bytes with `caps.storage.get(key)` and builds the part with `part_from_file(key, data)`, which
  picks the type from the extension. `ScopedStorage` confines keys to the caller's tenant, product
  and user. The `hello` graph demonstrates this with `image_key` and `audio_key` run inputs.
- **Usage:** calls with media record the usual token counts (image and audio cost is inside the
  provider's prompt tokens) plus `meta.inputs` such as `{"images": 1, "audio": 1}`.

## Consequences

- Verified on the real model: image colour recognition, exact audio transcription, and both
  together; bad keys (traversal, missing, unknown type) end in a clean `error` event.
- **No upload endpoint yet.** Users cannot put files into storage through the API, so `image_key`
  and `audio_key` only work for files placed there by other means. A secured upload route (size and
  type limits, identity required) is a public API addition and needs its own decision before the
  first product accepts user files.
- **Audio is not yet verified for quality** beyond a clear synthetic sentence; evaluate on real
  recordings before relying on it. Short clips only, because the model's audio context is limited.
- `reasoning_effort` is honoured on the `/v1` route and `think` on the `ollama_chat/` route; the
  two aliases use the matching setting. A future LiteLLM release may remove the difference.
- Supersedes the note in ADR-0018 that the capability layer is text-only.
