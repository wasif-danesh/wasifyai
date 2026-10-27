# Notebooks on the desktop

Part of [the desktop profile](../desktop-profile.md): what is built, how it is wired, what is not done.

## Notebooks (ADR-0065, stage E1: the engine)

`products/wasifyai-notebooks` is a library of sources per notebook: read, cut into passages, indexed on this
computer, and searched. The window and the grounded chat arrive in E3 and E2; this is the engine.

| Piece | File | What |
|---|---|---|
| Store | `wasifyai_notebooks/store.py` | `<data>/notebooks/notebooks.db`: notebooks, folders (8 deep), documents, passages; FTS5 by trigger, vectors in sqlite-vec; dedup by SHA-256 per folder; every read scoped by tenant and user |
| Hardening | `hardening.py` | extension list, bytes must match the extension, OOXML entry and unpacked-size limits, 100 MB, one safe path part for the stored name |
| Reading | `reading.py`, `docling_worker.py` | text, Markdown, CSV and HTML are read in the engine; the rest by Docling in its own process (`--serve`: one process per batch, gone after 60 s idle), 15 minutes per file at most |
| Cutting | `chunking.py` | SurfSense's recursive rules at 480 tokens of the search model's tokenizer; every passage keeps its Markdown line span |
| Search model | `embedding.py`, `models.yaml` | bge-small-en-v1.5 (quantised ONNX, 67 MB) through the Models panel like any model; the index records it and refuses another |
| Retrieval | `retrieval.py` | SurfSense's blend of BM25 and cosine (0.65), per notebook or per ticked sources; `mode` dense, lexical, hybrid for evaluation |
| Ingest | `ingest.py` | one source at a time, highest priority first; cancel checked between steps; nothing is read until the search model is present (sources wait, they do not fail); a file with almost no text fails in words (`No text could be read...`); work in progress at quit is failed at start with Retry |
| Reader setup | `reader_install.py`, `reader/` | `POST /setup/reader` with the size shown: environment from the engine's own Python, hashed lock per platform, nine weight files by SHA-256, a check that reads a test picture. The locks are **committed** in `products/wasifyai-notebooks/reader/requirements-<target>.lock` (`make reader-locks` writes them; the bundle script copies them), so a development checkout (`pnpm tauri dev`) can set the reader up too: before 2026-10-19 only the bundle had them and a checkout said "The reader is not part of this build" |
| Search index | `index.py` | notebooks are a creation kind (`notebook`) in My creations search (ADR-0041) |

Routes, under `/products/wasifyai-notebooks` (loopback token; another person's notebook is a 404):

| Route | Does |
|---|---|
| `GET /status` | what is set up: search model, reader (with setup progress), passage count |
| `POST /setup/reader` | start the reader setup; `{confirm_bytes}` must equal the size offered |
| `GET/POST /notebooks`, `GET/PATCH/DELETE /notebooks/{id}` | list (newest opened first), create, read (marks it opened), rename, delete |
| `GET/POST /notebooks/{id}/folders`, `PATCH/DELETE .../folders/{fid}` | folders; deleting one removes its sources |
| `GET /notebooks/{id}/documents` | sources, with `status` and `folder_id` filters; polled while any is reading |
| `POST .../documents` | a note |
| `POST .../documents/upload` | multipart `files`, optional `folder_id`; answers `created`, `duplicates`, `rejected` (each with its reason) |
| `GET/PATCH/DELETE .../documents/{did}` | read with its Markdown, rename or edit a note, delete (409 while being read) |
| `POST .../documents/{did}/retry`, `.../cancel`, `.../documents/move` | requeue, stop, file into a folder |
| `GET .../documents/{did}/original` | the stored file, always as an attachment |
| `GET .../passages/{chunk_id}` | a passage and its neighbours, for opening a citation |
| `POST .../search` | `{query, top_k, document_ids?, mode?}`: passages with scores and line spans; 409 `embedder_missing` |

Measured on the owner's Mac (14 files, 66 pages, 7 real PDFs and 7 generated files; details in
`docs/phase2-stage-e-plan.md`): 30 s from upload to all searchable with the reader running as one process
(72 s when each file started its own), 69 passages, retrieval 22 of 24 answerable questions at rank 1 and 24 of 24
in the top 3, 10 ms per question over HTTP; a clean setup of the reader 70 s (packages from the cache,
weights downloaded).

