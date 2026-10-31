# ADR-0096: Motion graphics becomes a scene editor for promotion and social content, with the assistant built in

- **Status:** Accepted (owner, 2026-10-31: all five decisions of the plan as recommended; the mockup,
  `docs/spikes/motion-editor-mockup.html`, approved with its recommended answers the same day). Stage MX1 built 2026-10-31; see "Built".
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
- **Not built yet:** the editor screen (MX2). Until then the Motion graphics screen shows a scene project as a read-only list, and the code view shows the page.
