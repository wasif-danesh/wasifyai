# ADR-0077: Video Builder (experimental): videos written as code, rendered deterministically

- **Status:** Accepted (2026-10-18, by the owner), together with the components it names. Labelled **experimental** in the app. **Renamed from "Compose" to "Video Builder" on 2026-10-18** (working name, chosen by the
  owner; "Compose" clashed with Compose Multiplatform and `docker compose`). Action names are `video_builder.*`.
- **Date:** 2026-10-18
- **Depends on:** ADR-0068 (action catalogue), ADR-0069 (our MCP server), ADR-0072 (the agent), ADR-0066 (speech,
  music, transcripts), ADR-0059 and ADR-0037 (images and generated video), ADR-0041 (searchable), ADR-0047, ADR-0061
  (how outside code enters).
- **Plan:** `docs/phase5-agent-training-video-builder-plan.md`, stages V0 to V3.

## Context

The owner wants "something like HyperFrames (experimental)". **HyperFrames** (HeyGen, Apache-2.0, read 2026-10-18)
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
- **GSAP licence.** HyperFrames' animations use GSAP. GSAP's "Standard No Charge" licence (Webflow, read 2026-10-18)
  allows commercial use but **forbids tools that let people build visual animations without code and help build a
  Webflow competitor**, and one copy says that if **end users are charged a fee** a paid "Business" membership is
  required. A video-composition product is near enough to be read both ways; it needs an actual licence decision,
  not an assumption. An alternative that avoids GSAP exists in principle (the Web Animations API, CSS animations,
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
   because a deterministic browser-to-MP4 renderer is hard to get right and the project is Apache-2.0 and
   agent-oriented. Adopting is gated on: the GSAP licence read (decision 8), a measured render speed (V0), and a
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
8. **Licence work before code (a gate, not a footnote).** Read the GSAP Standard No Charge licence as it stands,
   decide whether Video Builder is a "Prohibited Use" and whether a paid Business membership is needed if the app ever
   charges, and ask GSAP (it invites the question). If the answer is no or unclear, Video Builder ships on the Web
   Animations API or Anime.js and the HyperFrames conventions are followed only where they do not require GSAP.
   Likewise check the licences of the browser build, Node.js, fonts and any template asset (rule 12).
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
- The licence gate may change the engine. That is why it comes before code.

## Alternatives considered

- **Build our own renderer in Rust on the system webview.** The shell's webview cannot be driven frame by frame
  deterministically as far as we know (not tested); worth one spike (V0) before we rule it out, since it would
  remove the Chrome download. Not v1.
- **Remotion** (React-based; its licence is source-available with terms that depend on the size of the company, to
  be read before any use). Not adopted: React-only authoring and a licence we have not cleared.
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
4. Fonts: shipping a small set of open fonts (licences checked) so renders look the same on every machine.
5. The web deployment: rendering arbitrary code in a server needs a real sandbox; desktop only in v1.

## Not in v1

A visual timeline editor; live collaboration; rendering in the cloud; importing compositions from the web;
embedding third-party scripts; audio recording in the composition; the web deployment.

## Owner's answers (2026-10-18)

- **The desktop app will be open source and free**, so the **GSAP gate (decision 8) is cleared for the desktop**:
  no one is charged for it. It is not a free pass for everything: GSAP's terms (read earlier) bar using it to build a
  tool that competes with Webflow's visual animation builders, which Video Builder is not, and a **paid or hosted web
  version of Video Builder would need the question asked again**. The Web Animations API fallback stays as the plan B.

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
