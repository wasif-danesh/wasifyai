# CP0: the free checks for the cloud providers (2026-11-12)

Stage CP0 of `docs/cloud-v1-plan.md` (ADR-0100). **Done 2026-11-12.** Nothing was paid for, and no key was used. Every input below was read
from the providers' own published schemas:
- **Runware:** each model's `runware.ai/docs/models/<id>/schema.json`.
- **WaveSpeed:** each model's `wavespeed.ai/models/<id>/llms.txt` and its API docs.
- **Text and embeddings:** the vendors' own pricing pages.

## 1. Runware

**How a request works.**
- **Address and auth:** one address, `POST https://api.runware.ai/v1`, with `Authorization: Bearer <key>`.
- **The body is a list of tasks.** Each task has:
  - a `taskType`: `imageInference`, `videoInference`, `audioInference`, `3dInference` or `training`;
  - a `taskUUID` of our choosing;
  - the model's AIR id;
  - `deliveryMethod` set to `async` for long jobs; results are then fetched with the same UUID.
- **Inputs are taken in place.** Pictures can be a URL, a data URI, base64, or the UUID of an earlier upload. Clips and
  audio can be a URL or an upload UUID. So no upload step is needed when the file already has an address.
- **Each job's actual cost comes back:** `includeCost: true` returns it in USD. The usage event can record what was
  really charged (rule 9).
- **Testing a key:** the `authentication` task checks it without making anything, as before FA1.

**The v1 offers.** Each entry gives the model's AIR id, then what changes the build.

- **Images**
  - **Nano Banana 2.1** (`google:nano-banana@2.1`):
    - up to 14 reference pictures;
    - `resolution` is `1K`, `2K` or `4K`;
    - `settings.safetyTolerance` defaults to `none`.
  - **Grok Imagine Image 2.0** (`xai:grok-imagine@image-2.0`): up to 5 reference pictures; `settings.quality` is `low`
    or `medium`.
  - **FLUX.3 klein** (`bfl:flux@3-image-klein`): up to 4 reference pictures. **It takes no LoRA**, so trained looks go
    to fal.ai, as planned.
  - **Z-Image Turbo** (`runware:z-image@turbo`):
    - `inputs.seedImage` and `inputs.maskImage` (Inpaint);
    - `lora: [{model, weight}]`, where `model` is the AIR id of a look in Runware's library;
    - width and height from 128 to 2048.
- **Video** (every model here makes sound by default)
  - **Seedance 2.5** (`bytedance:seedance@2.5`):
    - 4 to 30 s, or `auto`;
    - `480p`, `720p` or `1080p`;
    - `settings.audio` defaults to true;
    - `inputs.frameImages` for the first and last frames.
    - **It can extend:** `inputs.video` plus `settings.operation: "extend"`.
  - **Gemini Omni Flash 1.2** (`google:gemini@omni-flash-1.2`):
    - 3 to 15 s;
    - `360p` to `4K`;
    - extends from `inputs.video`, or from `inputs.videoId` for a clip it made.
  - **MiniMax H3 Max** (`minimax:h3@max`) and **H3 Max Turbo** (`minimax:h3@max-turbo`):
    - 5 to 15 s at `480p` or `768p`;
    - `settings.promptExpansion`;
    - **no extend**, so H3's Extend goes to fal.ai, as planned.
  - **Grok Imagine Video 1.5 lite** (`xai:grok-imagine@video-1.5-lite`): 1 to 15 s, `480p` to `1080p`, first frame only.
- **Lip sync**
  - **Kling Avatar 2.0 standard** (`klingai:avatar@2.0-standard`): `inputs.image` and `inputs.audio`.
  - **OmniHuman 1.5** (`bytedance:5@2`): the same, plus an optional `mask`.
  - **Fabric 1.0** (`veed:fabric@1.0-hosted`): the same, at `480p` or `720p`.
- **Voice**
  - **MiniMax Speech 2.8** (`minimax:speech@2.8`): **only MiniMax's named voices**. A MiniMax cloned voice cannot
    speak here.
  - **Qwen3-TTS:**
    - clone with the base model: `inputs.audio` plus `settings.transcript`;
    - named voices with the CustomVoice model;
    - design with the VoiceDesign model, by `positivePrompt`.

    It speaks 10 languages (Chinese, English, Japanese, Korean, German, French, Russian, Portuguese, Spanish and
    Italian), with no Bengali or Hindi.
