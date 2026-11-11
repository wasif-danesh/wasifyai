# One provider for every product: fal.ai with the person's key (plan, 2026-11-11)

Status: **accepted by the owner 2026-11-11** ("Go with fal.ai and use a fake key for now"). **F1 to F5 built
2026-11-11 against a fake fal.ai**; F6 and the real-key run are left. Amends ADR-0095 (added there as "Amendment:
fal.ai for every product").

## Why fal.ai

The owner wants one provider that covers the most products, at a fair price, to test own keys across the app. The
comparison is in the owner's chat of 2026-11-11. In short:
- fal.ai covers text (OpenRouter's models through fal), images, video, speech, music, sound effects, 3D and lip sync
  from a picture, with one key.
- The app already speaks fal.ai's queue for images, video, speech and 3D (ADR-0095 K3 to K5).
- WaveSpeed covers almost as much and is often cheaper for video. It is the likely second provider, with its own
  runner, later. Runware is cheapest for pictures. Replicate costs more; Kie.ai is unreliable.

## What runs on the key today and what is added

| Product | Today on a key | Added here | fal.ai endpoint | Listed price |
|---|---|---|---|---|
| Chat and writing | any OpenAI-compatible provider | **fal.ai as a text provider** (F1) | `openrouter/router/openai/v1` (OpenAI-compatible, `Authorization: Key …`) | the model's token price; each answer reports its `cost` |
| Images | FLUX.2 make, change, combine | — | `fal-ai/flux-2`, `fal-ai/flux-2/edit` | per picture |
| Video | LTX-2 make, animate | — | `fal-ai/ltx-2/.../fast` | per second |
| Voice · speak | Kokoro | — | `fal-ai/kokoro` | per 1,000 characters |
| Voice · music | no | **songs and instrumentals** (F2) | `fal-ai/minimax-music/v2.6` (lyrics, instrumental; length chosen by the model), `fal-ai/elevenlabs/music` (instrumental, 3 s to 10 min) | $0.15 per song; $0.60 per minute, rounded up |
| Voice · sound effects | no | **sound effects** (F3) | `fal-ai/elevenlabs/sound-effects/v2` (0.5 to 22 s, loop) | $0.002 per second |
| Voice · lip sync | no | **LongCat and InfiniteTalk** (F4, the lip sync plan's LC3) | `fal-ai/longcat-single-avatar/image-audio-to-video`, `fal-ai/infinitalk` | $0.15 or $0.30 per second; $0.20 per second |
| 3D | Pixal3D with BiRefNet cut-out | — | `fal-ai/pixal3d`, `fal-ai/birefnet` | per model |

fal.ai's music and sound answer MP3. The app keeps WAV, so the answer is turned into WAV with the bundled FFmpeg
before it is saved, as everything else is.

## How

- **Keys.** New rows in Settings › Your keys: **Music**, **Sound effects** and **Lip sync** (ADR-0095: one key per
  product). Since 2026-11-11 a row holds keys only and the model is chosen in the picker's Cloud tab
  (`docs/own-keys-cloud-tab-plan.md`).
- **Text on fal.ai (F1).** A text provider "fal.ai" whose address is fal.ai's OpenAI-compatible route. Its key goes
  in an `Authorization: Key …` header, not `Bearer`. Its suggested models are OpenRouter names (`google/gemini-2.5-flash`,
  `openai/gpt-4o-mini`). Test sends a one-token chat, as for the other text providers.
- **Music and sound effects (F2, F3).** `KeyedSpeechEngine` gains `music`: while Music (or Sound effects) runs on
  the key, the music screen offers the keyed model and the request goes to fal.ai.
  - MiniMax takes the description as `prompt`, the lyrics as `lyrics`, and `is_instrumental`.
  - ElevenLabs Music takes `prompt`, `music_length_ms` and `force_instrumental`.
  - ElevenLabs sound effects take `text`, `duration_seconds` and `loop`.
  - A request a model cannot do is refused in words, the way `check_music` does today. Example: lyrics to
    ElevenLabs Music, which has no lyrics field.
- **Lip sync (F4).** `KeyedSpeechEngine.lipsync`: the cropped picture and the voice go to the chosen endpoint as
  data URIs (or through fal.ai's storage, if the real run shows data URIs are refused). The MP4 is fetched and saved.
  - LongCat: 480p or 720p; long voices in segments (`num_segments`, up to ~50 s), longer ones in pieces joined
    here.
  - InfiniteTalk: 480p or 720p; `num_frames` from the voice's length at 25 fps, up to 721 frames.
- **The web.** Admin › Media gets the same rows (Voice · Music, Voice · Sound effects, Voice · Lip sync) with fal.ai
  as a backend, like K5 did for Speak and 3D.
- **The check (F5).** `scripts/check_fal_key.py` makes one small thing per product:
  - Speech, music, sound effects and lip sync go through the app's own `KeyedSpeechEngine`.
  - Text goes through the app's own `text_client`.
  - Pictures, video and 3D go through fal.ai's queue with the endpoints and bodies the app uses.

  It runs against a fake fal.ai by default and against the real one with `--real`. With `--real` it reads the
  key from the app's keychain, or `FAL_KEY`. It writes the times and sizes, never the key.

## Stages

| Stage | What | Done when |
|---|---|---|
| F1 | fal.ai as a text provider | a chat with a fake fal.ai passes through `KeyedTextProvider`; Test works. **Built 2026-11-11** |
| F2 | Music on the key (MiniMax, ElevenLabs Music) | a song and an instrumental from the fake are saved as WAV. **Built 2026-11-11** |
| F3 | Sound effects on the key | a sound effect from the fake is saved. **Built 2026-11-11** |
| F4 | Lip sync on the key (LongCat, InfiniteTalk) | a lip sync video from the fake is saved; the screen asks nothing to be set up for a keyed model. **Built 2026-11-11**; longer voices in pieces not yet |
| F5 | The check script, all products, fake by default | it passes against the fake (all nine, 2026-11-11); the owner runs `--real` |
| F6 | Web Admin rows, help, search, docs; seen in the real window | walked in the window |

## The real run (owner, with a real key)

About **$5** in all. Every price below is as listed:

| Product | Test | About |
|---|---|---|
| Text | one short chat | under $0.01 |
| Images | one FLUX.2 picture | a few cents |
| Video | one 6 s LTX-2 fast clip | about $0.25 |
| Speech | one sentence with Kokoro | under $0.01 |
| Music | one MiniMax song; one 30 s ElevenLabs instrumental (charged as a minute) | $0.75 |
| Sound effects | one 5 s effect | $0.01 |
| 3D | one Pixal3D model | under $1 |
| Lip sync | 5 s LongCat at 720p; 5 s InfiniteTalk at 720p | about $2.75 |

## ADR-0095 amendment

To add under ADR-0095 when F1 is built:
- fal.ai is also a text provider, through its OpenAI-compatible OpenRouter route.
- Music, sound effects and lip sync run on fal.ai with their own key rows.
- K4's "Lip sync is not on a key" is replaced: it was true for MuseTalk on fal.ai, which needs a video. LongCat and
  InfiniteTalk start from a picture.
