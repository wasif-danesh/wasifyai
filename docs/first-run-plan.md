# Plan: the first run and one setup card per group (2026-11-18)

Decision: [ADR-0109](decisions/0109-first-run-and-one-setup-card-per-group.md), Accepted 2026-11-18. Mockup:
[`docs/spikes/first-run-mockup.html`](spikes/first-run-mockup.html).

Owner's words: "If we throw so many decisions at the first run, many will be scared and probably quit." "The user
won't go to settings." "Once the user decides to download, we should make the product fully workable."

Status: **planned, nothing built.** Desktop only; the web shows no cards (ADR-0109 decision 19).

## What is there today (read from the code, 2026-11-18)

| Piece | Where | Kept, changed or replaced |
|---|---|---|
| What an action needs | `Need` in `wasifyai_platform_sdk/actions/model.py` (`product`, `model`, `runtime`, `notebooks`, `chat`, `web`); 111 actions in `docs/contracts/actions.json` | kept; the gaps are filled in FR1 |
| Whether a need is met | `ToolHost.readiness` in `services/api/.../tool_host.py`: ready, `needs_setup` with a step and a screen, or unavailable; `app.status` lists it per action | kept; the cards read the same answer |
| One installer for every optional part | `wasifyai_platform_sdk/installer.py`, `services/api/.../components/` with pins in `components/manifests/<platform>.yaml` | kept; FR2 runs several parts as one job |
| Model downloads, confirm-first | `POST /desktop/models/{id}/download` repeating the exact files and total (ADR-0059) | kept; FR2 calls it for each model of a group |
| Chat's first-run card | `apps/desktop/src/choices/ChatStart.tsx` on the home | replaced by the Welcome in FR5 |
| Setup cards | `notebook/SetupCard.tsx`, `training/SetupCard.tsx`, `voice/RuntimeCard.tsx` (the engine only), `Model3d.tsx`, `VideoBuilder.tsx`, `Creative.tsx`, Code's | replaced by the one card in FR3 and FR4, except Train's explainer |
| Images and Video | no card; the model button's dialog | gain the card in FR4 |
| The menu | `packages/ui/src/shell/menu.ts` (`MENU_GROUPS`, `EXTRA_ITEMS`), `apps/desktop/src/menu.ts` (`ROUTES`); Lip sync is `voice.lipsync` in Video | Lip sync moves in FR4 |

Gaps found in the catalogue: the image and video actions say only `product`, never the model they need, and the voice
actions name `speak`, `transcribe`, `convert`, `edit`, but not the voice-copy and voice-design models. The cards
cannot be generated until every action names all it needs.

## Rules for every stage

- Real parts, real downloads, real models on a throwaway `DESKTOP_DATA_DIR`. No stand-in counts as checked.
- No number on a card that was not measured (ADR-0109 decision 14).
- Every word on a card is in `packages/ui/src/words.ts`, ready to translate.
- Nothing is downloaded without the person's click; the job repeats the exact files and the total to the engine.
- Each stage ends with its tests green, a walk of the real window where there is a screen, and a note in
  `docs/spikes/first-run-fr<n>.md` (what was measured, what was not).
- Commits are the owner's.

## Stages

**Built 2026-11-18: FR0 to FR5.** The differences from what is written below are in
`docs/spikes/first-run-fr1-fr5.md`:

- FR2 runs in the window over the engine's resumable jobs, with no engine job or `setup.group` action.
- The old cards are kept behind the gate.
- `ChatStart` stays on Notebook, Creative Studio and Motion graphics.
- Voice, Notebook and Motion graphics were set up for real through their cards.
- The first run was walked with Ollama only, in a browser against the real engine.

FR6 waits for the owner's look at the real window.

### FR0: measure

- The memory each local model really uses while working on this Mac (Kokoro, Parakeet, Qwen3-TTS 0.6B and 1.7B, dots
  TTS edit, ACE-Step, HTDemucs, song analysis, MuseTalk, Sortformer and ERes2Net, the chat models, FLUX.2 klein 4B,
  LTX-Video 2B, Pixal3D). Peak resident memory per run, with the one big-model slot (ADR-0056) as it is.
- Check ADR-0109's two cut-offs (download under three quarters of memory, key first over half) against those numbers
  for 8, 16, 24, 32 and 64 GB Macs, and write the table each card will show. If a cut-off gives a wrong answer for a
  real Mac, the plan says so and asks the owner before changing it.
- The download size of every part, from the manifests and the catalogue, in one table, checked against a real
  install of each.
- **Done when:** `docs/spikes/first-run-fr0.md` holds the measured table; every size and memory figure in the
  mockup is replaced by a measured one or marked as not measured.

