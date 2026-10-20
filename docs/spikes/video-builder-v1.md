# Video Builder V1a and V1b: the component and the sandboxed render (ADR-0077)

Date: 2026-10-20, the owner's MacBook Pro (Apple M5 Pro, 64 GB). Built and measured in one session; the plan is
`docs/motion-graphics-build-plan.md`. Scratch work (outside the repo): `~/Projects/wasifyai-spikes/v1b/`, 574 MB
(the installed component for the real tests, the first launcher experiments, renders). It can be deleted;
nothing in the repo depends on it. The owner approved the dependency list on 2026-10-20.

## Answer in one paragraph

**The open question of V0 is answered: yes, HyperFrames' own launch can be replaced without forking it.** HyperFrames starts
whatever file `HYPERFRAMES_BROWSER_PATH` (or `PRODUCER_HEADLESS_SHELL_PATH`) names, so we name a small launcher script
that removes `--no-sandbox` and the other weakening flags and adds a lock-down, and that **refuses to start without a
network filter**. The filter is a proxy on loopback that forwards to exactly one place, the render's own file server.
Through the real adapter, every hostile page of V0 now fails: a service on loopback heard **nothing**, the internet was
unreachable, a popup and a download got nowhere, permissions were denied, and a page that hangs, shows an `alert` or
eats memory is **killed with its whole process tree** (the hang in 26 s on a 25 s stall limit, the memory attack in 1.2 s
at a 3 GB limit with a 0.66 GB overshoot). A normal render through the sandbox is **byte-identical** to the unsandboxed
one. The component installs from nothing in 25 s on this Mac. 62 tests plus 5 route tests, a CI job on macOS.

## V1a: the component

