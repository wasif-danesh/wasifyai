# ADR-0086: One simple way to choose, get and use a model

- **Status:** Accepted (2026-10-21, by the owner: "I agree with the proposal. Let's build it.", all six recommendations)
- **Date:** 2026-10-21. **Built** the same day: `packages/ui/src/models/` (the button, the dialog, the Models page), `apps/desktop/src/choices/` (the adapters), tests in both.
- **Supersedes:** decision 1 of ADR-0064 (the Models screen with two tabs, On device and Discover) and the "Get it in Models" step
  of the screens. The rest of ADR-0064 stands: the engine does the browsing, opt-in network, only what the app can run by default, fit
  on every variant, confirm-first downloads, licence first, model cards as text.
- **Depends on:** ADR-0059 (confirm-first resumable downloads, one managed engine), ADR-0063 (found models, the fit check),
  ADR-0066 (speech and music models), ADR-0078 (the default chat model), ADR-0083 (the chat's model chip, the picture reader),
  ADR-0012 (licences)
- **Plan and the reasoning:** `docs/model-picker-plan.md`

## Context

A novice cannot tell what "Get it in Models" does or what to choose there. Today a missing model is a link to another screen; the image and
video screens need two separate things (the engine in Settings, then the model in Models); chat has no default; the Models page stacks three
sections and a Hugging Face search; and the 19 catalogue models have no type a screen can group by.

## Decision

1. **Every screen that needs a model has one control that names its job**: a button "Select image model", "Select voice model" and so on,
   showing the current model and its state (*ready*, *loading*, *not on this computer*). It replaces the dropdowns, chips and notices.
2. **Nine groups, named for what the person wants to do** (each is a picker title): **Chat**, **Images**, **Video**, **Voice** (speech, cloning,
   voice design, change a voice, edit speech, dub, audiobook), **Listening** (speech to text), **Music** (music, sound effects, split a song into
   parts), **Faces** (lip sync), **Documents** (the search model and the reader, no picker of its own), **3D**. A model belongs to one group and
   lists its tasks.
3. **The panel shows few models.** It opens on **Recommended for this computer**: at most three rows, the best fit for this computer's memory first
   (the fit check decides the order), each with its name, one plain line, its size and a state. **On this computer** lists what is there (found
   files and servers too). **More models** holds the rest, search, model folders and Hugging Face (ADR-0064's Discover, kept but demoted).
4. **Choosing a model that is on the computer makes it the choice for its group and loads it.** Chat loads at once (the person is about to type);
   image, video and other large models load on the first use (the first run says "Preparing the model"); the one big-model slot and its idle unload
   (ADR-0056) stay as they are. The choice is remembered per group and shared by every screen of the group.
5. **Choosing one that is not on the computer opens a dialog in plain words**: what it is, the size, a time estimate, that it runs on this computer,
   the licence in words (commercial use) with a link, whether it fits, free disk. **If it needs an engine the computer lacks (the image engine, the
   language engine, the speech runtime), the same dialog adds it to the total** ("Image engine 1.5 GB, once, plus FLUX.2 klein 4B 16.1 GB"). One
   "Download and use" runs the engine, the model and the choice as one job with one progress bar, resumable, with the exact files and total echoed to
   the engine as ADR-0059 requires. Nothing is downloaded without that click.
6. **Starting a task with no model chosen opens the same panel**, not an error.
7. **The Models page is for seeing and tidying**: a card per group (the model in use, its state, the disk it takes, Change, Remove) and, folded under
   **Advanced**, model folders, models found from other tools and Discover.
8. **Defaults.** Chat has a **first-run card**: "Get started: a chat model that also reads pictures", one button, chosen by this computer's memory
   (24 GB and more: Qwen3.5-9B once ADR-0078's checks pass; 16 and 8 GB: Qwen3 8B and Qwen3 4B, measured; the picture reader is added with a vision
   model). It is an offer, never an automatic download. Image, video, voice and music models are fetched on first use through the same dialog. One chat
   model serves Improve prompt, lyrics, notebook answers and the Studio outputs. Models are not bundled with the installer.
9. **Where the code lives.** The window composes the choices: an adapter per group in `apps/desktop` turns the existing engine routes (the catalogue,
   the speech and language engines, the components) into rows and runs "get and use"; the picker and its dialog are in `packages/ui` and know nothing
   of the engine. The engine routes and their confirm-first rules do not change. The names, one-line descriptions and tiers of the models are data in
   the window (English only in v1). The web app keeps hosted models and its own simple selects.

## Alternatives considered

| Option | Why not |
|---|---|
| Keep two tabs and add help text | the problem is the detour and the jargon, not a missing sentence |
| Download the recommended set at first run | breaks confirm-first (ADR-0059); a 16 GB image model is not for everyone |
| One engine route that returns every group's rows | the rows already exist in five engine routes; a window adapter adds no second source of truth. Revisit if the web needs it |
| Copy Unsloth's selector | AGPL (ADR-0062); its layout (Recommended, On Device, search, folders) is the pattern, the code is ours |

## Consequences

- New: `ModelPicker`, the download dialog and `useModelChoices` in `packages/ui`; a choices adapter per group and the model copy table in `apps/desktop`.
- Changed: the voice, music, tool, dub, audiobook, lip sync, image, video, 3D and chat screens lose their own model controls; `ModelsPage` is rebuilt;
  the shared voice `ModelPicker` stays for the web.
- The engine gains only what a combined "engine, model, choose" job needs if the window cannot compose it from the existing routes.
- ADR-0064 is amended at its top. Its Discover moves under "More models".

## Not in this version

Other languages, comparing models, ratings, automatic updates, a picker on the web (its models are hosted).
