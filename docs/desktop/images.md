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

The graph asks for a capability, not a model. Since ADR-0097 the recipe also keeps the model the person chose
(`model`, the product's first when it was left out), so "Make it again" uses the same one. The same seed gives the
same picture on the same installed model.

### Several models (ADR-0097, built 2026-11-07; `docs/image-video-models-plan.md`)

`product.yaml` lists `models:`, each with the capabilities it binds: FLUX.2 klein 4B (all four), Qwen-Image 2.1
(Create, Edit, Reference), Z-Image Turbo (Create), HiDream-O1 (Create), Ideogram 4 (Create), FLUX.3 Image Klein (Create,
Edit; its 8-bit int8 files, which run on a Mac) and FLUX.2 klein 9B (all four; its bf16 file, since the fp8 one does
not load on Apple's graphics chip). The person picks one with "Select image model"; the window
remembers it (`wasifyai:model:images`) and sends its id as `model` on every request. The engine's
`GET /desktop/models` gives each entry `can` (its capabilities, from `product.yaml`), so the side menu leaves out what the
chosen model cannot do and a screen opened anyway says so instead of making. The graph refuses an unknown model or one
that cannot do the mode before any work. Measured here (ComfyUI 0.44.2, 1024 px, first run includes loading): Qwen-Image
2.1 at 20 steps 137 s; Z-Image Turbo at 8 steps, see the plan; FLUX.3 Image Klein at 16 steps 60 s for 1344x768 once
loaded (108 s for the first picture with the load) and an edit at 1024 px in 121 s. FLUX.2 klein 9B at 1024 px: 104 s for the first picture with
the load, 25 s once loaded, an edit in 47 s (2026-11-08). `docs/phase2-stage-b-plan.md` has
the decisions.

**A model's prompt writer.** Ideogram 4 draws a refusal card for a plain sentence and a good picture for its structured
caption (a JSON object of a description and the picture's parts with their boxes). Its entry in `product.yaml` names a
writer in `settings` (`prompt_writer: write_ideogram_caption`, a prompt in `prompts/`); before the job the graph shows
"Writing the picture's caption", runs the person's words through `text.enhance` with that prompt (two tries), checks
the reply (`wasifyai_image/caption.py`: at most 8 parts, boxes kept in the frame, the shape the nearest common one) and
sends the caption as the job's prompt. The person's own words stay the picture's prompt and recipe. When the text model
cannot write it, the request is refused with `model_unavailable`: "This model needs the text model to write its
caption, and it could not."

**On the web** the admin chooses the model each product uses (Admin › Media › Models, below); a request that names
none uses it when it can do the mode, else the product's first model.

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

A request may carry `loras: [{name, weight}]` (at most 8, weight 0.05 to 2.0, names relative to a `loras` folder)
or, on the desktop, `styles: [{id, strength}]`: ids of the style records the engine keeps (ADR-0091 S1,
`desktop_styles.py`): each style is a file in `<models>/loras` with a `<file>.style.json` sidecar (title, source,
SHA-256, size, the model read from the header, fit, made for klein base, rank, trigger word). `GET /desktop/styles`
lists them (Train's first; files with no record are adopted), `POST /desktop/styles/import?name=` takes a file as the
body and keeps a checked copy, `PATCH` renames or sets the word, `DELETE` removes our copy. Only `.safetensors`; the
header alone is read; a style made for another model is not selectable and is refused in a request.
The screen (S2): the Styles section is always in view on Create, Edit, Inpaint and Reference (`StylesSection`);
its Add menu lists yours first, the styles kept here, the ones another app keeps (`POST /desktop/styles/from-found`
copies one in) "From this computer…" (`ImportStyleDialog`) and "From Hugging Face…" (`HubStyleDialog`, S3: a repository's
`.safetensors` files after browsing is allowed, the confirmed file fetched at its commit with its checksum, then
checked like any style; `/desktop/styles/hub/...`); Train's Try it has **Use in Create**.
S4: **Advanced** (steps, seed, how many pictures, a size of one's own; the graph takes `steps`, `width`,
`height`), **Saved looks** (`/desktop/styles/looks`), "Make it again" with the styles' ids and checksums, and the
actions `styles.list`, `styles.add_from_hub`, `styles.remove` plus `styles` on the image actions.
S5: **Recommended** in the Add menu (three styles checked in S0, pinned by checksum). On the web the same section
is read only over the styles an admin added in Admin > Styles (`service_styles.py`).
The image graph validates them before any model is asked, the recipe keeps them, and a workflow whose map file has
no `lora_chain` refuses them. `GET /desktop/loras` answers `{ready, available}`: a LoRA in a ComfyUI-layout folder
(`<root>/loras/...`) is usable once its root is a read-only folder ("Use it"); the app's own `models/loras` folder
is scanned too. The loader is model-only (`LoraLoaderModelOnly`). A missing file stops the job with `lora_missing`.
Vary re-runs the recipe with a new seed; Edit this result makes the picture Edit's source. Evidence and numbers:
`docs/phase2-stage-c-plan.md`.

The window may `PATCH`: the desktop CORS list includes it (the self-test found it was missing).

## Cloud models (ADR-0100, stage CP4)

With a Runware, WaveSpeed or fal.ai key (Settings › Your keys, for Images or for Every media product), the picker's
Cloud tab offers GPT Image 2.5, Nano Banana 2.1, Grok Imagine Image 2.0, FLUX.3 klein and Z-Image Turbo, each once,
"from" its lowest price with the keys there are. Each job runs on the cheapest offer that can do it: make, change
(Edit) and combine (Reference) on every model; Inpaint (`mask`) on GPT Image 2.5 and Z-Image Turbo only, so the screen
blocks Inpaint before Make for the other three. A provider that refuses before running hands the job to the next
offer. The requests are `services/media-worker/.../cloud_recipes.py` (the field names of each provider's schema,
`docs/spikes/fal-v1-fa0-inputs.md` and `docs/spikes/cloud-v1-cp0.md`); input pictures go to fal.ai's and WaveSpeed's
file stores first and inside the task on Runware; OpenAI's mask is turned into its clear-where-it-changes form. Looks
taught on this computer are for this computer's models and are refused on a cloud model; looks taught on a cloud
trainer are used as below. Checked against fakes only; the real run is CP13.

### Looks taught on a cloud model (ADR-0100, stage CP10)

With a key for Train models (Settings › Your keys) and a cloud trainer chosen under "Where it is taught" on the
pictures card (the Training group of the model picker: "This computer (AI Toolkit)" or, under Cloud, "FLUX.3 klein
look" or "Z-Image look"; `apps/desktop/src/choices/train-choices.ts`), Teach it sends the pictures and their captions as one zip (`001.png` beside `001.txt`) to the cheapest trainer with a
key instead of AI Toolkit on this computer: FLUX.3 klein on fal.ai; Z-Image on Runware (style looks only) or fal.ai
(style or a person or thing). It is priced per step and writes a `cloud.cost` usage event; a cloud run cannot be
paused. The look's file is kept beside the other styles as `wasify-cloud-<title>-<run>.safetensors` with where the
provider keeps it and the cloud model it is for (`cloud` in the styles list). On Images, a cloud look is chosen like
any style; the job carries its address (`lora_urls`) and runs on fal.ai's `lora` endpoint of that model, even when
another key is cheaper. A look taught on this computer, or for another cloud model, is refused in words. The code is
`services/api/.../cloud_train.py` (`CloudLookTrainer`), `desktop_styles.py` and `OfferRunner._check_looks` in the
media worker. Not built: video looks (no cloud video model in the catalogue takes a look since LTX-2 left in CP5);
the web's Train cards on the cloud come with CP11. Checked against fakes only; Runware's `modelTraining` task and its
answer field, fal.ai's trainer fields and `training_type` are checked in the real run (CP13).
