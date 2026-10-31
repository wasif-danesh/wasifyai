# ADR-0096: Motion graphics becomes a scene editor for promotion and social content, with the assistant built in

- **Status:** Accepted (owner, 2026-10-31: all five decisions of the plan as recommended; the mockup,
  `docs/spikes/motion-editor-mockup.html`, approved with its recommended answers the same day). Stages MX1 to MX4 built 2026-10-31; see "Built".
- **Date:** 2026-10-31
- **Asked by:** the owner, 2026-10-31: bring the features of KinoFold (`~/Projects/kinofold`, the owner's own project on HyperFrames) into
  Motion graphics, similar to the planned Creative Studio, for product promotion, social media and marketing content, with the chat
  assistant integrated.
- **Amends:** ADR-0077 ("A visual timeline editor" under "Not in v1") and ADR-0079 (the templates become scene kinds).
- **Depends on:** ADR-0041 (searchable), ADR-0056 (one engine, two shells), ADR-0068 (actions), ADR-0081 (tokens), ADR-0082 (chat
  components), ADR-0087 (engine workers), ADR-0088 (one job per person), ADR-0090 (Creative Studio), ADR-0093 (one shell), ADR-0094.
- **Evidence:** `docs/spikes/motion-editor-mx0.md`. **Plan:** `docs/motion-graphics-editor-plan.md`, stages MX0 to MX7.

## Context

A Motion graphics project today is one of five templates filled with words, previewed as a still. KinoFold has a multi-scene document
and an editor on the same render engine, and it lacks an assistant, generated media, a brand and any web version. Marketing content
needs both halves.

## Decision

1. **A project is a list of scenes** in a versioned document kept in the product's store. The HTML is always generated from the document;
   people and models never edit it. The five templates become scene kinds, and an existing project opens as one scene and looks the same.
2. **The editor has four regions:** Add tools on the left (Media, Words, Sound, Looks, Make, Brand), the preview in the middle, the
   Assistant and Scene tabs on the right, and the scene strip with the music row below. It is a strip of scenes, not a multi-track timeline.
3. **The preview is the HyperFrames player on plain files.** The engine serves the generated folder on a route with a short-lived signed
   token in its path, a tight content policy and byte ranges. The window's rules gain `frame-src http://127.0.0.1:*`. KinoFold's Studio
   server is not used. The export stays the final word. The player file is copied from the pinned 0.8.171 package; no upgrade is needed.
4. **The assistant is docked in the editor,** on the shared chat components, with the project and the selected scene sent with each
   message. It changes the document through actions, the same ones the screen and MCP use. **A change applies straight away and is one
   Undo step; making media or rendering says its cost first and follows "Ask me before".** Words the person typed are not rewritten
   unless asked. If the 9B model cannot plan scenes reliably (measured in MX3), starting points it fills in are the fallback.
5. **Make uses the products we have.** Image, Video, Speech and Music in a panel layout; results are saved to the Library as today and
   tagged with the project.
6. **The render path does not change:** the sandbox (ADR-0077), the exact-text check per scene (ADR-0079), one job per person (ADR-0088).
   Media is copied into the project's folder. Only fonts we ship are used, so the preview and the export match.
7. **The desktop and the web together at each stage,** because Motion graphics is live on both and the screen is shared.
8. **Built before Creative Studio.** The screen frame, media rail, Make panel and docked assistant are shared parts that it reuses.
   Song analysis, the plan and cuts on the beat stay Creative Studio's. CS0 still waits for the owner.
9. **The name stays "Motion graphics"** until the build works, then the owner decides.

## Options considered

| Option | Verdict |
|---|---|
| Port KinoFold's Rust and JavaScript | No: a different stack, no web, and it would be a second document system |
| Run HyperFrames' Studio server for the preview, as KinoFold does | No: a Node process per project, hard on the web, and the spike shows it is not needed |
| Merge this into Creative Studio | No: that product depends on model quality and is not yet measured. They share parts, not a product |
| Stills only, no live preview | No: motion is what is being edited |

## Consequences

- The window's content policy gains a frame source, and the engine gains a token-in-path route. Both get a test.
- `RENDER_NEED_GB` goes from 3 to 5.
- The web's preview needs a look at isolation (the player's frame allows scripts and same-origin): our generator is the only author of
  those files, and the tight policy applies.
- The screen's timing and fit lines use the spike's measurements until a real run corrects them.

## Risks

- **WebKit is not Chrome.** The preview can differ from the export. Shipped fonts reduce it, and the screen says the export is final.
- **Quality of the 9B model's plans and copy** is unmeasured until MX3.
- **Scope:** a strip of scenes can grow into a full editor. The plan keeps tracks out.

## Not decided here

Model-written compositions (MG2), a multi-track timeline, posting to social networks, and the final name.

