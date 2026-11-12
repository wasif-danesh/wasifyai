# OpenRouter for text, fal.ai for media: the cloud providers in v1 (plan, 2026-11-12)

> **Replaced (2026-11-12):** `docs/cloud-v1-plan.md` (ADR-0100, Accepted) changes how these models run:
> - **Text:** Claude Haiku 5.5 by default, with the person's choice of vendor.
> - **Media:** the cheapest of Runware, WaveSpeed and fal.ai.
>
> The model choices and FA0's findings below still hold. FA2 to FA11 are not built; the new plan's stages CP0 to CP13
> replace them.

Status: **accepted by the owner 2026-11-12** ("Yes, accept all": the models below and the seven recommended answers).
Recorded as ADR-0099. **FA0 done 2026-11-12** (`docs/spikes/fal-v1-fa0.md`; the models' inputs in
`docs/spikes/fal-v1-fa0-inputs.md`).

**Changed the same day by the owner:** text models run on OpenRouter directly, not through fal.ai. fal.ai adds its own
charge to OpenRouter's prices; OpenRouter itself charges the model makers' list prices (plus 5.5% when credits are
bought). So v1 has two providers, one per kind of model:
- **OpenRouter:** chat, vision, tools and embeddings (Chat, Notebook, the assistant and every text step).
- **fal.ai:** every media model (Images, Video, Lip sync, Voice, Music, Sound effects, 3D, Train models).

The file keeps its name so links still work.

What the owner asked for on 2026-11-12:
- fal.ai is the only cloud provider in v1 for media; OpenRouter for text models (changed the same day, above).
- The desktop uses local and cloud models.
- The web app uses only cloud models.
- It covers Chat, Notebook, Images, Video, Voice, Music, 3D, Train models, Motion graphics and Creative Studio.

This plan replaces the multi-provider work of 2026-11-11 (WaveSpeed, Runware and the text providers other than
OpenRouter; `docs/own-keys-cloud-tab-plan.md`). It also changes two Accepted decisions:
- ADR-0095: one key per product, and the web on engine workers or fal.ai.
- ADR-0087: the web runs the desktop's engines on workers.

So it needs a new ADR: **ADR-0099 "OpenRouter for text, fal.ai for media in v1; the web on cloud models"**.

## Where things stand today

| Product | Desktop on a fal.ai key today | Web today | Missing in the cloud |
|---|---|---|---|
| Chat (and every text step: prompts, lyrics, picture descriptions, the training judge) | yes, through fal.ai's OpenRouter route (F1) | LiteLLM to Ollama, OpenRouter, Gemini, Groq and others | the desktop and the web on OpenRouter directly |
| Notebook | the answer follows Chat | LiteLLM | the embedder (local on the desktop, LiteLLM on the web); reading audio sources |
| Images | FLUX.2 make, change, combine | ComfyUI or fal.ai (Admin › Media) | Inpaint; more models |
| Video | LTX-2 fast make, animate; lip sync (4 models) | ComfyUI or fal.ai; lip sync on fal.ai | Extend; more models |
| Voice | Kokoro speak (English) | engine workers; Speak on fal.ai | clone, design, transcribe, change a voice, edit speech, and other languages |
| Music | MiniMax 2.6, ElevenLabs Music, ElevenLabs sound effects | engine workers or fal.ai | edit music, split into parts |
| 3D | Pixal3D with BiRefNet | engine workers or fal.ai | nothing for v1 |
| Train models | local only (AI Toolkit, mlx-lm, Laya, LTX) | engine workers | all four cards |
| Motion graphics | its Make panel follows Images, Video, Voice and Music | the render is a job on an engine worker | nothing of its own |
| Creative Studio | its shots follow Images, Video and Lip sync | song analysis on an engine worker | nothing of its own |

## The models for v1 (researched 2026-11-12)

How they were chosen:
- **The list:** fal.ai's public model list (`GET https://api.fal.ai/v1/models`, every category).
- **Prices:** fal.ai's price list (`GET https://api.fal.ai/v1/models/pricing`, free, with the owner's key), and each
  model's page where the price is per token or per "unit".
- **Quality:** arena.ai's blind-vote leaderboards of 2026-11-08 (text to image, image edit, text to video, image to
  video).
