# Web parity ledger: what the web app does for each desktop feature

Owner rule (2026-10-21): the web app and the desktop app have the same features, and a new desktop feature is not done until the
web has a decision for it. The source of truth is `apps/web/lib/parity.ts` (one row per item of the desktop's side menu, with a
reason); `apps/web/lib/parity.test.ts` fails when a desktop menu item has no row or the web menu does something else.
This page adds what the menu does not show. The Voice, Music, Lip sync, 3D and Video Builder rows are "soon" because the web has no compute for them: the plan is `docs/phase6-web-identical-plan.md` (ADR-0087, Proposed). Plan: `docs/phase3-web-parity-plan.md`, W8.

| Desktop feature (since 2026-10-18) | Web | Notes |
|---|---|---|
| Design system (blue tokens) | same | shared `packages/ui` |
| New chat on assistant-ui: edit and branches, approval cards, attachments, Mic, read-aloud, Search and Thinking | same | shared screens; the web's Mic and read-aloud use the hosted speech aliases |
| Notebook chat, card fixes, resizable Studio | same | shared; notebooks always on, with the notebooks worker |
| Reference and Inpaint | live | shared `ImageWorkspace`; needs the image workflows on the GPU host |
| Extend video (5 and 8 s, your own file) | live | shared `VideoWorkspace`; needs ffmpeg (in the API image) and the video workflow on the GPU host |
| 3D models | soon | needs the Pixal3D engine as a GPU job (ADR-0080) |
| Video Builder | soon | needs the sandboxed browser render as a worker job (ADR-0077) |
| Speech, music, voices, splitting, dubbing, audiobook, lip sync | live when a worker has the model | engine worker (P0, P1 built); a screen appears when a worker lists a ready model |
| Model picker, Models page, first-run chat card | desktop only | the person's own local models; on the web an admin chooses the deployment's models |
| Save As box, window bar, Recents menu in the bar | desktop only | a browser downloads files and has its own bar |
| Notebook, speech and music switches | removed | no feature switches on either app |
