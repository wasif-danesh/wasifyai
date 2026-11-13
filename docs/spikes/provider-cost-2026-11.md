# Cloud provider cost comparison (2026-11-12)

The owner asked for this after FA1. OpenRouter's 5.5% credit fee is unwanted, and the cheapest provider is the priority.
Prices are the providers' own list prices on 2026-11-12. Nothing was paid for. Where they came from:
- **fal.ai:** its price API, and each model's `llms.txt`.
- **Runware:** `runware.ai/docs/models/index.json` for the model list, and each model's `schema.json`
  (`info["x-pricing"]`).
- **WaveSpeed:** `wavespeed.ai/model-sitemap.xml` for the model list (1,112 pages), and each model page for prices. There
  is no public price API without a key.
- **Text:** OpenRouter's endpoint list, Anthropic's list prices, and Google's, Vercel's and OpenRouter's billing pages.

## How each provider bills

| Provider | Billing | Fee on top | Notes |
|---|---|---|---|
| fal.ai | prepaid credits; invoices for high volume | none found | expiry not confirmed (one third party says 365 days) |
| Runware | prepaid credits, $20 minimum top-up, auto-reload | none | credits never expire |
| WaveSpeed | prepaid credits, auto top-up | none | credits never expire and can't be refunded; $1 free |
| OpenRouter | prepaid credits | **5.5%** per purchase (min $0.80) | own keys (BYOK): free up to $25,000 a month, then 5%, taken from credits |
| Anthropic direct | prepaid credits, auto-reload | none found | credits expire after 1 year |
| Google Gemini API | **prepaid credits**, $5 minimum | none found | new accounts start on prepay, and postpay is being phased out; credits expire after 12 months and can't be refunded |
| Vercel AI Gateway | prepaid credits, auto-reload | no markup; card processing fees "may apply" (amount not stated) | own keys are free but need purchased credits |

**Every option is prepaid.** No provider still bills small accounts after use; Google was the last one, and it is moving
to prepay. The difference between providers is the fee and the model prices.

## Media: price for the same thing

| Model and setting | fal.ai | Runware | WaveSpeed |
|---|---|---|---|
| Nano Banana 2.1, 1K picture | ~$0.040 ($35.29/M image tokens) | ~$0.034 ($30/M) | $0.040 |
| GPT Image 2.5 Sunburst, high, 1K | ~$0.125 | ~$0.125 | $0.090 |
| Grok Imagine Image 2.0 | $0.04 to $0.06 | $0.04 to $0.06 | $0.08 |
| FLUX.3 klein, ~1 MP | $0.009 | ~$0.006 (compute) | $0.010 ($0.015 with a LoRA) |
| Z-Image Turbo, ~1 MP | $0.005 | ~$0.0006 to $0.003 (compute) | $0.005 ($0.01 with a LoRA) |
| Seedance 2.5, 720p, per s | ~$0.46 ($21.4/M tokens) | $0.23 ($10.7/M tokens) | $0.36 |
| Seedance 2.5, 480p, per s | ~$0.21 | $0.10 | $0.18 |
| Gemini Omni Flash 1.2, 720p, per s | $0.082 | $0.070 | $0.070 |
| MiniMax H3 Max, 768p, per s | $0.08 | $0.08 | not offered (H3 $0.10) |
| MiniMax H3 Max Turbo, 768p, per s | $0.04 | $0.04 | not offered (H3 Highspeed $0.06) |
| Grok Imagine Video 1.5 lite, 720p, per s | $0.03 | $0.03 | not offered (full model $0.14) |
| Fabric 1.0, 480p, per s | $0.10 (Fast) | $0.08 | $0.07 |
| Kling Avatar v2 standard, per s | $0.06 | $0.044 | $0.056 |
| OmniHuman 1.5, per s | $0.16 | $0.132 | ~$0.16 |
| InfiniteTalk, 480p, per s | $0.20 | not offered | $0.03 |
| MiniMax Speech 2.8 HD, per 1,000 characters | $0.10 | $0.10 | $0.10 |
| Qwen3-TTS (speak, clone, design), per 1,000 characters | $0.09 | $0.015 | $0.05 to $0.50 |
| MiniMax Music, per song | $0.15 (2.6) | $0.15 (2.6) | $0.15 (3.0) |
| ACE-Step, per minute | $0.012 | ~$0.001 | $0.018 |
| Hunyuan3D 3.1 Pro (+PBR) | $0.375 (+$0.15) | $0.375 ($0.525 with PBR) | only v3 ($0.30) and 3.1 Rapid |
| TRELLIS 2 | $0.25 to $0.35 | ~$0.01 (compute) | $0.20 |
| Z-Image look, per training step | $0.00226 | $0.00182 (style looks) | $1.25 a run |