## Built

**MX1, 2026-10-31: the scene document.**

- A project of scenes is one more kind of composition (`template = "scenes"`): its slots are the document, `{name, shape, font, seconds, scenes: [{id, name, kind, fields}]}`. `kind` is one of the five templates, and shape and font belong to the whole project. So the store, versions, the worker's wire, search and the library needed no new paths.
- **It is one flat page, not nested compositions** (`templates._render_scenes`). This is a change from the spike, which used a file per scene as KinoFold does. The exact-text check, the lint on the worker and the code view all read one page, and the page plays the same way. `_scoped` gives each scene's ids a `s<id>-` prefix (a selector cannot start with a digit), nests its rules under the scene and offsets its clips. Each scene's timeline is added to one film timeline, and the film hides each scene outside its own time, because the check runs without the renderer's runtime.
- Old projects stay as they are until their first scene change (`as_scenes`), and Undo turns them back. So a version now records its template (`versions.template`, schema 3, on SQLite and Postgres).
- Edits are `builder/scenes.py`; the actions are `motion.write_scenes`, `motion.add_scene`, `motion.change_scene`, `motion.move_scene`, `motion.duplicate_scene`, `motion.remove_scene` and `motion.undo`. The project route returns `document` for every project.
- **Limits:** 30 scenes and 90 seconds in all. A scene with no length is 5 seconds. A film is transparent only if every scene is.
- **Checked for real** (`services/api/tests/test_video_builder_templates.py`, the pinned browser and sandbox): a five-scene film passes the check and each scene shows its own background; a wrong word in a later scene is caught; the 20 hard text cases pass as scenes; each of the five templates looks the same as a one-scene project, frame compared; three scenes made through the actions on SQLite and on Postgres. The worker path is tested on a stand-in worker, not a running stack.

**MX2, 2026-10-31: the editor screen.**

- `packages/ui/src/videobuilder/scenes/`: `SceneEditor.tsx` (the screen, the same on the desktop and the web), `use-scene-editor.ts` (one document, one selection, Undo that groups a typing session, a save queue), `LivePreview.tsx` (the player, loaded only when this screen opens). The left panel has Add and Looks for now; the assistant, arranging, media, Make and Brand are later stages, and no tool is shown before it works.
- **The preview** is `POST /builder/projects/{cid}/live` and `GET /builder/live/{token}/...` (`builder/live.py`). The token is `<project>.<expiry>.<signature>`, 76 characters, because the web's proxy allows 80 in a path segment; it is signed with a key in the store's `meta` table, so every API replica accepts it. The page comes with a tight content policy. Its other files come from `engine.live_kit()`: on the web the API has only the words, so it fetches them once from a worker (`builder.kit`). **Byte ranges are not served yet** because a words-only page does not need them; MX5 adds them with media.
- **Undo:** the screen keeps its own steps, with Redo, for this visit, then falls back to the versions kept with the project. Saves are 500 ms after the last change and never overlap. The engine's answer only fills in what it works out (lengths, default names), never the words being typed. A change the engine refuses stays on the screen, marked "Not saved", with its reason, and a video does not start until it is fixed.
- **Added to the document:** captions per scene (checked like any other words) and how a scene starts (cut, fade, slide). Added looks: night, sage, pulse. A film's poster is the first scene with everything on screen, because its first frame can be black.
- **The layout follows the room the editor has, not the window** (a container query), because the desktop's sidebar stays beside it.
- **Checked for real** (`apps/desktop/scripts/ui-audit.sh light motion-editor`, the desktop's window code on Vite in Chromium with the real engine, player and sandbox, on a throwaway data folder): a new project, three scenes edited, a look, captions, a slide, play across a scene boundary with the selection following, Undo and Redo, axe with no violations, the smallest window (720 x 520) with no sideways scroll, and a real 15 s video that passed the word check, its frames looked at. In WebKit (the small test program of the spike, under the window's rules plus `frame-src`): the same page loads and seeks and looks the same, with the shipped font.
- **On the web:** `apps/web/e2e/motion-editor.spec.ts` runs the shared screen through the BFF's addresses at desktop and phone sizes with axe, against a mocked engine. The worker's `builder.kit` is tested on a stand-in.
- **Not checked:** the packaged Tauri window itself, the web on a running stack, and a keyboard-only walk by a person. The owner's run in the real window is this stage's last gate.

**MX3, 2026-10-31: the assistant in the editor.**

