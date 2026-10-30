# ADR-0095: The person's own provider keys, one per product

- **Status:** Proposed (2026-10-29). The owner set the requirement: "Person's own key must be supported in v1. Even
  better, separate keys for each product." The mockup was approved by the owner on 2026-10-29. The real-key run of spike K0 is done at release time
  (owner, 2026-10-29); the stages are built against fakes until then.
- **Date:** 2026-10-29
- **Depends on:** ADR-0092 (the secret store: keychain on the desktop, the `secrets` table on the web), ADR-0005 and
  ADR-0025 (capabilities bound to providers; LiteLLM's OpenAI-compatible API), ADR-0086 (the model button and its
  dialog), ADR-0087 (the web is the desktop's twin).
- **Related:** ADR-0094 (no safeguards: the provider's own terms are the only ones that apply), ADR-0056 decision 4
  ("a cloud provider with the user's key", never built). Not ADR-0092's dropped product API keys: those were keys
  *we* would issue; these are keys the person brings for a provider.
- **Mockup:** `docs/spikes/own-keys-mockup.html`.

## Context

Every product runs on this computer today, or, on the web, on the service's own workers and the admin's gateway
bindings. The owner wants the person to be able to use their own provider account instead, product by product: a
chat key, an image key, a video key and so on, each saved once and used only by its product. On the web this is the
main way products run: the service does not pay for a person's models. *(Superseded for the web by the owner on
2026-10-29: on the web the admin selects the models and providers (fal.ai, OpenRouter and others) in Admin settings
and people do not bring keys; own keys are a desktop feature. Stage K5 is the admin's side.)*

## Decision

1. **A product runs "On this computer" or "With my key".** The products are Chat (and everything that writes text:
   lyrics, prompts, notebooks, the assistant), Images, Video, Voice, 3D and Motion graphics drafts. On the desktop the
   default is On this computer. The web has no own keys: the admin selects the models and their providers, fal.ai and
   OpenRouter among them (owner, 2026-10-29; stage K5).
2. **One key per product, never shared silently.** A key is saved under the name `keys.<product>` in the secret store
   (`keys.chat`, `keys.images`, ...): the keychain on the desktop. The same key can be used for two products only by saving it twice; the screen
   offers "Use the same key as Chat" as a shortcut that copies it. A key is never shown again, never logged and never
   sent anywhere but its provider.
3. **What is saved with it:** the provider, the model and, for an OpenAI-compatible server, its address. These are
   settings (not secrets) beside the key.
4. **Providers, first:**
   - Text: any OpenAI-compatible endpoint, with presets for OpenAI, OpenRouter, Groq, Google Gemini (its OpenAI
     endpoint) and Anthropic (its OpenAI-compatible endpoint). The existing `LiteLLMTextProvider` already speaks this
     protocol with a base URL and a key, so no new dependency is needed.
   - Images, video, 3D and voice: fal.ai (FLUX for pictures, LTX for video, Pixal3D for 3D, Kokoro for speech,
     MuseTalk for lip sync, all named by the owner on 2026-10-28), through its queue API over `httpx`, which the SDK
     already depends on. Other media providers are a later amendment.
5. **The model button says where it runs.** The top-bar button and its dialog (ADR-0086) show "With your key ·
   fal.ai" or "On this computer".
6. **Settings > Your keys** lists every product with its state (On this computer, Key saved, Key not working), a
   provider and model choice, a key field, **Test** (one tiny request, as the admin's model test does) and
   **Remove**. Testing never saves; saving tests first.
7. **Usage is recorded as today** (tokens, seconds, images), with the provider named, so the person can see what
   their key was used for. The app keeps no money count: billing is the provider's.
8. **Errors are passed on in words.** A refused or rate-limited request says which provider refused it and why, in
   its own words where it gives them (ADR-0094: the app adds no refusal of its own).

## Stages

| Stage | What | Done when |
|---|---|---|
| K0 | Spike: one OpenRouter chat, one fal.ai FLUX picture and one fal.ai LTX clip from the engine with a real key (`scripts/spike_own_keys_k0.py`, checked against a fake queue 2026-10-29) | **run with real keys at release time** (owner, 2026-10-29); times and the request shapes are written down then |
| K1 | The secret names, the settings beside them, Settings > Your keys with Test and Remove (desktop). **Built 2026-10-29** against fakes: `own_keys.py` (`/desktop/keys`), `createOwnKeysApi`, `YourKeys` in Settings > Your keys; a text key is tested with a one-token chat, a fal.ai key by asking about a request that does not exist (nothing is charged); not yet seen in the real window | a key is saved to the keychain, tested and removed in the window |
| K2 | Chat and every text product on the person's key. **Built 2026-10-29** against fakes: `KeyedTextProvider` (`own_keys_text.py`) is the desktop's text provider; while Chat and writing is "With my key" every `stream` and `chat` (chat, lyrics, Enhance, notebooks, the assistant, picture descriptions, training captions and judges) goes to that provider through the OpenAI-compatible client, tokens counted with the provider named; embeddings stay on this computer; a refusal is said in the provider's name. The model button shows "<model> · with your key · <provider>" as the chosen row, and choosing a model on this computer takes chat off the key (the key stays saved). Not seen in the real window | a chat, a lyric and a notebook answer come from the provider |
| K3 | Images and video on fal.ai. **Built 2026-10-29** against a fake fal.ai: `FalRunner` in the media worker (`backends.py`: submit, follow `status_url`, read `response_url`, fetch the file without the key; a stopped job is cancelled on fal.ai too) and `KeyedMediaRouter` (`own_keys_media.py`) in front of the desktop's runner, asked per job. Make a picture and Change a picture or Combine two (`fal-ai/flux-2`, `fal-ai/flux-2/edit`, pictures inline as data URIs), Make a video and Animate a picture (`fal-ai/ltx-2/text-to-video/fast` and `.../image-to-video/fast`, 6 or 8 s, no sound). Not on a key yet, said in words: Paint over part of a picture, Make a clip longer, and styles or looks made on this computer. The picker shows the keyed row for Images and Video; local memory warnings do not block a keyed job. Whether fal.ai's edit endpoint takes data URIs is checked at release (backlog A11); not seen in the real window | a picture and a clip made with the key are saved to the library |
| K4 | Voice and 3D on fal.ai. **Built 2026-10-29** against a fake fal.ai: `FalQueue` (the queue client, in `wasifyai_platform_sdk/fal.py` since 2026-10-30 so the web's API image, which has no media worker, can load it; `FalRunner` in the media worker uses it too) and, in `own_keys_engines.py`, `KeyedSpeechEngine` in front of the speech engine and `KeyedModel3d` in front of the 3D engine; both read `OwnKeysService.known`, kept current on every change in Settings. With Voice on a key, speaking (Speak, read aloud, dubbing and audiobooks, which speak through it) goes to `fal-ai/kokoro` with the 20 American voices it offers, speed passed on; the speech screen offers only that model. Clone, design, music, transcribe and the other voice tools stay here. With 3D on a key, nothing need be set up: the cut-out is `fal-ai/birefnet` and the model `fal-ai/pixal3d` (1024, texture from the detail chosen), pictures inline as data URIs. The picker shows the keyed row for Voice (speaking) and 3D. **Lip sync is not on a key**: fal.ai's MuseTalk (`fal-ai/musetalk`) takes a source video and an audio URL, while Lip sync here starts from one picture; so lip sync stays on this computer in v1 (owner, 2026-10-29). Checked at release (backlog A11): that Kokoro answers a WAV, that Pixal3D and BiRefNet take data URIs and that the cut-out keeps its transparency; not seen in the real window | a speech and a 3D model made with the key are saved to the library |
| K5 | The web: **the admin picks the provider** (owner, 2026-10-29: people do not bring keys; the admin can select fal.ai, OpenRouter and others). Text: Admin › Models already offers OpenRouter, Gemini, Groq, Cerebras and any OpenAI-compatible server through LiteLLM; no change. Media: Admin › Media gets **fal.ai** as a backend for Images (make, change, combine) and Video (make, animate), run by `FalRunner` from the binding; and two new rows, **Voice · Speak** and **3D · Make a model**, each "Engine workers" (today) or fal.ai. One key per row, encrypted like the other bindings, with Test and "Use the key saved for …". People see where it runs on the model button, read only. Mockup: `docs/spikes/admin-providers-mockup.html` (approved by the owner 2026-10-29). **Built 2026-10-29** against fakes: the `fal` and `engine-workers` backends in `media_backends.py` (fal.ai offered everywhere but painting over a picture and making a clip longer; its Test asks about a request that does not exist); the media worker's `BackendRouter` runs a `fal` row on `FalRunner` (an admin's row may name the edit or animate endpoint itself); the rows `wasifyai-voice/speech.speak` and `wasifyai-model3d/model3d.generate` in Admin › Media, run by the API through `KeyedSpeechEngine` and `KeyedModel3d` over `AdminProviders` (`admin_providers.py`: per tenant, the request's tenant set in `get_principal`; refreshed on save and every 30 s); "Use the key saved for …" (`key_from`); the last Test kept as the row's state ("Key not working"); `/models/in-use` names the choice ("FLUX.2 · fal.ai", 3D included). Not seen in a browser against a running stack; real fal.ai at release (backlog A11). A resumed 3D run after an API restart is made again on fal.ai, under the default tenant when no request carries one | the admin sets each row to fal.ai, and a person makes a picture, a clip, a speech and a 3D model through it |

## Consequences

- The desktop can make things a computer cannot (a 16 GB Mac can make video through fal.ai).
- What is sent to a provider leaves the computer; every screen that uses a key says so once, by its provider's name.
- Each product's provider is a separate setting, so a person can mix: chat on this computer, video on fal.ai.

## Open questions for the owner

1. ~~The mockup~~ Approved (owner, 2026-10-29).
2. ~~Which media providers besides fal.ai~~ Answered 2026-10-29 (owner): Runware, Muapi and others are added later, each with its own runner, test and provider entry; fal.ai only for now.
3. ~~On the web, the admin's models beside the person's keys~~ Answered 2026-10-29 (owner): the web has no own keys; the admin selects the models and providers (K5).
4. ~~CLAUDE.md rule 5 and the person's key~~ Answered 2026-10-29 (owner): LiteLLM is for the web; on the desktop,
   the person's own key may go straight to its provider. Rule 5 of CLAUDE.md says so.
