# Spike TD0: Pixal3D on the Mac (`pixal3d.cpp`, Metal) for ADR-0080

Date: 2026-10-18 to 2026-10-19. Machine: MacBook Pro M5 Pro, 18 cores, 64 GB, macOS 27.0.1, Xcode 27.1 (Metal toolchain installed).
Plan: `docs/phase5-agent-training-video-builder-plan.md` stage TD0; ADR-0080. Scratch folder (outside the repo, with every
log, input, GLB and script): `~/Projects/wasifyai-spikes/td0/`. Pixal3D only; TRELLIS.2 was not run.

**Read this first.**

- **Four spikes shared this Mac.** Every model run took the shared lock, so no two lock-holding runs overlapped. Two things
  can still disturb a time: other sessions' work that does not use the lock (a crude check of file activity in the other
  spikes' folders found activity during my first run, the 1361 s mascot, and during the cut-out stage of the chair, the
  sword and the frog job; none during the 3D stage of any other input; the first run is also the slowest of three runs of
  the same picture, see 3.4) and my own Blender renders, which ran while flow runs were in progress on several occasions
  (about 1 to 3 minutes each). `pmset -g therm` recorded no warning at the end, but I did not log temperature during runs.
  Treat times as **plus or minus 20 percent** (the same mascot picture took 1361, 1043 and 1015 s in three runs, with two
  different binaries, so I cannot split noise from the binary effect).
- **The text-to-picture step did not use the app's image engine.** The app's ComfyUI engine has no FLUX.2 klein weights
  installed on this Mac. I used the cached **FLUX.2 klein base 4B through mflux** (the separate art product's environment,
  `HF_HUB_OFFLINE=1`, 28 steps, guidance 4, 1024 by 1024), not the distilled klein 4B. It is the same model family, not the
  same run path.
- **Quality of the Q8_0 weights against the original CUDA Pixal3D: not done** (needs an NVIDIA machine; none rented). A build
  of the same commit in **CI** was not done (built locally only). **A run on a rented GPU: not done** (out of scope).
- **Quick Look: not verified** (section 5). **MoGe-2 and the NAF weights: read, not downloaded or run.**
- Nothing was committed. Downloads were approved by the owner before each one (stage 1, build tools, stage 2).

## Answers in short

1. **Licence.** Code and the flow weights are MIT. The one real condition is **DINOv3** (Meta), carried by `dinov3.gguf`
   inside the weights bundle. Its text allows use, copying, modification and **redistribution by a third party under the same
   agreement with a copy of the agreement**; it does not mention commercial use at all (neither allows nor bars it). **The
   "Built with DINOv3" line is in the text on Meta's website, and is not in the copy in Meta's GitHub repo, the Hugging Face
   mirrors, or the copy inside the bundle** (details in 1.4). That corrects ADR-0080's table, which cites only the website text.
2. **Pin.** Release `v0.10.1-desktop-alpha`, Metal asset SHA-256 `66663b1f…07c8` (full hash in 2.1). The tag object
   points at commit `1f432fd`, but the binary embeds commit `add368c` (a rewritten history with identical `src/`). I built
   `1f432fd` from source here in 20 s and it works. **The prebuilt Metal binary disables Metal's tensor API on this M5 Pro;
   my source build enables it.**
3. **Speed.** Single view at 1024: **198 to 1361 s per picture, median 696 s (11.6 min)**, almost entirely set by how many
   3D tokens the object needs (time = about 45 s + 0.07 s per token, r = 0.98). **Peak memory 17.7 to 18.8 GB** (process
   footprint; RSS up to 19.3 GB; the multi-view run 20.0 GB). **No crash, no failure in 27 command-line 3D runs and 2 server
   jobs.** Longer than the ADR's "about 6 minutes".
   **Single view accepts 1024 only** in this release (512 and 1536 are refused by design); 1536 works through an unsupported
   path (944 s and 26.3 GB for the chair).
4. **Multi-view** (four views, 90 degrees apart): works, 1506 s and 20.4 GB for the mascot; the four rendered views are
   reproduced at silhouette IoU 0.974.
5. **Output.** GLB opens in **Blender 5.2** and **`<model-viewer>` 0.8.2** (WebP textures included). **macOS Quick Look cannot
   make a thumbnail of any GLB on this Mac, including a plain Blender sphere**, so Quick Look is a macOS limit, not this
   output's fault. The GLB **requires `EXT_texture_webp`**. About 1M triangles, two 4096 textures, 30 to 42 MB, **not
   watertight** (edges shared by more than two faces). **The app cannot choose 50k/200k/1M**: the face target is fixed at
   1,000,000 in the single-view path; only the atlas size has a flag.
6. **Server.** `trellis-server` works on loopback. Three routes that matter, **no progress route, no cancel**. A client that
   disconnects does not stop the job; only killing the process does.
7. **Text to 3D** works end to end (frog mug, about 21 minutes after the four candidates). **The wrapper in ADR-0080 asks for a
   "three-quarter view"; that makes the model lean.** An eye-level straight-on picture gives an upright model.

## 1. Licence reading (done first, nothing downloaded for it)

State what the texts say. This is not legal advice.

### 1.1 `pixal3d.cpp` at the release

