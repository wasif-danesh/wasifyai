# Phase 2, stage D: the assistant on desktop (plan)

Status: **Proposed 2026-10-15**, waiting for the owner's answers to the questions at the end. Implements
ADR-0057 (the assistant product) on the desktop with a managed local language model (ADR-0062: llama.cpp), the
slot manager (ADR-0056) and the model discovery and fit checks that exist today (ADR-0063).

**Goal.** On the desktop home screen, type "Ask anything", get a streamed answer from a model that runs on this
computer (or from the person's own cloud key), keep the conversation, and have the assistant make an image or
find an earlier creation when asked. No Ollama, LM Studio or other tool needs to be installed.

**Not in this stage:** web search, code execution, MCP servers, browser agents, deep research (ADR-0057),
documents and retrieval (stage E), voice, fine-tuning, image editing tools beyond `image.generate`.

## What exists and what changes

| Today | After stage D |
|---|---|
| The home "Ask anything" box says the assistant arrives later | it sends the message to the `wasifyai-assistant` product and streams the answer |
| Graphs call text capabilities through `LiteLLMTextProvider` (an OpenAI-compatible client). The desktop has no gateway (`LITELLM_BASE_URL` empty), so Enhance and moderation wait | the desktop engine points the same provider at a local `llama-server`, or at the person's cloud endpoint. **No LiteLLM on desktop** |
| The slot manager has one owner, `image` | a second owner, `chat`: loading one unloads the other, and the window says so |
| Found language models are listed as "Not used yet" (ADR-0063) | they can be selected, subject to the fit check; the catalogue offers a recommended model to download |
| Fit is checked for image models and downloads | it is checked for language models too, including the context length the person picks |
| No conversations | `conversations` and `messages` tables, indexed for search (ADR-0041), a sidebar list of Recents |

## Design

### 1. llama.cpp as an optional component, installed on demand

The same pattern as ComfyUI (ADR-0059): pinned prebuilt release per platform (macOS arm64 with Metal first),
checksum verified, installed under the app's engine folder when the person first asks (or opens the assistant),
run as a **separate process** by the engine on loopback with a random port, never started by the window. It is
a native binary of about 220 MB (measured for Unsloth's copy), with no Python environment. The provisioner and
the component card in Settings are reused. The release pin and its checksums are data (`bundle.json` style).

### 2. The text provider

`llama-server` speaks the OpenAI chat API, so the existing OpenAI-compatible provider is pointed at it. The
engine owns the process and sets the provider's base URL; the assistant graph keeps naming capabilities
(`text.generate`, tool calling), never a model. The same provider class takes a cloud base URL and a key for the
"my own key" option, which keeps one code path.

### 3. Choosing the model

One selected model per capability, chosen from: found models (discovery, GGUF only), the app's catalogue (with
download and checksums, as for klein) and a running Ollama or LM Studio (detected by discovery, used through
their OpenAI endpoint). A model that is `too_big` cannot be selected. A `tight` one needs a confirmation. The
context length is a setting with a default of 8192; the fit check uses it, so the KV cache shows in the number.

### 4. One big model at a time

`chat` joins `image` in the slot manager. Asking for an image while the chat model is resident unloads it
(llama-server is stopped, which returns its memory, or kept idle if both fit, see question 5), and the other way
round. The fit check treats the other owner's memory as reclaimable. On a computer where both fit, the person
can turn on "keep both loaded", and the check then adds the two needs.

### 5. The assistant product (ADR-0057)

One LangGraph graph with a tool-calling loop; tools are capabilities built from their manifests, explicitly
allowed (first slice: `image.generate` and search my creations). Two events are added to the contract by
ADR-0057 (`tool_call`, `tool_result`); streaming text uses the existing `token` event. A tool call that makes an
image is a normal job: queue position, progress, a card in the message, the image in My creations. Safeguards
follow the existing switch (off locally).

### 6. The window

Home becomes the chat; Recents in the side menu list conversations. The shared chat module lives in
`packages/ui` so the web app mounts the same one. The library choice (`assistant-ui` or our own components on
shadcn) is a short spike with the ADR-0057 criteria before D5.

## Order of work

| Step | What | Evidence |
|---|---|---|
| D1 | llama.cpp component: pin, install, start, stop, repair, in Settings | install and start on the Mac and in a CI job like `comfyui`; memory and start time recorded |
| D2 | Text provider on desktop, `chat` slot owner, fit for language models, model selection (found, catalogue, running server) | unit tests with a fake llama-server; a real answer from a found model on the Mac; the slot switch measured |
| D3 | Conversations and messages tables, migration, search indexing, graph without tools, `token` streaming | store contract on SQLite and Postgres; graph tests; an end-to-end chat on the desktop profile with the fake provider |
| D4 | Tools: `image.generate`, search my creations; `tool_call` and `tool_result` events; evaluation cases | tool-choice cases kept in the repository; a message that makes a real image on the Mac |
| D5 | Shared chat UI and the desktop home | component tests; the window self-test sends a message and reads the answer |
| D6 | Recommended model in the catalogue, the bake-off numbers, docs, ADR status | measured table below |

## Questions for the owner (recommended answer first)

1. **Engine.** Managed llama.cpp installed on demand, with a running Ollama or LM Studio usable as a provider
   (recommended). The alternative, "only use the person's Ollama", breaks the self-sufficient aim.
2. **The first local model.** Decide by measurement, not by name: run a short bake-off, on this Mac, of the
   candidates already on disk (a 20B model from Ollama is there, 13.8 GB) and one or two small instruct models,
   judged on answer quality in English, tool-call validity, first-token time, tokens per second and memory. The
   result becomes the catalogue's recommended download. (Recommended: yes; no download is needed to start.)
3. **Cloud key.** Optional, OpenAI-compatible endpoint only in v1 (OpenAI, OpenRouter, and others that speak
   it), kept in the operating system's keychain by the shell and handed to the engine at launch, never written
   to the settings database (recommended). The alternative is the settings store, which is weaker.
4. **Tools in the first slice.** `image.generate` and search my creations only (recommended); edits, remix and
   documents follow with their stages.
5. **Chat and image together.** Default is one big model at a time with the switch explained in the window
   (recommended: it is correct on every computer); "keep both loaded" is an opt-in shown only where the fit check
   says both fit (this Mac: 64 GB, so yes).

## Measured so far (for the bake-off)

- This Mac: Apple silicon, 64 GB unified memory; klein 4B image peaks at about 17.6 GB.
- Found language models: `gpt-oss:20b` (Ollama, 13.8 GB, estimated need 14.8 GB), embedding models
  `bge-m3` and `nomic-embed-text` (Ollama).
- Unsloth's bundled llama.cpp is 224 MB on disk (`docs/spikes/unsloth-phase0.md`).
