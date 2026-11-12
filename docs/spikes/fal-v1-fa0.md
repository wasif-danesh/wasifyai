# FA0: the free checks for the v1 cloud providers (2026-11-12)

Stage FA0 of `docs/fal-only-v1-plan.md` (ADR-0099). Nothing was paid for:
- every call went to a fake or to fal.ai's free read routes;
- the owner's key was used only to read prices, and was never printed.

> **Overtaken the same day.** The owner moved text models to OpenRouter directly (ADR-0099, amended 2026-11-12),
> because fal.ai's route adds its own charge to OpenRouter's prices. LiteLLM then uses its own `openrouter/` provider,
> and section 1 below is not used. Sections 2 and 3 (the media models) still hold.

## 1. LiteLLM reaches fal.ai with its `Key` login (not used: text runs on OpenRouter)

The question: rule 5 wants every web LLM call through LiteLLM. fal.ai's OpenAI-compatible route
(`https://fal.run/openrouter/router/openai/v1`) wants `Authorization: Key …`, but LiteLLM's `openai/` provider sends
`Bearer …`.

How it was tested:
- The stack's own image, `ghcr.io/berriai/litellm:main-stable`, ran as a throwaway container.
- Its config had three models, all pointed at a fake fal.ai on this Mac.
- The fake refuses anything but `Key fake-fal-key` and records the header it gets.

| Model in LiteLLM | `litellm_params` | The fake saw | Result |
|---|---|---|---|
| chat, key only | `model: openai/anthropic/claude-haiku-5.5`, `api_key` | `Bearer fake-fal-key` | refused (401) |
| chat, with the header | the same plus `extra_headers: {Authorization: "Key …"}` | `Key fake-fal-key` | answered |
| embeddings, with the header | `model: openai/cohere/embed-5-fast`, the same header | `Key fake-fal-key` | answered |

**So:** an alias bound to fal.ai sets `extra_headers.Authorization` to `Key <the service's key>`, keeps `api_key` (any
value), and gives OpenRouter's model name after `openai/`. Rule 5 stands unchanged.

This was the plan for FA2 before the change:
- `model_access.build_params` writes that header for a fal.ai binding;
- the key stays in LiteLLM's database, encrypted as today;
- streaming is checked against the fake (the fake here answered whole replies only).

Found on the way: this LiteLLM image refuses to start without a master key (`LITELLM_MASTER_KEY`). `compose.yaml`
already sets one; this only mattered for the throwaway container.

## 2. The chosen models' inputs

Every endpoint in the plan's model tables was read from fal.ai's OpenAPI. Each one's fields, defaults and outputs are
in `fal-v1-fa0-inputs.md`. What changes the build:

**Images**
- **Inpaint on GPT Image 2.5 Sunburst too.** Its edit takes `mask_url` beside `image_urls`, so Inpaint can offer GPT
  Image as well as Z-Image Turbo (`mask_image_url`, `image_url`).
- **Several pictures** go to every edit endpoint as `image_urls` (combine).
- **Sizes differ by model:**
  - GPT Image, FLUX.3 klein and Z-Image take `image_size` names (`square_hd`, `portrait_16_9`…);
  - Nano Banana and Grok take `aspect_ratio` plus `resolution` (`1K`; Grok writes `1k`).

**Video**
- **Gemini Omni Flash** makes only 16:9 or 9:16. There is no square or 4:5; the screen offers only those two.
  Lengths are whole seconds.
- **Seedance 2.5** takes 4 to 10 seconds, or `auto`, and makes sound by default (`generate_audio`).
- **MiniMax H3 Max and Turbo:**
  - sizes are written `480P`, `768P`, `1080P`;
  - `prompt_expansion_mode` is required;
  - extend has `output: extended | continuation`.
- **Grok Imagine Video lite** has no extend (only the full model has one), as the plan says.

**Voice**
- **Cloning is two calls on Qwen3-TTS.** `clone-voice` returns a `speaker_embedding`, which Qwen3-TTS
  text-to-speech then speaks with. That is the $0.09 per 1,000 characters price.
- **MiniMax voice clone** returns a `custom_voice_id`. It speaks only on MiniMax's own speech models, so it needs
  MiniMax Speech as a Speak model as well.
- **Chatterbox multilingual** takes a named `voice` and `custom_audio_language`. Whether it accepts a reference
  recording is checked in FA5. If it does not, cloning has two options: Qwen3-TTS and MiniMax.
- **ElevenLabs v4** speaks only its own named voices (`voice`, default "Rachel"). There is no cloning on it through
  fal.ai.
- **Gemini 3.8 Flash TTS** takes `prompt`, `turns` and `speakers` (it can speak a dialogue of several voices) plus
  `style_instructions`.
- **Speech to text:**
  - Wizper defaults to English (`language: en`); the app passes the language or none.
  - Scribe v2 also tells speakers apart (`diarize`), which Dub can use.

**Music**
- **MiniMax Music 3 requires lyrics.** An instrumental needs the model's instrumental marker, checked in FA6.
- **Mureka song edit works only on songs Mureka made or that were uploaded to Mureka** (`song_id`, `upload_audio_id`).
  For "Edit music" on any recording, ACE-Step inpaint and Stable Audio 3 inpainting fit, so those two are the options.
  Mureka stays for songs only.
- **Demucs** returns six parts (vocals, drums, bass, piano, guitar, other).
- **SAM Audio** separates what a prompt names ("the vocals"), plus the rest.

**3D**
- Hunyuan3D 3.1 Pro takes `input_image_url`, with optional side views and `enable_pbr`.
- TRELLIS 2 takes `image_url` and `resolution` (512, 1024, 1536).
- Both return `model_glb`.

**Train models**
- **Picture trainers** take one zip of pictures:
  - FLUX.3 klein: `images_data_url`, `steps`, `trigger_phrase`;
  - Z-Image: `image_data_url`, `training_type` content, style or balanced.
- **Video trainers** take one zip of clips (`training_data_url`).
- Every trainer returns a LoRA file. The models' `lora` endpoints take it as `loras: [{path, scale}]`.

**Safety checkers.** Most endpoints have `enable_safety_checker`, on by default. ADR-0094 and the owner's release answers
say the app adds no censorship of its own. The build sends `false` wherever a model allows it, and leaves the provider's
own rules as they are. This is noted here for the owner to see; it is not a new rule.

## 3. Changes to the plan from FA0

- **Inpaint:** GPT Image 2.5 Sunburst and Z-Image Turbo.
- **Speak:** MiniMax Speech 2.8 HD ($0.10 per 1,000 characters) comes in, because MiniMax clone and design speak only
  on it. Speak then has four options.
- **Edit music:** ACE-Step inpaint and Stable Audio 3 inpainting. Mureka song edit is dropped, because it edits only
  Mureka's own songs.
