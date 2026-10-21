# Build plan: Video Builder's render path, then text to motion graphics (ADR-0077, ADR-0079)

**Status 2026-10-20: V1a, V1b, V1c and MG1 are built and tested (see "Progress" at the end); the chat path waits for A2 (MCP), and MG2 is not started. The owner approved the dependency table, the sandbox path (our own launch), the minimum of V2 pulled forward and Mac first, and asked for a stop after V1b.**

Written 2026-10-20. A plan, not a decision: ADR-0077 and ADR-0079 are Accepted and are not changed here. Nothing in it is built. **The roadmap's hold
(2026-10-19) on new features still applies**; this is the order of work for when the owner lifts it. Sizes are working days for one engineer with Claude
and are estimates. Evidence: `docs/spikes/video-builder-v0.md` (V0, measured on the owner's M5 Pro, 64 GB), ADR-0077 (with its V0 amendment), ADR-0079.

## The answer first: is it possible without trouble?

**Possible: yes.** V0 showed the render engine works on this Mac (a 60 s video in about 45 s, 2 to 3 GB, byte-identical output, transparent video included), and
the first motion graphics (the template path) need no model-written code.

**Without any trouble: no, and it is better to say where the trouble is now.** Everything below is additive (an experimental feature, an optional component, no
change to an existing screen or to any Accepted ADR), so the existing app cannot break because of it. The real risks are inside the new part:

| Trouble spot | Why it matters | How the plan handles it |
|---|---|---|
| **The sandbox is not solved yet** | Stock HyperFrames starts Chrome with `--no-sandbox` and no network limit; a hostile composition reached localhost and a remote host. Our locked-down launch worked, but **whether HyperFrames' own libraries let us replace their launch is unread** | V1b is the sandbox, first, before any screen. If the answer is "no", fall back to patching the launch or the OS-profile wrapper (localhost stays open) and say so in the screen text |
| **macOS Gatekeeper and the downloaded browser** | The pinned headless shell is ad-hoc signed, not notarised; with a quarantine flag it hangs silently for 8 s+ | Download without quarantine or clear it after the SHA-256 check; **test with the real Tauri app** (not verified yet) in V1a |
| **Node.js is not on the user's machine** | HyperFrames needs Node 22; the app ships a Python engine, not Node | A pinned Node as part of the component, never the user's Node |
| **Telemetry and home-folder writes** | The CLI phones npm/GitHub unless told not to and writes `~/.hyperframes` | Set `HYPERFRAMES_NO_TELEMETRY=1`, `HYPERFRAMES_SKIP_SKILLS=1`, redirect the home folder (**the redirect is untested**), and prove it with a network log in V1a |
| **Memory beside a model** | 2 to 3 GB per render fits on 64 GB; **16 and 32 GB with a model loaded is unmeasured** | Fit check (ADR-0063) before a render; honest message; measured in V1c |
| **Windows and Linux** | Nothing measured there; the CI runners are different | The component says "not available here" off the Mac until measured (ADR-0066 honest states); Mac-only tests first |
| **Fonts** | System fonts differ per machine; fonts have licences | Ship a small set of open fonts, licences read first (rule 12) |
| **Model quality for custom compositions** | Not assessed (MG0 second half) | The template path ships first; the custom path is a later stage and may stay off on small models |
| **A young dependency** | HyperFrames is weeks old, 0.8.x | Pin, wrap in `VideoBuilderEngine`, keep the Web Animations API fallback (ADR-0077) |

## Dependencies, in the order they are needed

Each is a pinned, hashed, on-request download into `<app data>/components/video-builder/`, shown with size, source and licence before the click (the existing
pattern of the audio runtime and the lip sync engine: a pins JSON, a runtime module, a setup card). **"Ask before adding a dependency" (CLAUDE.md): the owner
approves this list once, before V1a.**

| # | Dependency | Pin | Licence (as read) | Size | Notes |
|---|---|---|---|---|---|
| 1 | FFmpeg 4.4 and ffprobe 4.4.1 | npm `@ffmpeg-installer/ffmpeg` and `@ffprobe-installer/ffprobe` in the component's lock (darwin-arm64) | 24 MB | 0 | encode, the cut, transparent formats |
| 2 | Node.js 22 (pinned official build for the platform) | exact version and SHA-256 from nodejs.org's signed `SHASUMS256.txt` | MIT (**to confirm in V1a**) | **UNVERIFIED** (tens of MB) | V0 ran on Node 22.23.1 |
| 3 | Chrome headless shell for Testing | 152.0.7977.30, mac-arm64, SHA-256 `1db16c16e72bedfa747ed01c207a3fe8ee7370c35f2094279eb8878c996e8c79` (our pin from V0) | Chromium licences (BSD-style, bundled third-party notices; **read the bundle's `LICENSES` in V1a**) | 97.5 MB zip, 193 MB unpacked | no `--no-sandbox`; the installed Chrome is not offered |
| 4 | `hyperframes` 0.8.171 (+ `@hyperframes/producer` and its tree) | exact version and a lockfile with integrity hashes, installed by the pinned Node | Apache-2.0 | 134 MB `node_modules` (V0) | no postinstall network, no `npx`; tested offline |
| 5 | `gsap` 3.15.0 | vendored into each project from our copy | GSAP "Standard no charge": cleared for the free open-source desktop (owner, 2026-10-18); **re-ask before any paid or hosted version** | small | never from a CDN (the compiler downloads CDN scripts itself) |
| 6 | Open fonts (a handful) | files with hashes in the component | each font's licence (SIL OFL is typical; **read each before adding**) | a few MB | English first; Bengali and Indic later (shaping checks) |
| 7 | Motion-skills (MIT packs) | two already adapted in V0 (a lower third, a kinetic title) at commit hashes `aa8ef7e…` and `fccc94b…`; more only if MG0 shows they help | MIT, notice kept | text | stored as our own files, never fetched at run time |
| 8 | A CSV reader | the Python standard library | n/a | 0 | "chart from my CSV" is CSV only in MG1; spreadsheets (`xlsx`) only if the engine already has a reader (decide in MG1) |

**Not dependencies:** Remotion (rejected, licence), Three.js and WebGL (not in v1; untested in the sandbox), Playwright (HyperFrames uses puppeteer-core), Pinokio,
iart.ai's service, `npx skills add`.

## Stages (dependencies first)

### Step 0: owner decisions (1 hour of reading, no code)

Approve the dependency table above; choose the sandbox path (**recommended: (a) our own launch of the pinned shell**, with the OS-profile wrapper as fallback); confirm
"installed Chrome not offered"; approve the font list once licences are read; accept that off the Mac the feature shows "not available here". Defaults are in bold.

### V1a: the component (3 days)

- `video_builder_pins.json` and `video_builder_runtime.py` (like `musetalk_pins.json` and `lipsync_runtime.py`): download with progress and SHA-256, unpack, install the
  hashed npm tree with the pinned Node offline from a cached tarball set (no registry call at install), set telemetry/skills/home variables, a `status()` with plain-words reasons.
- The Tauri/engine downloads **without a quarantine flag**; test in the real app on this Mac. Setup card in **Video › Video Builder**, size and licence first.
- **Done when:** the component installs from nothing, `status()` says ready, a **network log shows zero requests outside the download hosts during install and during a
  render**, `~/.hyperframes` is untouched, and a smoke render of the V0 simple title works on this Mac. Unit tests for hash and pin failures; uninstall removes it all and says how many MB came back.

### V1b: the sandboxed render path (4 days) — the gate for everything else

- Answer the open question first (half a day): can `@hyperframes/producer` / `engine` take our browser launch and request handling? If yes: our adapter launches the pinned shell with the
  V0 "full" configuration (virtual origin `project.invalid`, request interception that serves only the project folder, proxy and resolver rules, download deny, popup closing, 2.5 s
  heartbeat with `terminateExecution`, **25 ms memory watchdog** with a limit set by the fit check, wall-time limit, process-tree kill on cancel and quit). If no: patch the launch in a pinned
  fork, or the OS-profile wrapper with localhost open, and record it in ADR-0077 as an amendment.
- **Lint step ahead of the compiler:** reject any non-local URL, any `<script src>` outside the project, any CDN import (the compiler fetches them in Node), `eval` and `new Function` in text from untrusted sources.
- **The hostile corpus lives in CI** (V0's attack pages: remote requests of six kinds, file reads, localhost, popup, download, permissions, `alert`, infinite loop, memory allocation) with
  "reaches nothing" as the assertion, run on macOS and Linux runners with the pinned shell cached. Windows is marked not-yet.
- **Done when:** every hostile case from V0 is stopped through the real adapter (not just the V0 harness), the memory attack stays under the limit plus 0.1 GB, a normal composition renders
  **byte-identically** to the unsandboxed V0 render, and the same tests run in CI.

### V1c: engine, projects, preview and the experimental screen (4 days)

- `VideoBuilderEngine` (create project, lint, preview frame, render with progress and cancel, list assets), project folders under the app data, the product package
  (`wasifyai-video-builder`) registered like other products, **one render at a time**, a fit check before a render, `video_builder.render`, `video_builder.preview_frame`, `video_builder.lint`.
- The screen (under **Video › Video Builder**, "experimental" label): a project list, a preview player, Render with progress and Cancel, "Save a copy", a read-only code view. Design tokens only (ADR-0081), plain words.
- Creations: kinds `composition` and `video` (render), with the full ADR-0041 checklist (index text, `caps.index_creation`, `unindex`, `IndexSource`, `ids=` filter, card and filter, `CreationKind`, eval corpus row), deletion that removes the project and its renders (asks first).
- Catalogue (ADR-0068): help files, `ui` pointers, `docs/contracts/actions.json`, executor tests.
- **Done when:** a template renders from the screen in the real app on this Mac, a hostile composition from the corpus fails with a plain message and nothing escapes, cancel stops within a few seconds and frees memory, memory and time are measured **with a model resident** and recorded in `desktop-profile.md`, and the library finds the render by its text.

### MG1: the template path (6 days)

- Five vetted templates with slots (text, numbers, colours, font, duration): **animated title, quote or kinetic text, chart from a CSV, lower third (transparent), captions slot** (the captions *from a recording* wait for V2; here they are typed). Vendored GSAP and shipped fonts only. Slot text goes in **verbatim** and is HTML-escaped (V0 showed injection strings do not execute).
- **Exact-text check** as V0 refined it: read the drawn text at the **hold frame** (or over sampled frames), compare with the input, and add the **pixel proof**; add the **clipped-glyph look-check** (a glyph-bounds test, then the picture-reading model of ADR-0078 as a second opinion). A failed check is shown in words, never silently fixed.
- `motion.make` (effect `make`) and `motion.revise`: the model fills slots only; **the plain-words loop**: describe, three stills and a short loop as the preview, "change it" in words, undo by version; outputs MP4, WebM alpha and ProRes 4444 where chosen (V0 verified alpha by decoding with libvpx).
- **Done when:** "lower third for Maya Chen, Head of Design" and "chart from my CSV" work from the screen **and from chat**, 20 slot cases (including long names, `& < > "` strings and Bengali ink) pass the check, a retyped name is caught, the transparent files decode with real alpha, and the evaluation rows are kept next to the assistant's.

### After MG1 (not part of "next")

- **MG0 second half** (about 20 requests with and without a skill on three model tiers) and **MG2** (model-written compositions, only through the V1b sandbox, off on small models) when the owner wants the custom path.
- **V2** (assets from the library, speech and captions with word times, music with ducking, an explainer from a script) and **V3** (assistant and agent authoring).
- **MG3** (more skills, more outputs). **Not in v1:** 3D/WebGL, Manim, a timeline editor, beat-synced cuts, a template store, the web version.

Total to the first working motion graphics: about **17 days** (V1a 3, V1b 4, V1c 4, MG1 6), plus Step 0.

## Rules these stages follow

- Each stage ends with unit tests, a real run on the owner's Mac, docs (this plan, `desktop-profile.md`, the help files), the search checklist where it creates something, and `git add` with a one-line commit message. No commits by us.
- Nothing is downloaded without a click that shows size and licence; nothing is installed without the owner's yes to the dependency table.
- The screen is always in the menu, labelled experimental (no Labs switch, owner 2026-10-21); with the component absent the feature shows one setup card and nothing else in the app changes.
- If V1b fails to find a safe path, the work stops there and the owner decides; no screen is built on an unsandboxed render.

## Questions for the owner (before V1a)

1. Approve the dependency table (Node 22, the Chrome headless shell, `hyperframes`, GSAP, a small font set)?
2. Sandbox path: our own launch of the pinned shell (recommended), with the OS-profile wrapper as the fallback?
3. Pull the minimum of V2 forward? MG1 needs the creation kinds, search and actions that the plan lists under V2; I put those in V1c, and leave speech, music and captions-from-a-recording for V2 proper.
4. Is "Mac first, other systems say 'not available here'" acceptable for this feature?

## Progress (2026-10-20): V1a and V1b done, stopping here for the owner

Measured and written up in `docs/spikes/video-builder-v1.md`; ADR-0077 has the amendment.

| Stage | State | What is true now |
|---|---|---|
| **V1a** the component | **Done** | Pins (`video_builder_pins.json`, the npm lock of 126 packages), `video_builder_runtime.py`, routes `GET /desktop/video-builder`, `POST /install` (with the size shown), `POST /uninstall`; installs from nothing in **25 s** on this Mac (288 MB downloaded, about 510 MB on disk); every hash checked; no install scripts; telemetry off; the person's home folder untouched (tested); 23 tests. **Not done from the plan:** the setup card in the window (it needs the screen, V1c); the Gatekeeper check **inside the packaged Tauri app** (the installer clears a quarantine flag if present; not tried in the app) |
| **V1b** the sandboxed render | **Done, with the answer to the open question: yes, the launch can be replaced without a fork** | A launcher named in `HYPERFRAMES_BROWSER_PATH` plus a loopback filter that forwards only to the render's own file server; guard with wall, stall and memory limits and a tree kill; lint before the compiler. With the real browser every hostile case is stopped (0 hits on the loopback canary, internet unreachable, memory attack killed in 1.2 s, hangs killed at the stall limit), a normal render is **byte-identical** to the unsandboxed one, and the corpus is proved to bite (the stock launch is hit). 11 hostile tests plus 33 unit tests, a CI job on macOS (`video-builder` in `desktop.yml`, not yet run on GitHub) |
| **V1c** | **Done 2026-10-20** | Engine, projects, preview and the experimental screen, the creation kinds with the search checklist, the actions, the setup card: see `docs/spikes/video-builder-v1.md` ("V1c") and the ADR-0077 amendment. One template (an animated title); a 5 s 720p title renders in 7 to 9 s. It lives inside the video product, not in a package of its own |
| **MG1b** | **Done 2026-10-21** | The prompt box (plain words fill the form, a CSV is read by the app), lengths 3 to 90 seconds (30, 60, 90 on the screen), real renders at 90 s measured (14 to 33 s, 2.0 to 2.3 GB), the draft tried on two real local models (11 and 10 of 12). ADR-0079 amendment, spike doc "MG1b" |
| **MG1** | **Done 2026-10-20** (screen, actions and engine; "from chat" needs A2) | Five templates with slots, two shipped open fonts (Inter and Source Serif 4, OFL, from the lock), the exact-text check run in the sandboxed browser before anything is drawn, `motion.make` and `motion.revise`, a version for every change with Undo, MP4, WebM alpha and ProRes 4444 files. Real run on this Mac: all five templates 7 to 10 s each, tree peak 2.2 to 2.3 GB, "lower third for Maya Chen" and a chart from CSV lines made, a retyped name refused with "The screen says “Maya Chan” but you wrote “Maya Chen”". 20 slot cases pass the check; WebM and MOV decode with real alpha. See `docs/spikes/video-builder-v1.md` ("MG1"), ADR-0079 amendment |

**Corrections to this plan found while building:** the component is 288 MB to download (the table said 97.5 MB for the browser alone, 134 MB for the
packages, and an unknown for Node: Node is 50 MB); **one LGPL package (libvips inside sharp) is in the tree**, used as shipped (rule 12, to be confirmed by counsel);
the browser's `--proxy-pac-url` does not work, so the filter is a proxy, not a PAC file; HyperFrames serves the page from a random port, so the filter
learns that port from the first request instead of being told it.
