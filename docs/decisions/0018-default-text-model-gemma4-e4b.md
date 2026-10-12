# ADR-0018: Default text model: Gemma 4 E4B

- **Status:** Accepted
- **Date:** 2026-10-08
- **Supersedes:** the prototype LLM line of ADR-0015 (`gpt-oss:20b`)

## Context

`gpt-oss:20b` is text only, and the project needs a multimodal model. It also needs about 16 GB
of RAM and a 13 GB download, which makes testing on ordinary laptops (Intel Macs, Windows via
WSL2, Linux) slow or impossible.

## Decision

Use **Gemma 4 E4B** (`gemma4:e4b` on Ollama, Apache 2.0, text and image input, 128K context) as
the default for every chat alias (`default-chat`, `lyrics-writer`, `moderator`) during the
prototype. Around 8 GB of RAM is enough, so every supported platform can run the stack.

Models stay behind LiteLLM aliases (ADR-0005, ADR-0010), so moving an alias to a larger model,
for example `gemma4:12b` for `moderator` and `lyrics-writer` in staging, is a one-line change in
`services/api/src/wasifyai_api/model_defaults.yaml`, or a few clicks in the admin area
(ADR-0025). Embeddings are unchanged
(`nomic-embed-text`, ADR-0017).

## Measured on the prototype (Apple Silicon, 2026-10-08; small samples, treat as indicative)

- **Image input works** through LiteLLM (a solid red image was identified as "Red").
- **Ollama reports** vision, audio, tools and thinking for `gemma4:e4b`; audio input was not
  exercised yet.
- **Thinking is on by default.** Reasoning is returned in a separate `reasoning_content` field
  and **counts against `max_tokens`**: with a small budget the visible `content` came back
  empty. It also raises latency and billed output tokens.
- **Lyrics JSON test** (8 song ideas, JSON-schema output, 3000-token budget):

  | | Valid JSON | `[verse]`+`[chorus]` tags | Avg time | Avg output tokens |
  |---|---|---|---|---|
  | Thinking on | 8/8 | 5/8 | 8.1 s | 948 |
  | Thinking off | 8/8 | 7/8 | 4.2 s | 447 |

  So thinking did not help this task. It is switched off per alias in config
  (`think: false` in `services/api/src/wasifyai_api/model_defaults.yaml`) for
  `default-chat` and `lyrics-writer`. The `moderator` keeps thinking until a refusal evaluation
  exists. Tag compliance is not perfect, so the lyrics node needs validation and a retry.

## Consequences

- Always give generous `max_tokens` (or none) for aliases with thinking on.
- The capability layer is text-only today: `caps.text.stream(name, system, prompt)` cannot pass
  an image. Image (and audio) input needs an API extension before a product can use it.

- Smaller model: expect weaker lyric quality and less reliable JSON and refusal behaviour than a
  12B-class model. The mandatory `check_request` guardrail should be evaluated on E4B and, if it
  falls short, moved to a larger model before any public use.
- Whether audio input is available on E4B is stated inconsistently by Google and Ollama; verify
  before building on it.
- Setup and docs now assume about 8 GB of RAM and roughly 10 GB of free disk for the models.
