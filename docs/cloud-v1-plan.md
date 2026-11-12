# Cloud models in v1: Haiku 5.5 for text, the cheapest provider for media (plan, 2026-11-12)

Status: **accepted by the owner 2026-11-12**: the direction, and "Yes, accept all" for the nine decisions at the end
(every recommendation). Recorded as **ADR-0100** (Accepted). CP0 to CP2 done 2026-11-12; CP3 is next.

What the owner asked for:
- "We will go with Haiku 5.5 in v1 for cloud option in desktop and web, although it will be better to make it flexible
  for users so they can enter their preferred vendor like Anthropic/ChatGPT/Gemini/DeepSeek/GLM."
- "Can we have Runware, WaveSpeed, and fal.ai, but include a check to use the cheapest among the providers?"

This plan replaces how `docs/fal-only-v1-plan.md` (ADR-0099) runs the models. It keeps that plan's choices:
- **The models:** three top and two cheaper for Images and Video, two or three for the rest.
- **The desktop:** local and cloud models.
- **The web:** cloud models only, with tools that are not models on CPU workers.
- **Not on the web:** Edit speech, Teach it to write and Teach it to decide.

Where the numbers come from:
- **Prices:** the providers' list prices on 2026-11-12, from `docs/spikes/provider-cost-2026-11.md`.
- **The fal.ai models' inputs:** `docs/spikes/fal-v1-fa0-inputs.md`.

## Where things stand

- **FA0 is done.** Its findings on the models' inputs still hold for fal.ai.
- **FA1 is done in the working tree and not committed.** It removed WaveSpeed, Runware, Anthropic, OpenAI, Gemini, Groq
  and the OpenAI-compatible server, and left OpenRouter (text) and fal.ai (media).
  - The last commit (`f9834ba1`) still has the removed code.
  - CP1 brings back what this plan needs, so FA1's deletions need not be committed first.
- **Lip sync runs on fal.ai today** (four models). Kokoro speech, MiniMax 2.6 and ElevenLabs music, and Pixal3D also run
  on fal.ai.
- **Nothing else from the fal.ai plan was built** (FA2 to FA11).

## Text

**Claude Haiku 5.5 is the default** on the desktop's Cloud tab and on the web, bought from Anthropic directly. The
person can choose another vendor and model instead (decisions 1 and 2).

| Vendor | Models in the catalogue (in / out per million tokens) | Address | Notes |
|---|---|---|---|
| **Anthropic** (default) | **Claude Haiku 5.5** `claude-haiku-5-5`: $0.10 / $0.50 for prompts up to 100K tokens, $0.50 / $2.50 above. Claude Sonnet 5.5: $2 / $10, for harder work | `api.anthropic.com`, its Messages API | prepaid credits; they expire after a year |
| **OpenAI** | GPT-6 Luna: $0.10 / $0.50 (up to a 272K-token prompt) | `api.openai.com/v1` | price confirmed at OpenAI (CP0); prepaid credits |
| **Google** | Gemini 3.8 Flash: $0.75 / $3.75 to 2026-12-31, then $1.50 / $7.50 | Gemini API (OpenAI-compatible route) | prepaid credits, $5 minimum |
| **DeepSeek** | DeepSeek V4.1 Flash `deepseek-flash`: $0.30 / $1.20, half price off-peak | `api.deepseek.com` (OpenAI-compatible) | China-based; the screen says where data goes |
| **Z.ai** | GLM-5.3 Flash `glm-5.3-flash`: $0.15 / $0.50 | `api.z.ai/api/paas/v4` (OpenAI-compatible) | China-based; recharged ahead (prepaid) |
| **OpenRouter** | any of the above, at the maker's price plus 5.5% on credits | already built | kept if decision 1 says so |

