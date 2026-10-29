# ADR-0091: Styles (LoRAs) in the image screens: add, check, stack and reuse them

- **Status:** Accepted (owner, 2026-10-25: "Take your recommendations on all seven questions", recorded in "Owner's answers" below).
  **Nothing is built; stage S0 (the measuring spike) starts when the owner says.**
- **Date:** 2026-10-25
- **Asked by:** the owner, 2026-10-25, with a picture of Unsloth Studio's "Create images" panel: our image module is very basic and does
  not let a person add LoRAs; check Unsloth's features and plan how to build them.
- **Depends on:** ADR-0059 (ComfyUI as the managed image engine, confirm-first downloads), ADR-0062 (Unsloth Studio is read for ideas, never
  copied), ADR-0063 (found models and tools, the fit check), ADR-0064 and ADR-0086 (the model hub, opt-in network, one model button),
  ADR-0068 (every feature is an action), ADR-0047 (safeguards), ADR-0073 to ADR-0076 (Train: the app makes image LoRAs), ADR-0081
  (design tokens), ADR-0087 (engine workers for the web), ADR-0090 (Creative Studio reuses these panels).
- **Evidence:** the local checkout `~/Projects/unsloth` (commit `133a8076d`, 2026-10-13): `studio/frontend/src/features/images/`,
  `features/generation-presets/` and `studio/backend/core/inference/diffusion_lora.py`; our code and the LoRA the app trained on this Mac
  (`models/loras/wasify-ena-b37ba287.safetensors`, header read). **Nothing was run** and nothing was copied.
- **Mockup:** `docs/spikes/image-styles-mockup.html` (colour sketches, not real output).

## Context

**What we have** (read 2026-10-25). The image engine already applies LoRAs; the screen just cannot get them in.
* The workflow maps (Create, Edit, Inpaint, Reference; `products/wasifyai-image/workflows/*.map.yaml`) have a `lora_chain`: up to 3
  `LoraLoaderModelOnly` nodes spliced before the sampler. A request carries `loras: [{name, weight}]`, weight 0.1 to 2.0, names relative to a
  `loras` folder, `.safetensors` only (`check_loras` in the image graph).
* `GET /desktop/loras` lists **found** files: a LoRA inside a ComfyUI-style `loras` folder is "ready"; one in a folder the app has not been
  allowed to read is "one click away" (`Use it`). The file header classifies it as a LoRA and guesses a coarse family (`flux`, `wan`, `sdxl`).
* The screen (`ImageWorkspace`) shows a **Styles** section **only when something was already found**. With nothing on disk the person
  sees no sign that styles exist. There is no way to add one, no download, no folder button, no check that a style fits the model, no
  trigger word, no delete; steps, seed and number of pictures cannot be set; the size is five fixed shapes; there are no presets.
* Train makes image LoRAs and puts them in `models/loras`; they show up as styles by accident, with no mark that you made them.
* The web does not pass styles at all, and the actions (`image.generate`, `image.edit`) take no styles, so the assistant cannot use them.

**What Unsloth Studio does** (ideas only):

| Feature | Unsloth | What it teaches us |
|---|---|---|
| LoRA rows | up to **8**, each with a text box for `owner/name` or `owner/name:file.safetensors` (with suggestions), a **strength 0 to 2** (steps of 0.05), a remove button | a stack is the normal use; strength matters |
| **Add LoRA** and **Folders** buttons | Add prefills the next suggestion; Folders opens the dialog that adds extra model folders | adding must be a button, not a file-system chore |
| Suggestions | a curated list plus everything found locally, **filtered by the loaded model's family**, trained-in-app adapters first and marked "fine-tuned" | show only what fits, yours first |
| Safety on the backend | the request carries an **id** (catalogue id, local stem or Hugging Face repo id), never a path; the backend resolves it; formats **.safetensors and .gguf only** (no pickled `.pt`); family tag enforced on the server too; a sidecar `.json` marks a file as an image LoRA | never let the screen name a path; never load pickles |
| Download | a Hugging Face repo id downloads on demand, one weight file picked from the repo | people paste a repo id |
| Baked adapters | some quantised builds need the LoRA merged at load, so changing it needs a reload | our ComfyUI chain avoids this |
| Presets | a "Default" menu: named bundles of size, steps, guidance, batch size and runs, kept per kind and per model; **LoRAs are not in a preset** | people reuse settings |
| Other generation controls | negative prompt, sampler, aspect ratio with a swap button, width and height from a limited list, steps, guidance, batch size, runs, seed, live preview, stop, ControlNet | the "advanced" set |
| Recipe in the gallery | every picture keeps model, size, steps, guidance, seed and its LoRAs as `id:weight`, and "load settings" restores them | reproducibility |