- **Chat:** OpenRouter's model list.

Prices are fal.ai's list prices on that day.
- "About" marks a price worked out from a per-token price. It is measured in FA11.
- MiniMax H3's lower promotional prices (to 2026-11-15) are left out; the standard ones are shown.

Images and video follow the owner's rule: **three top models and two cheaper ones**, more later. Every other category
has two or three.

### Images (make, change, combine, inpaint)

| | Model | fal.ai endpoints | Price (1024×1024) | Why |
|---|---|---|---|---|
| Top | **GPT Image 2.5 Sunburst** (OpenAI) | `openai/gpt-image-2.5/sunburst/text-to-image`, `…/edit` | about $0.13 at high quality | first in text to image (1429) and in image edit (1520) |
| Top | **Nano Banana 2.1** (Google) | `google/nano-banana-2.1`, `…/edit` | about $0.05 at 1K | 7th in text to image, 9th in edit; several pictures in one edit |
| Top | **Grok Imagine Image 2.0** (xAI) | `xai/grok-imagine-image/v2.0/text-to-image`, `…/edit` | $0.04 to $0.06 | 8th in text to image, 7th in edit; cheapest of the top |
| Cheaper | **FLUX.3 klein** (Black Forest Labs) | `blackforestlabs/flux-3/klein/text-to-image`, `…/klein/edit-image`, `…/lora` | $0.009 | best open-weights family; can be taught on fal.ai and used with the result |
| Cheaper | **Z-Image Turbo** | `fal-ai/z-image/turbo`, `…/turbo/inpaint`, `…/turbo/lora` | $0.005 | cheapest; the one with Inpaint; can be taught |

