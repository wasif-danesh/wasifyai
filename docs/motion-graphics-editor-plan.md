# Plan: Motion graphics becomes a scene editor for promotion and social content

**Status:** approved by the owner 2026-10-31 (all five decisions as recommended; the mockup, `docs/spikes/motion-editor-mockup.html`,
with its recommended answers); ADR-0096. MX0 to MX4 are done (MX0: `docs/spikes/motion-editor-mx0.md`; the others: "Built" in the ADR). MX5 is next.
Sizes are working days of one engineer with Claude, and they are estimates.

**Asked by:** the owner, 2026-10-31: bring KinoFold's features (`~/Projects/kinofold`, also built on HyperFrames) into Motion graphics,
similar to the planned Creative Studio, for product promotion, social media and marketing content, with the chat assistant built in.

## The answer first

- **The features fit.** KinoFold and our Motion graphics draw video the same way: HTML scenes with a seekable GSAP timeline, rendered
  by HyperFrames. So KinoFold's project format and render output are a close match.
- **The code does not carry over.** KinoFold is Rust and plain JavaScript. Ours is a Python engine and shared React screens, on the
  desktop and the web. The design, the document's shape and the behaviour move across; the code is rewritten.
- **Today a project here is one template filled with words.** The main change is that a project becomes a list of scenes, on an editor
  screen with a live preview.
- **Our sandbox, exact-text check, Library, search, actions and web workers stay.** KinoFold has none of these, so they are what we
  add to its idea.
- **Build this before Creative Studio.** It has no model-quality risk, and it builds the screen frame Creative Studio needs.

## What KinoFold has, and what we do with it

KinoFold's roadmap marks stages 1 to 7 as checked in the real Mac app. The items marked "not accepted" below are built there but their
real-app check is still pending, so they prove less.

| Feature in KinoFold | Motion graphics today | What we do |
|---|---|---|
| Project of ordered scenes, with a versioned document | One template and its fields per project | **New:** a scene document (MX1) |
| The screen: tools left, preview middle, scene details right, story strip and soundtrack row below | One form and a preview | **New:** the same four regions, in our design tokens (MX2) |
| Live preview with play and seek on the real composition | One PNG at a chosen second, made in the sandbox | **New, and the main technical unknown** (MX0, MX2) |
| Grouped undo and redo, autosave, a truthful "Saved" | Undo by saved version (20 kept) | **New** grouped undo on the screen; versions stay (MX2) |
| Add, duplicate, remove, reorder scenes; duration; total length | None | **New** (MX2) |
| Looks (6), transitions (none, fade, slide), text position | Themes (4) | **Merge** the looks and themes (MX2) |
| Layouts (3), drag and resize text and pictures on the preview, arrow-key nudges (not accepted) | None | **New** (MX4) |
| Captions and extra text per scene (typed) | Captions as a separate template | **Move** into every scene (MX2); from speech in MX6 |
| Photo or video as background or placed on the scene, fit and position (fit not accepted) | No media in a composition | **New**, from the Library or an upload (MX5) |
| Video trim and its own sound (not accepted) | None | **New** (MX5) |
| Sound per scene; one soundtrack with volume, start, loop | None | **New** (MX5) |
| Capture a scene as a picture | A still preview exists | **Small:** save the still to the Library (MX5) |
| Export: Draft, High, Best, with progress and cancel; H.264 check on import | MP4, WebM, MOV with progress and cancel; no quality choice | **Add** the quality choice and the codec check (MX5) |

**Not taken:**
- The Pip character and lip sync, which KinoFold itself removed. Our Lip sync stays its own tool.
- The HyperFrames Studio skin.
- The save journal and HTML hash checks: our document lives in the store, and the HTML is always regenerated from it.
- The starter migration and the App Store scripts.

**What we keep and KinoFold lacks:**
- The render sandbox (ADR-0077).
- The exact-text check (ADR-0079).
- Library, search, actions and MCP.
- The web on engine workers.
- WebM and ProRes with transparency.

## What marketing needs beyond KinoFold

KinoFold has no assistant, no way to generate media and no idea of a brand. These make it a marketing tool:

- **The assistant builds and edits the project** (next section).
- **Make from inside the editor.** Image, Video, Speech and Music tabs use the products we already have, and the result lands in the
  project. This is the Make panel of ADR-0090's amendment.
- **A brand kit:** logo, colours, fonts, and an end card with a call to action. Set once and used in every project.
- **Shapes for each channel.** We have landscape, portrait and square; add **4:5**. One project exports to several shapes at once.
- **1080p.** Our templates render landscape and portrait at 720p; KinoFold renders 1920 x 1080. Social needs 1080p, and its time and
  memory must be measured.
- **Marketing starting points:** product promo, launch announcement, sale or offer, testimonial, feature explainer, before and after,
  social post. Each is a set of scenes in the same document, so it stays fully editable.
- **Word-timed captions and voiceover**, from our speech products.

## The assistant in the editor

- **A chat panel docked in the screen**, on the same thread components as the assistant and the notebook chat (`useThreadChat` already
  sends extra run input, so the project and the selected scene go with each message).
- **From a brief to a project:** "a 20 second vertical ad for this product photo, for Instagram" becomes scenes, with words the model
  wrote and the look chosen. The person sees the scenes and edits them.