## The gaps, and what we decide

| Gap | Decision |
|---|---|
| No way to add a style | **Add a style** button, always visible, with sources: *Yours*, *From this computer*, *From Hugging Face*, *Recommended*, *Look in a folder* (decisions 1, 3 to 5) |
| No sign whether a style fits | **Read the file** and say in words: made for this model, made for another (blocked), or not sure (decision 6) |
| 3 styles at most | **8**, like Unsloth, with the time cost shown (decision 7) |
| Trained styles are anonymous | **Made by you** mark, listed first, with the **trigger word** and a "Use this word" button (decision 8) |
| Cannot remove a style | **Delete** only our own copies, with a question (decision 9) |
| No steps, seed, count, custom size | a collapsed **Advanced** section: steps, seed, how many pictures, size (decision 10) |
| No presets | **Saved looks**: size, steps and styles (by pointer) (decision 11) |
| Assistant cannot use styles | `styles` input on the image actions and three new actions (decision 12) |
| Web has none | desktop first; the web shows what an admin installed (decision 13) |
| Negative prompt, sampler, guidance, ControlNet, live preview | **not now**: klein distilled runs at guidance 1 where a negative prompt and the sampler do nothing useful; ControlNet needs a model we do not ship (listed in "Not decided here") |

## Decision (proposed)

1. **Styles stay "Styles" in words** (people do not know "LoRA"; the help and the tooltip say "a style, also called a LoRA"). The
   section is **always shown** in Create, Edit, Inpaint and Reference (all four workflows have the chain), collapsed to one line when
   none is chosen: "Styles (optional) · Add a style".
2. **A style is a record, not just a file.** Each style lives in the app's `models/loras` folder as the weight file plus a sidecar
   `<name>.style.json`: title, where it came from (trained here, a computer file, a Hugging Face repo and file), the SHA-256 of the file,
   size, the family and variant read from the file, the rank, a trigger word if one was found or typed, when it was added. Files found by discovery in other folders become
   records the first time they are used (a copy, never a move). The record is what the screen lists; the file name the workflow needs is
   derived from it.