- **Inpaint:** GPT Image 2.5 Sunburst (its edit takes a mask, FA0) and Z-Image Turbo inpaint ($0.01 per megapixel).
- **Next if wanted:** Seedream 5.0 Pro ($0.0675) or Qwen Image 3 ($0.04).
- **Replaced:** FLUX.2 (today's cloud model) gives way to FLUX.3 klein.

### Video (make, animate, extend; lip sync stays as built)

| | Model | fal.ai endpoints | Price per second | Extend | Why |
|---|---|---|---|---|---|
| Top | **Gemini Omni Flash 1.2** (Google) | `google/gemini-omni-flash/v1.2/text-to-video`, `…/image-to-video`, `…/extend` | $0.08 at 720p, $0.12 at 1080p; sound included | yes | first in text to video (1540) and image to video (1503) |
| Top | **Seedance 2.5** (ByteDance) | `bytedance/seedance-2.5/us/text-to-video`, `…/image-to-video` | about $0.22 at 480p, $0.47 at 720p | no | second in image to video (1494); the dearest |
| Top | **MiniMax H3 Max** | `minimax/h3-max/text-to-video`, `…/image-to-video`, `…/extend-video` | $0.05 at 480p, $0.08 at 768p | yes | third in image to video (1493) |
| Cheaper | **MiniMax H3 Max Turbo** | `minimax/h3-max-turbo/…` (make, animate, extend) | $0.025 at 480p, $0.04 at 768p | yes | half of H3 Max |
| Cheaper | **Grok Imagine Video 1.5 lite** (xAI) | `xai/grok-imagine-video/v1.5/lite/text-to-video`, `…/image-to-video` | $0.02 at 480p, $0.03 at 720p | no (the full model has it) | cheapest; full model 5th in text to video |

- The Extend screen offers only the models that can extend.
- **Next if wanted:** FLUX 3 Video (4th in text to video, $0.17 per second at 720p) or Wan 3.0 ($0.10).
- **Replaced:** LTX-2 fast (today's cloud model). LTX-2.3 stays the trainable video model (Train models).

### Chat, Notebook and every text step (on OpenRouter)

| Model | Price (input / output, per million tokens) | Use |
|---|---|---|
| **Claude Sonnet 5.5** (`anthropic/claude-sonnet-5.5`) | $2 / $10 | best answers, the assistant, the agents |
| **Gemini 3.8 Flash** (`google/gemini-3.8-flash`) | $0.83 / $4.12 | quick, strong with pictures |
| **Claude Haiku 5.5** (`anthropic/claude-haiku-5.5`) | $0.10 / $0.50 | cheapest; prompts, lyrics, descriptions |

All three take pictures and tools. **DeepSeek V4.1 Flash** ($0.02 / $0.40) is a cheaper fourth if wanted.

**Embeddings** (Notebook and My creations search), both multilingual:
- **Cohere Embed 5 fast** (`cohere/embed-5-fast`), $0.08 per million tokens;
- **Voyage 4 lite** (`mongodb/voyage-4-lite`), $0.02 per million tokens.

These are OpenRouter's own prices (the model makers' list prices). OpenRouter adds 5.5% when credits are bought, and
nothing per request. fal.ai's route to the same models adds its own charge (listed only as "$0.01 per unit"), which is
why text runs on OpenRouter directly.

### Voice

| Tool | Options and price |
|---|---|
| Speak | **ElevenLabs v4** ($0.08 per 1,000 characters); **Gemini 3.8 Flash TTS** ($0.045); **Chatterbox multilingual** ($0.025); **MiniMax Speech 2.8 HD** ($0.10; added in FA0, since MiniMax clone and design speak only on it). Kokoro ($0.02, English only) stays for now. |
| Clone a voice | **Qwen3-TTS clone 1.7B** (very cheap: $0.0008 per minute); **MiniMax voice clone** ($1.50 per voice); **Chatterbox** with a reference voice (the Speak price) |
| Design a voice | **Qwen3-TTS voice design** ($0.09 per 1,000 characters); **MiniMax voice design** ($3 per voice) |
| Speech to text | **ElevenLabs Scribe v2** ($0.008 per minute); **NVIDIA Nemotron ASR multilingual** ($0.008 per minute); **Wizper** (Whisper v3, by compute time, cheapest) |
| Change a voice | **ElevenLabs voice changer** ($0.30 per minute); **Chatterbox HD** ($0.02); **Chatterbox** ($0.015) |
| Lip sync | as built: Fabric 1.0 Fast, Kling Avatar v2, OmniHuman 1.5, InfiniteTalk |
| Edit speech | none on fal.ai (see below) |

Dub and Audiobook use these.

### Music

| Tool | Options and price |
|---|---|
| Songs | **ElevenLabs Music v2.5** ($0.60 per minute, rounded up); **MiniMax Music 3** ($0.002 per second); **Mureka v9.5** ($0.15 a song with lyrics, $0.50 without). These replace today's MiniMax 2.6 and ElevenLabs Music. Google Lyria 3.5 ($0.10) is a fourth if its lyrics support is enough. |
| Sound effects | **ElevenLabs Sound Effects v3** ($0.002 per second); **Mirelo SFX 2.0** ($0.01 per second); **Stable Audio 3 small SFX** ($0.02 a clip) |
| Split into parts | **Demucs** ($0.0007 per second); **SAM Audio separate** ($0.05 per 30 s); **Mureka stems** ($0.02) |
| Edit music | **ACE-Step inpaint** ($0.0002 per second); **Stable Audio 3 medium inpainting** ($0.044 a clip). Mureka song edit was dropped in FA0: it edits only Mureka's own songs. |
| Lyrics | the chat models above |

### 3D

| Model | Price | Note |
|---|---|---|
| **Pixal3D** (today's) | $0.06 | cheapest |
| **Hunyuan3D 3.1 Pro** | $0.375 (+$0.15 for PBR materials) | stronger shapes and textures |
| **TRELLIS 2** | $0.25 to $0.35 by size | open model, good textures |

Cut-out before 3D: BiRefNet (by compute time, as today), or Bria ($0.018).

### Train models

| Card | On fal.ai | Price | Used afterwards with |
|---|---|---|---|
| A picture look or subject | **FLUX.3 klein trainer**; **Z-Image trainer** | $0.0043 a step ($4.30 for 1,000); $0.00226 a step ($2.26 for 1,000) | FLUX.3 klein and Z-Image Turbo (their `lora` endpoints) |
| A video look or motion | **LTX-2.3 trainer**; **MiniMax H3 trainer** | $0.0048 a step; $0.005 (make) or $0.01 (animate) a step | LTX-2.3 (`fal-ai/ltx-2.3-22b/…/lora`) and MiniMax H3 (`minimax/h3/…/lora`) |
| Teach it to write | none | — | stays on the desktop, this computer |
| Teach it to decide | none | — | stays on the desktop, this computer |

The cheaper picture models are the ones that can be taught, so a look made in Train is used on the Images screen
without a third model.

### Motion graphics and Creative Studio

No models of their own. Their steps use the models above:
- Motion graphics: the assistant (chat), and the Make panel (pictures, clips, speech, music).
- Creative Studio: the plan (chat), the shots (pictures, clips, lip sync) and the voice.

Song analysis, the render and FFmpeg are tools, not models (decision 2).

### Not on fal.ai

- **Edit speech** changes words inside a recording in the same voice. In the cloud it could be approximated by cloning
  the voice and speaking the changed sentence, but that is a new design, not a port.
- **Teach it to write** (a small language model) and **Teach it to decide** (Laya) have no trainer on fal.ai, so these
  two cards stay desktop-only, on this computer, in v1.
- **Tools that are not models:** song analysis (beats and sections for Creative Studio), reading documents (the
  notebook's reader), the Motion graphics render and FFmpeg joins and cuts. See decision 2.

Sources:
- fal.ai model list and price list (API, 2026-11-12)
- [arena.ai text to image](https://arena.ai/leaderboard/text-to-image)
- [arena.ai image edit](https://arena.ai/leaderboard/image-edit)
- [arena.ai text to video](https://arena.ai/leaderboard/video/text-to-video)
- [arena.ai image to video](https://arena.ai/leaderboard/video/image-to-video)
- [OpenRouter models](https://openrouter.ai/api/v1/models)

## How it is built

**Two providers in the code: OpenRouter for text, fal.ai for media.**
- OpenRouter stays (it is already a provider on the desktop and in LiteLLM on the web). It serves only text models:
  chat, vision, tools and embeddings. fal.ai serves only media models.
- Remove WaveSpeed, Runware, OpenAI, Anthropic, Gemini, Groq and "another OpenAI-compatible server" from:
  - `PROVIDERS`;
  - the catalogue;
  - Settings › Your keys;
  - Admin › Models;
  - `cloud_queues.py` (the WaveSpeed and Runware clients) and their tests.
- Keys already saved for those providers are deleted on first start, with a note in the log (decision 4).
- The catalogue (`own_keys_catalogue.py`) stays the one list of cloud models. It gains the models above, each with its
  price and, once measured, its speed.

**The desktop: local and cloud.**
- The model picker keeps its This computer and Cloud tabs. The Cloud tab lists the catalogue's cloud models for the
  screen: OpenRouter's on the text screens, fal.ai's on the media screens.
- Choosing one runs it on that provider with the person's key. Choosing a local one runs it here.
- Settings › Your keys has two keys: one OpenRouter key for text, one fal.ai key for media (decision 5).
- Every screen says where its model runs and what is sent there.

**The web: cloud only.**
- The web lists only the catalogue's cloud models (OpenRouter for text, fal.ai for media).
- People choose from them in the same picker, or the admin fixes one per product (decision 3).
- The service's two keys, OpenRouter and fal.ai, are set once in Admin (decision 5).
- ComfyUI, the engine workers' models and Ollama are no longer used for models on the web.
- Chat stays behind LiteLLM (rule 5), bound to LiteLLM's own OpenRouter provider (`openrouter/<model>`) with the
  service's OpenRouter key. No special header is needed (FA0's `Key` header was for fal.ai's route and is not used).
- Embeddings go the same way. The search index is rebuilt once, because the embedder changes (ADR-0041).
- Usage events (rule 9) carry each job's price, so the admin sees what the service spends: OpenRouter's reported
  cost for text, fal.ai's listed price for media. The two bills stay separate.

**Inputs go up first.** Every picture, voice and clip for a media model is sent to fal.ai's file store before the request
(`FalQueue.upload`), as lip sync does now. A request body that carries a file is refused as too long.

## Stages

| Stage | What | Done when |
|---|---|---|
| FA0 | ADR-0099, the owner's answers below; a free spike: LiteLLM to fal.ai with the `Key` header for chat and embeddings, and each new model's schema read | **Done 2026-11-12**: ADR Accepted; chat and embeddings through LiteLLM with `extra_headers` against a fake; every model's inputs read |
| FA1 | OpenRouter and fal.ai only: the other providers, their clients, catalogue lines, key rows and Admin › Models entries removed; old keys deleted; OpenRouter limited to text, fal.ai to media | the tests pass with the two providers; Settings and Admin show OpenRouter for text and fal.ai for media | **Done 2026-11-12**: `cloud_queues.py`, the WaveSpeed and Runware runners and testers, the text providers other than OpenRouter and the OpenAI-compatible server removed on the desktop; Gemini, Groq, Cerebras and LiteLLM strings removed from Admin › Models (Ollama stays there until FA10); old keys deleted by `OwnKeysService._prune`; checked by tests only, not in the window |
| FA2 | Chat and Notebook: text, vision and tools on OpenRouter (the desktop's fal.ai chat route of F1 moves back to OpenRouter); the embedder on OpenRouter (web always, desktop when chosen); the OpenRouter catalogue lines updated to the models above; audio sources read with Wizper on fal.ai | a chat, a picture description, a notebook answer with sources, and a reindexed search, against a fake |
| FA3 | Images: the five models above (GPT Image 2.5 Sunburst, Nano Banana 2.1, Grok Imagine Image 2.0, FLUX.3 klein, Z-Image Turbo) in make, change and combine; Inpaint on Z-Image Turbo; trained looks used through the `lora` endpoints | each mode makes a picture against a fake |
| FA4 | Video: the five models above (Gemini Omni Flash 1.2, Seedance 2.5, MiniMax H3 Max, H3 Max Turbo, Grok Imagine Video 1.5 lite) in make and animate; Extend on the four that can | make, animate and extend against a fake |
| FA5 | Voice: speak, clone, design, speech to text and change a voice on the models above; Dub and Audiobook follow; Edit speech stays local (desktop) or is hidden (web) | each tool works against a fake; the screens offer only what the chosen model can do |
| FA6 | Music: the new song and sound effect models; edit and split on the models above; Lyrics follows Chat | both against a fake |
| FA7 | 3D: Hunyuan3D 3.1 Pro and TRELLIS 2 added beside Pixal3D | each makes a model against a fake |
| FA8 | Train models: picture looks on the FLUX.3 klein and Z-Image trainers, video looks on the LTX-2.3 and MiniMax H3 trainers, then used through their `lora` endpoints; writing and deciding stay desktop-only | a look trained and used against a fake; the web shows two cards |
| FA9 | Motion graphics and Creative Studio: nothing new; their steps follow the products, and the tools run per decision 2 | a project made end to end against fakes, on the desktop and the web |
| FA10 | The web cloud-only: the picker lists the catalogue, Admin's rows default to OpenRouter (text) and fal.ai (media), Helm without ComfyUI and model workers, usage events with prices | the web stack runs every screen with no GPU and no local model |
| FA11 | Real run with the owner's keys (OpenRouter and fal.ai): one small thing per model (short clips at the lowest size, one training of 100 steps per trainer), the "about" prices measured; then the window and browser walks | about $15 in all, asked before it runs |

Each stage keeps the rules: every creation searchable (ADR-0041), every feature an action (ADR-0068), docs with the
code, and the measured price and time shown before Make.

## Decisions (answered by the owner 2026-11-12: every recommendation accepted)

1. **Where text models run.** First answer: OpenRouter's models through fal.ai's route, on fal.ai's key. **Changed by
   the owner the same day: on OpenRouter directly**, because fal.ai's route costs more than OpenRouter itself.
2. **Tools that are not models on the web** (the Motion graphics render, song analysis, reading documents, FFmpeg).
   **They keep running on the service's own CPU workers** (no GPU, no model files).
3. **On the web, who picks the model.** **The admin turns models on in Admin, and people choose among them in the
   picker.**
4. **Saved keys of the removed providers.** **Deleted on first start.**
5. **One key or one per product.** Today the desktop has a key per product (ADR-0095). **One OpenRouter key for text
   and one fal.ai key for media**, with an optional key for a product that should be billed apart. The web has the
   same two keys, set by the admin.
6. **Edit speech on the web.** **Hidden on the web in v1**, kept on the desktop (local).
7. **Teach it to write and Teach it to decide on the web.** **Not on the web in v1**: fal.ai has no trainer for them.
