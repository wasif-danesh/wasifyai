# ADR-0109: The first run is one button, and each menu group sets itself up with one card

- **Status:** Accepted (2026-11-18, the owner: "Accept it"). Proposed 2026-11-18. Built 2026-11-18 (FR0 to FR5 of `docs/first-run-plan.md`; FR6, the owner's look at the real window, is left): see "Built" at the end.
- **Date:** 2026-11-18
- **Asked for by the owner, 2026-11-17 and 2026-11-18:** a guided first run like Steno AI's and Unsloth Studio's, not
  one for experts. "If we throw so many decisions at the first run, many will be scared and probably quit." "Each
  menu item should guide the user to set up or download the features. The user won't go to settings." "One card per
  group and no extra cards. Once the user decides to download, we should make the product fully workable. If lip
  sync causes confusion it may become an independent menu item. The download button in Voice should make the whole
  group initialised."
- **Mockup:** `docs/spikes/first-run-mockup.html` (Welcome, Getting ready, Ready, a first visit to Pictures, Use an
  API key, and every menu item's card on an 8, 24 and 64 GB Mac and with Ollama).
- **Amends:** ADR-0086 decision 8 and its rejected option "Download the recommended set at first run" (below).
- **Keeps:** ADR-0059 (nothing is downloaded without the person's click, with the size shown first), ADR-0063 (models
  other tools downloaded are found), ADR-0068 (every feature is an action), ADR-0086 (the model button, its panel and
  its download dialog), ADR-0093 (the one shell and its menu groups), ADR-0094 (no consent gates or terms), ADR-0100
  (cloud models on the person's keys), ADR-0108 (Meetings is its own group).

## Context

Today a new person opens the app to the chat's first-run card (ADR-0086). Every other part is set up from its own
place: Notebook, Creative Studio, Motion graphics, 3D, Train models and Code have setup cards; Voice has a card for
its engine only; Images and Video have none and fall back to the model button. Some parts are reached only through
Settings › Optional parts. A person who opens Voice and makes speech can then open Change a voice and meet a second
download, then Edit speech and meet a third.

Steno AI and Unsloth Studio both ask once, at the start, and then work. Unsloth's first run (read in
`~/Projects/unsloth`) installs its runtime and one model behind one button, with no choices.

ADR-0086 rejected "download the recommended set at first run" because it breaks confirm-first and "a 16 GB image
model is not for everyone". Both reasons still hold for a download of everything. They do not hold for one button
that says what it will download and how big it is.

The parts and their sizes on darwin-arm64 (measured from the manifests and the model catalogue, 2026-11-17):

| Group | Parts | Download |
|---|---|---|
| Chat | llama.cpp 12 MB, Qwen3 4B 2.5 GB (a model chosen by memory) | about 2.5 GB |
| Notebook | the chat model, BGE small 66 MB, the document reader about 0.42 GB | about 0.5 GB with chat |
| Meetings | audio.cpp, Parakeet 0.92 GB, Sortformer and ERes2Net 0.52 GB, Notebook's parts | about 2.0 GB |
| Images | ComfyUI 13 MB, FLUX.2 klein 4B 16.1 GB (24 GB of memory) | 16.1 GB |
| Video | ComfyUI, LTX-Video 2B 16.1 GB (14 GB of memory) | 16.1 GB |
| Voice | audio.cpp 42 MB, Kokoro 0.19 GB, Parakeet 0.92 GB, Qwen3-TTS 0.6B 1.99 GB and 1.7B 2.82 GB, Tone Color 0.07 GB, dots TTS edit 2.96 GB | 9.0 GB |
| Music | ACE-Step 1.5 Turbo 6.19 GB, HTDemucs 0.06 GB | 6.3 GB |
| Lip sync | the MuseTalk environment 2.1 GB, its weights 4.17 GB (12 GB of memory) | 6.3 GB |
| 3D model | Pixal3D and BiRefNet 8.98 GB (19.5 GB of memory) | 9.0 GB |
| Code | the coding engine 375 MB, Node 53 MB | 0.43 GB |
| Creative Studio | song analysis 0.96 GB, the video builder 0.32 GB, plus Video and Voice | 1.3 GB plus theirs |
| Motion graphics | the video builder | 0.32 GB |

Indian languages (the Indic engine 1.2 GB, Indic Parler-TTS 3.77 GB, IndicConformer 2.56 GB) add 7.5 GB. Training
needs a different trainer for each kind (pictures 1.8 GB, writing 64 MB, deciding 168 MB, video 182 MB).

## Decision

### The first run

1. **The first run is one button.** The Welcome screen has one primary button, **Get started**, that says what it
   costs: "Downloads a 2.5 GB chat model". It sets up chat only: llama.cpp and one chat model chosen by this
   computer's memory (ADR-0086 decision 8 keeps the choice of model). One progress screen, then **Ready**, with the
   menu.
2. **If a usable chat model is already on the computer** (Ollama, LM Studio, the Hugging Face cache, ADR-0063), the
   button uses it and says so: "Uses Qwen3 8B from Ollama · no download".
3. **If the computer is too small for a local chat model** (8 GB of memory), the main button is "Get started with an
   API key · Nothing to download", and the download is the second choice.
4. **A key is always the second way in**, as a link below the button: "I'd rather use an API key". It opens the
   model button's Cloud tab (ADR-0100) in a step of its own.
5. **Nothing else is asked at the first run.** No list of products, no tick boxes, no models for pictures or video.

### One card per group

6. **Every menu group that needs parts shows one setup card**, the same card whichever item of the group is opened
   first. Its one button sets up **every** part every item of the group needs, so the whole group works afterwards
   and no item of the group asks again. Voice's button covers Text to speech, Speech to text, Voices (copy and
   describe), Change a voice, Edit speech, Dub and Audiobook: "Set up Voice · 9.0 GB".
7. **The card lists what the group can do, the size, and what is set up already.** A part set up before (for example
   the chat model, or audio.cpp from Voice when Meetings is opened) shows "✓ set up" and is not counted again.
8. **Single items have a card of their own**: Creative Studio, Motion graphics, 3D model, Lip sync, Code. Library and
   Model hub need nothing. Train models shows one card that explains that each kind of training sets itself up when
   it is chosen (its trainers are large and unrelated).
9. **Creative Studio's card sets up what it uses.** It needs Video and Voice, so its button sets up all three:
   "Set up Creative Studio, Video and Voice · 26.1 GB" on a 64 GB Mac.
10. **Meetings includes Notebook's parts**, because asking about a meeting goes through a notebook (ADR-0108).

### Lip sync moves out of Video

11. **Lip sync becomes a menu item of its own**, below the groups with Creative Studio, Motion graphics and 3D model.
    Its parts (MuseTalk, 6.3 GB) are not Video's, and putting it in Video's card would make "Set up Video" download
    a second, unrelated model.

### Fit to the computer

12. **A part the computer cannot run well is left out of the group's download, and the card says what that
    affects.** A part is downloaded when the memory it needs is under three quarters of the computer's. On an 8 GB
    Mac: "Voice: 6 of 7 ready on this Mac. Edit speech needs a bigger Mac. Voices works, but describing a voice needs
    a bigger Mac", and the download is 3.2 GB.
13. **A key is the main button only where a key covers the whole group** (Images, Video, Lip sync, 3D model) **and
    the model would use more than half the computer's memory.** The button then reads "Use an API key" and
    "Download instead" stays as the second button whenever the computer can still run the model. Voice and Music
    always lead with the download, because no cloud offer covers Change a voice, Edit speech or Split into parts.
14. **The numbers on a card are measured, never guessed.** Sizes come from the manifests and the catalogue; no card
    promises a time per picture or per clip until it is measured.

### Languages

15. **Indian languages are not part of Voice's download.** They are added to it only when the app's or the
    computer's language is one of them; otherwise they are set up when one of those languages is chosen, with their
    size shown (7.5 GB).

### Where it comes from

16. **The cards are generated, not written by hand.** Each action in the catalogue (`docs/contracts/actions.json`)
    already says what it `requires` (a product, a runtime, a model, chat, notebooks, the web). A group's card is the
    union of its actions' requirements, priced from the components' manifests and the model catalogue. A new action
    with a new requirement changes its group's card without a new screen.
17. **One job per card.** The button runs every part of the group as one resumable job with one progress bar, the
    exact files and the total echoed to the engine as ADR-0059 requires, like ADR-0086's dialog does for one model.
18. **The model button and Settings › Optional parts stay** for changing a model, removing one or adding a part the
    card left out. The card is the front door, not the only door.

### On the web

19. **The web shows no setup cards.** It runs on the keys an admin set (ADR-0099, ADR-0100); an item with no key
    says so, as today.

### What this changes in ADR-0086

- Decision 8 ("Image, video, voice and music models are fetched on first use through the same dialog") becomes: a
  group's parts are fetched through its setup card on the first visit; the model button's dialog stays for changing
  a model.
- The rejected option "Download the recommended set at first run" stays rejected as a download of everything. A
  download of one group, behind one button that shows its size, is what this ADR decides.

## Alternatives considered

| Option | Why not |
|---|---|
| A first run that lists every product with tick boxes and sizes (the first mockup) | too many decisions for a first-time person; the owner: "many will be scared and probably quit" |
| Download the recommended set of every group at the first run | 50 GB and more, most of it for things the person may never open; breaks confirm-first (ADR-0086) |
| A card per menu item | Voice would ask up to four times; "make the product fully workable" means a group works after one yes |
| Leave setup to Settings › Optional parts and the model button | the owner: "The user won't go to settings" |
| Keep Lip sync in Video | "Set up Video" would also download MuseTalk; the owner allowed moving it out if it confuses |
| Always offer the key first | a key costs money per use and does not cover every Voice and Music item |

## Consequences

- New: the Welcome, progress and Ready screens; a `GroupSetupCard` in `packages/ui` fed by a requirements and sizes
  route in the engine; a job that sets up a list of parts.
- Changed: the menu (Lip sync out of Video), Voice's runtime card, Notebook's, Creative Studio's, Motion graphics',
  3D's and Code's setup cards replaced by the one card; Images and Video gain one.
- Every action's `requires` must be complete; a test checks that each menu item's card lists the parts its actions
  need.
- Not measured yet: the memory figures for Kokoro, Parakeet, ACE-Step's song analysis and the 16 GB Mac's cut-offs.
  Stage one measures them before the cards show them.
- The stages are in `docs/first-run-plan.md` (FR0 to FR6).

## Built (2026-11-18)

- **FR0.** Sizes and fit were measured: `docs/spikes/first-run-fr0.md`. The cut-offs are `desktop_fit`'s budget
  (75%) and capacity (90%). On a 24 GB Mac, Images is key only.
- **FR1.** `GET /desktop/setup/groups` (`setup_groups.py`).
- **FR2.** Run in the window as one step per part over the engine's resumable jobs, not as an engine job. There is
  no `setup.group` action, so the chat cannot offer a group's setup yet.
- **FR3.** `GroupSetupCard` in `packages/ui/src/setup/`.
- **FR4.** `SetupGate` in front of every screen. Lip sync is moved out of Video. The old in-screen cards are kept as
  a fallback.
- **FR5.** `FirstRun.tsx`. A model already in Ollama is used without a download.
- **How it was checked.** Walked on a fresh data folder in a browser against the real engine. Motion graphics and Voice
  (9.0 GB, 11 minutes, all seven items open) and Notebook (1.5 GB) were set up for real through their cards. Details, and what was not walked, are in `docs/spikes/first-run-fr1-fr5.md`
  and `docs/desktop/first-run.md`.
