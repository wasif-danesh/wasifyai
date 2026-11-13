# ADR-0080: Text and image to 3D: make a 3D model from a picture, or from words through a picture

- **Status:** Accepted (2026-10-18, by the owner), together with the components it names. The `<model-viewer>` dependency (decision 7) is approved. **Revised the same day** after the owner said
  both models run on a Mac: they do, and the first draft was wrong to say they did not. A maturity check
  remains (decision 4). **Priority decided by the owner the same
  day: Pixal3D first; TRELLIS.2 is not offered in v1 and gets no spike** (decision 5).
- **Superseded in part:** by ADR-0094 (2026-10-29): the picture check, the "I may use this picture" statement and the daily limits are removed.
- **Date:** 2026-10-18
- **Depends on:** ADR-0066 (a native runtime run as a managed component: the model for this one), ADR-0056 (one
  slot; llama.cpp managed), ADR-0063 (will it fit?), ADR-0073 (tiers; model cards; simplicity rules), ADR-0058 (the
  runner on another machine), ADR-0059 and ADR-0038 (images and prompt help), ADR-0068 (action catalogue), ADR-0077
  (Video Builder, for turntable videos), ADR-0078 (Qwen3.5-9B reads pictures), ADR-0064 (hub; gated models), ADR-0062 and
  ADR-0061 (reuse), ADR-0041 (searchable), ADR-0047.
- **Plan:** `docs/phase5-agent-training-video-builder-plan.md`, stages TD0 to TD4.

## Context

