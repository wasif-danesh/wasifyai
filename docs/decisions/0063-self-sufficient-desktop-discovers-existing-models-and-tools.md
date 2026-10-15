# ADR-0063: A self-sufficient desktop app that finds the models and tools already on the computer

- **Status:** Accepted (2026-10-15), owner decision: the scan is automatic and covers known folders only
- **Date:** 2026-10-15
- **Depends on:** ADR-0056 (profiles, provisioning), ADR-0059 (managed ComfyUI, models folder, read-only extra
  folders), ADR-0062 (engine per capability), ADR-0057 (assistant; chooses the text engine and formats, stage D)

## Context

The product aim: one app, for desktop and web, that does not need Ollama, LM Studio, Comfy Desktop, Pinokio,
AnythingLLM or Unsloth Studio to be installed. It brings its own engines (ComfyUI today, llama.cpp with the
assistant, training later) and installs them on demand.

Many users already have those tools and gigabytes of models on disk. Asking them to download the same files again
is the wrong first experience, and hiding what they already have makes the app look empty.

What exists today (stage A3): a models folder owned by the app, extra **read-only** folders the person may add by
hand, and `external` mode for an already running ComfyUI. There is no discovery.

## Decision

1. **Automatic scan, known folders only.** On first start and then at each app start (and on "Scan again"), the
   engine looks in a short list of known locations, in the background, at low priority. It never crawls the whole
   disk and never follows links out of those folders.
2. **The list is data, not code.** One versioned file (`discovery.yaml` next to the model catalogue) names each
   tool, its folders per operating system and the environment variables that move them (`OLLAMA_MODELS`,
   `HF_HOME`, `HF_HUB_CACHE`, ...). Adding a tool is a data change. The folders are our best knowledge and
   **must be verified per platform before the first release** (a small spike: install each tool, record where its
   files land), the same way the ComfyUI pins were.
3. **Read-only, in place.** Found files are never copied, moved, modified or deleted. The window offers no
   "remove" for them. Another tool's files stay that tool's.
4. **Identify by header, not by name.** Only headers and manifests are read (GGUF header, safetensors header,
   Ollama manifest JSON). The result is kind (language model, diffusion checkpoint, LoRA, VAE, text encoder, ...),
   architecture, quantisation and size.
5. **List everything recognised, and say what can be done with it.** A found model is matched against what our
   engines support per capability (ADR-0062) and the computer's memory, and gets one of the states below with
   a plain-words reason. Only `ready` and `can_use` items can reach a model picker.
6. **Nothing is used until the person selects it.** Discovery fills the list; the choice (one per capability) is
   the person's. A found model carries a source badge ("found in Ollama", "found in the Hugging Face cache").
7. **Running tools are detected, never required.** The engine probes the tools' default loopback ports; a found
   server is offered as an optional provider ("use your running Ollama"). We never start, stop or configure
   another tool, and nothing in the app depends on one being there.
8. **Private and bounded.** The result lives in the local database only and is never sent anywhere. Settings
   shows the scanned folders with a switch to turn the scan off and to add or remove folders. The scan has a
   time and file-count budget, skips network and removable drives unless the person adds them, and avoids folders
   that make macOS ask for permission (Documents, Desktop, removable volumes) unless the person adds them.
9. **Licences are shown, not granted.** The licence from the manifest or header is displayed when present.
   We redistribute nothing from other tools.

## Scope of the scan (owner decision, 2026-10-15)

The scan covers **every kind of model the product will run, from the first version of discovery**: language
models (GGUF and Hugging Face transformers folders), embedding models, image and video diffusion models,
LoRAs, VAEs and text encoders. It does not wait for the assistant. Each found item carries a state that says
honestly what can be done with it today:

| State | Meaning |
|---|---|
| `ready` | already in a folder the app uses |
| `can_use` | the app can use it in place; one click adds its folder (the file name, size and folder match a catalogue entry) |
| `later` | recognised, and a stage that will use it is planned (for example language models and the assistant, stage D) |
| `unsupported` | recognised, but no engine of ours can use it (with the reason) |

Which language-model **engine and formats** the assistant runs is still decided in the stage D plan (ADR-0057);
GGUF through llama.cpp is the candidate. Discovery lists them now so the person sees their models at once, and
the state changes from `later` to `can_use` when that stage ships.

## Not decided here

- Whether found models may be **hard-linked or copied** into the app folder on request. Not needed for use.

## Alternatives considered

| Option | Why not |
|---|---|
| Whole-disk crawl | Slow, invasive, triggers permission prompts, finds files that are not models |
| Manual add-a-folder only (today) | The app looks empty after install; most users will not know their folders |
| Copy or import found models | Doubles disk use for 10 to 100 GB files; risks version drift |
| Depend on Ollama or Comfy Desktop as the engine | Breaks the self-sufficient aim and our control of versions and security |

## Consequences

- The model catalogue (ADR-0059, A3) gains a second source, `found`, beside `catalogue`. The Models screen and
  the model pickers show both with their source.
- The engine gets a scanner (`desktop_discovery.py`), a table of found items, and routes under `/desktop/...`.
- A per-platform verification of the known folders joins the pre-release steps (ADR-0056).
- Detection of running servers needs a loopback-only allowlist of ports; it never probes anything else.

## Implementation status (2026-10-15)

| Decision | State |
|---|---|
| 1 automatic scan, known folders only | done: a background scan shortly after the engine starts, "Look again" in the window |
| 2 list is data | done: `discovery.yaml`; the paths still need the per-platform verification |
| 3 read-only, in place | done: nothing is written; "Use it" adds the file's models folder as a read-only folder |
| 4 identify by header | done: GGUF, safetensors, diffusers and transformers repos; `.ckpt` is never opened |
| 5 list everything recognised with a state | done: `ready`, `can_use`, `later`, `unsupported` with a reason |
| 6 nothing used until selected | done for catalogue image files (one click); language models wait for stage D |
| 7 running tools detected | detected and shown; selecting one as a provider is not built |
| 8 private and bounded | done: local settings store, budgets, switch and extra folders in Settings, permission-gated folders offered |
| 9 licences shown | done where the file says one |
| (added) does it fit | done: `desktop_fit.py`; a model that cannot fit is not offered and is refused before it runs (see `docs/desktop-profile.md`) |