- `LICENSE`: MIT; copyright Piotr Wilkin (trellis.cpp, the base) and raven (the changes).
- `NOTICE`: lists trellis.cpp (MIT), ggml (MIT, vendored as a submodule of `pwilkin/ggml` at `737e88f`, licence file
  `thirdparty/ggml/LICENSE`, "Copyright (c) 2023-2026 The ggml authors"), Microsoft TRELLIS.2 and TencentARC Pixal3D (the
  models), DINOv3 ("subject to the DINOv3 license, DINOV3_LICENSE.md in the model sets"), xatlas (MIT), cpp-httplib (MIT),
  stable-diffusion.cpp (MIT, optional, not used by us), Tauri (MIT/Apache-2.0), and the line "BiRefNet / RMBG
  background-removal models are used under their own licenses". It says the model weights are redistributed under their own
  terms, not under this repository's MIT.
- Vendored folders read: `thirdparty/fqms` (MIT, Spacerat and contributors), `thirdparty/meshoptimizer` (MIT, Arseny
  Kapoulkine), `thirdparty/xatlas` (MIT, Jonathan Young; the file also carries thekla_atlas MIT notices), `thirdparty/cpp-httplib`
  (MIT, Yuji Hirose), `thirdparty/stb` (stb headers: choose MIT or public domain), `thirdparty/ggml` (MIT). Nothing
  non-commercial, copyleft or NVIDIA-licensed is vendored, and nvdiffrast is not in the path.
- **The release tarball contains only binaries and dylibs: no LICENSE and no NOTICE.** MIT asks for the notices with copies, so
  the component installer has to add `LICENSE` and `NOTICE` itself.
- `<model-viewer>` (the copy vendored in the repo, 1,068,903 bytes, sha256 `283b0672…f033b`): a minified bundle whose headers say Google
  LLC with BSD-3-Clause (the Lit part) and Apache-2.0 notices for others; I did not list every bundled library. ADR-0080 calls it
  Apache-2.0; the licence texts of everything in the bundle have to ship with the app.

### 1.2 Weights bundles (`raven38/pixal3d-sv-q8_0-v1` @ `46d399a`, `raven38/pixal3d-q8_0-v1` @ `1c4f4bd`)

