# ADR-0077: Video Builder (experimental): videos written as code, rendered deterministically

- **Status:** Accepted (2026-10-18, by the owner), together with the components it names. Labelled **experimental** in the app. **Renamed from "Compose" to "Video Builder" on 2026-10-18** (working name, chosen by the
  owner; "Compose" clashed with Compose Multiplatform and `docker compose`). Action names are `video_builder.*`.
- **Superseded in part:** by ADR-0096 (2026-10-31): the visual editor in "Not in v1" is now planned.
- **Date:** 2026-10-18
- **Depends on:** ADR-0068 (action catalogue), ADR-0069 (our MCP server), ADR-0072 (the agent), ADR-0066 (speech,
  music, transcripts), ADR-0059 and ADR-0037 (images and generated video), ADR-0041 (searchable), ADR-0047, ADR-0061
  (how outside code enters).
- **Plan:** `docs/phase5-agent-training-video-builder-plan.md`, stages V0 to V3.

## Context

The owner wants "something like HyperFrames (experimental)". **HyperFrames** (HeyGen, read 2026-10-18)
renders **HTML, CSS, media and seekable animations into deterministic MP4**: a composition is a plain HTML file
(a root with `data-composition-id`, `data-width`, `data-height`; clips with `data-start`, `data-duration`,
`data-track-index`; animations as GSAP timelines on `window.__timelines`), the renderer seeks each frame in
headless Chrome and encodes with FFmpeg, so the same input gives the same file. It ships a CLI (`init`,
`preview`, `render`, `lint`), a browser Studio ("available, evolving"), and **21 skills** that teach coding agents
the loop plan, write HTML, add animation and media, lint, preview, render. It needs Node.js 22 and FFmpeg.

Why it fits this app: **the hard part of "make me a video" is not generating pixels, it is composing**: scenes,
text, timing, a voiceover that fits, captions, music under speech, images, a logo, a layout that works. The app
already makes the ingredients (speech, transcripts with word times, music, images, short clips, ADR-0066 and
ADR-0059, ADR-0037), and the agent (ADR-0072) can write HTML well. A generated clip model makes five-second
shots; a composition makes a 60-second explainer with a script, a voice, captions and charts, in a repeatable way.

Constraints that matter:

- **Compositions are code.** HTML and JavaScript written by a model, or taken from the web, run in a browser
  engine. That is an execution risk, unlike every other creation in the app.
- **Dependencies.** A headless Chrome (a large download), Node.js 22, FFmpeg (the app already ships one through
  `imageio-ffmpeg`). The desktop app is a Tauri shell with a Python engine; neither provides Chrome or Node.
- **GSAP.** HyperFrames' animations use GSAP. An alternative that avoids GSAP exists in principle (the Web Animations API, CSS animations,
  Anime.js), at the cost of leaving HyperFrames' conventions.
- **No GPU needed to render**, but CPU time is real: Chrome per frame plus encoding. Speed on a Mac is unmeasured.

## Decision

1. **A new product, `Video Builder`, marked experimental.** A "Video Builder" screen (under Video in the menu, behind a
   Labs switch in Settings) with: projects (a folder per composition), a **preview** player, a **Render** button
   with progress, an **asset panel** that inserts things from the library (pictures, speech, music, transcripts,
   clips), and a code view (read-only at first, editable later). The person can also say what they want and let
   the **assistant or the agent write it** (decision 5).
2. **Adopt HyperFrames as the render engine for v1; do not build our own renderer yet.** The seam is an interface
   `VideoBuilderEngine` (create project, lint, preview, render, list assets) so another engine can replace it. We adopt
   because a deterministic browser-to-MP4 renderer is hard to get right and the project is
   agent-oriented. Adopting is gated on: a measured render speed (V0), and a
   headless browser that is safe to ship (decision 4). If the gate fails, the fallback is our own engine on the
   same composition idea with the Web Animations API, which is a larger project and a new ADR.
3. **Installed as a managed component on request, like ComfyUI and the notebooks' reader:** the size, source and
   versions are shown first; the pinned HyperFrames package and Node.js runtime go to
   `<app data>/components/video-builder/`, the browser as a pinned **Chrome for Testing** build (or the person's
   installed Chrome if they choose, with a version check). FFmpeg is the app's own. No component is installed
   without a click, and none is needed by the rest of the app.