The owner named two projects. What was read (2026-10-18: both READMEs, their code, the Hugging Face pages, and the
community ports found after the owner's correction):

**TRELLIS.2** (Microsoft, 4 billion parameters, 12,000 stars). Image to 3D: a picture in,
a **textured model with full PBR materials** out, as **GLB**. On an H100 about 3 s at 512³, 17 s at 1024³ and 60 s at
1536³. **No text input.** The original code is CUDA only (Linux, an NVIDIA card with 24 GB or more, compiling
flash-attn, nvdiffrast, nvdiffrec, cumesh, o-voxel and flexgemm).

**Pixal3D** (Tencent ARC and Tsinghua, SIGGRAPH 2026, 2,500 stars). Image to 3D that lifts pixel features into 3D,
so the result follows the picture more closely; its `main` branch sits on the TRELLIS.2 backbone. Adds **multi-view
input** (four photos around an object plus their camera poses). **No text input.** The original code is also CUDA.

**Both run on a Mac through community ports** (found by searching GitHub; none of these is run by us yet):

| Port | What it is | Maturity | Measured by its author |
|---|---|---|---|
| **`raven38/pixal3d.cpp`** | **Native C++/GGML, no Python at runtime**, a fork of `pwilkin/trellis.cpp`. Runs **TRELLIS.2 (one image) and Pixal3D (four views)** in one pipeline: background removal, conditioning, the three flow transformers, decoders, mesh extraction, UV-textured **GLB** export. Backends **Metal, CUDA, ROCm, Vulkan**. Prebuilt binaries per platform (macOS arm64 Metal: 2 MB; Linux and Windows CUDA about 650 to 700 MB; Vulkan about 20 MB), a resident `trellis-server` over HTTP, a CLI | created 2026-09-13, 18 stars, one maintainer, 5 releases | Apple M5 24 GB: res-512 image to textured GLB in **9 min 21 s, 5.6 GB peak RSS**; RTX 4090: res-1024 cascade, about 3 min |
| `shivampkumar/trellis-mac` | PyTorch MPS port of TRELLIS.2; replaces nvdiffrast with a **Metal** rasteriser (`mtldiffrast`); hole filling disabled | 490 stars, 2026-04 | M4 Pro 24 GB: **5 min 13 s** cold at 512, about 18 GB peak; weights about 15 GB |
| `lyonsno/trellis2mlx` | **MLX-native** TRELLIS.2 | 9 stars, updated 2026-10-17 | M2 Pro 16 GB: 21 min for a shoe, 6.75 GB peak; M4 Max 3 to 9 min; a 768 warrior reached **63.8 GiB** |
| `Bingeljell/image-to-3dlab` ("AssetFurnace") | A complete **studio** around the above plus Hunyuan3D, Stable Fast 3D, **Qwen-Image text to picture, "Finish" clean-up and low-poly, auto-rig and animation, and an MCP server** | 836 stars, active 2026-10-17 | M5 32 GB: Pixal3D about 6 min, TRELLIS.2 15 to 35 min, Qwen-Image about 4.5 min; RTX 4090: Pixal3D about 3 min |

The timing claims are the authors' own and differ by method; **we measure on the owner's Mac (TD0)**.

**Pieces** (read 2026-10-18): `pixal3d.cpp` uses BiRefNet for the cut-out (the original pipelines' RMBG-2.0 is not used) and does its own
native postprocess, so the original code's nvdiffrast rendering and GLB texture baking are not in the path. MoGe-2 estimates the field of
view for Pixal3D. The `pixal3d-sv-q8_0-v1` GGUF weights bundle (a third party's Hugging Face repo) holds all model weights in one download,
including the DINOv3 encoder.

## Decision

1. **Product: "Make a 3D model"**, a card under Images in the menu, Labs-labelled "experimental" until TD0 passes,
   with the simplicity rules of ADR-0073: **pick a starting point, check, make, use it**. Starting points: *From a
   picture* (one object photo or drawing), *From words* (describe it), *From several photos* (four around an object,
   decision 6). No settings: the app chooses resolution and polygon count from the machine and shows "about N
   minutes". "For experts" holds engine, resolution, steps, polygon target, texture size, seed.
2. **Text to 3D goes through a picture, and the person approves the picture.** The words go through the prompt help
   (ADR-0038) with a wrapper for the best input ("a single object, centred, plain light background, front
   view at eye level, soft even light (corrected after TD0: a three-quarter view makes the model lean)"); the image model makes **four candidates** (ours, FLUX.2 klein; the studio above uses
   Qwen-Image, which is an option for our image catalogue, not a requirement); the person picks one or uploads their
   own; **then** the 3D run starts. The cheap steps stay cheap and the long run happens once.
3. **Input checks in plain words** before the long run: one clear object, big enough, centred, not cut off; the
   cut-out is shown ("is this the object?"); a photo of a person asks the likeness question of ADR-0073 decision 7
   and the image moderator runs when safeguards are on (ADR-0047); Pixal3D's responsible-use note (no non-consensual
   or sexualised depictions of real people, nothing involving minors, no impersonation) is adopted as our rule.
4. **Engine: `pixal3d.cpp` (running the Pixal3D models) as a managed native component, like audio.cpp and llama.cpp** (ADR-0066, ADR-0056). A
   pinned release (the Metal build for macOS, CUDA, ROCm or Vulkan elsewhere), its size and SHA-256 shown before the
   click, unpacked under `<app data>/components/model3d/`, run as one loopback `trellis-server` that owns the one
   slot while it works and exits on quit. **No Python, no conda, no compiling on the person's machine, no
   nvdiffrast**. It runs on **this computer** on a Mac (Metal), on Windows and Linux with NVIDIA, AMD or any Vulkan
   card, and on **my other machine** and **a rented GPU** through the same server. This removes the "a GPU container
   we build" idea of the first draft, and with it the rule-14 exception: we pin published binaries and, for
   supply-chain safety, **also build the same commit in CI** and compare. A check gates it (TD0):
   **Maturity.** `pixal3d.cpp` is two months old and has one maintainer. Mitigation: pin by commit and hash, keep
   the **descriptor-based engine seam** (below) so `trellis-mac` or `trellis2mlx` or the original CUDA code can
   replace it, and run a fixed regression set (decision 10) on every pin change.
5. **Pixal3D is the engine of record; TRELLIS.2 is not offered in v1** (owner's decision). The component runs the
   Pixal3D models: **single-view** (`pixal3d-sv`, Q8_0, about 8.4 GB of weights in the bundle the studio fetches) and
   **multi-view** (four views, decision 6). The same binary can also run TRELLIS.2 weights, but we neither download
   them, test them, nor describe them in the app. Engines are still **descriptors** with measured numbers (ADR-0073),
   so another engine can be added later without code changes: `pixal3d-cpp-sv`, `pixal3d-cpp-mv`, each stating memory,
   time per resolution on the tested machines and tiers. The
   fit check (ADR-0063) refuses a resolution that would not fit. Pixal3D's own default resolution is 1536, or 1024
   in low-memory mode. **Corrected after TD0: single view accepts 1024 only in this release (512 and 1536 are refused by
   design); measured on the owner's M5 Pro 64 GB: 198 to 1361 s per picture, median 696 s (about 11.6 minutes), 17.7 to
   18.8 GB peak.**
6. **From several photos** is offered on the Pixal3D multi-view model: four photos 90° apart at eye level, the first
   the front, with the shipped orbit poses as the default, or poses from a file in "For experts".
7. **Output and viewing.** A **GLB** with PBR materials, preview stills and a **turntable**, shown in a **3D viewer in
   the window** (orbit, zoom, lighting, wireframe). The viewer needs a web 3D library: Google's **`<model-viewer>`**
   which `pixal3d.cpp` itself uses for previews; **a new dependency, so approval is asked first**
   (recommended). Export: GLB always; OBJ and STL on request (STL only after a watertight check and repair).
   Polygon budget names: *Light*, *Standard*, *Detailed*. **Corrected after TD0: the face target is fixed at 1,000,000
   triangles; in v1 the three names map to an atlas size of 1024, 2048 and 4096, and the 50k and 200k face targets wait
   for a small patch to `pixal3d.cpp` (the owner's decision).** Hole filling and
   clean-up are the engine's; **"Finish"** (low-poly clean-up, keeping the picture's real pixels) is an idea from the
   studio worth a later stage, not v1.
8. **It is a creation (ADR-0041).** Kind `model3d`: the GLB, a thumbnail, the source picture and cut-out, the engine
   and versions, seed and settings (a recipe, so "Make it again" gives the same model), and the likeness statements.
   Searchable by the prompt and by a description the multimodal model writes from the
   previews. A card and a kind filter in the Library.
9. **Actions (ADR-0068):** `model3d.generate` (effect `make`, **costly**, `leaves_device` on a remote tier, needs
   consent on first use of a tier), `model3d.list`, `model3d.get`, `model3d.export`, `model3d.delete`. The assistant
   can say "make a 3D model of my mascot from this picture"; the agent and MCP clients use it with approvals. The
   studio's own MCP surface is a useful reference for names, not a dependency.
10. **Evaluation (TD0, kept):** a fixed set of 20 inputs (a mascot, a product photo, a pet, a plant, a chair, a sword,
    a building; and failures: glass, thin parts, text on an object, several objects) run with the Pixal3D models (single
    view, and multi-view on a subset) on each tier, scored for time and peak memory, silhouette agreement with the input from three viewpoints, texture fidelity,
    mesh validity, and **whether the GLB opens in Blender, `<model-viewer>` and macOS Quick Look**. It sets the default
    resolution and the plain-language promises ("works best with one object on a plain background").
11. **Video Builder link.** A turntable or fly-around of a model becomes a Video Builder template (ADR-0077): the GLB in
    `<model-viewer>` inside a composition, recorded frame by frame. Whether headless Chrome renders WebGL well enough
    without a GPU is **not verified** (TD3).
12. **Training and the studio's other features are out of scope for v1:** fine-tuning 3D models; rigging and animation
    (auto-rig is the studio's headline and a later product); game-ready prop sheets; Blender-based finishing.

## Consequences

- The Mac, the owner's own machine, is a first-class tier: a native binary like the rest of the app's runtimes,
  not a Python stack to compile. Windows and Linux work through Vulkan, CUDA or ROCm with the same server.
- A young dependency with one maintainer sits on the critical path; pinned, built in CI, replaceable by descriptor,
  and checked on a regression set.
- A 3D viewer dependency and a new creation kind (searchable, with a card) are added. The slot is busy for minutes
  while a model is made; the screen says so.

## Alternatives considered

- **The original CUDA code on a rented GPU.** Works, ships the NVIDIA baking and RMBG-2.0; kept only as a
  descriptor for comparison.
- **TRELLIS.2 as the main engine.** Not chosen (owner): Pixal3D follows the picture more closely by design and is the
  priority; TRELLIS.2 stays a possible later descriptor, with no spike now.
- **Python ports (`trellis-mac`, `trellis2mlx`).** Real and measured by their authors (about 5 min on an M4 Pro
  with the PyTorch port), but a Python and Metal-compiler stack to build on the person's machine, and `trellis-mac`
  pulls RMBG-2.0. Kept as alternates.
- **Adopt AssetFurnace (the studio) whole.** Ahead of what we plan (text to picture, finishing, rigging,
  provenance), but it needs Blender, full Xcode and several Python stacks, and is a product in its own right.
  Studied as a reference; we may reuse parts later (ADR-0062 level B).
- **Hosted 3D APIs.** No GPU, but data leaves and the owner's first hosted providers are Hugging
  Face and GitHub only. Possible later as another tier.
- **Hunyuan3D and Stable Fast 3D.** Not v1.

## Open questions

1. Real speed and peak memory on the owner's M5 Pro, at 512 and 1024, for the Pixal3D models, and whether the Metal
   path ever fails on complex objects (its README reports command-buffer failures on complex runs).
2. Which text-to-picture model gives the best 3D input (klein 4B against others); a measured prompt wrapper.
3. Whether the web product offers it (our GPU host, abuse controls; the likeness risk is higher there).
4. Quality of the quantised (Q8_0) weights against the original Pixal3D (a visual comparison in TD0).

## Not in v1

Rigging and animation, game-ready finishing, scene generation (many objects), editing a generated model, training or
fine-tuning, sharing or selling models, the web deployment.

## Still to do before anything is downloaded

Accepting this ADR does not install anything. The owner still has to say yes to the TD0 download (the pinned `pixal3d.cpp` Metal build and the Pixal3D weights, sizes
shown first).

## Amendment after spike TD0 (2026-10-19; `docs/spikes/pixal3d-td0.md`)

Measured on the owner's M5 Pro, 64 GB; timings ±20% because other spikes ran on the machine. Verdict: **TD1 Go and TD2 Go**,
with the conditions below.

- **Stability:** 27 command-line 3D runs and 2 server jobs finished with no crash or failure.
- **Speed and memory (single view, 1024):** 198 to 1361 s, median 696 s; time is about 45 s + 0.07 s per 3D token
  (r = 0.98), so it depends mostly on how detailed the object is. Peak 17.7 to 18.8 GB (a Mac needs about 19 GB free; 24 GB
  was not measured). 1536 works through an unsupported path (944 s, 26.3 GB for the chair). **Multi-view** (four views
  90° apart): 1506 s, 20.4 GB; the four rendered views reproduce at silhouette IoU 0.974. The earlier "about 6
  minutes" in this ADR was too optimistic: say **"about 5 to 25 minutes"** in the app.
- **Output:** a GLB of about 1M triangles with two 4096 textures, 30 to 42 MB, **not watertight**, requiring
  `EXT_texture_webp`. It opens in **Blender 5.2 and `<model-viewer>` 0.8.2** (use `loading="eager"`, start orbit 180°).
  **macOS Quick Look cannot preview any GLB on this Mac**, even a plain Blender sphere; export USDZ or OBJ later if Finder
  previews are expected (untested).
- **Server:** `trellis-server` works on loopback but has **no progress route and no cancel**; a disconnected client does
  not stop the job. The managed component reads the process output for progress, **kills the process to cancel and to
  free memory**, and deletes the leftover `.ply`, PNG and staging folder.
- **Text to 3D:** works end to end (a frog mug in about 21 minutes after four candidate pictures; the candidates came from
  FLUX.2 klein base 4B through mflux, because the app's ComfyUI engine had no klein weights installed on this Mac). An
  eye-level straight-on picture gives an upright model; the input check asks for one object, straight-on, plain
  background, and warns that glass, mirror metal, several objects and very thin parts do not come out well.
- **Pinning and build (decision 4b):** release `v0.10.1-desktop-alpha`, the Metal asset SHA-256 is recorded in the report.
  The tag points at commit `1f432fd` but the binary embeds `add368c` (a rewritten history with identical `src/`). **The
  prebuilt Metal binary disables Metal's tensor API on this M5 Pro; a source build of `1f432fd` (20 s here) enables it.**
  So: pin by the asset hash **and build our own binary in CI** from the pinned code with a current SDK (setting the
  deployment target), keeping the prebuilt as a fallback. Cut-out (BiRefNet GGUF) is
  part of the component, because single view needs a matted PNG.
- **The encoder bundle:** the app downloads the bundle from its Hugging Face repo at the pinned revision and does not mirror it.
- **Not done:** the Q8_0 quality against the original CUDA Pixal3D (needs an NVIDIA machine); a CI build of the pinned
  commit; a run on a rented GPU; MoGe-2 and NAF weights run; a 16 or 24 GB Mac; two requests at once on the server;
  multi-view at 1536 or from real photographs.

## Amendment after TD1 and TD2 (2026-10-21; `docs/spikes/pixal3d-td1.md`)

Built and tested: the component, the engine's 3D service, a product of its own, the creation kind, one action and the
screen, behind Labs (Settings › Labs, then **Images › 3D model**). Decisions of the owner the same day: **the upstream prebuilt
binary, pinned by hash** (not our own CI build yet), and real generations during the build.

- **A process per run, not `trellis-server`.** The server loads its weights for every request anyway, has no progress and no
  cancel, and keeps 2.5 GB after a job (TD0, section 6). The engine runs `trellis-cli` once for the cut-out
  (`--bg-only`) and once for the 3D run (`--sv-image ... --res 1024 --atlas N`): progress is read from its output
  (`[n/6]` stages and `[flow]` steps), cancelling kills the process group (a second or less), and the memory is free when it
  exits. The run holds the one big-model slot (`model3d`), so the chat and image models are put away first.
- **The component** (`model3d_runtime.py`, `model3d_pins.json`): the pinned release asset (2.4 MB, SHA-256), the single-view
  weights bundle at its pinned revision (13 files, 8.09 GB, every size and SHA-256 recorded and checked against the live
  servers) and the BiRefNet cut-out model (0.88 GB): **8.98 GB** in all, shown before the click. The weights use the resumable,
  hash-checked downloader of the Models screen.
- **Product `wasifyai-model3d`** (its own package, desktop only): a SQLite store of pictures and models, the files under
  `<app data>/model3d/`, one job at a time with progress and cancel, routes under `/products/wasifyai-model3d/m3d`. A model
  is the creation kind **`model3d`** (searchable by its title and the words it was made from, a row in the search corpus).
  A picture nobody made a model from is forgotten after 14 days.
- **Picture checks, in words** (decision 3): after the cut-out, one object found, all of it in the picture, big enough, in the
  middle, not several; a warning is said and the person goes on, a picture with no object stops. A picture that is already
  see-through is not cut again. The person confirms that they may use the picture and that it is not a photo of a real person
  who has not agreed (the likeness question of ADR-0073 decision 7).
- **Detail** (decision 7, corrected after TD0): Light, Standard and Detailed are the atlas sizes 1024, 2048 and 4096; the face
  target stays at one million triangles.
- **Actions:** one, `model3d.generate` (costly, long, asks first), taking a picture of the library; listing, looking, renaming,
  deleting, saving a copy and reading the file are the library's actions on the new kind. The catalogue's upper bound moves
  from 45 to 50 (decision 9 listed five actions; six of them are the library's).
- **The screen** (TD2): start from a picture or from words; from words the image engine makes four candidate pictures one
  after another (the wrapper asks for "front view at eye level", TD0's correction), the person picks one; then the check, the
  detail, the long run with its stages in plain words, and the result in a viewer with Save a copy, Make it again, Rename and
  Delete. `<model-viewer>` 4.1.0 is loaded when the first model is shown; the window's content security policy
  allows `blob:` in `connect-src` so that it can read the model the window fetched (the engine's route needs the session).
- **Not built:** four photos around an object (TD3), a turntable video (Video Builder), the 50k and 200k face targets (they need
  a patch to `pixal3d.cpp`), our own CI build of the binary (the prebuilt is pinned; it runs without Metal's tensor API),
  the web version (TD4), a card in the web library.

## Amendment: no Labs switch (2026-10-21, owner)

Decision 1's "behind Labs" is withdrawn. **Images › 3D model** is always in the desktop menu; the screen keeps its "experimental"
label, and nothing is released before the owner's own testing. The owner's reason: a switch is a second way to get lost in the app and
adds a state to test and to explain. The key `wasifyai.labs.model3d` is no longer read.

## Amendment: the 3D model is its own menu item (2026-10-24, owner)

A 3D model is not an image, so the screen no longer sits under Images. The side menu shows **3D model** (id `model3d`)
as a single item right after Motion graphics, before Library, Models and Train. The action ids (`model3d.*`), the
routes (`/images/3d` on the desktop, `/image/3d` on the web) and the engine are unchanged; the action's `ui`, its help
file and the menu mappings use the id `model3d` instead of `images.model3d`.
