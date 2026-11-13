# TD1 and TD2: the 3D component, the product and the screen (built and measured 2026-10-21)

What ADR-0080 asked for after the TD0 spike, built (experimental, in the menu): the component, the engine's 3D service, a product, the creation
kind, one action and the screen. The owner's decisions of the day: the upstream prebuilt binary pinned by hash, real
generations during the build, no further approvals. Measured on the owner's M5 Pro, 64 GB.

## What was built

| Piece | Where | Notes |
|---|---|---|
| Pins | `services/api/src/wasifyai_api/model3d_pins.json` | The release asset (2,440,967 bytes, SHA-256 `66663b1f...607c8`), 13 weight files and the BiRefNet file, each with size and SHA-256. **Every URL was asked for its `Content-Length` and matched the pinned size.** Total 8,977,179,071 bytes |
| Component | `model3d_runtime.py` | Finder (`WASIFYAI_MODEL3D_HOME` for development), installer (nothing fetched before the size shown is sent back; resumable hash-checked downloads; licence texts written beside the files; the engine is started once to check it), uninstall |
| Engine service | `desktop_model3d.py` | A process of `trellis-cli` per run; progress read from its output; cancel kills the process group; holds the one big-model slot; fit check; routes `/desktop/model3d` |
| Product | `products/wasifyai-model3d` | Store, picture checks, job manager, routes, one action, the library kind, the search source |
| Screen | `packages/ui/src/model3d`, `packages/client/src/model3d.ts` | From a picture or from words (four candidates), the check, the detail, progress, the viewer; menu item, desktop page |

## Measured, through the product's routes with the real engine and the real pinned binary

| Step | Result |
|---|---|
| Cut-out of a picture (a sword, 06 of the TD0 set) | **38 s**, 5.6 GB, a real RGBA cut-out; the checks said "One object, in the middle, with all of it showing" |
| 3D run, Light (atlas 1024) | **224 s**, peak **17.8 GB**, a GLB of **40.3 MB**, 993,988 triangles, 2 textures |
| 3D run, Detailed (atlas 4096) | **234 s**, peak 17.8 GB, **42.4 MB**, 993,988 triangles. The texture size changes the file by about 2 MB and the time by about 4 %: at a million triangles the geometry is the file |
| Progress | 49 updates over the run, never going back, through the six stages in plain words (the stage shares come from one 741 s run of TD0, so the bar is an estimate) ("Looking at the picture", "Placing the object in space", "Building the shape", "Cleaning up the mesh", "Painting the surface", "Saving the file") |
| Whole flow through the routes (upload, cut-out, checks, make, GLB, thumbnail) | **272 s** for this object; the GLB is valid (`glTF` v2, one mesh, `EXT_texture_webp` required), the extra files the engine leaves (a 181 MB `.ply`, PNGs, a staging folder) are deleted, and no engine process is left |
| Cancel while it works | the process is gone in **under 10 s** (the test allows 15), the slot is free, the status says not busy |

## The screen in the running app (checked 2026-10-21)

The real engine and the real window code, in the browser pane with a stand-in for the Tauri shell (the shell's commands answered by
a small script kept outside the repo), the window's content security policy sent as a header, and the TD0 weights.

| What | Result |
|---|---|
| Images › 3D model | The menu item is there from the start (the Labs switch was checked first, then removed the same day), the screen opens |
| A picture (a teapot, 0.9 MB) | Both pictures show; "One object, in the middle, with all of it showing"; the button stays off until the rights box is ticked |
| 3D run, Standard (atlas 2048), a blue porcelain teapot | **1,254 s (21 minutes)**, a GLB of 33.0 MB. The bar moved through the stages in words (8 % "Placing the object in space", 32 % "Building the shape", then on to 100 %) |
| Viewer | The textured model shows, turns when dragged; it also works with the window's policy (`blob:` in `connect-src`) and the library card's picture loads |
| Rename, library card | The new name is kept; the card shows the model's picture |
| Search | Found by its words, with `kind=model3d` and without, after the engine's start-up back-fill |

**The run took five times as long as the sword's** (224 to 234 s; TD0 had one 741 s run). The machine had 17 GB free of 64 GB, but swap showed
7.8 GB in use during the run, so memory may have played a part; the browser pane and other idle sessions were open; the detail
does not explain it (Light and Detailed differed by 4 %). Whether it is the object or the load was not tried; "5 to 25 minutes" on the screen holds, the teapot is
near its top.

**A bug found by looking:** the search route listed the creation kinds by hand and lacked `model3d` and `composition`, so a search
that found one would have failed and the kind could not be asked for. The route now uses the SDK's own list, with a test over
every kind.

Still not looked at: the real Tauri window (the stand-in is not the shell), the "Words" path with four candidates (the image engine
was the stub), a 16 or 32 GB Mac.

## Tests added

31 in the component and engine (pins checked, finder, installer with stand-ins, progress read from a real run's output, the two runs
with a fake engine including cancel, wall limit, slot), 44 in the product (picture checks on synthetic cut-outs, store, routes, job
manager, action, library kind, search), 7 in the client, 26 for the screen, 1 for the desktop menu, 2 gated real-engine tests
(`services/api/tests/test_model3d_real.py`, opt in with `WASIFYAI_MODEL3D_RUN=1`), one search corpus row.

## Decisions taken while building

- `trellis-cli` per run, not `trellis-server` (no progress, no cancel, memory kept: TD0 section 6).
- A product of its own (`wasifyai-model3d`), not part of the image or video product: its store, files, engine and screen are its own.
- `model3d.generate` is the only action; the rest is the library's. The catalogue's upper bound moved from 45 to 50.
- The window's content security policy gained `blob:` in `connect-src`, because the viewer reads the model the window fetched.
- Detail names map to the atlas sizes 1024, 2048 and 4096; the screen says that the model itself stays the same size.

## Not done

Four photos around an object (TD3), a turntable video for Video Builder, the 50k and 200k face targets (a patch to `pixal3d.cpp`), our
own CI build of the binary (the prebuilt turns Metal's tensor API off on this Mac; TD0 saw a source build run faster, within the noise of two runs), the web version, a card in
the web library, 16 and 32 GB Macs (the fit check refuses what cannot fit; nothing was run), a full from-scratch download of the weights
through the installer (the pins and sizes were checked against the servers, the installer is tested with stand-ins and the weights
used for the runs are the TD0 downloads). The screen was looked at in the browser pane (above), not in the Tauri window.