### FR1: what a group needs (engine)

- Fill the gaps in `requires`: every image, video, voice, music, lip sync and 3D action names its model needs; a test
  fails when an action that runs a local model names none.
- A group map: the menu group of each action comes from its `ui` pointer, so a group is the actions of its items.
  Creative Studio's group adds Video's and Voice's; Meetings' adds Notebook's (ADR-0109 decisions 9 and 10).
- `GET /desktop/setup/groups`: for each group, its items, the parts they need (each with its size, the memory it
  needs, set up or not), the fit for this computer (download, leave out with the items it affects, key first) and
  whether a key on the person's account covers it. Built from `readiness`, the manifests and the catalogue; nothing
  new is stored.
- Indian languages counted in Voice only when the app's or the computer's language is one of them (decision 15).
- **Tests:** each menu item's card lists every need of its actions; the fit rules on the FR0 table give the answers
  the mockup shows for 8, 24 and 64 GB; a part already set up is not counted.
- **Done when:** the route answers on this Mac with the real parts and the numbers match FR0.

### FR2: one job sets up a group (engine)

- `POST /desktop/setup/groups/{id}` with the exact parts and total the card showed; the engine refuses if they
  changed (ADR-0059). One job, one progress (parts done, bytes, the part now running), resumable after a restart
  (`action_jobs`, stage J3), stoppable.
- It runs the installer for each component and the model download for each model, in an order that puts the small
  parts first, so the first items of the group work while the big model is still coming.
- An action `setup.group` (ADR-0068) with a help file, so the chat can offer it too ("Voice is not set up: set it up,
  9.0 GB?") and asks before it runs (`needs_consent`).
- **Done when:** a real run sets up Voice on a fresh data directory on this Mac, every Voice item then works without
  another download, and a run stopped half way picks up where it stopped.

### FR3: the card (packages/ui)

- `GroupSetupCard` in `packages/ui/src/setup/`, drawn from the FR1 answer: the group's name, what it can do, the
  parts with "✓ set up", the size, the line naming items left out on this computer, the buttons (download first, or
  key first with "Download instead"), then the progress of the FR2 job in the same place.
- On `/design` with every state: nothing set up, part set up, small Mac, key first, running, stopped, failed.
- **Tests:** unit tests for each state; axe on `/design`.
- **Done when:** the card matches the mockup in light and dark, at 375 px and on the desktop width.

### FR4: every group uses the card (desktop)

- Each menu item whose group is not set up shows its group's card in place of the screen; after the job the screen
  opens. Voice's `RuntimeCard`, Notebook's, Creative Studio's, Motion graphics', 3D's and Code's setup cards are
  removed; Images and Video gain the card. Train keeps one card that explains each kind sets itself up when chosen.
- Lip sync becomes a single item below the groups (`MENU_GROUPS`, `EXTRA_ITEMS`, `ROUTES`, the action's `ui`
  pointer, its help file); its address stays `voice.lipsync`.
- Creative Studio's button sets up Creative Studio, Video and Voice in one job.
- **Done when:** a walk of the real window on a fresh data directory opens every menu item, meets one card per
  group, sets up Voice and Notebook for real, and never meets a second card in a set-up group
  (`ui-audit.sh light setup-groups`).

### FR5: the first run (desktop)

- Welcome with one **Get started** button and its cost, the progress screen, **Ready**. It sets up chat only:
  llama.cpp and the chat model ADR-0086 decision 8 chooses by memory.
- A usable model found in Ollama, LM Studio or the Hugging Face cache (ADR-0063) is used instead, and the button
  says so. On an 8 GB Mac the key is the main button.
- "I'd rather use an API key" opens the model button's Cloud tab as its own step.
- The first run shows once; a person who closes it lands on the home, and the chat's empty state offers the same
  button. `ChatStart` is removed.
- **Done when:** walked in the real Tauri window on a fresh data directory, three ways: download, with Ollama
  running, with a key.

### FR6: the whole walk

- One walk from a fresh install: Get started, chat, then every group's card, on this Mac, in light and dark, with
  axe on each screen.
- `docs/desktop/first-run.md` written; `CLAUDE.md` and `docs/desktop-profile.md` updated; ADR-0109 gets its "Built"
  lines.
- **Done when:** the owner has seen the real window.

## Not in this plan

- The web (no cards there).
- A cheaper or smaller model for a small Mac; that is a model choice (ask before adding one).
- Removing a whole group to free disk: the Models page does it per model today.

## Questions for the owner

None now. FR0 may raise one if a cut-off in ADR-0109 gives a wrong answer on a real Mac.
