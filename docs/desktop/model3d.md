# 3D models on the desktop

Part of [the desktop profile](../desktop-profile.md): what is built, how it is wired, what is not done.

## 3D models (ADR-0080, stages TD1 and TD2; experimental)

A 3D model made from a picture, or from words through a picture, on this computer. It is always in the
menu, as **3D model** (its own item after Motion graphics since 2026-10-24); the screen says it is experimental. Details and measurements: `docs/spikes/pixal3d-td1.md`.

| Piece | What |
|---|---|
| The component | `<app data>/components/model3d/`: the pinned `pixal3d.cpp` Metal build (`trellis-cli`), the Pixal3D single-view Q8_0 weights with the DINOv3 encoder and the BiRefNet cut-out model, **8.98 GB** shown before the click, resumable and hash-checked. `GET /desktop/model3d`, `POST /install` (the size shown must be sent back), `/install/cancel`, `/uninstall`. Apple-silicon Macs only |
| The engine | `desktop_model3d.py`: one process of `trellis-cli` per run (the cut-out, then the 3D run); progress from its output, cancel by killing the process group, the one big-model slot held while it works; about 19 GB of memory, 5 to 25 minutes |
| The product | `products/wasifyai-model3d`: pictures and models in `<app data>/model3d/model3d.db` and files beside it, one job at a time, routes under `/products/wasifyai-model3d/m3d`; a model is the creation kind `model3d` (search, library, rename, save a copy) |
| The screen | start from a picture or from words (four candidates from the image engine), the picture checks in words and the cut-out, Light / Standard / Detailed, progress with stages, a viewer (`<model-viewer>`), Save a copy (GLB), Make it again |
| Licence | "Built with DINOv3" on the setup card, the screen and each model; Meta's agreement and pixal3d.cpp's licence and notice travel with the files |

Not built: four photos around an object, a turntable video, 50k and 200k face targets, our own CI build of the binary, the web version.
