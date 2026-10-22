# Web parity ledger: what the web app does for each desktop feature

Owner rule (2026-10-21): the web app and the desktop app have the same features, and a new desktop feature is not done until the
web has a decision for it. The source of truth is `apps/web/lib/parity.ts` (one row per item of the desktop's side menu, with a
reason); `apps/web/lib/parity.test.ts` fails when a desktop menu item has no row or the web menu does something else.
This page adds what the menu does not show. Everything that needs a GPU, a model or a sandboxed browser runs on an engine worker (`docs/phase6-web-identical-plan.md`, ADR-0087). Plan: `docs/phase3-web-parity-plan.md`, W8.

| Desktop feature (since 2026-10-18) | Web | Notes |
|---|---|---|
| Design system (blue tokens) | same | shared `packages/ui` |
| New chat on assistant-ui: edit and branches, approval cards, attachments, Mic, read-aloud, Search and Thinking | same | shared screens; the web's Mic and read-aloud use the hosted speech aliases |
| Notebook chat, card fixes, resizable Studio | same | shared; notebooks always on, with the notebooks worker |
| Reference and Inpaint | live | shared `ImageWorkspace`; needs the image workflows on the GPU host |
| Extend video (5 and 8 s, your own file) | live | shared `VideoWorkspace`; needs ffmpeg (in the API image) and the video workflow on the GPU host |
| 3D models | live | the Pixal3D component on an engine worker (ADR-0087, P3); rows in Postgres, files in object storage |
| Video Builder | live | the sandboxed render on an engine worker (ADR-0087, P4); rows in Postgres, videos are library clips |
| Speech, music, voices, splitting, dubbing, audiobook, lip sync | live when a worker has the model | engine worker (P0, P1 built); a screen appears when a worker lists a ready model |
| Model picker on the Voice, Listening, Music and Lip sync screens | live (P5) | the same button and panel over the models the workers list; the choice is remembered in the browser; a model a worker lacks shows "ask an admin" to everyone but admins |
| Safeguards on the new screens (P6) | same | 3D pictures and Video Builder words are moderated while safeguards are on, with daily limits and usage events; worker seconds are an `engine.seconds` event |
| Getting a model onto a worker (the desktop's download dialog) | live (P5) | Admin > Workers: an admin starts the download on the worker, with its size first and progress; the worker checks the files; the same for the lip sync engine |
| Model picker on Image, Video, Chat and 3D screens; the nine-card Models page; first-run chat card | desktop only | the deployment's admin chooses chat models (Admin > Models) and the media worker's workflows; 3D has one model; the web has no per-person disk |
| Save As box, window bar, Recents menu in the bar | desktop only | a browser downloads files and has its own bar |
| Notebook, speech and music switches | removed | no feature switches on either app |

## Menu items (generated)

One row per item of the desktop's side menu, from `apps/web/lib/parity.ts`. `parity.test.ts` fails when this table is not what
the file says; update it with `UPDATE_LEDGER=1 pnpm --filter web exec vitest run lib/parity.test.ts`. A row that is not `live`
needs an `Accepted` entry, and the CI job `parity` (`.github/workflows/desktop.yml`, a requirement of the packaged app) and the
web job's test step fail without one. The desktop's actions are held to the same rows: an action's `ui` in
`docs/contracts/actions.json` must be a row here.

<!-- parity:start -->
| Menu item | Web | Why | Accepted |
|---|---|---|---|
| `chat` | live | the shared chat |  |
| `library` | live | My creations |  |
| `models` | desktop-only | the picker is on the voice, music and lip sync screens and an admin gets models onto a worker in Admin > Workers (P5); chat models are the admin's Models page; the nine-card Models page is the desktop's | owner, 2026-10-21: an admin chooses a deployment's models; the person's own disk is the desktop's. The models.* actions need the desktop's model service, so the web assistant does not offer them |
| `train` | soon | not built on either app | owner, 2026-10-21: training is not built on the desktop either (ADR-0073 onwards) |
| `notebook.create` | live | the shared notebooks, with the notebooks worker |  |
| `notebook.list` | live | the shared notebooks |  |
| `images.create` | live | shared ImageWorkspace |  |
| `images.edit` | live | shared ImageWorkspace |  |
| `images.inpaint` | live | shared ImageWorkspace, mode inpaint |  |
| `images.reference` | live | shared ImageWorkspace, mode reference |  |
| `images.model3d` | live | shared Model3d screen; Pixal3D runs as a job on an engine worker (ADR-0087, P3), rows in Postgres, files in storage |  |
| `images.library` | live | shared ImageLibrary |  |
| `video.create` | live | shared VideoWorkspace |  |
| `video.animate` | live | shared VideoWorkspace |  |
| `video.extend` | live | shared VideoWorkspace, mode extend; needs ffmpeg in the API image |  |
| `video.builder` | live | shared VideoBuilder screen; the sandboxed render runs as a job on an engine worker (ADR-0087, P4), rows in Postgres, videos are library clips |  |
| `video.library` | live | shared VideoLibrary |  |
| `voice.speak` | live | shared voice page, hosted models |  |
| `voice.transcribe` | live | shared voice page, hosted models |  |
| `voice.lipsync` | live | shown when a ready model can do it (a GPU host) |  |
| `voice.voices` | live | shown when a ready model can do it |  |
| `voice.convert` | live | shown when a ready model can do it |  |
| `voice.edit` | live | shown when a ready model can do it |  |
| `voice.dub` | live | shown when a ready model can do it |  |
| `voice.audiobook` | live | shown when a ready model can do it |  |
| `music.create` | live | shown when a ready model can do it |  |
| `music.library` | live | shown when a ready model can do it |  |
| `music.lyrics` | live | shown when a ready model can do it |  |
| `music.separate` | live | shown when a ready model can do it |  |
<!-- parity:end -->