**Asking a notebook (stage E2).** A question is a run of the product's graph, not a new route:
`POST /products/wasifyai-notebooks/runs` with `{text, notebook_id, conversation_id?, document_ids?}`.
The graph (`graph.py`) searches the ticked sources (a `search_sources` step), puts the best five passages in the
user message with the question (`grounding.py`, SurfSense's prompts), streams the answer, then checks the
labels (`[n]`): numbers that are not passages go, a sentence that says the sources do not hold the answer
carries none, and a label must share a word with its passage. The answer, its cited passages (text as it
was) and the conversation are saved in `notebooks.db`. The prompt is the shorter `compact` one for a chosen
model file under 1.5 GB and `capable` otherwise; the history is trimmed to the model's window
(`context - 1024 answer - 450 system - 2400 passages - question`). Routes added:
`GET/GET/PATCH/DELETE /notebooks/{id}/conversations[/{cid}]`. Measured with Qwen3 4B: 24 of 24 answers right,
refusals said in words, no labels on them, a median of 4 s (`docs/phase2-stage-e-plan.md`, "E2 evidence").

**Studio (stage E4).** `studio/` makes a notebook's outputs. Formats: `report`, `study_guide`, `flashcards`,
`quiz`, `mindmap`, `word`, `pdf`. A run of the notebooks graph with `studio: {format, prompt}` and the ticked
`document_ids` (formats: also `slides`, `datatable`, `audio`, `infographic`; `guide` is saved with the notebook, not as an output) saves an `artifacts` row (status `processing`), reads the sources cut to the model's window
(`studio/context.py`: whole, an even share each, or the best passages), asks the model for Markdown or JSON under
the prompt for its tier (`studio/prompts/`, SurfSense's), builds and checks it (`studio/formats.py`; one second
try with the reason), renders Word and PDF with `studio/word.py` and `studio/pdf.py`, and saves the body, the
data and the file under `<data>/notebooks/artifacts/<notebook>/<id>/`. Routes: `GET .../artifacts`,
`GET/PATCH/DELETE .../artifacts/{id}`, `POST .../artifacts/{id}/cancel`, `GET .../artifacts/{id}/file` (always an
attachment). `GET /notebooks/{id}/guide` answers the source guide (`guide`, `stale`, `ready`). An infographic's picture is made by a child run of the image product (the assistant's tool host), so it needs image generation set up; a deck is `.pptx` (python-pptx), a table `.xlsx` (openpyxl, values only), an audio overview a script, spoken on request (see "Speech" below). The window's Studio pane has a tile per format, a short brief (a focus and "made from 12 sources"),
the list of outputs (polled while one is being made), and viewers for each format.

The notebooks are served on the desktop profile only (the routes answer 503 without an app data folder); the
web profile needs a Postgres and pgvector adapter of the store (not built).

## Notebooks in the window (stage E3)

The shared screens are in `packages/ui/src/notebook/`, the client and the reducer of a question in
`packages/client/src/notebooks.ts`; the app only supplies the clients, the setup logic and the menu.

| Piece | What |
|---|---|
| `NotebookList` | cards with the counts (sources, being read, could not be read) and when it was opened; search by title and, through My creations search (`kind=notebook`), by the names of the sources |
| `SetupCard` | "Set up reading documents": the search model (through the Models panel's download) and the document reader (`POST /setup/reader`); each says its size and goes ahead only on a click; progress and a failure's sentence are shown |
| `NotebookWorkspace` | header (name, "12 of 14 sources, 2 being read"), three panes, tabs under 1,024 px; a new notebook opens on the add-sources screen and is saved when its first source is added or its name is set |
| `AddSources` | upload (picker or drop), copied text, Websites shown as Soon; files the engine will not take are named before sending |
| `SourcesPane` | tree with tri-state ticks (everything is ticked until something is unticked, so a source added later counts), folders, status per source with Retry and Stop, rename, move, remove |
| `SourceViewer` | the source's text as the notebook reads it, the cited passage marked; a removed source still shows the passage an answer used; a note can be edited; the original can be saved |
| `NotebookChat` | the thread, the search shown as one line, answers with `[n]` pills that open the passage, Copy, the scope and model chips, "Add a source first" and the other reasons the box is blocked |
| `StudioPane`, `OutputViewers` | the eleven formats as tiles, a brief, the outputs list, and viewers: Markdown, flashcards that turn over, a quiz that scores, a mind map as a tree, slides, a table, the audio script, an infographic with its exact facts; save the file; the Studio can be dragged wider or narrower by its left edge (arrow keys, double-click, or the expand button; the width is kept in this browser); rename and delete ask in a box of the page, and Save a copy writes into the Downloads folder through `POST /notebooks/{id}/artifacts/{id}/export` (the app window cannot download a file or show `window.confirm`/`window.prompt`, see backlog D18) |

The scope sent with a question is `document_ids` of the ticked, ready sources, or nothing when nothing is
unticked. The menu steps aside on a window narrower than 1,280 px while a notebook is open and comes back when
the person leaves it (a menu the person closed stays closed). The self-test creates a draft notebook, adds a file
through the real file input, sees it listed, and finds the notebook's card.