4. **A composition is rendered in a sandbox, because it is code.** The renderer runs with: a **fresh browser
   profile**, no extensions, **network requests blocked except to the project's own files and a local asset
   server** (request interception; no `fetch` or `<script src>` to other hosts; fonts and libraries are vendored
   into the project), file access limited to the project and the app's asset folder, a CPU and memory ceiling, a
   wall-time limit per render, no downloads, no permissions prompts, and the process killed on cancel or quit.
   Rendering a composition **from an untrusted source** (imported, or written by an agent that has read web
   pages: the taint rule of ADR-0070) shows a notice and requires a click. A composition cannot call the engine's
   API: assets are copied into the project first.
5. **Authoring by the assistant and the agent through the same catalogue.** New actions (ADR-0068): `video_builder.create`
   (from a template and a script), `video_builder.add_asset`, `video_builder.lint`, `video_builder.preview_frame` (returns a still so
   a model can look), `video_builder.render`. Our MCP server (ADR-0069) exposes them, so Claude Code or Hermes
   (ADR-0072) can write the HTML with HyperFrames' skills **and** use our speech, music and image actions for the
   assets, with our approvals. The HyperFrames skills are not copied into the app as-is: they are read, reviewed
   and adapted (they refer to tools we do not ship), and shipped as our own help files and a generated skill for
   Claude Code (ADR-0069, M3).
6. **Audio is ours.** The voiceover is `speech.speak` (a model and voice the person picks), **captions come from
   transcription with word times** (`speech.transcribe`), the music bed from `music.generate` or the library,
   with ducking under speech and loudness normalisation by FFmpeg. A composition declares tracks; the renderer
   mixes them. A script goes through the safeguards as any speech does (ADR-0066).
7. **Templates, not a blank page.** v1 ships five: **Explainer** (title, scenes of text and picture, voiceover,
   captions), **Slides to video** (a document or a notebook summary), **Report video** (a report from the agent
   with charts), **Social vertical** (9:16 captions), **Lyric or caption video**. A template is a HyperFrames
   project with slots our actions fill.
8. **Fallback without GSAP.** If GSAP does not work out, Video Builder ships on the Web Animations API or Anime.js
   and the HyperFrames conventions are followed only where they do not require GSAP.
9. **Outputs are creations (ADR-0041).** A composition (project folder, kind `composition`) and its renders (kind
   `video`, with a link to the composition and the render settings) are in My creations, searchable by their text
   (script, scene text, captions). A render records its determinism inputs (project hash, engine versions) so the
   same file can be reproduced.
10. **Experimental means:** behind a Labs switch, a banner on the screen, no promise of compatibility between
    versions of the composition format, and render defaults chosen for safety (720p30, a 10-minute ceiling) with
    1080p optional.

## Consequences

- The app gains a way to make **long, structured videos** that its video models cannot, and the agent gains a
  strong output ("turn this report into a two-minute video").
- A new component stack (Node, a browser, a render engine) and a new kind of risk (running composed code); the
  sandbox is the product's responsibility, not an afterthought.
- Depends on an external project that is young; pinned, wrapped and replaceable.

## Alternatives considered

- **Build our own renderer in Rust on the system webview.** The shell's webview cannot be driven frame by frame
  deterministically as far as we know (not tested); worth one spike (V0) before we rule it out, since it would
  remove the Chrome download. Not v1.
- **Remotion** (React-based). Not adopted: React-only authoring.
- **FFmpeg filter graphs and Python (MoviePy)** for compositing. Fine for slideshows; no HTML layout, charts,
  or animation timelines. Kept for simple slideshow renders if the engine is unavailable.
- **Generate everything with video models.** They make seconds of footage, not a script-driven video with text and
  charts; they remain a source of clips inside a composition.
- **Skip Video Builder.** An option; it is the owner's experiment and is cheap to try behind a switch.

## Open questions

1. Render speed and memory on a Mac for 720p30 and 1080p30 (spike V0), and whether the render can run while
   a model is resident (it competes for CPU and memory, not the model slot).
