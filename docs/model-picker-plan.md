# Plan: one simple way to choose, get and use a model (2026-10-21)

Owner's words: a novice cannot know what "Get it in Models" does or what to choose there. Every screen should say
**"Select audio model" / "Select music model" / ...**; choosing a model that is on the computer loads it; choosing one that is not
shows a dialog ("we need to download this"), and on a yes the app downloads it and then loads it. Show few models at first. Sort the
models into types a novice understands. Decide whether chat (and the other products) get a default multimodal model. This
follows the order of work the owner set on 2026-10-20 (bug pass, then a simple model picker like Unsloth's).

Status: **accepted by the owner 2026-10-21 (all six recommendations), written up as ADR-0086; built the same day (M0 to M5 below; see D22 in `docs/backlog.md` for what is left).** One change from the plan: the window composes the
choices from the existing engine routes (an adapter per group), instead of one new engine route; ADR-0086 decision 9.

## 1. What a novice meets today (read from the code, 2026-10-21)

| Where | What the person sees | Why it is hard |
|---|---|---|
| Speech, music, transcription, tools, dubbing, audiobook, lip sync | a plain list "Parakeet TDT 0.6B v3 (recommended, not on this computer yet)", then "Not on this computer yet (916 MB). **Get it in Models**" and "Set this model up first (see above)" (`ModelPicker.tsx`, `format.ts`) | the link leaves the task; "set up" and "get" are two words for one thing; nothing says what to press there |
| Images, video | a chip "FLUX.2 klein 4B · not downloaded · needs 24 GB", a notice "Real images need the image engine set up once. Open Settings", then another notice "The model is not on this computer yet. Get it in Models" | **two** separate things to get (the engine, then the model), in two different places |
| Chat | a model chip, "Choose a model" that opens Models; found files need the language engine (Settings); Ollama or LM Studio used if running | three sources (engine file, found file, running server) and no default |
| Notebooks | "Get the search model first (see Set up reading documents)" | a model and a component, two cards |
| 3D | its own setup card | a third pattern |
| **Models page** | tabs On device / Discover; On device has three stacked sections (the catalogue, "Chat model", "Found models"); Discover is a Hugging Face search | no types: a person looking for "something to turn speech into text" sees file names; Discover is for people who know what a GGUF is |

The catalogue itself (`products/*/models.yaml`) has **19 entries: 1 image, 1 video, 1 search model, 16 voice** (speech, cloning, voice design,
music, sound effects, stem separation, voice change, speech editing, lip sync, transcription). The voice entries carry `tasks`; the image and
video ones carry nothing a screen can group by. Language models come from a separate shelf (`hub-shelf.yaml`, 7 entries) and from files and servers
found on the computer. There is **no default language model**: a fresh install has no chat until the person finds one.

What already works and is kept: the confirm-first resumable download (`POST /desktop/models/{id}/download` repeating the exact files and total),
the fit check (`fits`, `tight`, `too_big`), model states (`ready`, needs the runtime, not on this computer, not available), the one big-model
slot that unloads on idle, discovery of models other tools left (ADR-0063), the curated shelf.

## 2. The pattern to copy (Unsloth Studio, from the screenshots and `studio/frontend/src/features/model-picker`, ideas only: it is AGPL)

- The control on each screen is a **button that names its job and shows the current model**: "Select audio model ⌄".
- It opens one panel: a **search box**, a **Search Hub** button, tabs **Recommended | On Device**, filters, and **Custom folders** at the bottom.
- The tab it opens on is the last one used; first time: On Device if there is anything, else Recommended.
- The panel is **scoped by what the screen does** (audio models on the audio screen).
- Engines are offered when needed (a "managed engine offer" dialog), not through a separate settings visit.

Where we go further, for a novice: Unsloth still expects the person to know what to look for. We show **one recommended model per task first**, in words
about what it does, and put search, folders and Hugging Face behind "More".

## 3. Types a novice understands

Name things by **what the person wants to do**, not by the model's kind. Seven groups, which are also the picker titles:

| Group (picker title) | Screens that use it | What is in it today |
|---|---|---|
| **Chat** ("Select chat model") | chat, the assistant, Improve prompt, notebook answers, Studio outputs | the language shelf; found and server models. A **"can read pictures"** mark for multimodal ones |
| **Images** ("Select image model") | Create, Edit, Inpaint, Reference | FLUX.2 klein 4B |
| **Video** ("Select video model") | Create, Animate, Extend | LTX-Video 2B |
| **Voice** ("Select voice model") | text to speech, voice cloning and design, change a voice, edit speech, dub, audiobook | Kokoro, Qwen3-TTS, VoxCPM2, Tone Color, MeanVC2, dots.tts Edit |
| **Listening** ("Select transcription model") | speech to text | Parakeet |
| **Music** ("Select music model") | music, sound effects, split a song into parts | ACE-Step, Stable Audio 3, HTDemucs, Mel-Band RoFormer |
| **Faces** ("Select lip sync model") | lip sync | MuseTalk |
| **Documents** (no picker; part of Notebooks) | notebooks | the search model and the document reader |
| **3D** ("Select 3D model") | 3D | Pixal3D (a component) |

(Listening and Faces are separate because each has one task and a novice looks for them by that word; they can fold into Voice if the owner prefers fewer groups.)

Each model gets, in data, a **group**, its **tasks** (as the voice entries already have), a **plain description** (one line, no jargon: "Turns speech into text with
times; fast and accurate in English"), a **size to get**, **memory to run** (from the fit check), a **short licence line**, and a **tier** (`recommended`, `also
good`, `advanced`). The plain descriptions are content work: about 25 lines, written once, in English (v1).

## 4. The single control: "Select … model"

A shared component `ModelPicker` in `packages/ui` (desktop only; the web serves hosted models) with the group as its argument.

- **The button** says "Select image model" when nothing is chosen, else the model's name with a small state: *ready*, *loading…*, *not on this computer*.
  It sits where the screen's chip, `<select>` and notices are now; those go.
- **The panel** opens on **Recommended for this computer**: the best model of the group that fits this computer's memory first (memory decides the order,
  using the fit check), at most three rows, each with name, one plain line, size, and a state. **On this computer** lists what is already there (also found
  files and servers). **More models** holds the `advanced` tier, search, custom folders and Hugging Face (ADR-0064's Discover, demoted but kept).
- **Choosing a model that is on the computer** makes it the choice for this group and loads it (the button says "Loading…", then "Ready"). It is remembered for
  the next visit and for every screen of the group.
- **Choosing one that is not** opens a dialog, in plain words:
  *"To use Parakeet TDT 0.6B v3 we need to download it. 916 MB, about 2 minutes on a typical connection. It runs on this computer; nothing is sent away. Commercial use
  is allowed (licence). [Download and use] [Not now]"*. Behind it the same confirm-first download runs (exact files and total echoed back, resumable, checksums).
  The dialog also shows **fit** ("fits this computer", or "too big for this computer: choose a smaller one") and free disk.
- **When the model needs an engine we do not have** (the image engine, the language engine, the speech runtime), the **same dialog adds it** to the total:
  *"Image engine 1.5 GB (once) + FLUX.2 klein 4B 16.1 GB = 17.6 GB."* One yes, one progress bar, no visit to Settings.
- **After the download** the model is selected and loaded without another click. Progress shows in the button (a thin bar), survives leaving the screen, and ends
  in a toast. A failure says what to do ("not enough space: 4 GB free, 17.6 GB needed") and keeps what was downloaded.
- **Starting a task without a model** (pressing Create with none chosen) opens the same panel instead of an error.

"Load" means different things by group, said honestly in the plan: chat starts the language server; speech and music load their runtime; image and video load
the weights into the one big-model slot on the first generation (a 16 GB load takes a while), so the button says "Ready" and the first run says "Preparing the
model…". Memory is protected by the slot manager that exists (one big model at a time; idle unload).

## 5. The Models page, for novices

Keep it as the place to **see and tidy**, not the place to start.
- A card per group (Chat, Images, Video, Voice, Listening, Music, Faces, Documents, 3D): the model in use, a state, the disk it takes, **Change** (opens the
  same panel) and **Remove**. A header line: this computer's memory and free disk, and total used by models.
- **Advanced** (folded): model folders, models found from other tools (Ollama, LM Studio, the Hugging Face cache), Discover (Hugging Face search).
- The word "catalogue", "found models" and "discover" disappear from the first view.

## 6. Defaults and first run (the owner's question)

Recommendation: **offer, do not install silently; never download without a yes**.
1. **First run shows one card on the chat screen**: "Get started: a chat model that also reads pictures. N GB. Takes about M minutes." One button
   "Download and use". The model is chosen **by this computer's memory** (tiers below). The person can pick another in the same panel at any time.
2. **Tiers** (from ADR-0078 and the measured shelf): 24 GB and more: **Qwen3.5-9B** (Apache-2.0, text and pictures; ADR-0078's checks are still to pass: its size,
   context, speed and guardrail results are not yet measured); 16 GB: **Qwen3 8B** or a 4B model; 8 GB: **Qwen3 4B** (measured here: 11 of 11 tool cases,
   2.5 GB). A picture reader (the small `mmproj` file, already in `projector-shelf.yaml`) is added with a vision model, in the same dialog and total.
   Gemma 4 E4B stays the low-memory choice ADR-0078 names. The exact list is data (`hub-shelf.yaml`, `model_defaults.yaml`), changeable by one line.
3. **Image, video, voice and music models are not downloaded in advance**: they are large (16 GB each for image and video) and not everyone will use them.
   The first time the person presses Create or Speak, the picker's dialog offers the recommended one. This is the same flow as everywhere else.
4. **One model for several products where it can be one**: the chat model also serves Improve prompt, lyrics, notebook answers, Studio outputs and the
   checks that today use the aliases (`prompt-enhancer`, `moderator`, `multimodal`, ADR-0078). The person changes it in one place.
5. **Not bundled with the installer** (size, licence checks per ADR-0012, and the app stays small). Offline first run says so and keeps the page usable.

## 7. Stages

| Stage | What | Done when |
|---|---|---|
| **M0 Decide** (this document, the ADR, the content) | owner answers the questions; ADR-0086 written (supersedes ADR-0064 decision 1 and its tabs; keeps its engine-side browsing, opt-in network, fit and licence rules); the 25 plain descriptions and the tier list agreed | the ADR is Accepted |
| **M1 Engine** | add `group`, `tasks`, `plain`, `tier` to every catalogue entry and the shelf; one route `GET /desktop/choices?group=` returning rows (id, title, plain, size, state, fit, licence, tier, prerequisites with sizes) for catalogue, shelf, found files and servers; `POST /desktop/choices/select` (choose and load); `POST /desktop/choices/get` (confirm echoes files, total **including the engine**; one job: engine, model, then select); progress and errors in words; remembers the choice per group | route tests (all groups, a missing engine, a failed download, too big, disk full), the existing download rules unchanged |
| **M2 Picker** | `ModelPicker` and the download dialog in `packages/ui`; replace the selects, chips and notices in the voice, music, tool, dub, audiobook, lip sync, image, video, 3D and chat screens | each screen shows "Select … model"; pressing the main action with no model opens the panel; UI tests with a fake engine; no "Get it in Models" or "Set this model up first" left |
| **M3 Models page** | cards per group, Advanced fold, header numbers | a novice can find a type and remove a model without a word of jargon |
| **M4 First run and defaults** | the chat card, tiers by memory, the picture reader added with a vision model; document and notebook setup folded into the same dialog | a fresh data folder reaches a working chat with one click and one progress bar |
| **M5 Check** | real run on the Mac for each group (cold start: choose, dialog, download, load, use); copy and accessibility pass; docs and help files; the ADR's evidence | the owner's test passes on a fresh data folder |

Rough size: M1 two to three days, M2 three to four, M3 one, M4 one to two (plus ADR-0078's measurements for Qwen3.5-9B if it becomes the top tier), M5 one.

## 8. Risks and what we do about them

- **Two things to get (engine and model) look like one.** The dialog shows both and the total; the engine is installed first and says so.
- **A recommended model that does not fit** (16 GB Mac and a 24 GB model): the order is by fit, `too_big` is greyed out with the reason and the nearest smaller one named.
- **Licences**: each recommended model's licence is re-read from its files (ADR-0012); the dialog states commercial use in words.
- **Disk**: free space is checked before the dialog says yes; partial downloads resume.
- **The first load is slow** (16 GB): honest wording ("Preparing the model, about a minute"), the slot manager keeps one big model resident.
- **Offline**: the panel shows what is on the computer and says downloads need a connection; nothing is requested without a yes.
- **Existing choices**: people who already chose a chat model, folders or found models keep them (migrated, not asked again).
- **Web**: not affected (hosted models); the shared screens keep working without the picker.

## 9. Questions for the owner

1. **The groups** in section 3: nine, or fold Listening and Faces into Voice (seven)?
2. **Default chat model**: offer the one-click first-run card (my recommendation) or leave chat empty until the person chooses? And may the top tier be **Qwen3.5-9B** once
   its checks pass, with **Qwen3 4B** (measured) as the 8 and 16 GB choice until then?
3. **Loading on select**: load chat at once (the person is about to type), load image and video on the first generation (my recommendation), or load everything at once?
4. **Demote Discover** (Hugging Face search) to "More models" and **hide found models and folders under Advanced**: yes?
5. **How many models in the first view**: at most three per group, one marked "Recommended for this computer"?
6. **Engines**: fold "Set up image generation" into the model dialog so the engine is never a separate step (my recommendation)?