- Not gated. Card: `license: other`, `license_name: mit-and-dinov3`. A `LICENSE.md` indexes it: **`dinov3.gguf` is under the
  DINOv3 License; the other eight files are MIT** (`MIT_LICENSE.md`: copyright Tencent 2026 and Microsoft). The bundle ships a copy
  of the DINOv3 agreement (`DINOV3_LICENSE.md`, SHA-256 `25d122eb…9e`, **byte-identical to Meta's GitHub file**).
- The multi-view bundle has the same structure. The five shared files (encoder, NAF, three decoders) are byte-identical in both
  (checked: the hard link worked and every SHA-256 matched the manifest).
- Inconsistency to resolve: the bundle labels `pixal3d_naf.gguf` as MIT from "Tencent Pixal3D / Microsoft TRELLIS.2", but the
  multi-view manifest's `source` says it was converted from `valeoai/NAF` `naf_release.pth`. The NAF code repository on GitHub is
  **Apache-2.0**; I found no separate licence for the weights file. **Not verified; ask the bundle's author or ship the Apache-2.0
  notice for it.**
- Pixal3D (`TencentARC/Pixal3D`): MIT (card and `LICENSE`). Its `NOTICE` lists dinov2 (Apache-2.0), TRELLIS.2, Direct3D-S2 (DreamTech)
  and MoGe (MIT), and **does not mention DINOv3** although the converted encoder is DINOv3.

### 1.3 The cut-out model and the camera model

- **BiRefNet** is needed for any picture that has no transparent background. `pixal3d.cpp` uses a file named `birefnet.gguf`.
  The one the studio pins is `ilintar/trellis2-gguf` `q8/birefnet.gguf` @ `a57397b` (882,749,024 bytes; I fetched it and its SHA-256
  `10c5dd4d…bc1` matches Hugging Face). That repo's card says `license: other` and "see the source model", and it names the
  TRELLIS image model as the source, not BiRefNet. **Upstream `ZhengPeng7/BiRefNet` is MIT** (card and GitHub `LICENSE`, "Copyright (c)
  2024 ZhengPeng"). So the GGUF's own licence is unlabelled and the upstream is MIT; which BiRefNet variant was converted is not
  stated. The studio also fetches a 224 MB "BiRefNet-lite"; I did not use it.
- The Bria **RMBG-2.0** is not used by `pixal3d.cpp` (the Python studio and `trellis-mac` differ).
- **MoGe-2** is not used by the native binary: single view uses a fixed 20 degree field of view, and MoGe appears only in
  Python helpers (`tools/estimate_transforms_moge.py`). Cards `Ruicheng/moge-2-vitl` and `-normal`: `license: mit`; GitHub
  `microsoft/MoGe`: MIT LICENSE text, README says its DINOv2 code is Apache-2.0. Not downloaded.

### 1.4 Meta's DINOv3 licence text: what it says

Two published versions differ in one clause.

| | Meta's GitHub `LICENSE.md`, the Hugging Face files (`timm/…dinov3…`, the bundle) | Meta's web page `ai.meta.com/…/dinov3-license` |
|---|---|---|
| SHA-256 / date | `25d122eb…9e` (all three copies identical); "Last Updated August 19, 2025" (GitHub history: 14 Aug import, 19 Aug fix touching only the date and the survival-clause numbers) | dated "August 14, 2025" |
| Grant (§1.a) | non-exclusive, worldwide, **non-transferable**, royalty-free, limited licence to use, reproduce, distribute, copy, create derivative works of, and modify the DINO Materials | same |
| Commercial use | **not mentioned** (no "non-commercial" clause, no "commercial" clause) | same |
| Redistribution by a third party (§1.b.i) | allowed, **only under the same agreement, and a copy of the agreement must be provided** with the materials or derivatives | same, plus: "(B) prominently display 'Built with DINOv3' on a related website, user interface, blogpost, about page, or product documentation" |
| Attribution | only: acknowledge the use in **research publications** (§1.b.ii) | that, plus the "Built with DINOv3" display above |
| Other conditions | comply with law and trade controls (§1.b.iii); no reverse engineering, and do not encourage it (§1.b.iv); not a sanctions target, **no ITAR, military, warfare, nuclear, espionage or weapons end use** (§1.b.v) | same |
| Risk terms | no warranty (§3), no liability (§4), licence ends if you sue Meta over the materials or outputs and you **indemnify Meta** for third-party claims from your use or distribution (§5.b), ends on breach, then delete and stop using (§6), California law and courts (§7), Meta may change the agreement and continued use means agreement (§8) | same |
| Acceptance | "By clicking I Accept below or by using or distributing any portion or element of the DINO Materials, you agree" | same |

**I could not tell which version governs.** Neither GitHub revision contains the display clause. The gated Meta page on Hugging
Face could not be read without logging in. Safe handling that costs nothing: show "Built with DINOv3" in the feature's About and on
each model card, ship the agreement text, and say so to Meta's version if the owner wants certainty.

**Whether our app may download the bundle for the user, or must convert the encoder.** The texts allow third-party redistribution
under the agreement with the agreement attached, and the bundle does attach it. They do not mention a gate for derivatives. The
bundle is a format conversion of the ViT-L/16 weights (`timm/vit_large_patch16_dinov3.lvd1689m`, an **ungated** mirror that carries the
identical `LICENSE.md`); Meta's own repo `facebook/dinov3-vitl16-pretrain-lvd1689m` is **gated, manual approval**, and its form asks
first and last name, date of birth, country, affiliation, job title, IP location, and acceptance of the Meta Privacy Policy. If our
app downloads the file from Hugging Face to the user's machine without hosting it, the texts impose no extra step on the user beyond
the agreement; if our servers carry or mirror it, §1.b.i (and the display clause if it applies) apply to us. Converting the encoder
ourselves needs Python, torch and the conversion tools on the person's Mac, which breaks the "no Python, no compiling" rule of the
component, and still needs the same agreement. **A choice for the owner and a lawyer, not mine.**

**What the owner must do by hand:** only if the conversion route is chosen, accept Meta's gate on the Hugging Face page above (with
the personal details it asks for) in a browser. Nothing in this spike needed it.

## 2. Pin and build

### 2.1 The pin

| Item | Value |
|---|---|
| Release | `v0.10.1-desktop-alpha`, prerelease, published 2026-09-20 |
| Asset | `trellis-metal-macos-arm64.tar.gz`, 2,440,967 bytes, **SHA-256 `66663b1f7af49798c5ae47a6dd2744fbc92e92bfe477f9fb889b839dd33607c8`** (equals GitHub's digest) |
| Contents | `trellis-cli` (1,552,040), `trellis-server` (2,077,680), `libggml*.dylib`; no licence files |
| Hashes | `trellis-cli` `c5fabe6f…fa3`, `trellis-server` `93c2a254…214` |
| Signing | ad-hoc, linker-signed; **`minos 14.0`, built with SDK 14.5** on a `macos-14` runner, `GGML_NATIVE=OFF`; no quarantine flag when fetched with `gh` |
| Commit | **conflict:** the git tag points at `1f432fd3f0689c504fa1e9b15b038c33584174d1` (also the head of branch `release/0.10.1`; the CI run `Build & Release` was started on it); the release text and the binary's own GLB metadata say `add368c651e91b5de942b0700e4352d52912865e`. `add368c` is the same stack of commits with rewritten history (same messages and times, 317 commits differ). **`src/`, `include/`, `CMakeLists.txt` and the ggml pointer are identical** between the two; they differ in docs, removed showcase binaries and 3 lines of `app/src-tauri/src/config.rs`. Pin by asset SHA-256 and record both |
| ggml | submodule `pwilkin/ggml` @ `737e88f25d4f62254f3b7a726fd9663036cc94da`, same on both |

### 2.2 Source build of the same code on this Mac

Needs full Xcode (**installed**: Xcode 27.1, `metal` found) plus cmake and ninja (**not installed; the owner approved a private
`uv` venv with cmake 4.4.4 and ninja 1.13.2**, 55 MB, in the scratch folder). Commands:
`cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=OFF` then
`cmake --build build --target trellis-server trellis-cli -j 8`. **Result: configure and build (201 steps) took 20 s wall in total (48 s CPU, 8 jobs), exit 0,
and it runs** (same mascot picture: silhouette IoU 0.995 to 0.997 against the prebuilt's GLB from four views; not bit-identical).
Differences that matter:

| | Prebuilt (from the release) | My build of `1f432fd` |
|---|---|---|
| Metal tensor API (the M5's matrix hardware path) | **"not supported in this environment - disabling"** (log, every run) | both f16 and bf16 tensor-API tests pass |
| Mascot time | 1361 s and 1043 s (two runs) | **1015 s** (HR shape flow 424 s against 611 s and 506 s) |
| Binary's deployment target | macOS 14 | **macOS 27.0** by default; set `CMAKE_OSX_DEPLOYMENT_TARGET` when we build in CI, and test the tensor path on a macOS 26 Mac (not done) |

The speed gain is a single pair of runs and the noise is about the same size (see "Read this first"); the mechanism (tensor API
off in the prebuilt) is in the logs. A build in CI with a macOS 26/27 SDK is the way to get it. **Not verified:** that a binary
built with the new SDK still runs on an older macOS, and a bit-exact rebuild (the binaries differ in hash by design).

### 2.3 Weights, exactly as run (bundle revisions from `bootstrap_pixal3d.py` of `Bingeljell/image-to-3dlab`)

Single view, `raven38/pixal3d-sv-q8_0-v1` @ `46d399ac986f45a0d7f5b1ca5058614d8729a131`; **9 files, 8,091,975,360 bytes (8.09 GB, 7.54 GiB)**,
every size and SHA-256 matched the manifest:

| File | Bytes |
|---|---|
| `dinov3.gguf` (image encoder, DINOv3 licence) | 323,657,920 |
| `pixal3d_naf.gguf` | 1,334,656 |
| `pixal3d_ss_flow_sv.gguf` | 1,426,559,744 |
| `ss_dec.gguf` | 147,379,392 |
| `pixal3d_shape_flow_512_sv.gguf` | 1,476,761,760 |
| `shape_dec.gguf` | 881,361,568 |
| `pixal3d_shape_flow_1024_sv.gguf` | 1,476,761,760 |
| `pixal3d_tex_flow_1024_sv.gguf` | 1,476,813,984 |
| `tex_dec.gguf` | 881,344,576 |

Cut-out: `ilintar/trellis2-gguf` @ `a57397bd3d351599d9729fc144b3f87c3f87d65b`, `q8/birefnet.gguf`, 882,749,024 bytes.
Multi-view, `raven38/pixal3d-q8_0-v1` @ `1c4f4bdddb5fef1dc5efa512d4b88e899b10bd91`: four more flow files, **5,856,897,248 bytes
(5.86 GB)** (`pixal3d_ss_flow_mv`, `pixal3d_shape_flow_512_mv`, `pixal3d_shape_flow_1024_mv`, `pixal3d_tex_flow_1024_mv`), the
other five shared. Both sets together: about 13.95 GB, plus 0.88 GB for the cut-out model. (The studio quotes 8.4 GB for its
single-view install; the exact bundle total is 8.09 GB.)

## 3. Single view on this Mac (the Pixal3D single-view model, 1024)

### 3.1 How it was run

`trellis-cli --sv-image cutout.png --models <sv dir> --seed 42 --res 1024 out.glb` with the prebuilt binary. **Single view needs
a picture that already has a real transparent background** (the server answers 400 otherwise, see 6); the pipeline's own cut-out is
`trellis-cli picture.png out.glb --models <dir with birefnet.gguf> --bg-only`, which writes `_cutout.png`. So each input is two
runs: the BiRefNet cut-out, then the 3D run. **Cut-out: 36 to 103 s (shorter later in the session), 5.6 GB peak** (the README says the BiRefNet
deformable-convolution kernel has only a CPU fallback on Mac). The cut-out of the mascot looked clean.

The 20 inputs were made with FLUX.2 klein base 4B (28 steps, 97 to 246 s each, **peak footprint 21.6 GB**) from the ADR's wrapper:
"a single object, centred, plain light background, three-quarter view, soft even light". No pictures of people. Seven normal
ones named in the ADR (mascot, product photo = sneaker, pet = cat, plant, chair, sword, building), six more normal ones, and seven
failure cases (glass, two thin-part cases, text on an object, several objects, a mirror-polished object, fur). A 21st input, an
ornate galleon, was added to push complexity.

### 3.2 Results (all single-view, 1024, prebuilt binary, `rc = 0`)

HR tokens = the number of tokens the 1024 shape stage works on. Peak GB = macOS "peak memory footprint" of the process.
Front IoU = silhouette overlap between the input cut-out and the GLB rendered from the front (the pipeline's own camera),
both cropped to their bounding box. 21 is the stress case.

| # | input | class | HR tokens | total s | peak GB | tris | atlas | GLB MB | comps | edges on >2 faces | front IoU |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 01 | mascot | normal | 16237 | 1361 | 18.7 | 959,628 | 4096 | 34.9 | 3 | 2915 | 0.990 |
| 02 | product-sneaker | normal | 10435 | 742 | 18.1 | 998,340 | 4096 | 37.6 | 1 | 495 | 0.990 |
| 03 | pet-cat | normal | 7310 | 526 | 18.2 | 934,230 | 4096 | 33.6 | 1 | 378 | 0.982 |
| 04 | plant | normal | 16462 | 1222 | 18.7 | 976,026 | 4096 | 34.8 | 1 | 1854 | 0.985 |
| 05 | chair | normal | 5653 | 478 | 18.2 | 933,118 | 4096 | 35.4 | 6 | 7537 | 0.950 |
| 06 | sword | normal | 1094 | 241 | 17.7 | 995,184 | 4096 | 42.4 | 3 | 146 | 0.933 |
| 07 | building | normal | 14110 | 1034 | 18.6 | 929,322 | 4096 | 33.0 | 1 | 1025 | 0.977 |
| 08 | robot-toy | normal | 5261 | 394 | 18.0 | 971,602 | 4096 | 35.0 | 1 | 965 | 0.967 |
| 09 | teapot | normal | 10176 | 698 | 18.4 | 940,800 | 4096 | 34.1 | 2 | 997 | 0.988 |
| 10 | treasure-chest | normal | 13576 | 991 | 18.8 | 992,732 | 4096 | 42.3 | 1 | 18857 | 0.985 |
| 11 | backpack | normal | 9037 | 629 | 18.2 | 994,556 | 4096 | 38.4 | 1 | 6616 | 0.986 |
| 12 | dragon-figurine | normal | 10026 | 693 | 18.1 | 978,148 | 4096 | 34.3 | 1 | 180 | 0.969 |
| 13 | toy-car | normal | 11215 | 783 | 18.4 | 955,864 | 4096 | 35.3 | 1 | 1488 | 0.984 |
| 14 | wine-glass | glass | 4660 | 394 | 18.1 | 999,554 | 4096 | 37.0 | 3 | 3859 | 0.986 |
| 15 | thin-wire-lamp | thin parts | 1659 | 198 | 17.7 | 715,136 | 4096 | 30.2 | 1 | 346 | **0.476** |
| 16 | coffee-tin-text | text on object | 13530 | 1022 | 18.5 | 931,290 | 4096 | 33.5 | 1 | 64 | 0.982 |
| 17 | three-fruits | several objects | 5903 | 424 | 18.1 | 972,448 | 4096 | 36.0 | 4 | 128 | 0.974 |
| 18 | bonsai-thin | thin parts | 8469 | 555 | 18.1 | 945,206 | 4096 | 37.4 | 2 | 2406 | **0.472** |
| 19 | chrome-kettle | reflective | 12303 | 873 | 18.5 | 996,898 | 4096 | 35.9 | 2 | 1710 | 0.977 |
| 20 | plush-fur | fur | 14311 | 1029 | 18.6 | 950,952 | 4096 | 34.8 | 1 | 139 | 0.991 |
| 21 | galleon (stress) | complex | 13223 | 968 | 18.4 | 964,522 | 4096 | 39.7 | 1 | 6953 | 0.801 |

Of these, 06 (0.93) and the chair (0.95) are the weakest normal cases; the two thin-part cases score about 0.47 because the
overlap of wires and bare twigs punishes any offset (the pictures look right, see below); the galleon's rigging does the same.

### 3.3 What the pictures show (rendered from four sides with Blender; contact sheets in `out/contact/`)

- **Geometry and colour follow the picture well for compact objects** (mascot, sneaker, cat, plant, chair, sword, building,
  robot, teapot, chest, backpack, dragon, car, fruit, tin). Colour is **darker or duller** than the picture in places (the chair's
  green seat becomes olive; the multi-view result turned the mascot redder).
- **The wrapper's "three-quarter view" makes models lean.** The single-view model assumes a camera at eye level, so a picture
  taken from above comes back tilted: the plant pot, chair, car and chest lean. **Test:** the same plant, asked for "straight-on front
  view at eye level" instead, came back upright with a sensible back (1324 s, 18.7 GB). **ADR-0080's wrapper should say "front
  view, eye level"**, and the input check should say so.
- **Glass:** the wine glass keeps its outline from the front, but from the sides the bowl is crumpled and the stem leans; it is a
  textured shell, not clear glass.
- **Thin parts:** the wire lamp and the bonsai come back as thin structure (715k and 945k triangles, not the 1M target), right in
  outline, loose in detail. The galleon's rigging is turned into lumpy ropes.
- **Text on an object:** the front "COFFEE" is crisp; the sides wrap or crop it, nothing invented that reads as text.
- **Several objects:** four components; the orange became a flat disc and parts merge. Do not promise several objects.
- **Reflective:** the "chrome" kettle comes back as a **white matte kettle**: the base colour is 254 white and the metal channel is
  near zero (checked in the file and in `<model-viewer>`). Mirror finishes are lost.
- **Fur:** the plush rabbit is fine as a soft white form without fur detail.

### 3.4 Time, memory, failures

- **Time = 45 s + 0.07 s x HR tokens** (21 inputs, r = 0.98): 198 s at 1,659 tokens, 1361 s at 16,237. **Median 696 s, mean 714 s.**
  A fixed ~93 s goes to the first stage (picture features and the sparse-structure flow) even for the smallest object. The mascot
  took 1361 s (prebuilt), 1043 s (prebuilt, `--dump-post` run to the same flows) and 1015 s (source build).
- **Memory:** 17.7 to 18.8 GB peak (process footprint), RSS peak up to 19.3 GB; nearly independent of the object (the weights dominate).
  Do not promise it on a 16 GB Mac; a 24 GB Mac is not measured. The cut-out stage peaks at 5.6 GB (not overlapped). Each run also
  leaves a 181 MB `.ply`, a 30 MB PNG and a staging folder next to the GLB (about 245 MB per run): the component must delete them.
- **Failures: none.** 27 command-line 3D runs (21 inputs, plant-eye, frog, multi-view, dump-post, source build, 1536) and 2 server
  jobs (one aborted by the client), 23 cut-outs and 26 picture generations all returned 0 or completed. The README's remark about Metal command-buffer
  failures on complex runs did **not** reproduce, but my largest object was 16,462 tokens against a cap of 49,152; **heavier objects
  (the README's 45k-token "turret") were not tried.**
- **Resolution:** the single-view CLI and server **refuse 512 and 1536** ("supports --res 1024 only in this release", 400 from the
  server); there is no 512 texture flow. **1536 through the multi-view path with the single-view weights** (an unsupported route:
  `--views <staged dir> --pixal3d-weights sv --res 1536`): the chair took **944 s** (against 478 s) at **26.3 GB**, gave one component
  (against six) and fewer bad edges (1124 against 7537), silhouette IoU 0.96 against the 1024 version; the picture looked as good.
  **Do not offer 1536 in v1.**

## 4. Multi-view

Four views 90 degrees apart (front, right, back, left, elevation 0, field of view 20 degrees, distance 3.119: the engine's canonical
rig, no `transforms.json`, `--mesh-scale 1.0`) were **rendered from the mascot's single-view GLB with Blender** (flat albedo, RGBA with
a real alpha). The multi-view run (`--views DIR`, multi-view weights) took **1506 s, peak 20.4 GB RSS / 20.0 GB footprint, return 0**:

| | single view (mascot) | multi-view |
|---|---|---|
| time | 1361 s (1015 s source build) | 1506 s |
| peak memory | 18.7 GB | 20.0 to 20.4 GB |
| GLB | 959,628 tris, 34.9 MB, 3 comps | 967,442 tris, 33.5 MB, 10 comps, 446 edges on >2 faces |
| agreement with the four views | front 0.990 (it saw one view) | **all four views, silhouette IoU 0.974, 0.973, 0.973, 0.975**; colours redder than the input |

**Caveat:** the views came from the single-view model, so this tests that multi-view is consistent with its own inputs, not which
model is closer to a real object (I had no real four-photo set or ground-truth model). The engine needs pre-matted RGBA views and a
`mesh_scale` that is not guessed. Multi-view adds 5.86 GB of weights and about 10 percent more time. Offer it in TD3, not v1.

## 5. The output file

| Viewer | Result |
|---|---|
| **Blender 5.2.2 LTS** (headless import) | opens, one mesh, WebP textures decoded (two 4096 images), material present; checked on the mascot, chair, lamp, kettle and a 50k replay. Blender sees the UV seams as open edges, which is normal |
| **`<model-viewer>` 0.8.2** (the copy vendored by `pixal3d.cpp`, in the built-in browser, WebGL on) | loads and renders the 35 MB mascot, the chair and the kettle with their textures; load events fired, no error. **It must be created with `loading="eager"`**, otherwise a hidden pane never loads the model. The GLB's front faces glTF -Z, so a viewer must start at a camera orbit of about 180 degrees to show the front. **A headless Chrome render for Video Builder was not tried** |
| **macOS Quick Look** | `qlmanage -t` hung, and `QLThumbnailGenerator` returns "Could not generate a thumbnail" (code 102) **for our GLB and for a plain Blender-exported sphere GLB**, so the system has no GLB generator in this session; `mdls` does classify the file as `org.khronos.glb`. A visible `qlmanage -p` window was **not verified** (I stopped using screen capture after one capture showed unrelated personal content, which I deleted) |

Findings about the file:

- **Required extension: `EXT_texture_webp`** (listed as required). Viewers without it cannot open the file. `--webp off` writes PNG
  textures; **not tested**, and it would be much larger. Blender and `<model-viewer>` handle WebP.
- **Contents:** one mesh, one material (a base-colour RGBA texture and a metal/roughness texture, both 4096), positions, normals, one UV set.
- **Not watertight.** After welding vertices by position: **0 open edges**, but 64 to 18,857 edges shared by more than two faces, 1 to 6 components,
  up to 986 degenerate triangles; one picture (mirrored "chrome") has two parts. STL export needs a repair step first (as ADR-0080 says).
- **The face budget is fixed at 1,000,000** in the single-view and multi-view path (`decimate_qem(... 1000000 ...)` in `trellis_cli.cpp`);
  the lamp had fewer because there was less surface. **There is no flag for 50k or 200k.** The `--decim` flag is the older cluster-grid
  method; `--atlas` and `--tex-res` set the texture. I got the settings by running the single-view flows once with `--dump-post` (1043 s) and
  replaying the post-processing with the `post-replay` tool built from the same source (130 to 170 s each, 12.3 GB):

| Setting (mascot) | Triangles | Texture | GLB size | Blender |
|---|---|---|---|---|
| 1,000,000 faces, atlas 4096 (the engine default) | 958,940 | 4096 x 2 | 33.9 MB | opens |
| 200,000 faces, atlas 2048 | 198,826 | 2048 x 2 | 6.6 MB | opens |
| 200,000 faces, atlas 4096 | 198,826 | 4096 x 2 | 7.3 MB | opens |
| 50,000 faces, atlas 2048 | 47,856 | 2048 x 2 | 1.8 MB | opens |
| 50,000 faces, atlas 1024 | 47,856 | 1024 x 2 | 1.6 MB | opens |

A replay at the default (958,940 triangles) is close to but not identical with the real run (959,628, 4 components against 3), so the
replay tool is a stand-in. At normal viewing sizes 50k looked fine; zoomed in, only the 1M version kept the fur micro-texture.
**Light 50k and Standard 200k therefore need either a patch (a face-target option) or a repair/decimate step of our own that
keeps the UVs; neither is built.** Presets can map to atlas 1024 / 2048 / 4096 without a patch.

## 6. The server

`trellis-server --models <mv dir> --models-sv <sv dir> --host 127.0.0.1 --port N` (loopback by default; **no authentication**).
Idle: 8 MB RSS, up in about 1 s. Weights load per request (per stage, then freed).

| Route | What it does (measured) |
|---|---|
| `GET /health` | `ok` |
| `GET /capabilities` | `{"busy":bool,"completed":N,"mv":{"configured","available","model_set","version","model_family"},"sv":{...}}`; checks files and sizes, not hashes; shows if a model set is missing and why |
| `POST /generate-sv` | multipart: `image` (PNG with a real alpha only, 64 MiB, 64 megapixels), optional `fov` (radians), `seed`, `resolution` (**1024 only**), `uv` (xatlas or box); returns `model/gltf-binary`. Errors are JSON with 400 (no image, no alpha, bad resolution) or 503 (model set missing) or 500 |
| `POST /generate-mv` | `view0..view3` RGBA parts, optional `transforms`, `mesh_scale`, `seed`, `resolution` (1024/1536), `uv`, `band`, `webp`, `num_views` |
| `POST /generate` | the single-image TRELLIS.2 path (not used, not tested) |
| `/progress`, `/status`, `/cancel`, `/jobs`, `GET /generate` | 404 |

- **Progress:** none over HTTP. `capabilities` gives only `busy` and a `completed` counter. Stage lines (`[1/6] ... [6/6]`, `[flow] n/12`
  with a time estimate) are printed on the **server's stdout**, so the app must read the process output to show progress.
- **Cancel:** none. A client that closes its connection does not stop the job: after I killed the client at 90 s, `busy` stayed `true`
  for another 135 s until the job finished by itself. The only way is to stop the process (**SIGTERM works: exited in under 3 s**).
  Requests are serialised by a mutex (one slot, as ADR-0056 wants); a second request waits (not stress-tested).
- **Memory:** the chair through the server took 456 s (the CLI 478 s) and produced the same GLB except 5 bytes (a timestamp): deterministic
  for a fixed seed. Sampled footprint (every 20 s; **it under-reads the peak, which the CLI measured at 18.2 GB**): 7.5 GB at most; after the
  job **2.5 GB footprint (4.4 GB RSS) stayed held**, 1.0 GB after the second job; it did not return to the idle 2.5 MB until the process exited.
  So "release memory afterwards" means: stop the server process (it starts in about a second).
- **Guard rails seen:** the server answered a missing alpha with "input image has no real alpha matte; provide a pre-matted RGBA image" and
  1536 with "single-view generation supports resolution 1024 only".

## 7. Text to 3D

Prompt (mine): "a ceramic mug shaped like a cartoon frog, green glaze, smiling face", wrapped as the ADR says. Four candidates with FLUX.2 klein base
4B via mflux took 97, 100, 104 and 106 s each (peak 21.6 GB). I picked candidate 2 (the frog with the handle most clearly drawn),
cut it out (100 s) and ran it: **1145 s, 18.5 GB peak, front silhouette IoU 0.987**; the back and sides are plausible (a glazed frog
body, handle, bare base). Total from words to GLB on this Mac: about **28 minutes** (candidates 407 s, cut-out 100 s, 3D 1145 s) plus
the time the person spends choosing.
Candidates and result: `inputs/t2i/`, `out/contact/t2i-frog.jpg`. What to change from ADR-0080:

1. The wrapper must ask for a **front view at eye level**, not "three-quarter view" (3.3).
2. The app needs its own **cut-out** step (BiRefNet GGUF, 0.88 GB, 36 to 103 s) or an alpha from the image model, because single view takes only a
   matted PNG.
3. The time to promise is **"about 5 to 25 minutes"** (3D 3 to 23 minutes plus the cut-out), set by the object's complexity, which the
   app only learns after the structure stage (about 93 s in), so the estimate can be refined once a run has started.

## Descriptors (measured here, M5 Pro 64 GB)

```yaml
- id: pixal3d-cpp-sv
  engine: pixal3d.cpp v0.10.1-desktop-alpha (Metal), model set pixal3d-sv-q8_0 v1
  resolution: 1024            # the only single-view resolution the release accepts
  time_s: {min: 198, median: 696, max: 1361}   # 21 pictures; ~45 s + 0.07 s per HR token; plus 36-103 s cut-out
  memory_gb_peak: 18.8        # max process footprint (RSS 19.3); cut-out stage 5.6 GB separately
  weights_gb: 8.09 (+0.88 cut-out)
  outputs: GLB, ~1M triangles (face budget fixed), 2 x 4096 WebP textures, 30-42 MB
  licence_flags: [mit_code, mit_flow_weights, dinov3_conditional, birefnet_gguf_unlabelled, naf_label_unverified]
  commercial_use: conditional  # DINOv3 agreement + display/attribution; nothing in the texts bars commercial use
- id: pixal3d-cpp-mv
  engine: same binary, model set pixal3d-q8_0 v1 (+5.86 GB)
  resolution: 1024            # 1536 offered by the engine, not run
  time_s: 1506                # one run, mascot
  memory_gb_peak: 20.4
  inputs: four pre-matted RGBA views 90 degrees apart, mesh_scale
  commercial_use: conditional  # as above
```

## DINOv3 position

- **The texts do not bar commercial use and do allow third-party redistribution** under the same agreement with the agreement attached. The
  bundle attaches it. Download-by-the-user from Hugging Face needs no click from the user in the texts; **hosting or mirroring it
  ourselves would make us a distributor.** Meta's website text adds the "Built with DINOv3" display; the GitHub/Hugging Face text does not.
- **Recommended handling (for the owner to confirm):** the app downloads the bundle from its Hugging Face repo at the pinned revision, shows
  the Meta agreement in the install card, shows "Built with DINOv3" in the feature's About and on each model's card (costs nothing and
  covers the stricter version), keeps `DINOV3_LICENSE.md` next to the file, and records `commercial_use: conditional`. Do not mirror it.
  Converting the encoder ourselves is not worth it: it adds a Python stack and the same agreement.
- **Open:** ask the bundle's author (or Meta) which text governs; resolve the NAF label; confirm the BiRefNet GGUF's licence with its
  author.

## Go or no-go

- **TD1 (platform: component, creation kind, actions, viewer): GO**, on these conditions:
  1. Pin by the asset SHA-256 above **and build our own binary in CI** from the pinned code with a current SDK (the tensor API is off in the
     prebuilt), with the licence and notice files added; set the deployment target; keep the prebuilt as a fallback.
  2. Run the server as a managed loopback process with the process output read for progress, **kill the process to cancel and to free memory**,
     and delete the leftover `.ply`, PNG and staging folder.
  3. A cut-out step is part of the component (BiRefNet GGUF), because single view needs a matted PNG.
  4. Presets: map **Light / Standard / Detailed** to atlas 1024 / 2048 / 4096 now; the 50k / 200k face targets need a small patch to
     `pixal3d.cpp` (a face-target option) or a UV-preserving decimate. Until then offer only the 1M mesh.
  5. `<model-viewer>` (approved in ADR-0080) with `loading="eager"` and a start orbit of 180 degrees; GLB needs `EXT_texture_webp`;
     Quick Look cannot preview it, so export USDZ or OBJ later if Mac users expect Finder previews (not tested).
- **TD2 (the screen): GO**, on these conditions: the wrapper becomes "front view, eye level"; the input check asks for one object,
  straight-on, plain background; say "about 5 to 25 minutes"; warn that glass, mirror metal, several objects and very thin parts do not come out
  well; offer 1024 only; keep multi-view and 1536 out of v1. The Mac needs about 19 GB free for the run (24 GB not measured).
- **Not decided here:** the DINOv3 position is the owner's (above); quality against the CUDA original is not measured.

## Not done or not verified

- Q8_0 against original CUDA quality; a CI build of the same commit; a rented-GPU run; TRELLIS.2 (out of scope).
- Quick Look preview window; headless-Chrome render of a GLB; `--webp off`; the NAF weights licence; the BiRefNet GGUF's licence; MoGe-2 (not run);
  which DINOv3 text governs; a macOS 26 run; a 24 GB or 16 GB Mac; objects above 16,462 HR tokens; two requests at once on the server;
  multi-view at 1536; a multi-view run from real photographs.
- Timing contention was not controlled (see the first section); bit-exact reproduction of the prebuilt binary.

## What the owner must do next

1. Decide the DINOv3 route (recommended above) and, if wanted, have the display clause and the NAF label checked; accept Meta's gated page by hand
   in a browser **only** if the conversion route is chosen.
2. Say yes or no to patching `pixal3d.cpp` (face-target option) for the 50k / 200k presets.
3. Approve building the pinned commit in CI with a current SDK (and testing it on a macOS 26 Mac).
4. Optional: one run on a rented NVIDIA GPU for the Q8_0 quality comparison.

## Files in the scratch folder

`td0/` has: `inputs/` (20 pictures and cut-outs, the 4 text-to-picture candidates), `out/sv1024/` (21 GLBs), `out/mv/`, `out/res1536/`,
`out/srcbuild/`, `out/replay/`, `out/contact/` (contact sheets), `out/server/`, `logs/` (`runs.tsv`, `stages.tsv`, `server_test.log`, every
`.out/.err/.time`), `tools/` (the lock wrapper, queue, GLB checker, Blender rig, IoU) and `src/` (the licence texts read, the build).