- **Editing in words:** "shorten scene 2", "use our brand colours", "add a call to action at the end", "make a version for TikTok".
- **The model can look.** Qwen3.5-9B reads pictures, so it can see a product photo or a frame of the scene it just changed.
- **How it edits:** through actions on the document (ADR-0068), the same ones the screen uses, so MCP gets them too.
- **Each change the assistant makes is one Undo step.** Making media or rendering shows its cost first and follows "Ask me before".
- **The words rule holds.** Words the person typed are never rewritten without being asked. Words the model wrote are ordinary scene
  text the person can see and change, and the exact-text check compares against whatever the document says.
- **Measured, not assumed.** The evaluation gets rows for this. Whether 9B can plan scenes reliably is checked in MX3; if it can't,
  starting points filled in by the model are the fallback.

## How it relates to Creative Studio (ADR-0090)

| | Motion graphics (this plan) | Creative Studio |
|---|---|---|
| Made from | Words, product pictures, a brand | A song or a story |
| A project is | Scenes the person arranges | A plan of shots cut to the music |
| Pictures come from | The person's media first; generated when asked | Generated for every shot |
| Depends on model quality | Little | Heavily; CS0 measures whether it is good enough |

- **Shared parts:** the screen frame (`EditorFrame`), the media rail, the Make panel and the docked assistant go in `packages/ui`, and
  Creative Studio uses them when it starts. Its stages CS1 to CS3 get smaller; the size is worked out then.
- **Its own parts:** the plan, the song analysis and the cuts on the beat stay Creative Studio's.
- **ADR-0090 changes** by a short amendment naming the shared parts. CS0 still waits for the owner.

## Stages

Each stage ends with tests, a real run on the owner's Mac, docs, help files, `docs/contracts/actions.json` where actions change, and
`git add` with a one-line commit message.

| Stage | What | Days | Done when |
|---|---|---|---|
| **MX0** | **A mockup and a spike; no product code.** The mockup is for the owner's approval. The spike answers the four unknowns below. | 4 | The owner approves the mockup; the four answers are in `docs/spikes/` with numbers |
| **MX1** | **The scene document.** Store schema, Python generator from document to HTML, per-scene exact-text check, actions on scenes. The five templates become scene kinds; existing projects open as one scene and look the same. Search indexes every scene's words. | 5 | A three-scene project renders through the sandbox from an action, on both stores; old projects unchanged |
| **MX2** | **The editor screen.** Four regions, scene strip, scene details, live preview with play and seek, looks, transitions, typed captions, grouped undo, autosave. Keyboard and phone layout. Same screen on the desktop and the web. | 6 | The owner makes and exports a words-only video in the real window; axe passes |
| **MX3** | **The assistant.** Docked chat, project and selected scene in context, brief to scenes, edits in words, one Undo per change, evaluation rows. | 5 | A brief becomes an editable project; the evaluation shows how often 9B gets it right |
| **MX4** | **Arrange.** Drag and resize on the preview, layouts, arrow keys. | 3 | What is placed in the preview lands in the same place in the export |
| **MX5** | **Media and sound.** Library or upload; background and placed pictures; fit; video trim and sound; scene sound; soundtrack; capture; quality choice; object storage on the web. Assistant actions grow to match. | 6 | Export has the footage and non-silent sound, on the desktop and on a web worker |
| **MX6** | **Make panel.** Image, Video, Speech and Music tabs in a panel layout; voiceover; captions with word times from speech. | 4 | A generated picture and a voiceover land in a scene without leaving the screen |
| **MX7** | **Marketing pack.** Brand kit, the starting points, 4:5, 1080p, several shapes from one project, the end card. | 5 | One project exports vertical, square and landscape with the brand applied |

**Total: about 38 days.** MX0 to MX3 (20 days) gives a words-only editor with the assistant, which is usable on its own.

### What MX0 found (`docs/spikes/motion-editor-mx0.md`)

1. **Live preview works without a server process.** The player in the pinned package plays plain files in Chromium and in WebKit. The
   window's content rules need `frame-src http://127.0.0.1:*`, and the route needs a signed token in its path and byte ranges.
2. **Media works through the sandbox unchanged:** pictures, trimmed H.264, HEVC, scene sound, clip sound and a soundtrack.
3. **60 s at 1080p with footage: 48 s, 4.74 GB, 46 MB.** Faster than real time. The stated need of 3 GB goes up to 5.
4. **No HyperFrames upgrade** is needed.

## Rules this follows

- **Rule 6:** rendering stays a job; the preview does no GPU work.
- **Safety of the live preview:** the document only holds data, the HTML comes from our generator with text escaped, and model-written
  HTML stays out of the editor (MG2 is not part of this).
- **ADR-0041:** the composition kind is already searchable; the index text grows to all scenes.
- **ADR-0068:** every new thing a person can do is an action with a help file.
- **ADR-0094:** no consent gates or marks are added.
- **v1 is English only**, and nothing in the document assumes English. The shipped fonts cover Latin only today, which MX7 notes.
- **Not in this plan:** model-written compositions (MG2), a full multi-track timeline, scheduling or posting to social networks, and
  analytics.

## Decisions (owner, 2026-10-31: all as recommended)

| # | Question | Recommended |
|---|---|---|
| 1 | Motion graphics becomes the scene editor, under a new ADR (ADR-0096) that amends ADR-0077 and ADR-0079? | Yes |
| 2 | Build this before Creative Studio, sharing the screen frame? | Yes |
| 3 | The desktop and the web together at each stage, or desktop first? | Together: Motion graphics is live on both today and the screen is shared; only MX5's storage is extra work on the web |
| 4 | Assistant edits apply straight away with Undo, or ask each time? | Straight away with Undo; costly work asks first |
| 5 | Keep the name "Motion graphics" now that it makes whole promos? | Keep it until the build works, then decide |
