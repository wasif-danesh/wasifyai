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
main way products run: the service does not pay for a person's models.

## Decision

1. **A product runs "On this computer" or "With my key".** The products are Chat (and everything that writes text:
   lyrics, prompts, notebooks, the assistant), Images, Video, Voice, 3D and Motion graphics drafts. On the desktop the
   default is On this computer; on the web it is With my key (the admin may still offer the service's own models).
2. **One key per product, never shared silently.** A key is saved under the name `keys.<product>` in the secret store
   (`keys.chat`, `keys.images`, ...): the keychain on the desktop, the `secrets` table per person on the web
   (`<tenant>/<user>/keys.<product>`). The same key can be used for two products only by saving it twice; the screen
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
   fal.ai" or "On this computer"; a product with no key on the web says "Add your key" and opens the key screen.
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
| K3 | Images and video on fal.ai | a picture and a clip made with the key are saved to the library |
| K4 | Voice and 3D on fal.ai | a speech, a lip sync and a 3D model made with the key |
| K5 | The web: keys per person, With my key as the default | a person on the web makes each kind of thing with their own keys |

## Consequences

- The desktop can make things a computer cannot (a 16 GB Mac can make video through fal.ai).
- What is sent to a provider leaves the computer; every screen that uses a key says so once, by its provider's name.
- Each product's provider is a separate setting, so a person can mix: chat on this computer, video on fal.ai.

## Open questions for the owner

1. ~~The mockup~~ Approved (owner, 2026-10-29).
2. Which media providers besides fal.ai, if any, for v1.
3. On the web, whether the admin's own models stay available as a choice beside the person's keys.
4. CLAUDE.md rule 5 says every LLM call goes through LiteLLM. A person's key can either go to its provider directly
   from the engine (the OpenAI-compatible client the text provider already uses, pointed at the provider; no new
   service on the desktop) or through a LiteLLM model added per key on the web. Recommended: directly on both, and
   rule 5 amended to "every LLM call goes through the OpenAI-compatible text provider".
