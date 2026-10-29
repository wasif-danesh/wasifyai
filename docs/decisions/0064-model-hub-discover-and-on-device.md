# ADR-0064: A model hub: discover open-weight models and see what is on the device

- **Status:** Accepted (2026-10-15), with the owner's answers recorded at the end (all recommended). **Decision 1 (two tabs) is superseded by ADR-0086**: Discover moves under "More models" of the model picker and under Advanced on the Models page
- **Date:** 2026-10-15
- **Depends on:** ADR-0056 (profiles, provisioning), ADR-0059 (models folder, downloads), ADR-0062 (engine per
  capability), ADR-0063 (found models, fit check), ADR-0057 (assistant; its model picker uses this hub)

## Context

The owner wants a screen like Unsloth Studio's Model hub: one place to discover open-weight models, download
them, and see what is on the device. Unsloth's hub (read from a screenshot and the Phase 0 spike, about 37k lines
of TypeScript in its `hub` feature) has two tabs, **Discover** and **On Device**; a search box with sort and
capability filters; a list with name, publisher, downloads, likes and age; a detail panel with the capability
tags, the variant and size to download, parameters and library, and the model's README; and a header
with this computer's memory, the number of cached and local models and the download backend.

What we have: a one-model catalogue with pinned checksums (ADR-0059), a confirm-first resumable download
manager that accepts catalogue entries only, discovery of models other tools left on the disk (ADR-0063) and a
fit check (`fits`, `tight`, `too_big`). There is no way to find a model we have not hand-picked.

## Decision

1. **The hub is the Models screen, with two tabs.** **On device** is what exists today made one list: the
   app's own folder, found models (ADR-0063) and the Hugging Face cache, each with size, source, fit and
   the actions that apply (use, unload, remove from the app's folder). **Discover** is new. The side-menu entry
   stays "Models".
2. **The engine does the browsing; the window never talks to the internet.** The window's content security
   policy stays closed to loopback. The engine calls the Hugging Face API and serves the results through
   `/desktop/hub/...` routes (search, model detail, files). That also gives one place for caching, rate limits,
   the token and tests with a fake server.
3. **Hugging Face is the one live source in v1.** The Hub's API gives search, `pipeline_tag`, library,
   downloads, likes, file lists with sizes and SHA-256 for large files, and the commit to pin. A **curated shelf**
   ships with the app (recommended models we have measured: ADR-0062's per-capability choices), so Discover is
   useful on first open and offline. Ollama's library has no stable public API: its models are reached through
   a running Ollama (ADR-0063) or by their GGUF files.
4. **Opt-in network.** The first time Discover is opened a plain notice says what will be contacted
   (`huggingface.co`), what is sent (the search words and the model ids opened, no account, no identifiers) and
   that it can be turned off in Settings. Nothing is requested before the person agrees. Offline, Discover shows
   the curated shelf and the last cached results with their age.
5. **Only what the app can run is offered by default.** A filter, on by default, limits Discover to models an
   engine of ours can run (ADR-0062): language and embedding models as GGUF for llama.cpp; image and video models
   only in families with a verified workflow (ADR-0059). "Show everything" lists the rest as view-only, with the
   reason they cannot be used. Pickle formats (`.ckpt`, `.bin`, `.pt`) are never offered for download.
6. **Fit on every card and every variant.** The fit check (ADR-0063) is shown per variant, so a quantisation
   that fits is visible next to one that does not. A `too_big` variant is greyed out with the reason and the
   nearest smaller variant suggested.
7. **Downloads reuse the confirm-first manager.** For a model chosen in Discover the engine builds a catalogue
   entry on the fly from the Hub: the revision is pinned to the commit seen, sizes and SHA-256 come from the
   file list, and the same confirmation (exact files, total size, source, free space) and checksum rules
   apply. A file without a published checksum is refused. Several downloads queue; one runs at a time.
8. **Gated models** are marked,
   and need the person's own Hugging Face token, kept in the operating system's keychain by the shell and handed
   to the engine at launch (never written to the settings database). We never ship or proxy a token of ours.
9. **Model cards are shown as text, safely.** The README is rendered as Markdown without scripts and **without
   loading remote images or links automatically** (a placeholder with "load images" per card), so opening a card
   does not contact third-party hosts.
10. **The header shows this computer:** memory (and the card's memory where there is one), free disk, models on
    the device, and a download in progress. These are the numbers the fit check uses, so the badges can be
    trusted by looking at them.
11. **Nothing is auto-updated or auto-selected.** An update shown for a model on the device is only a note
    ("a newer revision exists"); fetching it is a normal confirmed download.

## Alternatives considered

| Option | Why not |
|---|---|
| Embed Unsloth's hub frontend | Large, tied to its backend routes and its engine set; ADR-0061 prefers selective import. We build our own on `packages/ui` and borrow the layout |
| Window calls Hugging Face directly | Opens the content security policy, spreads the token, makes testing harder |
| Curated catalogue only | Safest, but goes stale and cannot answer "what is the newest Qwen" |
| Index Ollama's library by scraping | No stable API; fragile |
| Auto-download recommended models | Violates confirm-first (ADR-0059) and surprises people with 10 to 50 GB transfers |

## Consequences

- A new engine module (`desktop_hub.py`) with a cached Hub client, a fake Hub for tests, and a function that
  turns a Hub file list into a downloadable entry. No new Python dependency (`httpx` is there).
- The download manager takes entries built at run time, not only the packaged catalogue; entries persist in the
  settings store so an interrupted download resumes after a restart.
- The Models screen becomes two tabs; `ModelsPanel` and `FoundModels` become parts of the On device tab.
- A token store in the shell (keychain), shared with the cloud key of the assistant (stage D).
- The curated shelf is data (`hub-shelf.yaml`), reviewed like the catalogue.

## Not in this version

Uploading or publishing, comparing models side by side, ratings of our own, model merging, conversion between
formats, ModelScope and other hubs, and automatic updates.

## Owner's answers (2026-10-15: all recommended)

1. **Opt-in notice** before the first request; nothing is contacted before the person agrees.
2. **Hugging Face only** in v1, plus the curated shelf.
3. **Default filter "runs on this computer"** is on; "Show everything" is one click.
4. **README images blocked** until the person asks, per card.
5. **Hugging Face token** for gated models is supported, kept in the operating system's keychain.

## Implementation status (2026-10-16)

| Decision | State |
|---|---|
| 1 two tabs, On device and Discover, in Models | done |
| 2 the engine browses, the window never does | done: `/desktop/hub/...` |
| 3 Hugging Face only, with a curated shelf | done: `hub-shelf.yaml` (6 models, each checked) |
| 4 opt-in network | done: a notice before the first request; a switch in Settings; the engine refuses (403) until agreed |
| 5 only what the app can run by default | done for language and embedding (GGUF); image and video are listed as view-only |
| 6 fit on every variant | done, at the chat context; estimates labelled |
| 7 downloads reuse the confirm-first manager | done: the engine rebuilds the entry from the repository at its current commit and refuses a list that differs |
| 8 gated models and a token | **a gated model is refused**: the token reaches the engine through `HF_TOKEN` only, and the keychain and its sign-in are not built |
| 9 model cards as text, no remote images | done: front matter, HTML and pictures removed in the engine |
| 10 header with this computer | not done: the memory and disk figures appear in the confirmation and in the fit badges, not in a header |
| 11 no automatic updates | done: nothing is fetched without a confirmation |
