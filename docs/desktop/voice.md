# Speech, music, lip sync, dubbing and audiobooks on the desktop

Part of [the desktop profile](../desktop-profile.md): what is built, how it is wired, what is not done.

## Speech: speak and transcribe (ADR-0066, stage V1)

One native program, audio.cpp (Apache-2.0), serves every speech model on this computer, and the person picks the
model from a list. Evidence: `docs/spikes/voice-v0.md`, `docs/phase2-voice-plan.md`.

| Piece | Where | What it does |
|---|---|---|
| Language first (stage L2 of `docs/voice-languages-plan.md`) | `packages/ui/src/voice/LanguageField.tsx`, used by Text to speech and Audiobook | the screen opens on the language used last on either screen (`wasifyai.voice.language`, English the first time); ready languages are listed first, then every other language the app names. The language filters the models, and the model's voices (`voicesFor`). Where no ready model speaks it, a note offers the models that would (Get one, or Use one in the cloud) and, in the window, opens the model list. Picking a model that does not speak the language switches to one it speaks. The words box takes the language (`lang`, `dir="auto"`). Not yet sent to the model: L7 |
| Model descriptors | `products/wasifyai-voice/models.yaml` (`voice:` block of an entry) | tasks, languages, voices, options, sample rate, measured speed and memory, and the weights' licence with `commercial_use` (yes, conditional, no, unreviewed) and its evidence. Only `yes` can be recommended. Types and request checks: `platform-sdk/voice_models.py` |
| Spec data | `products/wasifyai-voice/specs/` | audio.cpp `v0.9.0` spec files; a test checks that voices, options and the package file agree |
| Runtime | `wasifyai_api/audio_runtime.py`, pins in `audio_pins.json` | installer (size and SHA-256 shown first, confirm to download, unpacked safely, checked by running `--version`), or "use the copy already on this computer" (same tag, same hash); one `audiocpp_server` with every model that is present, lazy loading, one model in memory, loopback; the `audio` owner of the one slot (starting it stops a resident chat model, and the reverse) |
| Routes | `GET /desktop/audio`, `GET /desktop/audio/models?task=`, `POST /desktop/audio/install` (`confirm_bytes`), `/use-found`, `/stop`; `GET /desktop/models?task=` filters the catalogue | model states: ready, needs the runtime, not on this computer, not available |
| Product | `wasifyai-voice`: graph `speak` (a run), `/speeches`, `/transcripts` (upload, list, get, rename, delete, export txt, srt, vtt) | `voice.db` and files in the app's storage; speeches and transcripts are in My creations search (kinds `speech`, `transcript`) |
| Window | Voice menu: Text to speech, Speech to text | model button ("Select ... model") with its dialog; voice list; options made from the descriptor; setup card for the runtime; a made-before list; a transcript with times and Save as text or subtitles |

Rules in the code: a request is checked against the descriptor before it is sent (an unknown option or voice is
refused in words, because the runtime answers a mistake with HTTP 500 and may ignore an option silently); the
runtime's own messages are not shown; a cancelled request restarts the runtime; no model is chosen for the person
silently (the recommended one is only the starting choice).

Recordings: the runtime reads WAV only. Other formats are converted with ffmpeg when it is on the computer, else with
macOS's `afconvert`; with neither the person is told to install ffmpeg or save a WAV. Bundling ffmpeg is an open
question for the owner (licence and size).

### Voice on cloud models (ADR-0100, stage CP7)

With a Runware, WaveSpeed or fal.ai key (for the product, or for Every media product), each voice task can run on a
cloud model, chosen in its own picker. Four cloud products carry them, each with its own model in use:

| Product (Settings › Your keys) | Tasks | Models and offers |
|---|---|---|
| Voice | Speak | Kokoro (fal.ai), ElevenLabs v4 (WaveSpeed, fal.ai), Gemini 3.8 Flash TTS (fal.ai, WaveSpeed), Chatterbox (fal.ai, WaveSpeed), MiniMax Speech 2.8 HD (Runware, fal.ai, WaveSpeed) |
| Copy or design a voice | Clone, design | Qwen3-TTS (copy and design on Runware, design on fal.ai), Chatterbox (copy on WaveSpeed), MiniMax voice (copy and design on fal.ai and WaveSpeed) |
| Speech to text | Transcribe | Scribe v2 (fal.ai), Whisper (WaveSpeed) |
| Change a voice | Convert | Chatterbox (fal.ai, WaveSpeed) |

