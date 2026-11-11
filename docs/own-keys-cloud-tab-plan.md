# Keys per product, cloud models in the picker (plan, 2026-11-11)

Status: **mockup approved by the owner 2026-11-11** ("Approve, build it"; `docs/spikes/provider-keys-mockup.html`,
third version). **CT1 to CT5 built 2026-11-11 against fakes**; CT6 left. Amends ADR-0095 ("Amendment: keys hold no model; the picker's Cloud tab").

## What changes

- **Settings › Your keys stores keys only.** One row per product. A row holds any number of provider keys
  (fal.ai, WaveSpeed, Runware and, for chat, the text providers). Each key is tested before it is saved. A row
  never names a model.
- **The model picker gets a Cloud tab** (Recommended · On this computer · Cloud · More). It lists every model the
  app can run for that product on each provider with a saved key, grouped "With your fal.ai key", each row with
  its provider and listed price. With no key, the tab says so and links to Your keys.
- **Choosing a cloud row** makes the product run there (`use`). Choosing a model on this computer clears `use`;
  the keys stay.

## Storage

The settings row of a product:

```
{"use": {"provider": "fal", "model": "fal-ai/infinitalk"} | absent,
 "keys": {"fal": {"ok": true, "said": "", "tested_at": 0, "base_url": "", "model": ""}}}
```

- The secret of a key is `keys.<product>.<provider>`.
- A row of the old shape (`mode`, `provider`, `model`, secret `keys.<product>`) is read as one key plus `use`
  when its mode was `key`, and is rewritten in the new shape the first time it is read.
- `route(product)` still answers a `KeyRoute(provider, model, key, base_url)` from `use`, so the chat, media,
  speech and 3D code that reads it does not change. The web's admin providers keep the same interface.

## The cloud catalogue

`own_keys_catalogue.py`: one line per model the app knows how to call (product, provider, endpoint, title, one
line, price). Only models whose request the app builds are listed:

| Provider | Chat | Images | Video | Voice | Music | Sound effects | Lip sync | 3D |
|---|---|---|---|---|---|---|---|---|
| fal.ai | OpenRouter models | FLUX.2 | LTX-2 fast | Kokoro | MiniMax 2.6, ElevenLabs | ElevenLabs SFX | LongCat, InfiniteTalk | Pixal3D |
| WaveSpeed | its LLMs | Z-Image Turbo | — | — | MiniMax 2.6 | — | InfiniteTalk, InfiniteTalk Fast, LongCat Avatar | — |
| Runware | its LLMs | FLUX.1 schnell, dev | — | — | MiniMax 2.6 | — | — | — |
| OpenRouter, OpenAI, Anthropic, Gemini, Groq | their models | | | | | | | |
| Another OpenAI-compatible server | the model named with the key | | | | | | | |

A provider is offered in Settings only for products it has models for. More models are more catalogue lines.

## Routes (`/desktop/keys`)

| Route | What |
|---|---|
| `GET ""` | products with their saved keys (state only, never the key), providers, `use` |
| `POST /{product}/keys/{provider}/test` | test a pasted key (or the saved one) |
| `PUT /{product}/keys/{provider}` | test, then save |
| `DELETE /{product}/keys/{provider}` | remove the key; clears `use` if it was that provider |
| `GET /{product}/cloud` | the Cloud tab's rows |
| `PUT /{product}/use` | `{provider, model}` or `null` |

## Stages

| Stage | What | Done when |
|---|---|---|
| CT1 | storage, migration, routes, client | engine tests pass, old rows read. **Built 2026-11-11** |
| CT2 | catalogue and routing of the chosen model | each catalogue model reaches its runner against a fake. **Built 2026-11-11** |
| CT3 | WaveSpeed and Runware runners | images, music, lip sync and text on both, against fakes. **Built 2026-11-11** (text through the OpenAI-compatible route, not run against a fake) |
| CT4 | Settings › Your keys | the screen's tests; seen in the browser. **Built 2026-11-11** |
| CT5 | the Cloud tab and the adapters | choosing a cloud row and a local one, tested. **Built 2026-11-11** |
| CT6 | docs, help, a real key | the owner's real run (fal.ai first) |

Not built here: WaveSpeed and Runware for video, voice, sound effects and 3D; the web Admin side (F6).

Unchecked against the real services: WaveSpeed taking the picture and the voice as data URIs (fal.ai does); WaveSpeed's
MiniMax without lyrics writing its own; Runware's `getResponse` answer for an audio task. The real run will tell.