What this shows:
- **fal.ai adds about 17.6% to Google's models.** Nano Banana 2.1 costs $1.764 and $35.29 per million tokens there,
  against Google's $1.50 and $30. Gemini Omni also costs about 17% more on fal.ai.
- **Runware charges the model makers' prices or less.** It is the cheapest or tied on nearly every model it has.
- **Seedance 2.5 is half price on Runware,** on the same token basis as fal.ai. Both prices include the sound, which is
  on by default.
- **WaveSpeed is the cheapest for InfiniteTalk** (about a seventh of fal.ai's price), GPT Image at high quality, and
  Fabric. Its audio tools (below) cost the same as fal.ai's or more.

## Which provider has each of the plan's models

Runware has the plan's picture and video models and most lip sync, but very little audio and no trainer the plan can
use. WaveSpeed has almost all the audio. fal.ai has everything. A dash means the provider doesn't offer it.

| Plan item | Runware | WaveSpeed | fal.ai |
|---|---|---|---|
| Every picture model | yes; Z-Image takes a mask and a LoRA; **FLUX.3 klein takes no LoRA** | yes, with LoRAs | yes |
| Gemini Omni, Seedance, H3 Max and Turbo, Grok lite | yes | no H3 Max or Turbo, no Grok lite | yes |
| Lip sync: Fabric, Kling Avatar, OmniHuman | yes | yes | yes |
| Lip sync: InfiniteTalk | — | $0.03 per s | $0.20 per s |
| ElevenLabs v4 speech | — | $0.08 | $0.08 |
| Gemini 3.8 Flash TTS | only 3.1 | $0.05 | $0.045 |
| Chatterbox speech and voice change | — | $0.03 per 1,000 characters; $0.02 per min | $0.025; $0.015 |
| Voice cloning | Qwen3-TTS $0.015 per 1,000 characters, Fish Audio, HeyGen | Qwen3-TTS, MiniMax $1.60 a voice | Qwen3-TTS, MiniMax $1.50 a voice |
| Voice design | Qwen3-TTS | Qwen3-TTS, MiniMax $3.10 | Qwen3-TTS, MiniMax $3 |
| Speech to text | — (only Gemini chat models that listen) | Scribe v2, Whisper $0.001 per s | Scribe v2 $0.008 per min, Wizper |
| ElevenLabs voice changer | — | $0.24 per min | $0.30 per min |
| ElevenLabs Music v2.5 | — | $0.75 per min | $0.60 per min |
| Mureka v9.5 | — | $0.225 a song | $0.15 a song |
| MiniMax Music 3 | only 2.6 | $0.15 a song | $0.002 per s |
| Sound effects | Mirelo 1.5 only, $0.00025 per s | ElevenLabs v3 $0.002 per s, Mirelo 2.0 $0.02 per s | ElevenLabs v3 $0.002 per s, Mirelo 2.0 $0.01 per s, Stable Audio 3 |
| Split into parts | — | vocals and the rest $0.001 per s; Mureka stems $0.09 a song | Demucs (6 parts) $0.0007 per s, SAM Audio, Mureka stems $0.02 |
| Edit music | ACE-Step | ACE-Step | ACE-Step, Stable Audio 3 inpaint |
| Pixal3D | — | — | $0.06 |
| FLUX.3 klein trainer | — (FLUX.2 klein style trainers only) | — | $0.0043 a step |
| LTX-2.3 and MiniMax H3 video trainers | — | — (LTX-2 19B trainer only, $0.0035 a step) | yes |

## A sample month

The month:
- **Pictures:** 100 on Nano Banana, 50 on GPT Image at high quality and 50 on FLUX.3 klein.
- **Video:** 100 s each of Seedance, Gemini Omni and H3 Max Turbo.
- **Lip sync:** 60 s each on Kling Avatar, OmniHuman and InfiniteTalk.
- **Voice:** 20,000 characters of speech, 30 minutes of speech to text and 5 minutes of voice change.
- **Music:** 5 minutes of music, 2 songs and 3 songs split into parts.
- **3D:** 5 models each on Hunyuan3D and TRELLIS.
- **Training:** one look trained.

| Choice | Month |
|---|---|
| fal.ai only | $107.15 |
| Runware first, fal.ai for the rest | $77.52 (−28%) |
| Runware first, WaveSpeed for the rest | $66.25 (−38%) |
| The cheapest of the three for each item | $65.27 (−39%) |

The month's largest costs:
- **Seedance:** $46 on fal.ai, $23 on Runware.
- **InfiniteTalk:** $12 on fal.ai, $1.80 on WaveSpeed.

With InfiniteTalk moved to WaveSpeed, or dropped for Runware's lip sync models, "Runware first, fal.ai for the rest"
costs about $66 as well.

## Text

| Model (per million tokens, in / out) | Model maker | OpenRouter | WaveSpeed | Runware |
|---|---|---|---|---|
| Claude Sonnet 5.5 | $2 / $10 (Anthropic) | $2 / $10 + 5.5% | Sonnet 5 at $2 / $10 | not in its model list |
| Claude Haiku 5.5 | $0.10 / $0.50 (Anthropic) | $0.10 / $0.50 + 5.5% | not found | not in its model list |
| Gemini 3.8 Flash | $0.75 / $3.75 until 2026-12-31, then $1.50 / $7.50 (Google) | $0.75 / $3.75 + 5.5% | $1.50 / $7.50 | not listed (3.5 Flash $1.50 / $9) |
| DeepSeek V4.1 Flash | | $0.022 / $0.40 + 5.5% | $0.15 / $0.60 | $0.15 / $0.60 |

No reseller sells below the model maker's price. The only difference is the fee:
- **5.5%:** OpenRouter credits.
- **No fee:** Anthropic and Google directly; OpenRouter with your own keys (below $25,000 a month).
- **No markup, but a card fee of unstated size:** Vercel AI Gateway.

At $50 a month of text, OpenRouter's fee is about $2.75. It is small next to the media savings.

## Suggestion (for the owner to decide)

**Media: Runware first, fal.ai for the rest.**
- **Runware runs** every picture and video model in the plan, most of lip sync, MiniMax and Qwen3 speech, Hunyuan3D and
  TRELLIS. These are the expensive items, and Runware is the cheapest for them.
- **fal.ai runs** what Runware lacks:
  - ElevenLabs speech, music and voice change;
  - Chatterbox, speech to text, Mureka and Demucs;
  - Stable Audio, Pixal3D;
  - the FLUX.3 klein and video trainers, and FLUX.3 klein with a trained look.

  fal.ai is the same price as WaveSpeed or cheaper on most of these, and it is already built.
- **WaveSpeed instead of fal.ai** saves little beyond InfiniteTalk. It also leaves the trainers, Pixal3D, Stable Audio
  and Demucs with no provider. Two other choices give most of its saving:
  - drop InfiniteTalk for Runware's lip sync models (Kling Avatar, OmniHuman, Fabric, sync lipsync-2);
  - or keep InfiniteTalk as the only WaveSpeed model.

**Text: Anthropic and Google directly,** with no fee:
- **Anthropic:** Claude Sonnet 5.5 and Haiku 5.5.
- **Google:** Gemini 3.8 Flash. Its embedding model's price is checked in FA2.
- **Both are prepaid, and credits expire after a year,** so small top-ups are better.
- **For one text key:** Vercel AI Gateway (no markup) or OpenRouter with your own keys (no fee below $25,000 a month).
  Both still need a credit balance with them.