- **Music**
  - **ACE-Step 1.5 turbo** (`runware:ace-step@v1.5-turbo`):
    - songs from 30 to 300 s, with `lyrics`, `bpm` and `vocalLanguage` (which includes `bn` and `hi`);
    - **edit music by repainting:** `inputs.audio` plus `settings.repaintingStart` and `repaintingEnd`.

    So Runware can take Edit music (on ACE-Step), and WaveSpeed can't (§2).
- **3D**
  - **Hunyuan 3D 3.1 Pro** (`tencent:hunyuan-3d@3.1-pro`): up to 8 pictures, `settings.pbr`.
  - **TRELLIS 2** (`microsoft:trellis-2@4b`): resolution 512, 1024 or 1536. It returns GLB.
- **Training**
  - **Z-Image style trainer** (`runware:z-image@style-lora-training`):
    - `inputs.dataset`, 10 to 4,000 `trainingSteps`, `triggerWord`;
    - `importModel` (`air`, `name`) puts the result in Runware's library, under an AIR id that Z-Image's `lora` then
      uses.

    Whether the file can also be downloaded for fal.ai is checked in CP10.

## 2. WaveSpeed

**How a request works.**
- **Address and auth:** each model has its own address, `POST https://api.wavespeed.ai/api/v3/<model-id>`, with
  `Authorization: Bearer <key>`.
- **It runs asynchronously:** the answer is a prediction id, polled at `GET /api/v3/predictions/<id>/result`. The status
  is `created`, `processing`, `completed` or `failed`, and the outputs are URLs.
- **Inputs are URLs.** Files go up first:
  1. `POST /api/v3/media/uploads` with `filename`, `size` and `content_type`;
  2. `PUT` the bytes to the `upload.url` it returns, without the key;
  3. use `data.download_url` in the request.

  Files can be up to 200 MB, and they are kept for 7 days.
- **Balance:** `GET /api/v3/balance` returns `data.balance` in USD. A key test can use it without making anything.

**The v1 offers** (the WaveSpeed model id, then what changes the build):

- **Images**
  - **GPT Image 2.5 Sunburst** (`openai/gpt-image-2.5-sunburst/text-to-image`, `…/edit`):
    - `quality` from `low` to `max`;
    - `resolution` `1k`, `2k` or `4k`;
    - `aspect_ratio`;
    - **the edit takes `mask_image`**, so Inpaint can use WaveSpeed's cheaper price, with fal.ai as the fallback.
  - **Nano Banana 2.1** (`google/nano-banana-2.1/text-to-image`, `…/edit`): `images[]`, `aspect_ratio`, `resolution`
    `1k` to `4k`.
- **Video**
  - **Gemini Omni Flash 1.2** (`google/gemini-omni-1.2-flash/text-to-video`, `…/image-to-video`):
    - 16:9 or 9:16 only;
    - 3 to 15 s;
    - a `last_image` for animate.
  - **Seedance 2.5** (`bytedance/seedance-2.5/image-to-video`, `…/video-extend`):
    - 4 to 30 s;
    - `generate_audio` defaults to true;
    - **it has extend.**
- **Lip sync**
  - **Fabric 1.0** (`veed/fabric-1.0`): `image`, `audio`, `480p` or `720p`.
  - **InfiniteTalk** (`wavespeed-ai/infinitetalk`): `image`, `audio`, an optional `mask_image` and `prompt`, at
    `480p` or `720p`.
  - **Kling Avatar v2 standard** (`kwaivgi/kling-v2-ai-avatar-standard`): `image`, `audio`, `prompt`.
