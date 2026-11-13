# CP13: the paid run with real keys (2026-11-13)

Stage CP13 of `docs/cloud-v1-plan.md` (ADR-0100). **Done 2026-11-13, except the parts named in
"Not done".** Every media offer of the catalogue made one small thing with the owner's own Runware,
WaveSpeed and fal.ai keys, and the text jobs of CP2 ran on Claude Haiku 5.5 with the owner's
Anthropic key. Each job went through the app's own code (`KeyedMediaRouter`, `KeyedSpeechEngine`,
`KeyedModel3d`, `AnthropicText`), never a hand-written request, so a fault found was a fault of the
app. Every fault below was fixed, tested against a fake that now answers as the provider really
does, and run again for real.

To keep the cost down (the owner's ask):
- Pictures were made at 1024 x 1024.
- Clips were asked for at one second, so each model made its shortest clip.
- Lip sync used a 3 s voice.
- Songs were made once per offer.
- The inputs (a face, a teapot, a 5 s voice) were made first, on the cheapest offers.

## What it cost

About **$12.20** in all:

| Provider | Spent | How it is known |
|---|---|---|
| Runware | $4.23 | its balance, $20.05 before and $15.82 after |
| WaveSpeed | $3.89 | its balance, $12.00 before and $8.11 after |
| fal.ai | about $4.10 | the costs the app recorded, corrected for the clips (below). This key may not read the balance |
| Anthropic | $0.002 | the tokens of the six jobs |

The app recorded less than this, for two reasons, both fixed:
- **Short clips.** Clips were priced at the one second asked for, not the model's shortest clip. On
  WaveSpeed this was Seedance ($0.375 recorded, $1.44 charged) and Omni ($0.07 against $0.21).
- **Runware's own costs.** These were not kept.

With the clips corrected, WaveSpeed's record comes within $0.40 of its balance. WaveSpeed's job list
gives no costs, so the rest is not explained. It may be the three jobs it took and then failed.

## Results

Every offer passed in the end: 23 picture jobs, 10 clips, 3 Extends, 17 voice jobs, 13 songs and
sound effects, 6 split or edit jobs, 8 lip syncs, 4 3D models, and 6 text jobs. The exceptions are
Pixal3D, which fal.ai does not have (taken out of the catalogue), and the few offers marked "not
run".

"Try 2" or more means the first try found a fault, which was fixed before the next.

### Pictures

All 19 picture offers plus the inputs passed.
- **Edits.** Every "add a red scarf" edit kept the same face.
- **Inpaints.** Every "blue jumper" inpaint stayed inside the mask, except Z-Image on fal.ai (below).

| Offer | Fault found | Fix |
|---|---|---|
| GPT Image 2.5 and Nano Banana 2.1 on WaveSpeed: edit, inpaint | WaveSpeed refused every input file (403) | WaveSpeed's upload address is signed over the headers it names (`If-None-Match: *` as well as the type). They are now sent as given (`cloud_queues.py`) |
| Grok Imagine 2.0 on Runware | "Unsupported use of 'seed'" | no seed for it (`runware_image(..., seed=False)`) |
| Z-Image Turbo on Runware: inpaint | the jumper barely changed | `strength: 1.0`; Runware's default barely paints |

Z-Image Turbo inpaint on fal.ai works, but fal.ai's endpoint is a ControlNet inpaint: it draws the
whole picture again, guided by the part outside the mask.
- With a short prompt ("A blue wool jumper") it made a picture of a jumper alone.
- With a full description it made the right picture, but the framing and the face shifted.

On Runware, at full strength, only the masked part changes. Runware is also cheaper, so with both
keys the app already picks it.

### Clips

All 10 offers made a clip from the face picture, each the same person moving.

| Offer | Fault found | Fix |
|---|---|---|
| Gemini Omni Flash 1.2 on Runware | refuses `seed`, and has no sound switch (its settings are `temperature` and `topP` only) | neither is sent |
| Grok Imagine Video 1.5 lite on Runware | refuses `seed` and `settings` | neither is sent |
| MiniMax H3 Max and Max Turbo on Runware | `settings.audio` refused (its settings: `promptExpansion` only) | not sent |
| every clip | **the recorded cost was too low.** A one-second ask is made at the model's shortest length (Omni 3 s, Seedance 4 s, H3 5 s), but it was priced at one second. H3 on fal.ai was recorded as $0.083; it was charged for 5 s, about $0.41 | each video offer has a `minimum`, its shortest clip's price |
| Runware's prices | Runware said what each job cost (`includeCost`), and the app threw that away | the media worker now records Runware's own cost in place of the list price (`RecipeRunner.charged`) |

Runware's own costs, against the catalogue:

| Model | Runware charged | Catalogue had | Now |
|---|---|---|---|
| H3 Max | $0.28 for 5 s | $0.08 a second | $0.056 a second |
| H3 Max Turbo | $0.14 for 5 s | $0.04 a second | $0.028 a second |
| Grok video | $0.04 for 1 s | $0.03 a second | $0.04 a second |
| Omni | $0.21 for 3 s | $0.07 a second | as it was |
| Seedance | $0.934 for 4 s | $0.23 a second | as it was |

Grok, Omni and H3 clips come with a quiet sound track (Grok and Omni peak at about -34 dB) although
no sound is asked for. The video product keeps only the picture of a clip it joins; a clip made
alone keeps its track. This is left as it is.

### Extend

Three checks were run: Omni on Runware, Seedance on Runware, and H3 Turbo on fal.ai.

| Offer | Found | Fix |
|---|---|---|
| Omni on Runware | extended a 1 s clip. It answers the whole clip (the original second, then 3 s more) but always wide (16:9), even for a square clip | the join now fills and cuts the answer to the source's shape (`join_clips`), where it stretched it before |
| H3 Turbo on fal.ai | a 1 s clip: "Failed to read the video file"; a 5 s clip: extended to 10.8 s, the whole clip | none: a clip that short cannot be extended on fal.ai, and fal.ai's words do not say why |
| Seedance on Runware | a 1 s clip: "Media duration must be in [2, 30] seconds", which the app shows. A face clip, twice: refused by ByteDance's content check within 13 s, nothing charged. A 2 s teapot clip: extended, $1.04 | Seedance answers **only the new part**, which starts at the clip's last frame, and the product took it as the whole clip (the first 2 s would have been lost). Its answer is now named `continued`, and the product keeps the whole source before it |

Seedance on WaveSpeed is assumed to answer the same way, since it is the same ByteDance model. It
was not run.

### Voice, cloning, transcription, changing a voice

All 17 jobs passed.
- **ElevenLabs v4 on WaveSpeed refused "Rachel".** That voice is fal.ai's default, and WaveSpeed
  does not have it. The default is now Aria, and the list holds only the voices both providers know.
- **Transcription.** Both models wrote the test sentence word for word.

### Music and sound effects

All 13 offers passed.

| Offer | Fault found | Fix |
|---|---|---|
| MiniMax Music 3 on fal.ai, Mureka v9.5 on fal.ai, Stable Audio 3 small, Stable Audio 3 inpaint, Mureka stems on fal.ai | **wrong names.** fal.ai's queue takes any name and then refuses the job ("no billing definition"). Its price API answers a "compute seconds" price for a name it has no model at, so CP12's check let them through | the real names, from fal.ai's model list: `minimax/music-3`, `mureka/v9.5/generate/song` (and `/instrumental`), `fal-ai/stable-audio-3/small/sfx/text-to-audio`, `fal-ai/stable-audio-3/medium/audio-inpainting`, `mureka/api/song/stem`. The price script now treats a "compute seconds" price as "not listed". The app now says "fal.ai has no such model", where it said "did not accept the key" |
| MiniMax Music 2.6 and 3 on WaveSpeed | "A required parameter is missing": a song needs words | Music 3 is asked to write them (`lyrics_optimizer`). Music 2.6 on WaveSpeed cannot, so a song without words is refused before anything is sent, and another offer takes it |
| MiniMax Music 3 on fal.ai | takes only songs with words | the same refusal before sending |
| ElevenLabs Sound Effects v3 on WaveSpeed | wants `prompt` and `duration` | its own names |

MiniMax and Mureka pick a song's length themselves: 21 s to 234 s for the same ask.
- **Per-song offers:** the price is right whatever the length.
- **MiniMax Music 3 on fal.ai (per second):** it is priced at the 120 s shown, but made 21 s. The
  cost written ($0.24) is too high; it really cost about $0.04. Left as it is: an estimate that
  errs high.

### Split into parts, edit music

All 6 jobs passed.
- **Mureka stems on fal.ai:**
  - It reads no WAV ("The supplied input could not be processed"), so the recording is now sent
    as an MP3 (`to_mp3`).
  - It answers one zip of every part; the vocals and the instrumental are read out of it
    (`stems_in_zip`).
- **ACE-Step on Runware:** `duration` is refused when a clip is given, so it is no longer sent.
  Without it, a 22.7 s clip works; the "30 to 300 s" message came from that field alone.

### Lip sync

All 8 offers made a 3 s talking clip of the face, with its sound. Each kept the face and moved the
mouth with the words. InfiniteTalk on fal.ai took 23 minutes for the 3 s (the others took 1 to 3
minutes); it is the dearest per second there, and is never the default (below).

| Model | Provider | Cost | Size |
|---|---|---|---|
| Fabric 1.0 | fal.ai | $0.30 | 640 px |
| Fabric 1.0 | WaveSpeed | $0.21 | 624 px |
| Kling Avatar v2 | Runware | $0.132 | 960 px |
| Kling Avatar v2 | fal.ai | $0.169 | 960 px |
| OmniHuman 1.5 | Runware | $0.396 | 1440 px |
| OmniHuman 1.5 | fal.ai | $0.48 | 960 px |
| InfiniteTalk | WaveSpeed | $0.09 | 624 px |
| InfiniteTalk | fal.ai | $0.60 | 640 px |

### 3D models

| Offer | Fault found | Fix |
|---|---|---|
| Hunyuan3D 3.1 Pro on fal.ai | none | made a 27 MB model, $0.375 |
| TRELLIS 2 on WaveSpeed | none | made an 11 MB model, $0.20 |
| Hunyuan3D 3.1 Pro on Runware | refuses `seed` | not sent |
| TRELLIS 2 on Runware | wants `inputs.image`, one picture | sent so |
| both on Runware | the answer names the file in `outputs.files[0].url` (status `success`), which the app never read, so it waited until its time ran out | `runware_url` reads it |
| TRELLIS 2 on Runware: price | charged $0.025 to $0.029 | $0.028 (was $0.01) |
| Pixal3D on fal.ai | fal.ai has no model at `fal-ai/pixal3d`: no schema, no price, "Application not found" | **taken out of the cloud catalogue.** This computer's own Pixal3D is not touched |

TRELLIS on Runware was then run again through the app and made its model. Hunyuan3D on Runware was
not run again: it had already been charged once, and it uses the same task.

### Text on Claude Haiku 5.5

All passed. Effort is set per job, and caching is on. Six jobs cost $0.0012 in all.

| Job | Product | Result |
|---|---|---|
| Chat | Chat | right; no thinking on an easy question at medium effort |
| Chat, thinking shown | Assistant (high) | a 12-answer puzzle, right, with 367 characters of thinking shown |
| Picture description | Images | the face described in one sentence |
| Tool call and its follow-up | Assistant | called `make_image("A red teapot")`, then answered after the result |
| Creative Studio plan | Creative Studio | three beats under the real schema, each within its lengths |
| Notebook answer | Notebooks | answered from source [2] only, and said what the sources do not say |

Two faults were found:
- **The plan was refused (400).** Anthropic's structured output allows `minItems` of 0 or 1 only,
  and no string lengths. Every schema now goes through the SDK's `transform_schema`, which keeps
  what Anthropic enforces and moves the rest into the descriptions. The callers already check the
  answers, and the writer asks again on a wrong count.
- **The app said only "Anthropic answered 400."** It now adds Anthropic's own words.

## Prices changed in the catalogue

| Offer | Was | Now | Why |
|---|---|---|---|
| Kling Avatar v2, fal.ai | | $0.0562 a second | fal.ai's price API |
| Stable Audio 3 small sound effects | $0.02 a clip | $0.0206 a clip | fal.ai's price API |
| Stable Audio 3 inpaint | $0.044 a clip | $0.0442 a clip | fal.ai's price API |
| H3 Max on Runware | $0.08 a second | $0.056 a second | measured |
| H3 Max Turbo on Runware | $0.04 a second | $0.028 a second | measured |
| Grok video on Runware | $0.03 a second | $0.04 a second | measured |
| TRELLIS 2 on Runware | $0.01 | $0.028 | measured |
| every clip | no minimum | its shortest clip's price | see "Clips" |

Not changed, though the providers list other amounts:
- **MiniMax H3 on fal.ai.** The price API answers $0.035 and $0.0175 a second, which looks like the
  480p price; the app makes 768p.
- **Mureka stems on WaveSpeed.** Its base price is now $1.05.
- **Mureka v9.5 on fal.ai.** Its price API answers $0.005 "units", which says nothing per song.

## Not done

- **Training.** No trainer was run, by the owner's choice.
- **Not run, to save money:**
  - MiniMax Voice cloning ($1.50 to $3 a voice);
  - Mureka stems on WaveSpeed ($1.05);
  - Seedance's Extend on WaveSpeed.
- **The search floor for bge-m3.** It needs the model fetched (asked before any download), so it
  stays at 0.57.
- **The window and browser walks.** These need the keys pasted into Settings › Your keys (desktop)
  and Admin › Media (web) by the owner.

The run's script and outputs were kept outside the repository and are not part of the product.
