# Phase 2, stage D: the assistant on desktop (plan)

Status: **Approved 2026-10-15** with all five recommended answers below (owner: "all recommended"). **D1, D2 and D2b done**
(see the evidence sections at the end); D3 to D6 not started. Implements
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
| Found language models are listed as "Not used yet" (ADR-0063) | they can be selected, subject to the fit check; the model hub (ADR-0064) lets the person find and download others |
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

One selected model per capability, chosen from: the model hub's On device list (found models, GGUF only, and
what the app downloaded), the hub's Discover tab (ADR-0064, with download and checksums) and a running Ollama or LM Studio (detected by discovery, used through
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
| D2b | Model hub (ADR-0064): Discover and On device tabs, the Hub client in the engine, downloads of Hub models, the curated shelf | Hub client tests against a fake Hub (search, files, checksums, gated, offline, rate limit); a real search and a confirmed download of a small model on the Mac; the fit badge per variant |
| D3 | Conversations and messages tables, migration, search indexing, graph without tools, `token` streaming | store contract on SQLite and Postgres; graph tests; an end-to-end chat on the desktop profile with the fake provider |
| D4 | Tools: `image.generate`, search my creations; `tool_call` and `tool_result` events; evaluation cases | tool-choice cases kept in the repository; a message that makes a real image on the Mac |
| D5 | Shared chat UI and the desktop home | component tests; the window self-test sends a message and reads the answer |
| D6 | Recommended model in the catalogue, the bake-off numbers, docs, ADR status | measured table below |

## Decisions (all five approved as recommended)

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

## D1 evidence (2026-10-15): the llama.cpp component

- **Pin:** llama.cpp release `b11655`, one archive per platform in `engine-manifest.json` (macOS arm64 with
  Metal, macOS x64, Linux x64 and arm64, Windows x64; processor builds off the Mac). The five SHA-256 values and
  sizes were checked by downloading each archive, not only read from the release page.
- **Installer** (`llamacpp.rs`): check, download (checksum and size), unpack, verify (`llama-server --version`),
  `state.json`. Four steps, no Python. The archive extractor now keeps symbolic links that stay inside the tree
  (the Mac and Linux archives are made of them) and refuses any that do not; zip archives are unpacked the same
  way. Tests: install, wrong checksum, no server in the archive, a server that does not start, unsupported
  platform, link safety.
- **Engine** (`llama_server.py`): finds the install from `state.json`, starts one `llama-server` on loopback
  and a free port for one model, restarts when the model or context changes, stops it to give memory back, and
  names the usual failures (not installed, model file gone, unknown architecture, out of memory).
  `GET /desktop/language-engine` and `POST .../stop` report and stop it.
- **Window:** Settings has a "Language models" card (set up, progress, installed version and backend, repair).
- **On the owner's Mac (M5 Pro, 64 GB):** installed through the window's self-test in 3 s (12 MB archive);
  `b11655` with Metal loaded a 13.8 GB gpt-oss 20B file found in Ollama's folder and answered a chat request in
  4.7 s including the model load. A 1.2 MB test model loads and answers in 0.6 s.
- **Two findings:**
  1. **Ollama's own gpt-oss file does not load.** It stores the architecture as `gptoss`, which llama.cpp
     refuses ("unknown model architecture"). A llama.cpp-format file of the same model (also in the Ollama
     folder, named `llamacpp:...`) loads. Discovery now marks `gptoss` as unsupported with that reason, and the
     engine turns the server's message into a plain sentence. Expect more tool-specific names: the real answer is
     to try to load, which D2's model selection does.
  2. **Off the Mac the build is processor-only.** The fit check (`desktop_fit.py`) must treat the engine as
     `cpu` when the installed backend is `cpu`, even on a computer with an NVIDIA card; CUDA and Vulkan builds
     are a separate pin to choose later. D2 passes the backend into the fit check.
- **CI:** a `llamacpp` job installs the component through the window's self-test on macOS, downloads a 1.2 MB
  model pinned by commit and SHA-256, starts the installed server on it and asks for an answer.

