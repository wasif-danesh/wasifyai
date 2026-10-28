# The image screens on the desktop

Part of [the desktop profile](../desktop-profile.md): what is built, how it is wired, what is not done.

## Recipes, favourites and saving a copy (stage B)

Every image row keeps a **recipe** (`images.recipe`, versioned JSON: prompt, mode, size name, width, height,
seed) and a `favourite` flag. A run may carry a `seed` (0 to 2^31-1; anything else is refused before any work);
without one the graph draws it, so the recipe always holds the seed that made the picture.

| What | Where |
|---|---|
| `PATCH /products/wasifyai-image/images/{id}` `{favourite}`, `GET .../images?favourites=true` | `products/wasifyai-image/wasifyai_image/routes.py` |
| `POST .../images/{id}/export`: body `{path}` writes the file at the path the person chose in the system's Save As box (the window opens it with Tauri's dialog plugin and cannot write a file itself; the engine refuses a folder, a missing folder and anything inside its own data folder); without a `path` it copies into the export folder (`WASIFYAI_EXPORT_DIR`, which the shell sets to the operating system's own Downloads folder, for the assistant's export action) and never overwrites. The video, 3D and notebook-output export routes take the same `{path}`; screens that hold the bytes themselves (speech, music, transcripts, lip sync, a source's original) send them to `POST /desktop/save` with the path. Answers `{name, path}`; 404 where no folder is set (web profile) | same; `export_dir` of the engine's services is set by the desktop builder in `assemble.py` |
| Postgres columns | migration `0017_image_recipes` |
| SQLite columns on an older file | migration 1 of the image store (`SQLITE_MIGRATIONS`, `columns=`), run by the SDK's `migrate` (stage J1) |
| "Make it again" | text images with a recipe only: an edit's source picture is deleted once the image is saved |

The recipe does not name the model: the graph asks for a capability. The same seed gives the same picture on the
same installed model. `docs/phase2-stage-b-plan.md` has the decisions.

### Reference and Inpaint (built 2026-10-21; `docs/image-inpaint-reference-plan.md`, `docs/spikes/image-ir0.md`)

Both run on FLUX.2 klein 4B through ComfyUI; no new model.

- **Reference** (*Images › Reference*, action `image.reference`): two pictures and a prompt make a new picture at a size the person
  chooses. Workflow `flux2-klein-4b-reference`: the Edit mechanism with a second reference, each picture scaled to half a megapixel
  (about 70 s instead of 100 to 120 s at a full megapixel, with both subjects still recognisable). Exactly two pictures.
- **Inpaint** (*Images › Inpaint*, action `image.inpaint`): the person paints the area (brush, eraser, rectangle, or a rectangle by
  numbers for the keyboard) and says what to put there. Workflow `flux2-klein-4b-inpaint`: klein has no inpainting model, so the
  Edit workflow runs on a copy of the picture with the area filled white ("fill the white area with ..."), and the result is pasted back
  through the mask: **outside the mask the picture is identical to the last pixel** (tested: two runs with different prompts and seeds
  agree on all 916,567 pixels outside the grown mask). The picture is worked on at about one megapixel. The model sometimes ignores a
  small area. The agent's `image.inpaint` takes a rectangle (shares of the picture) because an agent cannot paint.
- Each takes up to three uploads per run (`image`, `image2`, `mask`; `PICTURE_SLOTS` in the SDK); the graph deletes all of them on every
  way out. The mask is uploaded when the person presses Generate and is checked (not empty, not nearly all of the picture, the
  picture's shape) before any GPU work.

### Styles (LoRAs), Vary and Edit this result

A request may carry `loras: [{name, weight}]` (at most 3, weight 0.1 to 2.0, names relative to a `loras` folder).
The image graph validates them before any model is asked, the recipe keeps them, and a workflow whose map file has
no `lora_chain` refuses them. `GET /desktop/loras` answers `{ready, available}`: a LoRA in a ComfyUI-layout folder
(`<root>/loras/...`) is usable once its root is a read-only folder ("Use it"); the app's own `models/loras` folder
is scanned too. The loader is model-only (`LoraLoaderModelOnly`). A missing file stops the job with `lora_missing`.
Vary re-runs the recipe with a new seed; Edit this result makes the picture Edit's source. Evidence and numbers:
`docs/phase2-stage-c-plan.md`.

The window may `PATCH`: the desktop CORS list includes it (the self-test found it was missing).