Each speaking model offers its own named voices (`own_keys_voice.py`, `SPEAKERS`); Chatterbox has one. A MiniMax voice
costs $1.50 to $3.10 to make, so it is made once: the voice MiniMax keeps is remembered by the recording or the words
that made it (`own_keys.voices` in the settings), and later speech in it goes to MiniMax Speech 2.8 HD on the provider
where it was made, per character. Recordings go to fal.ai's and WaveSpeed's stores first and to Runware with its
`mediaStorage` task. Scribe's timed words are joined into sentences for the transcript. Dubbing and Audiobook use
whichever models their steps resolve, so they follow these choices. Edit speech and splitting stay on this computer.

Not built: ElevenLabs' voice changer (it changes to its own named voices, and the screen changes to a recorded voice);
Wizper (its price is not listed); Qwen3-TTS copying on fal.ai (two requests, a voice file and then speech). Not yet
known, for CP13: WaveSpeed's field names for ElevenLabs, Gemini, Scribe, Whisper and Chatterbox's speech to speech, and
whether WaveSpeed takes ElevenLabs' voices by name. Checked against fakes only.

### Dictation: the Mic in the chat box (ADR-0083, stage CO4)

The chat box writes down what the person says. The window records the microphone (`getUserMedia` and an `AudioWorklet` loaded from `/recorder-worklet.js`, a file of the app itself because the window's content policy
refuses a blob) and averages it to a 16 kHz mono 16-bit WAV in the page; `POST /products/wasifyai-voice/dictation` returns the text and keeps nothing (WAV only, 10 MB and 5 minutes at most, a silent clip refused;
`wasifyai_voice/dictation.py`). The model slot has a **light-owner rule**: the speech model stays in memory beside the chat model when `ModelsService.fits_beside` says the two fit (the chat server's memory plus the
speech model's catalogue figure, against the fit check's budget), and dictation does not wait for a chat answer that is being written; when they do not fit, dictation unloads the chat model and the window says so.
The shell has `src-tauri/Info.plist` (`NSMicrophoneUsageDescription`) and `Entitlements.plist` (`com.apple.security.device.audio-input`, used when the app is signed); Cargo does not watch `Info.plist`, so after
editing it run `touch build.rs`. With no speech model the first press shows a setup card (name, licence, source, size, one download). Details and what was not verified: `docs/spikes/composer-co0.md`, "What CO4 built".

### Read aloud: the speaker under a reply (ADR-0083, stage CU3)

A button under each assistant reply speaks it with the local speech model (Kokoro 82M, Apache-2.0, 190 MB on disk, English only). It is opt-in (only a press starts it), local and keeps nothing: `POST /products/wasifyai-voice/read-aloud`
(`wasifyai_voice/read_aloud.py`) turns the reply into plain words, cuts it into passages and speaks the one asked for, and the window asks for the next while the first plays. The model slot treats it as dictation's twin: the same
`audio` owner with `beside_bytes` = 1 GB, so the voice stays beside the chat model when `fits_beside` says the two fit. With no voice the first press shows a setup card (name, licence, source, languages, size, one download). Details and what was not verified:
`docs/spikes/composer-co0.md`, "What CU3 read-aloud built".

### Your voices and the audio overview (stage V2)

| Piece | What it does |
|---|---|
| Descriptors | `design` and `clone` rules in `models.yaml` say how a model takes a description (`instruct_option` for Qwen3-TTS, `text_prefix` for VoxCPM2, which ignores the option) and a recording (reference words required or optional, 2 to 30 seconds). Checks: `check_design`, `check_clone` in the SDK |
| Saved voices | `/products/wasifyai-voice/voices`: `POST /voices/design` (name, description), `POST /voices/clone` (recording, name, **consent** `own` or `permission`, optional words), `PATCH` (name, description, the words), `DELETE`, `GET /voices?kind=`. A voice is not tied to a model: any ready model that can design or clone speaks it. A clone without a consent answer is refused (422 `consent_required`); the answer, its sentence and the time are kept with the voice |
| Recording | converted if needed, kept as WAV of at most 30 seconds (cut at the start), refused under 2 seconds; stored for playback and as a file under `<data>/voice/voices/` that the runtime reads |
| Speaking | a run of the Speak graph with `saved_voice` (and optionally `model`); the engine picks the recommended design or clone model otherwise; refused in words before loading when the voice cannot be used with the model (words missing, recording length) |
| Window | Voice > Voices: describe or clone, hear a sample, change the words, delete, "Use in Text to speech"; Text to speech lists "Your voices" and then offers the models that can do what that voice is |
| Audio overview | `POST /notebooks/{id}/artifacts/{aid}/voices`: the script's turns are spoken one by one by a speech model with built-in voices (Kokoro: a woman and a man by default, or `voices: {"1": id, "2": id}`), joined with pauses, kept as `overview.wav`, and the output's data gains `audio: true`; `GET .../voices` says how far it has got, `GET .../audio` is the sound. In the Studio viewer: "Speak it", progress, a player |

