# ADR-0099: OpenRouter for text, fal.ai for media in v1; the web runs on cloud models

- **Status:** Accepted (2026-11-12, by the owner: "We will support only fal.ai in v1. The desktop will use local and
  cloud models. The web app will only use cloud models." The plan, its models and its seven answers: "Yes, accept all").
- **Amended:** 2026-11-12, by the owner, the same day: "LLMs will be provided by OpenRouter and the media models will
  be provided by Fal", because text models through fal.ai cost more than on OpenRouter directly.
- **Changed by:** ADR-0100 (Accepted 2026-11-12). It replaces decisions 1, 2, 3 and 7:
  - text: Claude Haiku 5.5 by default, with the person's choice of vendor;
  - media: the cheapest of Runware, WaveSpeed and fal.ai.

  Plan `docs/cloud-v1-plan.md`.
- **Date:** 2026-11-12
- **Plan:** `docs/fal-only-v1-plan.md` (stages FA0 to FA11, the models chosen for each product). The file names keep
  "fal-only" so links still work.
- **Changes:**
  - ADR-0095 (one key per product, several providers; the web's Admin › Media on engine workers or fal.ai);
  - ADR-0087 (the web runs the desktop's engines on workers);
  - the multi-provider amendment of 2026-11-11 (`docs/own-keys-cloud-tab-plan.md`).
- **Keeps:** rule 5 (on the web every LLM call goes through LiteLLM), ADR-0041 (every creation searchable), ADR-0068
  (every feature an action), ADR-0094 (no safeguards of our own).

## Context

The app spoke to many providers by 2026-11-12:
- for chat: OpenAI, Anthropic, Gemini, Groq, OpenRouter, any OpenAI-compatible server;
- for media: fal.ai, WaveSpeed and Runware.

The web ran its models on ComfyUI and on engine workers with the desktop's models.

The owner wants as few providers as possible to test, bill and support in v1, and a web app that needs no GPU and no
model files.
- **fal.ai** serves every media product: pictures, clips, speech, music, sound effects, lip sync, 3D, and training of
  picture and video looks.
- **OpenRouter** serves the text models (chat, vision, tools, embeddings) at the model makers' list prices. Its only
  extra is 5.5% when credits are bought.
- fal.ai also serves OpenRouter's models through its own route, but it adds its own charge on top. That made text cost
  more there than on OpenRouter directly, so text stays on OpenRouter.

## Decision

1. **Two cloud providers, one per kind of model.**
   - **OpenRouter** runs every text model: Chat, Notebook, the assistant, and every text step (prompts, lyrics, picture
     descriptions, Creative Studio's plan, the training judge), with vision, tools and embeddings.
   - **fal.ai** runs every media model: Images, Video, Lip sync, Voice, Music, Sound effects, 3D and Train models.
   - WaveSpeed, Runware, OpenAI, Anthropic, Gemini, Groq and "another OpenAI-compatible server" are removed from the
     code, Settings › Your keys and Admin. Keys saved for them are deleted on first start.
   - Neither provider is used for the other kind: no media on OpenRouter, no text through fal.ai's OpenRouter route.
2. **The desktop runs local and cloud models.** The picker keeps This computer and Cloud. Cloud uses the person's keys:
   **one OpenRouter key for text and one fal.ai key for media**, with an optional key per product for separate billing.
3. **The web runs only cloud models.**
   - The service has one OpenRouter key and one fal.ai key, set in Admin.
   - The admin turns models on, and people choose among them in the picker.
   - ComfyUI, model workers and Ollama no longer serve models on the web.
   - Chat and embeddings still pass through LiteLLM (rule 5), bound to LiteLLM's own OpenRouter provider.
4. **Tools that are not models stay on the service's own CPU workers on the web:** the Motion graphics render, song
   analysis, reading documents and FFmpeg. They need no GPU and no model files.
5. **The models** are the catalogue's lines, chosen 2026-11-12 (`docs/fal-only-v1-plan.md`, "The models for v1"):
   - images and video: three top models and two cheaper ones each;
   - every other product: two or three.

   More are added later as catalogue lines.
6. **Not on the web in v1:** Edit speech (no fal.ai model) and the two training cards with no fal.ai trainer (Teach it
   to write, Teach it to decide). All three stay on the desktop, on this computer.
7. **The admin sees what the service spends.** Every cloud job writes a usage event (rule 9) with its price:
   OpenRouter's reported cost for text, fal.ai's listed price for media. The two bills stay separate.

## Consequences

- Two request clients: LiteLLM (web) and the desktop's OpenAI-compatible client for OpenRouter; `FalQueue`, its uploads
  and its request log for every media product. Media inputs always go to fal.ai's file store first.
- The search index on the web is rebuilt once, because the embedder changes (ADR-0041).
- `cloud_queues.py` (WaveSpeed, Runware) and the other text providers' code and tests are deleted.
- The web's Helm values lose ComfyUI and the model workers. A CPU worker stays for the tools of decision 4.
- Two outage points: an OpenRouter outage stops the web's chat; a fal.ai outage stops the web's media. The desktop can
  still use its local models.
- A third provider later is a new ADR, not a setting.
