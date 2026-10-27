# Models, the language engine and the hub on the desktop

Part of [the desktop profile](../desktop-profile.md): what is built, how it is wired, what is not done.

## Finding models other tools left here (ADR-0063)

The engine looks, by itself shortly after it starts, in the known folders of Ollama, LM Studio, the Hugging Face
cache, ComfyUI (including Comfy Desktop's shared folder), Unsloth Studio, Pinokio, AnythingLLM, GPT4All and Jan.
The list is data (`services/api/src/wasifyai_api/discovery.yaml`); `OLLAMA_MODELS` and `HF_HUB_CACHE` move
their entries.

| Piece | Where |
|---|---|
| Header readers: GGUF (architecture, name, quantisation, licence; the tokenizer is never read), safetensors (tensor names classify language / image / video / LoRA / VAE / text encoder), diffusers and transformers repos by `model_index.json` and `config.json`; `.ckpt` is named, never opened | `desktop_discovery.py` |
| Bounded walk: depth 7, 60 000 files, 25 s; folder links are not followed; stubs under 1 MB and vocabulary-only GGUFs are dropped; shards count as one model | same |
| States: `ready` (already in a folder the app uses), `can_use` (a catalogue file in the right folder: one click adds that folder as a read-only models folder), `later` (recognised, a planned stage uses it), `unsupported` | `assess()` |
| Running servers (Ollama, LM Studio, ComfyUI) answered on loopback only; reported, never started or used yet | `probe_servers()` |
| Routes: `GET /desktop/discovery`, `POST .../scan`, `PUT .../settings` `{enabled, folders}`, `POST .../use` `{id}` | same |
| Window: "Found on this computer" under Models; "Finding models" in Settings (switch, more folders) | `FoundModels.tsx`, `pages/Settings.tsx` |

macOS asks before an app reads Documents, Desktop, Downloads or removable drives, so such known folders
(`needs_permission` in the data file) are offered with "Look in this folder" instead of being read. The result is
kept in the settings store (`desktop.discovery`) and lives on this computer only.

Measured on the owner's Mac (Ollama, the Hugging Face cache, Comfy Desktop's shared folder, Unsloth): 26 models
found in 0.1 s: 4 language, 6 image, 2 video, 3 embedding, 1 LoRA, 9 parts and files of image models; three
FLUX.2 klein files are `can_use`.

## The language engine (llama.cpp, stage D)

An optional component like the image engine, installed on demand from Settings ("Set up the language engine").
It is llama.cpp's prebuilt release for this platform (pinned in `engine-manifest.json`, checksum checked,
about 12 to 20 MB, no Python), unpacked under `<app data>/engine/llamacpp/<release>/` with a `state.json` the
engine reads. The engine (`llama_server.py`) runs one `llama-server` at a time on loopback for one model file and
stops it to free the memory. Only the Apple-silicon build uses a GPU; the other builds run on the processor.
`GET /desktop/language-engine` and `POST /desktop/language-engine/stop` are the routes; choosing a model and the
chat provider are D2 (`docs/phase2-stage-d-plan.md`).

## The model hub (ADR-0064, stage D2b)

Models is a page of nine cards (Chat, Images, Video, Voice, Listening, Music, Faces, Documents, 3D), each with the model in
use, the one picker every screen has ("Select image model", ...) and Remove (ADR-0086). Choosing a model that is on the
computer uses it; choosing one that is not opens a dialog with the engine and the files, the total, the time, the licence and
where they come from, and "Download and use" does the lot. The window composes this from the routes below
(`apps/desktop/src/choices/`); the picker itself (`packages/ui/src/models/`) knows no engine. **Advanced** keeps the model folders,
the files other tools left here and Discover. The first time, the chat card offers the model that suits the computer's memory.
**Discover** finds open models on Hugging Face and fetches one. The window never contacts the internet: the
engine does (`desktop_hub.py`, `/desktop/hub/...`), only after the person agrees (Settings has the switch), and a
download is only started from the exact files and size the person confirmed, re-checked against the repository at
its current commit and its published SHA-256. Pickle formats are never offered; a gated model is refused until
account sign-in exists. The recommended list (`hub-shelf.yaml`) works without the network.

## The chat model (stage D, D2)

The model that answers when the app needs words: improving a prompt now, the assistant next. It is chosen in
Models ("Chat model"): a found GGUF file run by the app's own `llama-server` (the language engine must be set
up), or a model of a running Ollama or LM Studio, used where it is.

| What | Where |
|---|---|
| The choice and the session that makes it ready (holds the `chat` slot for a file) | `desktop_language.py` `LanguageService` |
| The text provider every product's text capabilities use on the desktop | `LocalTextProvider`, supplied as `ProviderDeps.text_provider` in `main.py` |
| `GET /desktop/language`, `PUT /desktop/language` `{item_id, context}` or `{server}` or `{clear}`, `POST /desktop/language/try` | `desktop_llm.py` |
| Fit at the chosen context, with the engine's own backend | `language_machine()` and `desktop_fit.need_of_language(chosen=...)` |
| Window | `ChatModel.tsx`, `language.ts` |

A file is refused when the engine cannot read it (`unsupported`) or the computer cannot hold it (`too_big`); a
server is only one the engine found itself on `127.0.0.1`. Choosing never starts anything: the first request
does, so a person who only browses Models costs no memory.

## Will it fit? (ADR-0063)

`desktop_fit.py` answers `fits`, `tight` or `too_big` for a model, with a reason in plain words, from what the
computer has now.

| Device | Capacity (more cannot work) | Budget (free to use now) |
|---|---|---|
| Apple silicon (unified memory) | 90% of the memory | 75% of it, or what is available if less |
| NVIDIA card | the card's memory; a language model may spill into 50% of the RAM | the card's free memory (the same spill rule) |
| Processor only | 85% of the memory | what is available |

- **Free memory** is read from `vm_stat` (macOS), `/proc/meminfo` (Linux) or `GlobalMemoryStatusEx` (Windows);
  the card from `nvidia-smi`. Memory held by the app's own resident model counts as free, because the next model
  is loaded into it.
- **What a model asks for:** the catalogue's declared (measured) figure where it has one, otherwise an estimate:
  language models are weights plus the KV cache for 8192 tokens (from the GGUF header) plus 0.6 GB; image and
  video files are weights x 1.15 plus 3 GB (6 GB for video). Estimates are labelled "about".
- **Where it is used:** the Models list and found models (a badge and the reason); the download confirmation
  (`too_big` needs "get the files anyway", the engine refuses a request without `accept_memory`); the Create
  screen (a notice for `tight`, Generate off for `too_big` with the reason); and the engine itself, which
  refuses a real image job that cannot fit before anything is loaded (`FitGuardRunner`, error `model_too_big`).
  A found model that cannot fit is never offered with "Use it".
- **Tune with measurements.** The 0.9 / 0.75 / 0.85 limits and the +3 GB working memory are starting values;
  record real peaks per model family and adjust.