- **Voice**
  - **ElevenLabs v4** (`elevenlabs/eleven-v4`): `voice_id` is one of ElevenLabs' named voices (default "Alicia"),
    plus `stability` and `similarity`.
  - **Gemini 3.8 Flash TTS** (`google/gemini-3.8-flash/text-to-speech`): `voice`, `style_instructions`, `speakers`
    and `turns` (a dialogue).
  - **Chatterbox** (`chatterbox/text-to-speech`, `…/speech-to-speech`): **takes a `reference_audio`**, so it can speak
    or change speech in a given voice.
  - **MiniMax voice clone and design** (`minimax/voice-clone`, `minimax/voice-design`):
    - we choose the `custom_voice_id`;
    - clone names the speech model the voice is for (up to `speech-2.8-hd`).

    WaveSpeed also has `minimax/speech-2.8-hd`, so a voice cloned there speaks there.
  - **Speech to text:**
    - Scribe v2 (`elevenlabs/scribe-v2`): `language_code`, `diarize`;
    - Whisper (`wavespeed-ai/openai-whisper`): `language`, translate, timestamps.
  - **ElevenLabs voice changer** (`elevenlabs/voice-changer`): changes to ElevenLabs' named voices only.
- **Music and sound effects**
  - **ElevenLabs Music v2.5** (`elevenlabs/music-v2.5`): `music_length_ms` from 3 s to 10 min, `force_instrumental`.
  - **MiniMax Music 3** (`minimax/music-3.0`): `lyrics`, `is_instrumental`.
  - **Mureka v9.5** (`mureka-ai/mureka-v9.5/generate-song`): `lyrics` is required. Instrumentals go to its
    `generate-bgm`.
  - **Mureka stems** (`mureka-ai/stem-song`): `audio-separation-1` or `-2`. The page lists $0.09 and $1.05, so it is
    measured in CP13 before use.
  - **ElevenLabs Sound Effects v3** (`elevenlabs/sound-effects-v3`): 0.5 to 30 s, `loop`.
  - **Mirelo SFX 2.0** (`mirelo-ai/sfx-2.0/text-to-audio`): 0.1 to 600 s.
  - **ACE-Step 1.5** (`wavespeed-ai/ace-step-1.5`): **makes songs only; it has no inpaint.** So Edit music on ACE-Step
    runs on Runware and fal.ai, not WaveSpeed.
- **3D**
  - **TRELLIS 2** (`wavespeed-ai/trellis-2/image-to-3d`): resolution 512, 1024 or 1536; `texture_size`;
    `remove_background` defaults to true.

## 3. Text vendors: prices and billing

| Vendor | Model | Price per million tokens (in / out) | Billing |
|---|---|---|---|
| Anthropic | Claude Haiku 5.5 `claude-haiku-5-5` | $0.10 / $0.50 up to a 100K-token prompt, $0.50 / $2.50 above; cached reads $0.01 | prepaid credits with auto-reload; expire after a year |
| OpenAI | GPT-6 Luna | **$0.10 / $0.50** up to a 272K-token prompt, $0.20 / $0.75 above; cached $0.01 (OpenAI's page) | prepaid credits |
| OpenAI | gpt-5-nano | $0.05 / $0.40 | prepaid credits |
| Google | Gemini 3.8 Flash | $0.75 / $3.75 to 2026-12-31, then $1.50 / $7.50 (thinking billed as output) | prepaid credits, $5 minimum, expire after 12 months |
| DeepSeek | V4.1 Flash `deepseek-flash` | $0.30 / $1.20 at peak, $0.15 / $0.60 off-peak; cached $0.006 | a topped-up balance; granted credit can expire (its balance API separates the two) |
| Z.ai | GLM-5.3 Flash `glm-5.3-flash` | $0.15 / $0.50; cached $0.03 | recharged on the billing page (prepaid); expiry not stated |

Notes:
- OpenAI's page doesn't say whether GPT-6 Luna takes pictures. OpenRouter lists it with picture input; CP2 checks this.
- Z.ai's own pages don't say whether GLM-5.3 Flash takes pictures. OpenRouter lists it with picture input, and Z.ai
  sells separate vision models (GLM-4.6V). Checked in CP2.
- DeepSeek also takes Anthropic-format requests (`https://api.deepseek.com/anthropic`).

## 4. Embeddings on the web (decision 4)

| Model | Price per million tokens |
|---|---|
| **OpenAI text-embedding-3-small** | **$0.02** |
| OpenAI text-embedding-3-large | $0.13 |
| Google gemini-embedding-001 | $0.15 ($0.075 in batch) |
| Google gemini-embedding-2 | $0.20 ($0.10 in batch) |

**So:** the web uses **OpenAI text-embedding-3-small**, on the admin's OpenAI key. It is the cheapest by far, and
multilingual. The desktop keeps its local embedder (decision 4).

## 5. LiteLLM with Haiku 5.5, DeepSeek, Z.ai and OpenAI embeddings (passed)

**How it was tested.**
- The stack's own image (`ghcr.io/berriai/litellm:main-stable`, LiteLLM **1.106.1**, already in Podman) ran as a
  throwaway container with `drop_params: true`.
- Four aliases pointed at a fake on this Mac. The fake answers in each vendor's shape (Anthropic Messages, OpenAI chat,
  embeddings) and records every request body.
