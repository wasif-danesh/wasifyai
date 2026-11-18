# The first run and one setup card per group (ADR-0109)

Built 2026-11-18, stages FR0 to FR5 of `docs/first-run-plan.md`; the stage notes are `docs/spikes/first-run-fr0.md`
and `docs/spikes/first-run-fr1-fr5.md`.

## What the person sees

- **The first run.** The home shows a Welcome with one **Get started** button and what it costs. It sets up chat
  only:
  - When a chat model is already on the computer (Ollama, LM Studio, a found file), the button uses it and says
    "Uses X … · no download".
  - Otherwise it downloads the chat model the model button would pick, and says how big it is.
  - "I'd rather use an API key" opens Settings › Your keys. When the computer is too small for a chat model, the
    key is the main button and "Download a chat model instead" is the second.
  - The steps are Welcome, then Getting ready (progress, Stop), then You're ready (Start chatting).
  - It shows once (`wasify.first-run.done` in the window's storage) and only while chat is not set up, so a person
    who had chat before never sees it. **Not now** goes to the home. While chat is still not set up, the home then
    shows a "Get a chat model" notice with the same button.
- **One card per group.**
  - Opening any menu item whose group cannot work yet shows the group's card in place of the screen. The card
    lists every part with its size or "✓ set up", the items left out on this computer, and one button: "Set up
    Music · 6.3 GB", or "Use an API key" first when a key covers the group and its model is too big for the
    computer.
  - Pressing the button sets up every item of the group, small parts first, with the progress on the card. The
    screen opens when it is done.
  - A screen whose model in use is ready, a cloud model on the person's key included, opens as it is.
  - If the groups can't be read (the engine is starting, or an older engine), the screen opens: the card is a
    front door, never a wall.
  - The window's self-test (`smoke.ts`, CI's `smoke`, `install` and `package` jobs) opens the same `gate` it
    uses for pictures, so it passes the cards and the first run and checks the screens themselves.
- **Lip sync** is its own menu item below the groups (`EXTRA_ITEMS`), after a divider; its address stays
  `voice.lipsync`.

## Where the code is

| Piece | File |
|---|---|
| What each group needs, and the fit to this computer | `services/api/src/wasifyai_api/setup_groups.py`, route `GET /desktop/setup/groups` |
| Its tests (real catalogues, fake part states, 8/16/24/64 GB) | `services/api/tests/test_setup_groups.py` |
| Client types | `packages/client/src/setup.ts` (`createSetupApi`), `apps/desktop/src/api.ts` (`setupApi`) |
| The card and its words | `packages/ui/src/setup/GroupSetupCard.tsx`, `words.ts`; on `/design` |
| What a press runs (steps per part, the run store) | `apps/desktop/src/setup-groups.ts` |
| The gate in front of every screen | `apps/desktop/src/SetupGate.tsx`, used by `Shell.tsx` |
| The first run | `apps/desktop/src/FirstRun.tsx`, `pages/Home.tsx` |
| The walk | `ui-audit.sh light first-run,setup-groups`; `WASIFYAI_SETUP_GROUP="path|Label|otherPath"` sets one group up for real |

## How it decides

- **The parts of an item.** These come from its actions' `requires` (`Need(kind, name)`), plus `ITEM_ALSO` for
  the model needs the actions do not name: Voice's clone and design models, and the image and video models.
  - Creative Studio adds the needs of Video and Voice.
  - Meetings adds Notebook's.
  - A model need resolves to the model in use, else the recommended one, else the first. Its engine's component
    comes with it.
- **The fit.** It uses `desktop_fit`'s shares of memory, so the card and the model button never disagree:
  - A part is downloaded when it needs at most the budget (75% of unified memory).
  - "Download instead" offers it up to the capacity (90%).
  - A key comes first when a key covers the group and a part needs more than half the memory.
  - Chat is key first at 8 GB or less.
  - The memory figures are the catalogue's `approx_ram_gb` and each component's own.
- **Indian-language speech** is counted only when the app's or the computer's language is one of them (macOS
  `AppleLanguages`).
- **Pressing the button.** It runs the group's parts in the window, one step per part, over the engine's existing
  routes:
  - components through `installStep`;
  - models through `modelStep`, which the engine downloads as resumable jobs;
  - chat through the chat choice's `get`, or `choose` for a model already here.

  Stop aborts the steps. Pressing again carries on: a finished part is set up, and a model download resumes.
- **Watching parts.** One stream of part changes serves the whole window (`onComponentStatus` in
  `components.ts`). A stream per listener used up the few connections the window may hold open to the engine, and
  everything else waited behind them.

## Not built, or different from the plan

- **No engine job or action.** There is no `POST /desktop/setup/groups/{id}` and no `setup.group` action. The
  window runs the steps over the engine's own resumable jobs (ADR-0086 decision 9). So:
  - a setup does not carry on by itself after the window closes;
  - the chat cannot offer a group's setup; it points to the screen instead.
- **The old cards are still there.** The in-screen setup cards (Voice's `RuntimeCard`, Notebook's, Creative
  Studio's, Motion graphics', 3D's, Code's) stay behind the gate as a fallback. They show only when the gate lets
  a screen through that still lacks a part. `ChatStart` is gone from the home but stays on Notebook, Creative
  Studio and Motion graphics.
- **The web shows no cards**, by decision.