3. **Sources.**
   * **Yours:** what Train made (the sidecar is written by Train; a button on a trained model's card says **Use in Create**).
   * **From this computer:** choose or drop a `.safetensors` file; the engine reads **the header only**, checks it, shows the result
     ("a style for FLUX.2 klein 4B, 83 MB, rank 16"), and on a yes **copies** it into the app's folder. The original is untouched.
   * **From Hugging Face:** a repo name or address; uses the model hub (ADR-0064): the opt-in network switch, a list of the repo's files,
     only `.safetensors` offered, the exact file and size shown, the confirm-first resumable download of ADR-0059, the file
     checked after it arrives (decision 6). **Nothing is requested before the person agrees.** The window never talks to the internet.
   * **Look in a folder:** the existing folders setting, reachable from here (it is hidden in Settings today).
   * **Recommended:** a small list **we reviewed** for klein 4B (family, file hash pinned), after stage S0. Empty until then.
   * **Not in v1:** CivitAI (most community LoRAs live there). It needs its own terms, an account key and a content policy; the person can
     download a file and use "From this computer". It is open question 2.
4. **The screen never names a path.** A request carries a **style id**; the engine resolves it to a file in its own folder and refuses an
   unknown id. A name that is not in the records, a `..`, an absolute path or a file that is not `.safetensors` is refused (the check we
   already have, kept, and applied to the new ids). **Pickled formats (`.ckpt`, `.pt`) are never offered or read.**
5. **Checks on a file before it is kept:** a header of a sane size; only tensors, no code; every tensor name a known LoRA style; size under
   a ceiling (**2 GB**, a klein 4B style is 50 to 500 MB); not already present (same hash); a name that is safe on disk. The reader never
   loads the weights into memory. A file that fails says why in words ("This is a checkpoint, not a style").
6. **Does it fit?** A fingerprint read from the header says which model the style was made for. Measured on the one LoRA we have: the
   tensor names carry `double_blocks` and `single_blocks`, the model width is **3072**, there are **5 double and 20 single blocks**, which
   is FLUX.2 klein 4B (FLUX.1 shares the width but has 19 and 38 blocks; the 9B variant differs and is to be measured in S0). The
   result is one of **fits** (shown with a tick), **made for another model** (shown but not selectable, "it would give noise here") and
   **not sure** (selectable with a warning). The family tag in the sidecar, when present, is checked against the fingerprint; a mismatch
   is shown. The engine enforces the same rule on the request (as Unsloth does), so no client can load a wrong-family file.
7. **Up to 8 styles, strength 0 to 2 in steps of 0.05** (the engine accepts 0.1 to 2.0 today; 0 means "off", so the screen offers 0.05 to
   2). The chain limit in each workflow map goes from 3 to 8. The honest line before Generate says what the styles cost ("2 styles add about
   2 s"), measured in S0. The order of the rows is the order of the chain.
8. **Trigger words.** Many styles need a word in the prompt. The record stores it (typed, or found in the file's metadata or the repo's
   description), and the row offers **Use this word**, which adds it to the prompt. Train's "magic word" uses the same field.
9. **Remove.** The trash icon takes a style out of **this picture**. A separate **Delete from this computer** (in the style's menu) removes
   our copy and its record after a question, never a file we did not copy; deleting is the `destroy` action and always asks.
10. **Advanced (collapsed): steps, seed, how many pictures, size.** Steps are an input of the workflow map already; seed is already sent;
    how many pictures runs the job that many times with consecutive seeds; size is a width and a height on the model's grid (multiples
    of 16, within the fit check), with the five shapes as shortcuts. **Not shown:** guidance (klein distilled runs at 1), negative prompt
    and sampler (no effect there). If S0 shows a style trained on the base model needs more steps or a different guidance on the distilled
    model, guidance joins this section for that case.
11. **Saved looks (presets).** A name for a bundle of size, steps and **styles by pointer** (id and strength, no weights). Applying a look
    that names a style that is not on this computer says so and offers to get it again from the recorded source. The default look is
    the model's recommendation. Recipes of finished pictures already carry the styles; they gain the style's id and hash so "Make it
    again" can say "this picture used Ena (hash …), which is not here".
12. **Actions (ADR-0068).** The image actions gain an optional `styles` list (id, strength). New actions with help files, `ui` pointers,
    contract rows and tests through `ActionExecutor`: `styles.list` (`read`, `private`), `styles.add_from_hub` (`make`, `leaves_device`,
    `needs_consent`: a network read and a download), `styles.remove` (`destroy`, always asks). "From this computer" has no action
    (a person's file dialog, not an agent's). Surfaces: `assistant` and `mcp` for list, use and add from the hub.
13. **Web.** Desktop first. On the web a person cannot bring files (no per-person disk; ADR-0087's rule for models). An **admin** puts
    styles on the GPU host through the existing worker model-fetch path, and the web shows them **read only** in the same section: pick,
    set strength, no add or delete. A row in `docs/web-parity-ledger.md` says so when S1 starts.
14. **Creative Studio (ADR-0090) uses these panels.** The Make panel's Image tab shows the same Styles section; a character can name its
    style. Nothing here depends on that ADR.
15. **Safeguards.** Styles are the person's own responsibility and are not content-inspected. **Prompts and pictures are
    checked by the safeguards switch exactly as today** (ADR-0047); a style does not change that, and there is no separate "mature"
    mode (see question 7). A style we did not review is shown as "not reviewed by us", never recommended and
    never a default.

## How it is built

| Piece | Where |
|---|---|
| Style records, header reader, family fingerprint, copy-in, delete | engine, `desktop_styles.py` (next to `desktop_discovery.py`; the discovery reader is reused) |
| Routes | `GET /desktop/styles` (records with fit state), `POST /desktop/styles/import` (streamed upload, header check), `POST /desktop/styles/hub/files` and `POST /desktop/styles/hub/download` (through the hub service and the download manager), `DELETE /desktop/styles/{id}`; `GET /desktop/loras` stays for compatibility until the screen moves |
| Chain size | `lora_chain.max: 8` in the four workflow maps; `MAX_LORAS = 8` in the image graph and the provider |
| Screen | `packages/ui/src/image/` a `StylesSection` (rows, add menu, fit, trigger word), used by `ImageWorkspace` in full and panel layouts; the two dialogs in `packages/ui/src/image/styles/`; the desktop adapter in `apps/desktop/src/styles.ts` |
| Client | `packages/client/src/styles.ts` with the types and a transport-based API, so the web can use the read-only part |
| Hub reuse | the hub service gains a "style" kind: lists only `.safetensors`, never pickles |
| Train hand-off | Train writes the sidecar and shows "Use in Create"; the first trained style is the one on this Mac |

## Staged plan (each stage ends with tests, a real run on the owner's Mac, docs and `git add`; sizes are working days with Claude)

| Stage | What | Size | Done when |
|---|---|---|---|
| **S0** | **Spike, measured, outside the repo.** (a) Which LoRA key styles ComfyUI applies to klein 4B: our converted ones, `diffusion_model.*`, kohya `lora_unet_*`, diffusers `transformer.*`; which need a converter; (b) the fingerprint (blocks, width) for klein 4B, klein 9B and FLUX.1 files; (c) time and memory with 1, 3 and 8 styles; (d) how a style trained on **klein base** behaves on our **distilled** model at 4 steps and at more steps; (e) where trigger words live in real files; (f) pick the Recommended ones from a short list of klein-4B styles. Downloads: a handful of files, under 5 GB, deleted after | 1.5 | `docs/spikes/styles-s0.md` with a measured table, the formats that work, the fingerprint rules, a reviewed shortlist, and a go or no-go |
| **S1** | Engine: records and sidecars, header checks, fingerprint, import, delete, `GET /desktop/styles`, chain 8, request validation by id, tests with fixture files | 3 | a fixture style imports, is classed, applied to a stub job; hostile files (a `.ckpt`, a huge header, a name with `..`) are refused |
| **S2** | Screen: the always-visible Styles section, the add menu, rows with strength, fit and trigger word, remove, delete, folders, Yours first; the dialog for "From this computer"; Train's "Use in Create" | 4 | the owner adds the trained style from the screen and uses it in Create, Edit, Inpaint and Reference |
| **S3** | Hugging Face: file list, the confirm dialog, download, recheck, offline behaviour, tests with a fake hub | 3 | a real klein-4B style from the shortlist downloads, is checked and used |
| **S4** | Advanced section, Saved looks, recipes with ids and hashes, `styles` on the image actions, the three new actions, help files, the contract rows | 4 | "Make it again" restores styles; the assistant can list and use one; the action tests pass |
| **S5** | The Recommended list, the web read-only section (admin installs through the worker path), the ledger row, the panel layout for Creative Studio | 3 | the web shows an admin's styles; the ledger gate passes |

Total about 18.5 working days. S0 alone says whether community styles work on our distilled model, which decides how useful the rest is.

## Consequences

* A person can finally bring their own look into every image screen, and the app tells them truthfully whether it fits.
* The app now keeps a small **catalogue of files the person added** (records, hashes). That is the first user-supplied model-like
  asset the engine owns, so deletion, disk use (the Models page must show it) and the fit check need to know about it.
* The image screen gets heavier; the collapsed sections keep the first view as simple as today.

## Risks

* **A distilled model may not take a style trained for the base model, or may need more steps.** S0 measures it; if it fails, the
  Advanced section gets guidance and the Recommended list says which styles work.
* **Wrong-family files are the common mistake** (the screen already warns about noise). The fingerprint is a header heuristic and can
  be wrong for unusual files, hence the third state "not sure".
* **Unreviewed styles.** We mark them "not reviewed" and never recommend them. The person carries the responsibility (decision 15); the terms of service (backlog B4) must say so before a public release.
* **Disk.** Each style is up to 2 GB; the Models page must list them with sizes and a delete.
* **Copying by accident.** Nothing from Unsloth's code is copied. The mockup, the schema and the words are ours.
* **Content.** A style can change what the base model will draw. The safeguards switch is the one control (decision 15); it is off by
  default on the desktop (ADR-0047). That is a product choice for the owner, not a technical limit (question 7).

## Not decided here

CivitAI as a source; ControlNet and its models; a negative prompt, sampler and guidance for models that use them; live preview; the
text-encoder part of a LoRA (our chain patches the diffusion model only, as klein's does); merging styles into a new file; sharing styles
between people; training from the Styles section (Train stays its own screen); a styles page of its own.

## Owner's answers (2026-10-25)

The owner took the recommendation on every question.

| # | Question | Answer (decided) | Where it landed |
|---|---|---|---|
| 1 | How many styles at once | **8**, with the time cost shown | Decision 7; chain limit 8 |
| 2 | Sources in v1 | **Yours, this computer, Hugging Face and a folder**; CivitAI later (a CivitAI file can be added through "From this computer" until then) | Decision 3 |
| 3 | The Advanced section | **Yes, collapsed**: steps, seed, how many pictures, size; guidance, negative prompt and sampler stay out until a model needs them | Decision 10 |
| 4 | The word | **Styles**, with "(LoRA)" in the help and the tooltip | Decision 1 |
| 5 | Web | **Desktop first**; the web shows only what an admin installed, read only | Decision 13 |
| 6 | A Recommended list | **A short reviewed list** after S0 | Decision 3; S5 |
| 7 | Content | **Styles are not content-inspected; prompts and pictures follow the safeguards switch as today; no separate mature mode.** What the switch does on a public service is decided before launch (backlog B4) | Decision 15 |

## Open questions for the owner

None. What S0 will decide with measurements (not owner questions): which LoRA formats ComfyUI applies on our distilled klein 4B, the
fingerprint rules, the time and memory per style, whether styles trained on the base model work at 4 steps, where trigger words live, and
which klein-4B styles are worth recommending.