| Part | Pin | Download | On disk | Licence |
|---|---|---|---|---|
| Node.js | 22.23.1, SHA-256 from nodejs.org's `SHASUMS256.txt` | 50.1 MB | 187 MB | MIT |
| Chrome headless shell | 152.0.7977.30 (our V0 pin) | 97.5 MB | 193 MB | Chromium (BSD-3-Clause, bundled notices in `LICENSE.headless_shell`) |
| npm packages | `hyperframes` 0.8.171 and `gsap` 3.15.0, 126 packages, `package-lock.json` pinned by SHA-256, integrity hashes on all, `npm ci --ignore-scripts` | about 40 MB fetched | 128 MB | Apache-2.0 (20), MIT (81), ISC, BSD, CC0, 0BSD, GSAP "Standard no charge" (cleared for the free desktop), **LGPL-3.0-or-later (libvips inside sharp: one prebuilt library used as shipped, not modified; keep its notice)** |
| **Total** | | **288 MB shown before the click** | **about 510 MB after install** (npm's cache is removed) | |

- Files: `services/api/src/wasifyai_api/video_builder_pins.json`, `video_builder/package.json` and `package-lock.json`,
  `video_builder_runtime.py` (pins, `find_install`, `render_env`, the installer, `uninstall`), `desktop_video_builder.py`
  (`GET /desktop/video-builder`, `POST /install` with the size that was shown, `POST /uninstall`). It follows the pattern of the audio
  runtime and the lip sync engine: nothing is fetched before the person has seen the size and confirmed it; `state.json` is written last.
- **Everything is checked:** every download against its size and SHA-256 (a mismatch keeps nothing), zip entries against paths that
  leave their folder, the lock against its pin; packages install with **no install scripts** (only `esbuild` has one, and it only
  validates a binary). The browser is downloaded by the engine (no quarantine flag) and a flag is cleared if one is there.
- **Quiet by construction:** the environment of every component process **starts empty** (no proxy settings, no tokens), with
  `HYPERFRAMES_NO_TELEMETRY=1`, `HYPERFRAMES_SKIP_SKILLS=1`, `DO_NOT_TRACK=1`, and a `HOME` inside the component, so
  `~/.hyperframes` is not touched (tested: its files and times are unchanged by a render). The install log's only
  network hosts are nodejs.org, storage.googleapis.com and registry.npmjs.org (every `resolved` URL in the lock is the npm registry).
- Not available off Apple-silicon Macs: `plan()` says 0 bytes and `start()` says so in words.
- Run for real into a scratch data folder: 25 s from nothing to ready (node 5 s, browser 13 s, packages about 5 s, checks 1 s); `--version`
  of HyperFrames and of the browser both ran; the CI script `scripts/ci-video-builder.py` does the same.

## V1b: how the sandbox works, and what was tried

1. **The launcher** (`video_builder_sandbox.LAUNCHER`, written to `<component>/bin/launch-browser`): drops `--no-sandbox`,
   `--disable-setuid-sandbox`, `--disable-popup-blocking`, `--enable-automation`; keeps everything else HyperFrames asked for;
   adds `--proxy-server=http://127.0.0.1:<filter>`, `--proxy-bypass-list=<-loopback>` (so loopback goes through the filter too),
   `--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1`, WebRTC through the proxy only,
   `--deny-permission-prompts`, and the quiet flags; sets `HOME` to a per-render throwaway folder (a saved file lands there and
   is deleted); **exits 97 if the real browser, the filter port or the throwaway home is missing**: it never starts without them.
2. **The filter** (`FilterProxy`, asyncio, no new dependency): forwards to one loopback port, the **first loopback port the browser asks
   for** (HyperFrames serves the page from a random local port, and the composition cannot have run before its own page was
   requested); every other request, including a CONNECT to anything else and a request to another loopback port, is **closed with no
   response** (the page sees a failed request) and written to a bounded list ("N requests were blocked").
3. **The guard** (`run_render`): its own process group, a wall-time limit, a stall limit (no output at all), a memory watchdog that
   samples the process tree's resident memory with `ps` (about 15 ms a sample), and a kill of the whole tree on a limit, on cancel
   and on quit; plain-words results ("too much memory", "took too long", "stopped making progress", "cancelled").
4. **The lint** (`lint_project`): refuses non-local URLs (HTML attributes, CSS `url()` and `@import`, any `http(s)`, `ws(s)` or
   `ftp` address outside vendored files), `file:` addresses, paths that leave the folder, network APIs (`fetch`, `XMLHttpRequest`,
   `WebSocket`, beacons, workers) and dynamic code (`eval`, `Function(`, `import(`, `window.open`). It is a first line, with a clear message,
   because HyperFrames' compiler fetches CDN scripts in Node before the browser exists; the filter is the boundary.

**Dead ends (kept so they are not repeated):** (a) `--proxy-pac-url` with a `file:` or a `data:` PAC **is ignored by the headless shell**
(the canary was reached): do not use it. (b) A fixed render port (`PRODUCER_PORT`) is not the per-render file server's port;
that port is random, hence the first-asked rule. (c) The shell's `--proxy-server` works, and so does `<-loopback>`; the first test of
the filter looked broken because the shell tool (zsh) does not split an unquoted `$F` into arguments: use arrays or bash. (d) The
page's own `fetch(... mode:"no-cors")` is not evidence: judge by the canary's log, and make the filter close the connection instead
of answering 403 (an opaque 403 resolved the page's promise and read "reached" although nothing was).

## Results

Real pinned browser, real HyperFrames render, real adapter (`test_video_builder_hostile.py`, 11 tests, 110 s):

| Case | Result |
|---|---|
| Remote requests: fetch, XHR, image, script, WebSocket, keep-alive beacon to example.com | all failed; 12 refused requests recorded; the frame is green (nothing worked) |
| Service on loopback (fetch to `127.0.0.1` and `localhost`, WebSocket, image) | **canary heard 0 requests**; green |
| `file:` script and image from a folder outside the project | blocked; `window.SECRET` undefined |
| Geolocation, notifications, camera | denied |
| `window.open` to a remote page and a blob download | popup's request refused (3 recorded); **no file saved anywhere**; `~/Downloads` unchanged |
| `alert()` and `for(;;){}` | the render hangs; **killed by the stall limit at 26 s** (limit 25 s); no browser or node process left |
| 256 MB typed arrays without end | **killed in 1.2 s**, tree peak 3.66 GB at a 3 GB limit (overshoot 0.66 GB at a 15 ms sampling; a normal render peaks at 0.6 GB by this measure); nothing left running |
| Cancel during a render | whole tree gone |
| Control (a page driven only by its timeline) | renders; **byte-identical** MP4 to the unsandboxed render; the person's `~/.hyperframes` unchanged |
| **Negative control**: the same localhost attack through the stock launch | the canary **is** hit and the frame is red: the corpus bites |

Unit tests (`test_video_builder_sandbox.py`, 33): the filter on real sockets (first port wins, closes everything else, survives garbage and
a 70 KB header), the launcher (flags dropped and added, refuses without the filter, rewrites a tampered file), 13 lint cases, the guard on
stand-in processes (failure, stall, wall time, memory, cancel, refused projects, environment). `test_video_builder_runtime.py` (18): pins,
what counts as installed, the environment, the installer on stand-ins (hash mismatch keeps nothing, a failed step says so, zip path escape,
wrong confirmation, other platforms, uninstall).

## Not covered, and what V1c must still do

- **Memory limit values:** the overshoot depends on the attack's speed and the poll (15 to 40 ms); the default is 4 GB and V1c sets it from
  the fit check. **A render's resident memory measured by `ps` was 0.6 GB for the control page, against 1.8 GB that V0's sampler reported
  for the same size: the two measure differently; compare like with like.**
- **A popup window stays open until the render ends** (it sits behind the same filter, so it reaches nothing); CPU time is limited only by the wall limit.
- **Not measured:** WebRTC and service-worker escapes (WebRTC is forced through the proxy by a flag; not attacked), Windows and Linux (the component is
  Apple-silicon only), the **Gatekeeper behaviour with a quarantine flag inside the packaged Tauri app** (the installer clears the flag if set; not
  tried in the real app), a render with a model resident on 16 and 32 GB Macs, audio and video inputs.
- The filter's "first loopback port" rule trusts that nothing but the render's own page is requested first; a future change in HyperFrames
  (a health check on another port before the page) would block the render, loudly (`blocked` lists it), not silently.
- The component directory also holds Node's bundled npm and corepack (187 MB); trimming it is possible and not done.
- **Side effects outside the scratch folder:** the stock-launch control runs of the experiment (before the component existed) used the real home and updated
  `~/.hyperframes` once (22:17); the component itself is tested not to.

## V1c: the engine, the projects and the screen (measured 2026-10-20)

Run for real through the desktop engine (`create_app()` with the desktop profile, the component installed by the V1a installer, the real browser), not through stand-ins:

| Step | Result |
|---|---|
| Component state | installed, source `env`, supported; fit check "It needs 3.0 GB; 37 GB is free." |
| Create a project | 2 KB page; the title and the line are escaped text |
| Preview at 1.5 s | **4.3 s** the first time (a PNG of 1280x720, 175 KB), **0.00 s** again (kept next to the project) |
| Render of 5 s at 720p | **7 to 9 s**, tree peak **2.28 GB**, 0 refused requests, a 1280x720 MP4 of 5.00 s |
| A second render while one runs | refused with "A video is already being made" (409, code `busy`) |
| The clip | in Your videos (`mode composition`, 1280x720, 5 s, found by its words), downloadable, **Save a copy** works |
| Cancel after 1.2 s | stopped in **1.3 s**, status `cancelled`, **0 leftover processes** |
| Delete | 204, the clip and the project gone, the library empty |
| 12 s landscape 720p / 12 s square 1080 | 8.0 s / 8.0 s, 2.29 / 2.30 GB |
| With a 14 GB process held beside it (stand-in for a resident model) | 7.1 s and 8.2 s; 2.32 and 2.33 GB; fit "fits" (64 GB) |

Looked at: the preview of a long portrait title wraps over six lines with nothing clipped (descenders intact) and the subtitle under it; the title mask-slides in and the bar draws.
The system font stack renders as the machine's own (SF here): fonts differ per machine until MG1 ships its own.

Tests added: 31 (product: template, store, routes, render manager, actions, library kind, search), 5 routes, 7 client, 14 screen, 1 menu; the existing menu, catalogue and index tests updated for the new item, kind and combined source.


## MG1: five templates, the exact-text check and `motion.make` (measured 2026-10-20)

Run for real through `motion.make` with the real component and browser (not stand-ins), on this Mac (M5 Pro, 64 GB):

| Request | Result |
|---|---|
| lower third, "Maya Chen" / "Head of Design", WebM | ok in about 8 s; check 2 places, passed; tree peak about 2.25 GB |
| chart from the lines `North, 120` `South, $95` `East, 150` `West, 1,200.5` | ok in 9.5 s; check 9 places (title, four labels, four numbers), numbers shown as typed |
| animated title, quote, captions (MOV) | ok in 7.8 to 8.3 s each; peak 2.24 to 2.30 GB |
| a page whose name was retyped to "Maya Chan" after it was written | **refused before drawing**: "The screen says “Maya Chan” but you wrote “Maya Chen”."; the project is kept and no clip is made |

Proved in the gated tests (`services/api/tests/test_video_builder_templates.py`, needs the component): every template
passes the check and is drawn; the shipped font really loads (`Inter:loaded`); **20 slot cases** (a 55-character double-barrelled
name, `<script>`, `&`, `<`, `>` and `"` strings, Bengali in four templates, unbreakable 80-letter titles, eight chart rows,
four captions) show exactly and inside the safe area; a retyped name, a squeezed (cut off) word and a word that is never drawn
are each caught; the lower third as **WebM decodes with real alpha** (libvpx, transparent corners, a bar not the full frame)
and as **ProRes 4444 MOV** the same; an opaque title has no clear pixel.

**What the real check found that stand-ins could not** (all fixed): a waiting predicate that returned a GSAP timeline never
resolved in puppeteer (it must return a boolean); a second line dimmed to 0.8 is not "still fading in" (threshold 0.75);
removing all clipping made a layout that was already tight reflow (so the chart has more room), and a clip layer redraws the
Bengali headline rule a few pixels differently (tolerance 80 pixels; a real cut shows hundreds); unbroken words overflowed
(every slot may now break anywhere, and long titles shrink); Bengali marks were cut by a too-tight mask.

Looked at: stills of all five templates and of a portrait lower third with a 56-character name over three lines (inside the margin).

Tests added: 57 (templates and the report comparison), 41 in the rewritten builder file (versions and Undo, the upgrade of an
existing store, check gating, formats, `motion.make`/`motion.revise`, the library), 32 gated real-browser tests, 3 client, 9 screen.

Not done: moderation of slot text (ADR-0079 decision 9), the chat path (A2), a looping preview clip, the second-opinion
picture model, Bengali in a font we ship, 16 and 32 GB Macs, the `video-builder` CI job on GitHub (now also runs the template tests).

## MG1b: lengths to 90 seconds and the prompt box (measured 2026-10-21)

**How long can a video be on this Mac** (M5 Pro, 64 GB; real renders through the sandbox):

| Case | Draw time | Tree peak | File |
|---|---|---|---|
| title 30 s / 60 s / 90 s, 720p | 6.8 s / 10.1 s / 13.8 s | 2.04 / 1.99 / 2.03 GB | 0.3 / 0.7 / 0.9 MB |
| quote 90 s, square 1080 | 16.5 s | 2.28 GB | 1.7 MB |
| title 90 s, portrait | 14.3 s | 2.06 GB | 0.9 MB |
| chart 90 s, square | 16.7 s | 2.23 GB | 1.3 MB |
| lower third 90 s, WebM alpha | 25.9 s | 2.20 GB | 0.5 MB |
| lower third 90 s, ProRes 4444 MOV | 18.1 s | 2.20 GB | **143.8 MB** |
| captions 90 s (30 lines), WebM alpha | 33.1 s | 2.22 GB | 1.4 MB |

Time grows slowly with length and memory not at all: the pages are mostly still frames. The ceiling of 90 seconds is a choice,
not a limit of the Mac; the guard stays at 15 minutes and 4 GB. A busier page (video inside, 3D) is not what these templates are.

**The prompt box with real models** (12 requests: names, a quote, a chart from numbers in the sentence, captions, `& < > "`,
accented and Bengali text, a length and a shape; `Gemma 4 e4b` and `gpt-oss:20b` through Ollama, structured output):

| Model | Right | Time per request | Misses |
|---|---|---|---|
| gemma4:e4b | 11 of 12 | 1.6 to 3.6 s | picked "lower third" for a Bengali name and a role (arguable) |
| gpt-oss:20b | 10 of 12 | 1.4 to 2.8 s (8.7 s first) | left out "30 seconds" and "60 seconds" |

Every quoted word came back exactly. The first version (one answer with every field of every template) failed 10 of 12 on
gemma: it wrote the words, then blanks until it ran out of room, and filled looks nobody asked for. Two small questions and
dropping unasked looks fixed it. These are 12 requests, not the MG0 measurement of ADR-0079 (about 20 requests on three tiers).

Through the real desktop engine (app profile, the component installed, Ollama's `gemma4:e4b` chosen with `PUT /desktop/language`):
draft 6.5 s (the model's first load), create, check passed, a transparent WebM drawn in 11.7 s and kept as a clip of Your videos.
The CSV case drafted a chart whose rows came from the file. It also found two things now fixed: an unquoted `$1,200.5` was split
into two cells, and one check failed to run once, right after the model had been used (it passed three times alone; both the
check and the drawing are now tried once more).

Not done: moderation of the words (refused instead while the safeguards are on), the MG0 half on three model tiers, the
chat path (A2), spreadsheets, a looping preview, a progress picture of the draft beyond "Reading your request".

## First CI run (2026-10-21): what it found

Three failures, all real: (1) a test of the install plan assumed the machine running it was an Apple-silicon Mac (it is now
pinned, with a test for the other case); (2) a raw hex colour in the chequerboard behind transparent previews broke
`design:check` (now `color-mix` of the text colour); (3) **every render on the clean macOS runner failed because FFmpeg and
ffprobe were not installed**: HyperFrames does not bring them and `imageio-ffmpeg` has no ffprobe, so the plan's "FFmpeg is the
app's own" was wrong, and it was hidden on the owner's Mac by Homebrew. Fixed as in the ADR-0079 correction; shipping FFmpeg with
the component is left to the owner.