- The right column has two tabs, Assistant and Scene, and the chat stays alive under the other tab. The shared `ChatScreen` gained what a docked chat needs: `runInput`, `beforeTurn` (the editor saves first), `onToolResult`, `onWorking`, `undoOfTool` and `firstMessage`. A project keeps its own chat (`compositions.conversation_id`, schema 4).
- **How it knows the project:** each message carries `working_on`, naming a read action (`motion.read_project`). The graph calls it before every model call, so the model sees its own changes. What it returns replaces the prompt and decides what may be proposed (`builder/editor.py`). Only `propose_action` is offered. Only a read action can be named, the project on the screen replaces whatever the model wrote, and the person owns it because the read runs as them.
- **Decision 4 as built:** a change runs without a card and is one Undo step, in the bar and on its own card in the chat. `video_builder.render` is costly and still shows a card. After outside text the taint rule still asks for everything. While the assistant works the editor's panels are inert, so a save cannot overwrite what it just did.
- **First screen:** "What do you want to promote?" with a shape, seven starting points that add to the brief, Start empty, and the five one-off graphics. The starting points only add words for now; MX7 makes them ready-made sets of scenes. **Attaching a picture to a brief waits for MX5**, with media.
- **The evaluation** (`products/wasifyai-assistant/evals`, kind `editor`, 20 cases, each change applied to a real project through the action's own input). On Qwen3 8B Q4_K_M, first answer only: 6 of 20 at first, 20 of 20 after the fixes below (the runs before the last fix gave 18 and 19, so expect some variation). The brief, the discount it must not invent, and the words that look like instructions all pass.
- **What the real runs changed:**
  - The model puts a scene's settings beside `fields`, and the scene's own settings inside it. The actions now read both, and refuse by name what is neither.
  - It rewrote the whole project to change one thing, and invented "10% off". The guide now has worked examples and a firmer rule.
  - It took a refusal for success and said "Done". A refused change now tells it plainly that nothing changed.
  - The film went back to 0:00 on every reload because the player has no event for a page it loads again, and a film that fades in showed black. The preview now asks again a few times after each load, and opens a moment in.
  - After a first version the selection fell on the last scene, so "this scene" meant the end card.
  - The word check called a big serif title cut off: redrawing large letters' edges changes up to 0.9% of them. The limit now scales with the word (a test keeps real cuts caught). This one was already there for one-off titles.
- **Checked for real** (`apps/desktop/scripts/ui-audit.sh light motion-assistant`, on the chosen model, Qwen3.8 27B MLX, in Chromium with the real engine): a brief became a first version of 4 scenes in about 25 to 40 s; "make this scene 3 seconds", a square version undone from its card, an added end card; the discount request changed nothing and asked; "make the video" showed the card, and a video was made. The clock, the player and the page agree after every change. The walk deletes what it made.
- **Not checked:** the packaged Tauri window, the web on a running stack, and languages other than English. Whether the wording is good enough for a real campaign is the owner's to say.

**MX4, 2026-10-31: arranging on the preview.**

- A scene has `arrange`: for a part (`templates.PARTS`, by kind, plus the caption), its left, top and width as percent of the picture, and a scale. A part not named stays where the template puts it, and an empty `arrange` is the design. It becomes an ordinary rule of the page (`part_selector`, `_arrange_rules`), so the check, the render and the preview all read the same thing. Scale is CSS `zoom`, which keeps the percentages; the picture measurements below show it.
- **The overlay** (`scenes/ArrangeOverlay.tsx`) is over the player, because the page is on another origin on the desktop. The page reports where its parts are and moves one during a drag, by `postMessage` from its parent only (`live.py`). That script is in the preview's page and never in what is rendered. What stays is the document, saved when the drag ends.
- Watch and Arrange above the preview. Drag a part, drag its corner to resize it (the letters grow with the box), or use the arrow keys (Shift for further, plus and minus to resize), with one Undo for a run of keys. Layouts under the scene's details (As designed, Top, Middle, Bottom) write ordinary places, so anything can still be moved.
- **The guide is the word check's margin:** 6% of the width on every side, so it is taller in percent on a wide picture. The first guide was 6% of the height, and a title inside it was refused. A part outside the guide now turns red and says so.
- The assistant can place parts too (`arrange` on `motion.change_scene`); two evaluation cases.
- **Checked for real** (`apps/desktop/scripts/ui-audit.sh light motion-arrange` on a throwaway folder, the window's code in Chromium): a title dragged and resized with the mouse, then keys. The document says x 10, y 18, width 45; the page measures the same; in the exported video the letters are at x 10.3, width 44.5, as they are on the preview. axe has no violations. `test_video_builder_templates.py` proves a placed part through the check and a render.
- **In WebKit** (the spike's small program): a placed, scaled title on a page with the editor's script loads, seeks and draws in its place. Dragging was not driven there.
- **The evaluation**, now 22 cases on Qwen3 8B: 21 of 22, first answer only. The one that failed wrote a look that does not exist; that is refused in words and the model is told to fix it.
- **Not checked:** the packaged Tauri window, touch on a real phone, and the web on a running stack.