2. Whether the Tauri webview (WKWebView) can render a composition frame by frame with the same determinism: if yes,
   the Chrome component can be dropped.
3. Which HyperFrames features we need beyond the renderer (its Studio, its skills, its catalogue) versus our own
   screen.
4. Fonts: shipping a small set of open fonts so renders look the same on every machine.
5. The web deployment: rendering arbitrary code in a server needs a real sandbox; desktop only in v1.

## Not in v1

A visual timeline editor; live collaboration; rendering in the cloud; importing compositions from the web;
embedding third-party scripts; audio recording in the composition; the web deployment.

## Amendment after spike V0 (2026-10-19; `docs/spikes/video-builder-v0.md`)

Measured on the owner's M5 Pro, 64 GB, while other spikes ran (times are pessimistic). Verdict: **V1 Go, with its first
milestone changed to the sandboxed render path.**

- **Speed and determinism:** a 10 s title renders in 6.6 to 8.8 s warm (12.7 s cold), a 60 s composition in 41 to 49 s
  at 720p30 (2 to 3 GB) and 58 s at 1080p30; MP4 12 to 25 MB. The same input gave a **byte-identical MP4** across runs,
  worker counts, Chrome 152 and 155, and with or without network (one machine only).
- **A stock HyperFrames render is not sandboxed** (decision 4 is therefore a build task, not a setting): it starts Chrome
  with `--no-sandbox`, popups allowed and no network limit, and a hostile composition rendered through the real CLI
  reached localhost and a remote host. A locked-down launch (fresh profile, request interception allowing only the
  project, no downloads or prompts) stopped remote access, file reads, localhost, downloads, prompts and an infinite loop;
  **memory exhaustion needs a 25 ms watchdog** (about 0.1 GB overshoot at a 1 GB limit). **V1 must start with our own
  launch** (or an OS-profile wrapper, which leaves localhost open), vendor GSAP and fonts, **reject non-local URLs at
  lint time** (the compiler fetches CDN scripts in Node), run the watchdog and `terminateExecution`, and keep the hostile
  corpus in CI. The managed component must set `HYPERFRAMES_NO_TELEMETRY=1` and `HYPERFRAMES_SKIP_SKILLS=1` and redirect
  `~/.hyperframes`.
- **Browser (decision 3):** the pinned **headless shell 152.0.7977.30** (97.5 MB download, 193 MB unpacked) is ad-hoc
  signed, not notarised, and macOS **quarantine blocks it**: download without the quarantine flag or clear it after the
  hash check. The installed Chrome works but is 4 GB with an uncontrolled version.
- **WKWebView (open question 2):** it seeks a GSAP composition deterministically (1,800 frames, identical on three
  runs, 43 fps), so a Chrome component is not strictly required on a Mac; verified for GSAP and CSS only (video, audio,
  fonts, WebGL untested; not Chrome-identical). A possible later alternative, not a V1 dependency.
- **Transparent video:** HyperFrames itself writes WebM VP9 with alpha and ProRes 4444 (decode with libvpx; the default
  decoder drops the alpha). Fonts must be shipped with templates: system fonts differ per machine.
- **Not measured:** another Mac or 16 and 32 GB with a model resident, Docker, Windows and Linux, audio and video inputs,
  4K, HyperFrames Studio, CPU-time limits, WebRTC and service-worker escapes.

## Amendment after V1a and V1b (2026-10-20; `docs/spikes/video-builder-v1.md`)

The component and the sandboxed render path are built (engine side only; no screen, no render route yet: that is V1c).

- **Decision 4 is met without forking HyperFrames.** The V0 open question ("can the producer's launch be replaced?") is answered: HyperFrames
  starts the file named by `HYPERFRAMES_BROWSER_PATH`, so a **launcher script** drops the weakening flags (`--no-sandbox`, popup blocking off) and adds the
  lock-down, and **refuses to start without a network filter**. The filter is a loopback proxy that forwards to one place, the render's own file server
  (the first loopback port the browser asks for, which a composition cannot choose); everything else is closed and counted. A guard kills the whole process
  tree on a wall-time limit, a stall limit, a memory limit or a cancel. With the real browser, every hostile case of V0 is stopped, a service on loopback hears
  nothing (the localhost gap V0 left open is closed), and a normal render is byte-identical to the unsandboxed one. The OS-profile wrapper (option b) is not needed.