Saved voices and recordings are in My creations search (kind `voice`). Voices stay on this computer.

### Music (stage V3)

Music is another task of the same product and the same runtime, picked from the same kind of list.

| Piece | What it does |
|---|---|
| Descriptors | a `music` block: the modes a model makes (`song`, `sfx`), per mode whether it takes lyrics (`optional`, `required`, `unused`), whether it can leave the singing out (`toggle`, `always`, `never`) and its lengths as [shortest, usual, longest] seconds; and `request`, how the runtime takes the parts: the duration as a field of the request (`top`) or an option (`option:<name>`), the option that carries lyrics, what an instrumental is called (`[Instrumental]`). Catalogue: ACE-Step 1.5 Turbo (MIT, recommended), Stable Audio 3 Small music and sound effects (Stability Community Licence: **conditional**, never recommended) |
| Checks | `check_music`: a description of 3 or more characters; lyrics for a model that does not sing, or with "no singing", or singing that is required but missing, are refused in words (never dropped); a length outside the model's range is brought into it |
| Engine | `AudioEngine.music`: builds the request from the descriptor, chooses a random seed when none is given (the runtime's default is fixed, so every run would repeat), waits up to 40 s per second of music (at most two hours), reads the answer as raw audio or as JSON with base64 audio |
| Product | the Speak graph with `task: "music"`, `music_edit` and `lyrics`; `/tracks` (list with `?favourites=`, get, download as WAV, MP3 or M4A, rename, favourite, delete), `/formats`; `voice.db` table `tracks` (schema 4: favourite, parent track, edit recipe); My creations search (kind `track`) |
| Window | Music > Create (model list, Music or Sound effect when the model has both, description, lyrics only if it sings, "No singing" only if it can, length, seed, the model's own options such as BPM and key, 1 to 4 takes, an estimate from the measured speed, elapsed time while it works, Cancel), Your music (play, search, Favourites only, save as WAV / MP3 / M4A, rename, favourite, delete, "Make it again", "Another take", "Change it") and Lyrics (describe a song, get words written by the chat model, send them to Create) |
| Edits | `music` descriptors list an `edit` block per model. ACE-Step: **repaint** a time range, **extend** past the end, **cover** in another style. Stable Audio: **inpaint** a masked range, **restyle**. `check_music_edit` refuses a part an action does not use; ranges are clamped and merged; the result is a new track that points at its parent, never an overwrite |
| Assistant | `propose_action` with `music.generate` (a card, then a child run of the music product); the chat shows a player and opens the track in Your music |
| Options | `bpm` and `keyscale` change ACE-Step's output and are sent; the runtime silently ignores anything it does not know (`language`, invented names), so every option is checked against the descriptor first |

Not built: the ComfyUI ACE-Step workflow as a second engine for the same list, models beyond these (HeartMuLa and
others), a watermark decision for generated audio, a song longer than 4 minutes, and a listening check of the
quality (sung lyrics in order cannot be tested by machine).

### Music on cloud models (ADR-0100, stage CP8)

Four cloud products carry the music tools, each with its own model in use (Settings › Your keys, or the Cloud tab of
the Music group on the Models page). Each job runs on the cheapest offer with a key; a refusal before running hands it
to the next. The requests are `services/api/.../own_keys_music.py`; the engine is `KeyedSpeechEngine` (`music`,
`music_edit`, `separate`).

| Product (engine id) | Models and offers | Notes |
|---|---|---|
| Music (`key:music`) | MiniMax Music 2.6 (Runware, WaveSpeed, fal.ai), MiniMax Music 3 (WaveSpeed $0.15 a song, fal.ai $0.002 a second), ElevenLabs Music v2.5 (WaveSpeed, fal.ai), Mureka v9.5 (WaveSpeed, fal.ai) | MiniMax and Mureka pick the length; MiniMax 3 is priced at the length shown (120 s), so WaveSpeed wins. Mureka sings only given lyrics; an instrumental goes to its own endpoint, and on fal.ai it costs $0.50, so WaveSpeed's $0.225 wins |
| Sound effects (`key:sfx`) | ElevenLabs Sound Effects v3 (WaveSpeed, fal.ai), Mirelo SFX 2.0 (WaveSpeed, fal.ai), Stable Audio 3 small (fal.ai), ElevenLabs Sound Effects v2 (fal.ai) | priced per second except Stable Audio (a clip) |
| Split into parts (`key:split`) | Demucs (six parts, fal.ai), SAM Audio (the singing and the rest, fal.ai), Mureka stems (the singing and the backing; WaveSpeed, fal.ai) | the recording goes up first; each stem the provider answers is fetched and kept as a track, as with the models on this computer |
| Edit music (`key:musicedit`) | ACE-Step 1.5 repaint (Runware, fal.ai), Stable Audio 3 inpainting (fal.ai) | one stretch of a clip at a time; it is listed with the music models that can change a clip (Change it) |

Field names not shown on the providers' pages are marked "(CP13)" in `own_keys_music.py` and checked in the real run
(stage CP13): fal.ai's Mureka, Mirelo, Stable Audio and ACE-Step inpaint names, and what Mureka stems answers. Not
built: Mureka's own song edit (it edits only Mureka's songs; dropped in FA0), ACE-Step's extend and cover on the cloud.

### Audio tools (stage V4)

Three tools work on a recording the person already has: a track, a speech, or a file added with **Add a recording**
(Your music keeps it as a track of kind "added from a file"). Each is a model chosen from a list, and each result is a
**track** in Your music with `parent_id` (what it came from) and an `edit` record, so search, favourites, rename and
saving as WAV, MP3 or M4A already work on it.

| Tool | Models (all `commercial_use: yes` unless marked) | What it needs |
|---|---|---|
| Split into parts (`separate`) | HTDemucs 4 stems (recommended), HTDemucs 6 stems (adds guitar and piano), Mel-Band RoFormer (vocals and instrumental): MIT | a recording up to 10 minutes; it is converted to 44.1 kHz stereo first; choose which parts to keep |
| Change a voice (`convert`) | Tone Color VC (OpenVoice v2, MIT, recommended), MeanVC2 (Apache-2.0) | a **saved cloned voice** to sound like (its consent record is copied into the result); both recordings are converted to the rate the model reads |
| Edit speech (`edit`) | dots.tts Edit (Apache-2.0 project, weights card says "other": `conditional`, never chosen for the person) | what the recording says now, written down by the speech-to-text model on request, and what it should say: the difference becomes `<sub targ="new">old</sub>`, `<del>`, `<ins>` tags (up to 5 separate changes) |

Routes: `POST /tracks/import` (multipart), `POST /words` (write down what a library recording says; nothing is
saved), and graph tasks `separate`, `convert`, `speech_edit` on `/runs` (source: `source_track` or `source_speech`).
The window: Music > Split into parts, Voice > Change a voice and Edit speech, and the same three as buttons on every
track in Your music. Not built: voice conversion with built-in voices (RVC), singing conversion (Seed-VC is GPL-3.0),
Vevo2 (CC-BY-NC-ND), enhancement and restoration models, and diarisation.

### Music on the image engine (stage V3b)

A music model can be run by the image engine's ComfyUI instead of audio.cpp (`engine: comfyui` in its descriptor).
The first is **ACE-Step 1.5 Turbo (image engine)**: the same song model, with the language of the lyrics and the time
signature as options (the audio.cpp build ignores a language). It needs the image engine set up and a 10 GB
checkpoint, and it holds the image slot while it works. The workflow is `products/wasifyai-voice/workflows/`, a copy
of the web product's with its last node changed to `PreviewAudio` so nothing is left in ComfyUI's output folder; its
map file names the inputs, so the code has no node ids. The model list shows "Needs the image engine" for it when
that is missing. It is not recommended: on a Mac, audio.cpp on Metal is about twice as fast. The reason for it is
Windows and Linux with a graphics card, where the pinned audio.cpp build runs on the CPU.

### Lip sync (stage V5)

A picture and a voice make a video of the face saying it. The model is chosen from the list like every other
(EchoMimic v3 flash, the only one; it replaced MuseTalk on 2026-11-10, ADR-0066); the engine is an **optional component**, not part of the app.

| Piece | What it does |
|---|---|
| The engine | EchoMimic v3's code at an exact commit and a hashed package lock (the `lipsync` part of `components/manifests/<platform>.yaml`, `lipsync_server/echomimic.lock.txt`), set up on a click after the size is shown, with the app's own `uv`, into `<app data>/engine/lipsync` (its own environment: torch must not touch the engine's). Apple-silicon Macs only for now (the one measured). The engine does this itself, like the speech runtime, not the shell like the image engine. A copy set up by hand is used as it is when `WASIFYAI_LIPSYNC_HOME` names it (development: `src/` the code, `venv/`, `weights/`) |
| The weights | the catalogue entry `echomimic-v3-flash` (7 files, 9.4 GB: the EchoMimic v3 flash-pro transformer and its config, the Wan 2.1 VAE and CLIP image encoder, chinese-wav2vec2-base) fetched in Models after the person sees their size; when the server starts they are linked under `weights/`. The two fixed prompts ship encoded in `lipsync_server/echomimic_prompts.safetensors`, so the 11 GB text encoder is not needed |
| The process | one `uvicorn` server on loopback (`lipsync_server/`), started on demand, stopped when something else takes the memory (it is its own owner of the one slot: about 29 GB at 720p from a near-square picture, 41 GB at 720x1280) and when a run is cancelled |
| The picture | added with `POST /pictures`: checked, flattened to a clean PNG (no location or camera data), at most 1024 pixels; kept until a clip uses it, or for a day |
| The shape and size | as the picture (kept between 9:16 and 16:9), 9:16, 16:9, 1:1 or 4:5, at 480p or 720p on the short side (the model's `lipsync.sizes`, default 720). The engine works out the size (`lipsync_frame`) and the server crops the picture to it, centred across and 40% down; the screen shows the same crop and the size in pixels |
| The voice | words (made into speech here with the default model, and kept as a speech), or a recording from the library; at most 60 seconds (the model's `max_voice_s`) |
| The clip | `clips` in `voice.db` (schema 5): the video, the picture (its poster), what the voice came from, the person's answers, the time taken; `GET/PATCH/DELETE /clips`, `/clips/{id}/download`; My creations search finds it by title and words (kind `lipsync`) |

**Consent and the mark (ADR-0044, ADR-0066 decision 8).** Before anything is made the person says **what the picture
is** (a drawing, a picture of themselves, a picture of someone who agreed) and **whose voice it is** (made here from
words, their own, one they have permission to use). Without both answers the run is refused before any work is done;
"made here from words" is only accepted for words, or a speech made here, never for a recording of the library.
The answers and their wording are kept with the clip. Every video carries a visible **"AI-generated"** label on a
dark plate in the bottom-left corner of every frame, drawn by the server, and a metadata comment; the descriptor
must say `mark: required` or it does not load, and there is no switch. The system safeguards of ADR-0047 (classifier,
moderation, daily limit) are not part of the desktop; consent and the mark are.

**In the cloud (2026-11-12).** With a fal.ai key saved for Lip sync, the picker's Cloud tab offers VEED Fabric 1.0
Fast, Kling Avatar v2, OmniHuman 1.5 and InfiniteTalk. LongCat was taken off (owner, 2026-11-12); the cheaper offers on WaveSpeed and Runware came back with ADR-0100 (below). Each row says
its price and, where measured, its time per video second (`docs/spikes/lipsync-cloud-race.md`: Fabric 5 to 25 s (25 s used for the estimate),
Kling about 40 s, OmniHuman about 45 s, InfiniteTalk about 50 s at 480p). Before Make the screen says the time and
the cost of this voice at the chosen size; no length is forced. The picture and the voice go up to fal.ai's file
store first, then the model is asked (`own_keys_engines.py`, `lipsync_body`). Fabric and OmniHuman make a square whatever they are
sent, so the screen hides the shape and sends a square picture; Kling and InfiniteTalk keep the shape at a size they
pick, and the screen says their measured size as "about" (`frame`, `frame_short`). On the web the admin puts
the same four on fal.ai in Admin › Media (row `speech.lipsync`, `docs/runbooks/web-notebooks-voice.md`).

**The cheaper offers (ADR-0100, stage CP6).** The same four models also run where they are cheaper, with fal.ai kept as
the fallback: Fabric 1.0 on WaveSpeed ($0.07 a second at 480p), InfiniteTalk on WaveSpeed ($0.03), Kling Avatar v2
on Runware ($0.044) and OmniHuman 1.5 on Runware ($0.132). A key for Lip sync or for Every media product on any of the
three providers is enough. Each job goes to the cheapest offer with a key, and a provider that refuses before running
hands it to the next. The screen's price per second is the cheapest keyed offer's at each size, and its "where" is the
provider of the default size. WaveSpeed is sent `image`, `audio` and the size (and InfiniteTalk a prompt), both
uploaded to its store first; Runware is sent a `videoInference` task with the picture inside it and the voice uploaded
first (`mediaStorage`). The measured times and frame sizes are fal.ai's; WaveSpeed's Fabric at 720p is priced at double
its 480p until the price refresh (CP12) reads it. Checked against fakes only; the real run is CP13.

Not built on this computer: other lip sync models (InfiniteTalk, LivePortrait, the CUDA `liveavatar`), video as the input,
faster settings that keep the face (at 720p a clip costs about 2.5 minutes of work per second of video on a 64 GB M5 Pro, 6.7 minutes in portrait; 448 px is ten times faster but changes the face), choosing where the crop is, several faces, a CUDA lock for Windows and Linux, and
languages: nothing was tested beyond English.

### Dubbing (stage V6)

A recording said again in another language. It uses what is already there (no new model): the separator, the speech
to text model, the chat model, a speaking or copying model, and ffmpeg. Two steps, so the translation can be read and
changed before anything is spoken.

| Step | What happens |
|---|---|
| The script (`dub_script`) | the voice is separated from the background (Mel-Band RoFormer by default; both parts are kept in Your music), what is said is written down with times (Parakeet), and each line is translated by the chat model, in batches of 40 with a length hint per line, a line at a time where a batch does not come back as the right number of lines. The result is a list of lines: start, end, what was said, what it becomes |
| The dub (`dub`) | each line (as the person left it) is spoken, fitted to its time (played up to 1.3 times faster if it runs over; the largest overrun is reported), and mixed with ffmpeg over the background at its time into a 44.1 kHz stereo track |
| The voice | the **original speaker's**, copied from the longest stretch of the separated voice that the model takes (needs the person's word that it is theirs or that they have permission; kept with the track), a **saved** voice (a cloned one, or a designed one), or a **built-in** voice (only for a language the model has voices in) |
| The languages | the ones a speaking or copying model on this computer knows, from the descriptors, named from the one shared list (`platform-sdk/languages.py` and `packages/ui/src/voice/languages.ts`, stage L1 of `docs/voice-languages-plan.md`; each shown with its own name, "Bengali (বাংলা)"); today English (Kokoro, built-in voices), and English, Chinese, Japanese, Korean, German, French, Russian, Portuguese, Spanish and Italian (Qwen3-TTS, copying a voice). Writing down the original needs the speech to text model's languages (25 European ones) |
| The track | `mode: dubbed`, `parent_id`, the script, the language, the fit and the consent in its `edit` record; its translated words are searchable |

Needs ffmpeg on the computer (the dub says so in words when it is missing). One speaker only: the lines of two
voices would be spoken in one. Not built: telling speakers apart, lip sync of the dubbed voice (use Lip sync on the
result), sound effects kept separate from music, and a video as the source (a recording's audio only).

### Audiobook (stage V7)

A long text read aloud, chapter by chapter. No new model: any speaking model, with a built-in voice, a designed voice
or a cloned one.

| Step | What happens |
|---|---|
| The chapters | `POST /audiobook/plan` finds them at headings (`Chapter 3`, `CHAPTER ONE: ...`, `# Title`, `Part II`, `Prologue`, `1. Title`), else cuts the text between paragraphs into parts of about 6 000 characters; nothing is made or kept. The person reads them, renames, edits the words, joins a chapter with the next or removes one. A text is at most 400 000 characters, a chapter 60 000, a book 200 chapters |
| Speaking | each chapter is cut into pieces of at most 700 characters at sentence ends (Chinese and Japanese stops too), spoken one at a time and joined with 0.25 s between pieces and 0.7 s after a paragraph; the title is spoken first (it can be left out) |
| Keeping | **each chapter is a track the moment it is done** (`mode: chapter`, the words in `lyrics`, so a book is found by what it says); a failure or a cancel leaves the earlier chapters and the message says which; optionally one track of the whole book (`mode: audiobook`) for books up to about 100 000 characters, which is about two hours, because it is joined in memory |
| The window | Voice > Audiobook: the title, the text (pasted or a `.txt` or `.md` file), the chapters, the voice (a built-in one with the model's own options such as speed, or a saved one), the progress by chapter and part, Cancel |

Not built: chapter markers inside the whole-book file, MP3 or M4A in one go (save each track in Your music), reading
from the notebooks' sources, several voices in one book, and pronunciation notes.
