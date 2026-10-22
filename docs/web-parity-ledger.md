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
| Getting a model onto a worker (the desktop's download dialog) | live (P5) | Admin > Workers: an admin starts the download on the worker, with its size first and progress; the worker checks the files; the same for the lip sync engine |
| Model picker on Image, Video, Chat and 3D screens; the nine-card Models page; first-run chat card | desktop only | the deployment's admin chooses chat models (Admin > Models) and the media worker's workflows; 3D has one model; the web has no per-person disk |
| Save As box, window bar, Recents menu in the bar | desktop only | a browser downloads files and has its own bar |
| Notebook, speech and music switches | removed | no feature switches on either app |