What Haiku 5.5 needs from the code (from Anthropic's notes on the model):
- **No temperature, top_p or top_k other than the default, and no assistant prefill.** Each returns an error. The app
  sets a temperature in four places, and the Haiku path must not send them:
  - `desktop_llm.py:189`
  - `remote_builder.py:333`
  - `desktop_video_builder.py:146`
  - `model_defaults.yaml:35`
- **It thinks before answering by default.** Thinking is billed as output and counts toward `max_tokens`. Effort is set
  per job:
  - **low:** prompts, lyrics, picture descriptions;
  - **medium:** chat and Notebook;
  - **high:** the assistant, Creative Studio's plan and the Motion graphics editor.
- **Answers are read by block type, not by position:** a reply can start with a thinking block. Thinking blocks go back
  unchanged with tool results, and earlier turns are never edited.
- **It may decline a request** (`stop_reason: "refusal"`). The app shows that as an answer, not as an error.
- **Prompts over 100K tokens cost five times as much.** Notebook keeps what it sends under 100K tokens.
- **Prompt caching** for the long system prompts and tool lists: cached reads cost a tenth of the input price.
- **It is called through Anthropic's own API:** Anthropic's Python SDK on the desktop, and LiteLLM's `anthropic/`
  provider on the web. Anthropic's OpenAI-compatible route is not used: it lacks thinking and effort.

The other vendors use the desktop's existing OpenAI-style client, and LiteLLM's own provider for each on the web
(`openai/`, `gemini/`, `deepseek/`, and `openai/` with Z.ai's address).

**Embeddings.** Anthropic has none, so Notebook and My creations search need another source (decision 4):
- the desktop keeps its local embedder;
- the web uses OpenAI text-embedding-3-small at $0.02 per million tokens (CP0), on the admin's OpenAI key.

## Media: the cheapest provider for each job

How it works:
- **Offers.** Each media line in the catalogue lists its **offers**. An offer is a provider, its endpoint for the model,
  a price for each setting, and what it can do (a mask, a trained look, extend).
- **Picking an offer.** At Make, the app prices the job on every offer that has a key and can do what was asked. It
  picks the cheapest; on a tie, Runware, then WaveSpeed, then fal.ai.
- **Fallback.** If the chosen provider refuses before running, the next offer takes the job. A job the provider may
  have charged for is never sent again.
- **Inputs.** Pictures, voices and clips are uploaded to the chosen provider just before the request: fal.ai's file
  store, Runware's image upload, WaveSpeed's upload.

The tables list the offers v1 builds: **the cheapest and one fallback** (decision 5). A dash means the model is not
offered there. Prices are per picture (1K), per second of video, per 1,000 characters, per minute, per song or per
model, as marked.

### Images

| Model | Runware | WaveSpeed | fal.ai | Built in v1 |
|---|---|---|---|---|
| GPT Image 2.5 Sunburst (high) | ~$0.125 | **$0.09** | ~$0.125 | WaveSpeed, fal.ai (both take a mask for Inpaint, CP0) |
| Nano Banana 2.1 | **~$0.034** | $0.04 | ~$0.04 | Runware, WaveSpeed |
| Grok Imagine Image 2.0 | **$0.04 to $0.06** | $0.08 | $0.04 to $0.06 | Runware, fal.ai |
| FLUX.3 klein | **~$0.006**, no trained looks | $0.01 ($0.015 with a look) | $0.009 | Runware; fal.ai for trained looks and as the fallback |
| Z-Image Turbo (and Inpaint) | **~$0.001 to $0.003**, mask and looks | $0.005 | $0.005 | Runware, fal.ai |

### Video

| Model | Runware | WaveSpeed | fal.ai | Built in v1 |
|---|---|---|---|---|
| Gemini Omni Flash 1.2 (720p) | **$0.07**, can extend | $0.07 | $0.082 | Runware (Extend too), WaveSpeed |
| Seedance 2.5 (720p) | **$0.23**, can extend | $0.36, can extend | ~$0.46 | Runware, WaveSpeed (Extend on both, CP0) |
| MiniMax H3 Max (768p) | **$0.08**, no extend | — | $0.08, extends | Runware; fal.ai for Extend and as the fallback |
| MiniMax H3 Max Turbo (768p) | **$0.04**, no extend | — | $0.04, extends | Runware; fal.ai for Extend and as the fallback |
| Grok Imagine Video 1.5 lite (720p) | **$0.03** | — | $0.03 | Runware, fal.ai |

### Lip sync (built today on fal.ai, which stays as the fallback)

| Model | Runware | WaveSpeed | fal.ai | Added in v1 |
|---|---|---|---|---|
| Fabric 1.0 (480p) | $0.08 | **$0.07** | $0.10 (Fast) | WaveSpeed |
| Kling Avatar v2 standard | **$0.044** | $0.056 | $0.06 | Runware |
| OmniHuman 1.5 | **$0.132** | ~$0.16 | $0.16 | Runware |
| InfiniteTalk (480p) | — | **$0.03** | $0.20 | WaveSpeed |

### Voice

| Tool and model | Runware | WaveSpeed | fal.ai | Built in v1 |
|---|---|---|---|---|
| Speak: ElevenLabs v4 | — | $0.08 | $0.08 | WaveSpeed, fal.ai |
| Speak: Gemini 3.8 Flash TTS | only 3.1 | $0.05 | **$0.045** | fal.ai, WaveSpeed |
| Speak: Chatterbox | — | $0.03, takes a reference voice | **$0.025** | fal.ai, WaveSpeed |
| Speak: MiniMax Speech 2.8 HD | $0.10, named voices only | $0.10 | $0.10 | Runware, fal.ai; a MiniMax cloned voice speaks on WaveSpeed or fal.ai, where it was made (CP0) |
| Clone and design: Qwen3-TTS | **$0.015** | $0.05 and up | $0.09 | Runware, fal.ai |
| Clone and design: MiniMax | — | $1.60 / $3.10 a voice | **$1.50 / $3** | fal.ai, WaveSpeed |
| Speech to text: Scribe v2, Wizper / Whisper | — | Scribe; Whisper $0.06 per min | **Scribe $0.008 per min**, Wizper | fal.ai, WaveSpeed |
| Change a voice: ElevenLabs | — | **$0.24 per min** | $0.30 per min | WaveSpeed, fal.ai |
| Change a voice: Chatterbox | — | $0.02 per min | **$0.015** | fal.ai, WaveSpeed |

### Music and sound effects

| Tool and model | Runware | WaveSpeed | fal.ai | Built in v1 |
|---|---|---|---|---|
| Songs: ElevenLabs Music v2.5 | — | $0.75 per min | **$0.60 per min** | fal.ai, WaveSpeed |
| Songs: MiniMax Music 3 | only 2.6 | $0.15 a song | $0.002 per s (cheaper below 75 s) | fal.ai, WaveSpeed (the pick depends on length) |
| Songs: Mureka v9.5 | — | $0.225 a song | **$0.15 a song** | fal.ai, WaveSpeed (a Mureka song is edited only where it was made) |
| Sound effects: ElevenLabs v3 | — | $0.002 per s | $0.002 per s | WaveSpeed, fal.ai |
| Sound effects: Mirelo 2.0 | 1.5 only | $0.02 per s | **$0.01 per s** | fal.ai, WaveSpeed |
| Sound effects: Stable Audio 3 small | — | — | $0.02 a clip | fal.ai only |
| Split: Demucs, SAM Audio | — | vocals and the rest only | **fal.ai** | fal.ai only |
| Split: Mureka stems | — | $0.09 a song | **$0.02** | fal.ai, WaveSpeed |
| Edit: ACE-Step inpaint | **repaint, by compute time** | no inpaint (CP0) | $0.0002 per s | Runware, fal.ai |
| Edit: Stable Audio 3 inpainting | — | — | $0.044 a clip | fal.ai only |

### 3D

| Model | Runware | WaveSpeed | fal.ai | Built in v1 |
|---|---|---|---|---|
| Pixal3D | — | — | $0.06 | fal.ai only (as today) |
| Hunyuan3D 3.1 Pro | **$0.375** ($0.525 with PBR) | only v3 and 3.1 Rapid | $0.375 (+$0.15 PBR) | Runware, fal.ai |
| TRELLIS 2 | **~$0.01** (compute time) | $0.20 | $0.25 to $0.35 | Runware, WaveSpeed |

### Train models

| Card | Runware | WaveSpeed | fal.ai | Built in v1 |
|---|---|---|---|---|
| Picture look on FLUX.3 klein | — | — | $0.0043 a step | fal.ai only |
| Picture look on Z-Image | **$0.00182 a step**, style looks only | $1.25 a run | $0.00226 a step; content, style or balanced | Runware for style looks, fal.ai for the rest and as the fallback |
| Video look on LTX-2.3 or MiniMax H3 | — | LTX-2 19B only | yes | fal.ai only |
| Teach it to write, Teach it to decide | — | — | — | desktop only, on this computer (as decided) |

A trained look is a LoRA file. It is used on the providers that can load it: fal.ai and WaveSpeed by its address,
Runware once it is uploaded there.

### Motion graphics and Creative Studio

They have no models of their own. Their steps pick offers like any other job, and the tools that are not models run as
ADR-0099 decision 4 says.

## How it is built

**One catalogue.** `own_keys_catalogue.py` stays the one list of cloud models:
- a text line names its vendor and model;
- a media line names its model and its offers.

The router, the price shown before Make, the usage event and the Cloud tab all read it.

**Keys.**
- **The desktop:** Settings › Your keys has a key for each text vendor and each media provider, all optional.
  - Text runs on the vendor of the chosen model; Haiku 5.5 needs an Anthropic key.
  - Media runs on whichever providers have keys: one key is enough, and more keys give cheaper picks and fallbacks.
  - The optional key per product (ADR-0095) stays, for separate billing.
- **The web:** Admin › Models holds the service's text vendor keys (in LiteLLM, encrypted as today). Admin › Media
  holds the three media keys.

**The router** (`own_keys_engines.py` and the web's media worker), for each media job:
1. Find the offers for the chosen model that have a key and support the job's options and inputs.
2. Price each one with its formula for the job's settings, and order them.
3. Upload the inputs to the first provider and send the job.
4. If that provider refuses before running it, go to the next offer. Otherwise report the result or the error.
5. Write the usage event with the provider and the price.

**The screens.**
- The Cloud tab and the web picker show a model once, with "from $x".
- The price line before Make says "on Runware, $0.23" and so on.
- Each screen says where its model runs and what is sent there (existing rule).

**Prices kept current.** `scripts/cloud-prices/refresh` rereads each provider's price list and writes the changes as a
reviewable diff of the catalogue:
- fal.ai's price API (with a key);
- Runware's model `schema.json` files;
- WaveSpeed's model pages.

## Stages

| Stage | What | Done when |
|---|---|---|
| CP0 | The decisions answered and ADR-0100 Accepted (**done 2026-11-12**). Free checks, nothing paid: every Runware and WaveSpeed offer's inputs read (as FA0 did for fal.ai); OpenAI's, Z.ai's and DeepSeek's prices and billing confirmed on their own pages; LiteLLM's support for Haiku 5.5's effort setting and for DeepSeek and Z.ai checked against a fake; the embedding choice priced | a written note like `fal-v1-fa0-inputs.md` for the two new providers; the decisions recorded. **Done 2026-11-12** (`docs/spikes/cloud-v1-cp0.md`): inputs, prices, billing and embeddings read; LiteLLM 1.106.1 reaches Haiku 5.5 (temperature dropped, effort passed), DeepSeek, Z.ai and OpenAI embeddings against a fake |
| CP1 | Providers back in shape: from the last commit, the WaveSpeed and Runware clients, runners, testers and tests; Anthropic, OpenAI and Gemini; DeepSeek and Z.ai added. The per-product `use` choice gives way to the text vendor choice and the media router. Key pruning deletes only Groq, Cerebras and the OpenAI-compatible server | the tests pass; Settings and Admin list the vendors and the three media providers (against fakes). **Done 2026-11-12:** `own_keys.py` lists the six text vendors (Anthropic first) and Runware, WaveSpeed and fal.ai; key tests for Anthropic (its free model list), WaveSpeed (balance) and Runware (`authentication` task); the catalogue has Haiku 5.5, Sonnet 5.5, GPT-6 Luna, Gemini 3.8 Flash, DeepSeek V4.1 Flash and GLM-5.3 Flash, direct and through OpenRouter, and the WaveSpeed and Runware picture and song lines back; `cloud_queues.py` and the runners restored; web Admin offers the five vendors beside OpenRouter (Z.ai at its fixed address through `openai/`). Pruning keeps the vendors, WaveSpeed and Runware. The per-product `use` stays for now: the text vendor choice is the Chat row's `use`, and the media `use` gives way to the router in CP3. Text to Anthropic still goes through its OpenAI-compatible route with a temperature until CP2 |
| CP2 | Text on Haiku 5.5: Anthropic's own API (the SDK on the desktop, LiteLLM's `anthropic/` on the web); effort per job; no temperature or prefill; refusals shown; prompt caching; Notebook under 100K tokens; the other vendors selectable; embeddings per decision 4 | a chat, a picture description, an assistant tool call, a Creative Studio plan and a Notebook answer with sources, against a fake of each vendor. **Done 2026-11-12:** the desktop reaches Anthropic through the `anthropic` SDK (`anthropic_text.py`): no temperature or prefill, adaptive thinking with an effort per job (low for prompts, lyrics and picture descriptions; medium for chat and Notebook; high for the assistant, Creative Studio and Motion graphics), thinking summaries only when the person turns Thinking on, structured output for schemas, prompt caching, a refusal said in words; the thinking blocks of a tool loop are kept and replayed unchanged, and when Anthropic refuses them (preserved thinking) or they are gone the round runs with thinking off. Motion graphics' draft now follows a cloud key too. The web's aliases are Haiku 5.5 with an effort each and a new `planner` alias (assistant, Creative Studio, Motion graphics); the keys are LiteLLM's environment. Web embeddings are OpenAI 3-small at 1024 and 768 dimensions (no migration; the index re-embeds by its model name); the search floor is 0.35 until CP13 measures it. Notebook's sources and history are capped at 75K estimated tokens, under the 100K price step. Tested against fakes of Anthropic and the four OpenAI-compatible vendors |
| CP3 | The router: offers in the catalogue, pricing per offer, the cheapest pick, the tie order, fallback only before running, pinned voices, songs and looks, usage events with the provider | unit tests over priced offers, refusals and pinned results |
| CP4 | Images: the offers in the Images table, in make, change, combine and Inpaint; trained looks | each mode on each offer against a fake |
| CP5 | Video: the Video table's offers in make and animate; Extend on Runware (Omni, Seedance), WaveSpeed (Seedance) and fal.ai (H3) | make, animate and extend on each offer against a fake |
| CP6 | Lip sync: the cheaper offers added beside fal.ai | each model on its new offer against a fake |
| CP7 | Voice: speak, clone, design, speech to text and change a voice; Dub and Audiobook follow; Edit speech stays local (desktop) and hidden (web) | each tool on each offer against a fake |
| CP8 | Music and sound effects: songs, sound effects, split and edit | each on each offer against a fake |
| CP9 | 3D: Hunyuan3D 3.1 Pro and TRELLIS 2 beside Pixal3D | each on each offer against a fake |
| CP10 | Train models: picture looks (FLUX.3 klein on fal.ai; Z-Image on Runware or fal.ai), video looks on fal.ai, and their use afterwards | a look trained and used against fakes; the web shows two cards |
| CP11 | The web cloud-only (the old FA10): the picker lists the catalogue; Admin's keys; Helm without ComfyUI and model workers; Motion graphics and Creative Studio end to end | the web stack runs every screen with no GPU and no local model, against fakes |
| CP12 | The price refresh script, and the prices in the catalogue checked by it | the script writes a diff and the tests pass on it |
| CP13 | Real run with the owner's keys, asked before it runs: one small thing per offer (short clips at the lowest size, one 100-step training per trainer), the text jobs of CP2 on Haiku 5.5, measured prices against the catalogue; then the window and browser walks | about $30 in all |

Each stage keeps the rules: every creation searchable (ADR-0041), every feature an action (ADR-0068), docs with the
code, and the measured price and time shown before Make.

## Decisions (answered by the owner 2026-11-12: every recommendation accepted)

1. **Which text vendors to offer.** Anthropic, OpenAI, Google, DeepSeek and Z.ai, as asked. Should OpenRouter stay as a
   sixth? *Recommended: yes.* It is already built, and gives access to any model. Its 5.5% fee is the person's choice.
   The "another OpenAI-compatible server" option stays removed: local models already run on This computer.
2. **How the person picks a text model.** A short list per vendor (its cheap model and its strong one), or a list plus
   a field to type any model name. *Recommended: the list only.* A typed name can be a model that lacks pictures or
   tools, and the screens would break in ways that are hard to explain.
3. **On the web, who chooses the vendor.** *Recommended: the admin* (as in ADR-0099 and the release answers). The
   admin sets the keys and turns models on; people pick among them, with Haiku 5.5 as the default.
4. **Embeddings for Notebook and My creations search** (Anthropic has none).
   - **The desktop:** *recommended*, the local embedder it has today: free, and nothing leaves the computer.
   - **The web, one of:**
     - (a) OpenAI's or Google's embedding model, on the admin's key for that vendor;
     - (b) the small local embedder on the web's CPU worker: no extra vendor, but a model file on the web.

     *Recommended: (a)*, priced in CP0. It keeps the web free of model files, as ADR-0099 wants.
5. **How many offers per model in v1.** *Recommended: the cheapest and one fallback*, as in the tables. Every offer would
   roughly double the connections to build and test. More are added later as catalogue lines.
6. **Fallback.** *Recommended: automatic, but only when the provider refused before running.* Never resend a job that
   may have been charged.
7. **Tie order.** *Recommended: Runware, then WaveSpeed, then fal.ai.* Runware's credits never expire, and fal.ai has
   the most models to spare for fallbacks.
8. **Price updates.** *Recommended: the script writes a diff that is reviewed and committed.* Prices are never changed
   by themselves.
9. **The desktop's media keys.** *Recommended: any one of the three is enough.* The app picks among the providers the
   person has keys for, and says when another key would make a model cheaper.