- **Decision 3 (a managed component):** `<app data>/components/video-builder/` holds a pinned Node.js 22.23.1 (50 MB download), the pinned Chrome headless shell
  152.0.7977.30 (97.5 MB) and the 126 npm packages of a lock with integrity hashes (`hyperframes` 0.8.171, `gsap` 3.15.0; no install scripts). The person sees
  **288 MB** before the click; about 510 MB is used after. Telemetry and the skills download are off, the environment starts empty, `HOME` is inside the component.
  The installed Chrome is not offered (owner, 2026-10-20: the plan's default).
- **Decision 8 (GSAP):** GSAP is vendored into each project from the component's copy, never from a CDN, and the lint refuses any non-local URL before
  HyperFrames' compiler (which downloads CDN scripts in Node) sees it.
- **Still open for V1c and later:** the memory limit from the fit check; a quarantine flag inside the packaged app; WebRTC and service-worker escapes; Windows and Linux; a model
  resident on small Macs. The browser's popup stays open until the render ends (behind the filter).

## Amendment after V1c (2026-10-20; `docs/spikes/video-builder-v1.md`, `docs/desktop-profile.md`)

The engine, the projects and the experimental screen are built; the first working Video Builder is one template (an animated title).

- **Where it lives:** not a separate product package. It is a part of the **video product** (`products/wasifyai-video/wasifyai_video/builder/`), because what it makes
  are videos: a render is a clip of Your videos (`mode = "composition"`), so listing, saving a copy, deleting and search needed nothing new. A project is its own
  library kind, `composition`. A separate package can be split off later without changing the routes or the actions.
- **One render at a time, a fit check first** (ADR-0063: a render needs about 3 GB; `too_big` refuses before anything starts), run through the sandbox of V1b, with
  progress, a cancel that kills the whole tree, and a plain sentence for every way it can end. A render left running when the app closes is marked failed at the next start.
- **The words are exact by construction (ADR-0079 decision 7, template path):** the title and the line go into the page as escaped text, never as markup and never inside
  the script (a test parses the page with every hostile string and compares the title's text with what was typed). The page reads no clock and loads nothing from outside.
- **ADR-0041 checklist:** index text (title and line), indexed on create, on change and rename, removed on delete (and its clips with it), one index source for clips and
  compositions, an `ids=` filter on the list route, `composition` in `CreationKind` and the library kinds, a row in the search corpus (not run: it needs the stack).
  **Not built:** a card and a filter in the web `/creations` page, because the feature is desktop only and the desktop has no creations page yet.
- **Deletion** (the library action always asks): stops a render in progress, deletes the clips made from the project (files, rows, search), its folder and its row.
- **Measured on the owner's Mac (M5 Pro, 64 GB):** setup 25 s; a 5 s 720p title previews in 4.3 s and renders in 7 to 9 s at about 2.3 GB; 12 s at 1080x1080 renders in
  8 s; the numbers did not change with a 14 GB process holding memory beside it (64 GB is not a small Mac: 16 and 32 GB are still unmeasured).
- **Not in V1c:** the moderation of slot text when safeguards are on (decision 9 of ADR-0079), shipped fonts and the other four templates (MG1), the `preview_frame` action
  (MG1), the web, and the check of macOS quarantine inside the packaged app.

## Amendment: no Labs switch (2026-10-21, owner)

Decision 10's "behind a Labs switch" is withdrawn for Video Builder (and so for Motion graphics in ADR-0079). **Video › Video Builder**
is always in the desktop menu; the screen keeps its "experimental" label and nothing is released before the owner's own testing. The
key `wasifyai.labs.video-builder` is no longer read.

## Amendment: Motion graphics is its own menu item (2026-10-24, owner)

The screen is not a video model, so it no longer sits under Video. The side menu shows one item, **Motion graphics**
(id `motion`), after Music and before Library, Models and Train. Action ids (`video_builder.*`, `motion.*`), the route
(`/video/builder`) and the engine are unchanged; only the menu item and the screen's name changed.