## D2 evidence (2026-10-16): the chat model, the provider and the slot

- **Provider.** On the desktop every `litellm` text binding of a product resolves to `LocalTextProvider`
  (`ProviderDeps.text_provider`), so Enhance and the other text capabilities of the products need no change.
  It streams from the chosen model through the OpenAI chat API, records token usage, refuses a prompt that
  carries a picture (a text model), and when nothing is chosen answers with a plain sentence that points to
  Models. Embeddings from a local model wait for the documents stage.
- **Choosing** (`LanguageService`, `/desktop/language`): a found GGUF file that the engine can run and the
  computer can hold (the fit check, at the chosen context length, with the engine's own backend: a processor
  build ignores a graphics card), or a model of a running Ollama or LM Studio (only a server the engine itself
  found on loopback, and only a model it listed). The choice is kept across restarts. A file with no chat
  template of its own is chosen with a note.
- **The slot.** `chat` is a second owner next to `image`. A file runs in the app's own `llama-server` while the
  `chat` slot is held: an image model is unloaded first, and an image job started afterwards stops the chat
  model, giving its memory back. A model of an external tool never takes the slot (its memory is its own).
- **Window.** Models has a "Chat model" card: the chosen model with a context-length choice, a try-it, and the
  list of files and running models with their fit badge and "Use for chat".
- **On the owner's Mac** (llama.cpp b11655, Metal, a 13.8 GB gpt-oss 20B file from the Ollama folder):
  choose, then try: 3.5 s including the load; Enhance through the product route: 5 s; the model stays loaded
  after a chat (`running: true`); an image job unloaded it in under a second; the next chat reloaded it in 3.4 s.
- **Findings.**
  1. **Ollama's files often carry no chat template** (it keeps templates beside the file, in its own syntax).
     The engine then falls back to a generic template, and a reasoning model like gpt-oss shows its working in
     the answer. The file chosen here had none (checked in 0.05 s from the header), and the answers read
     accordingly. The window now says so when such a file is chosen. The fix is a model file that has its
     template (Hugging Face, LM Studio, Unsloth), or the same model through a running Ollama; the model hub
     (D2b) is how people get such files.
  2. **Reasoning models need their template to separate the thinking from the answer.** With the right template
     llama-server returns the thinking apart from the content; without it Enhance would paste the thinking
     into a prompt. D4 should add an output guard for Enhance (reject an answer that starts like a plan).

## D2b evidence (2026-10-16): the model hub

- **Engine** (`desktop_hub.py`): a Hugging Face client with a ten-minute cache and a stale answer when
  offline; search (`filter=gguf` for language and embedding, a pipeline for image and video); one repository
  with its variants (quantisation from the file name, shards grouped, vision projectors left out, a file with
  no published SHA-256 never offered), its licence, architecture, context length and whether it carries a chat
  template; the model card as plain text; and the download, rebuilt from a fresh look at the repository
  (commit-pinned URLs, the repository's own sizes and checksums) and refused if the confirmed list differs.
- **Files** go to `<models>/language/<publisher>--<repo>/`; discovery scans that folder as "Wasify AI", so a
  downloaded model appears in On device with its fit and can be chosen for chat or deleted (only files under
  that folder can be deleted).
- **Window**: Models has On device and Discover tabs. Discover shows the recommended list without any
  network, asks before the first request, then searches with a kind and a sort, shows a result list and a
  detail panel with variants, fit badges and a confirmation. Settings has the browsing switch.
- **On the owner's Mac, against the real Hugging Face:** search 0.4 s; the repository 0.3 s; Qwen3 0.6B at
  Q4_K_M (397 MB) downloaded and verified in 43 s; it appeared in On device as fits; chosen for chat with no
  template note; try-it 1.1 s; Enhance through the product route 2.1 s, returning a clean prompt (the same
  route returned reasoning text with the Ollama file that had no template: D2 finding 1 is fixed by getting a
  file that has its template).
- **Not done:** the keychain token and sign-in for gated models; the memory and disk header; image and video
  models are view-only until stage C and the video stage have workflows to run them.