- Requests went in OpenAI's format, as the web's services send them.

| Alias (`litellm_params.model`) | Sent to LiteLLM | What reached the vendor |
|---|---|---|
| `anthropic/claude-haiku-5-5` | `temperature: 0.2`, `top_p: 0.9`, `reasoning_effort: "low"`, a system message, a picture, a tool | `POST /v1/messages` with `x-api-key` and `anthropic-version: 2023-06-01`. **No temperature or top_p** (dropped). `thinking: {type: "adaptive", display: "summarized"}` and **`output_config: {effort: "low"}`**. The picture became a base64 `image` block, the tool a custom tool, the system message `system`. |
| the same, streamed | `stream: true`, `reasoning_effort: "high"` | the same shape with `effort: "high"`. The streamed answer came back in OpenAI chunks; the thinking block's signature arrived in `thinking_blocks`. |
| the same, no effort | `temperature: 0` | no temperature and no `thinking`, so Haiku uses its default (adaptive, medium effort). **`max_tokens: 128000`** was sent, because none was given. |
| `deepseek/deepseek-flash` | `temperature: 0.2`, a picture | `POST <api_base>/chat/completions`, Bearer key, the picture as `image_url`, the temperature kept (DeepSeek accepts it) |
| `openai/glm-5.3-flash` (`api_base` Z.ai's `/api/paas/v4`) | `temperature: 0.7` | `POST /api/paas/v4/chat/completions`, Bearer key |
| `openai/text-embedding-3-small` | one text | `POST <api_base>/embeddings` |

**So:**
- Rule 5 stands: the web reaches Haiku 5.5, DeepSeek, Z.ai and OpenAI embeddings through LiteLLM's own providers, with
  no special headers.
- The web's code needs no change for Haiku's refused settings. LiteLLM drops them, and turns `reasoning_effort` into
  Haiku's effort.
- The desktop calls Anthropic directly (CP2), so it must do the same itself: no temperature, `top_p` or prefill, and
  effort per job.
- **Every Haiku call should set `max_tokens`.** Without one, LiteLLM asks for the model's full 128,000 tokens. Only the
  tokens used are billed, but a runaway answer could get long.
- **Thinking blocks come back in `thinking_blocks`.** The web's chat must pass them back unchanged with tool results
  (Haiku's rule), and must not edit earlier turns.
- **Not tested here:** prompt caching (`cache_control`) through LiteLLM, and a real Anthropic answer. Both are checked in
  CP2 and CP13.

## 6. Changes to the plan from CP0

- **Extend:**
  - Seedance 2.5 can extend on Runware and WaveSpeed, so the Extend screen gains Seedance;
  - Gemini Omni extends on Runware;
  - H3 Max and Turbo extend on fal.ai only.
- **Inpaint on GPT Image** runs on WaveSpeed (cheapest), with fal.ai as the fallback.
- **Edit music on ACE-Step** runs on Runware (cheapest) and fal.ai. WaveSpeed has no ACE-Step inpaint.
- **Chatterbox on WaveSpeed takes a reference voice.** This answers FA0's open question for WaveSpeed; fal.ai's
  Chatterbox is checked in CP7.
- **MiniMax voices:** a voice cloned on WaveSpeed speaks on WaveSpeed's MiniMax Speech 2.8 HD, and one cloned on fal.ai
  on fal.ai's. Runware's MiniMax Speech has named voices only.
- **Runware reports each job's cost,** so its usage events record the real price.
- **Embeddings on the web:** OpenAI text-embedding-3-small, $0.02 per million tokens.
