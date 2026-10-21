# ADR-0065: Notebooks: a NotebookLM-style, source-grounded workspace, built on SurfSense's local code

- **Status:** Accepted (2026-10-16). The E0 gate (spike S1 to S6, `docs/spikes/surfsense-investigation.md`
  section 9) **passed the same day**: decisions 7, 8 and 9 are confirmed and decision 10 was corrected by the
  measurements (below). Supersedes ADR-0060.
- **Date:** 2026-10-16
- **Depends on:** ADR-0017 (storage), ADR-0035 (upload hardening), ADR-0041 (creations are searchable), ADR-0056
  (one engine, two shells; slot manager), ADR-0057 (assistant), ADR-0061 (how outside code enters),
  ADR-0063/0064 (model discovery and hub), ADR-0059 (image engine). Evidence:
  `docs/spikes/surfsense-investigation.md`.
- **Supersedes:** ADR-0060 (documents: a local-first RAG product). Its constraints are kept (ingest as a job,
  hardening, a locator on every chunk, structured generation, evaluation as part of done, privacy). What changes is
  the product shape (a notebook, not a document library), the reuse base (SurfSense, not Unsloth's `rag`), and the
  scope (Studio outputs are in the first release).

## Context

The owner replaced the requirement: build the features of **Gemini NotebookLM**, and reuse the open-source project
**SurfSense** (`MODSetter/SurfSense`, cloned at `~/Projects/SurfSense`) where it helps.

The investigation (read, not run; details and counts in the spike document) found:

- SurfSense's **desktop app** is already a local, offline NotebookLM-style product on the same stack shape as ours:
  one SQLite file with FTS5 and sqlite-vec, Docling parsing, a bge-small embedder on onnxruntime, llama.cpp for
  text, a window with Sources, Chat with citations and Studio (twelve output formats).
- It is **Apache-2.0** except two directories (`surfsense_backend/app/proprietary/`,
  `plugins/remote/proprietary/`) that are not part of the desktop app. Its offline licence module sells paid
  plugins and is not needed.
- Its code is separable. In the pipeline areas we would take, 80 to 90 percent of files do not import its model
  layer; the coupled files reach the model through one seam, which maps to our `ProviderDeps.text_provider` and
  the slot manager.
- Its UI is built on other libraries than ours (Base UI, TanStack Query, assistant-ui, react-intl), so UI is
  re-implemented to the same behaviour, with pure logic files copied.
- It lacks some NotebookLM features: a source guide with suggested questions, saving an answer as a note,
  video overview, and (as a design choice) web, Drive and YouTube sources.
- Its largest part (the opencode **agent**, 10.5k lines) and its plugin system are a separate product decision.

## Decision

1. **A product `wasifyai-notebooks`** on the same engine (ADR-0056). The user-facing name is **Notebook**: a named
   container of sources, chats, notes and generated outputs. SurfSense's word is "workspace"; ours is "notebook".
   One chat history per notebook, many conversations.
2. **Take SurfSense code by import, own it, record it** (ADR-0061 decision 3): Apache-2.0 files are copied
   area by area into `products/wasifyai-notebooks/`, each area with a `PROVENANCE.md` (source path, commit
   `622c1ded8`, date, what changed), the original headers kept, and a `NOTICE` entry. The reference clone stays
   outside the repository and is not tracked for upstream changes except security fixes.
3. **What is taken** (matrix in the spike, section 6): the ingest pipeline and its rules; the embedding spec,
   encoder and vector table; hybrid retrieval and its tokenizer; folders and source scope; the chat grounding
   (prompts by model tier, budget, citations); the Studio structured formats and their builders; the podcast
   script writer; PDF tools when a feature needs them.
4. **What is not taken in v1:** the agent and opencode, plugins and MCP, the model/runtime layer (`modules/llm`),
   the licence and cloud-import modules, the Electron shell, and the script-running office paths (PPTX and
   XLSX as model-written Python). Each is a later, separate decision.
5. **One datastore file for the product: `notebooks.db`** next to `wasifyai.db` (desktop). SQLite with WAL, FTS5
   and sqlite-vec, behind a store interface. Reasons: the extension loading and the write pattern of ingest stay
   away from the main file (SurfSense measured contention and gave the queue its own file for the same reason);
   deleting a notebook is a file-level operation for its documents; migrations are the product's own. The web
   profile (Postgres and pgvector) is an adapter written when the web product needs it (not in this ADR).
6. **Ingestion is a job** on our queue (rule 6): parse, chunk, embed, index, with progress over SSE, cancel and
   retry, one document at a time on the desktop. Hardening is always on (ADR-0035, SurfSense's byte-and-extension
   agreement, 500 MB, zip-bomb limits). The in-process worker is used; SurfSense's Huey and second process are not
   taken.
7. **Parsing: Docling as an optional component** ("Document reader"), installed on demand the way ComfyUI and
   llama.cpp are, with a built-in reader for plain text, Markdown, CSV and HTML that needs no component. Docling
   is what gives layout, tables and OCR for PDF, Word, PowerPoint, Excel and images. **Measured (E0):** about
   1.4 GB on disk (1.0 GB packages, 0.4 GB weights), 3.5 s to start, 0.15 to 0.6 s per page, 2.2 to 3.7 GB while
   it runs. It therefore runs as its own **process that exits when idle** (slot owner `reader`), and a file that
   yields no text fails visibly ("could not read the text; is it a scan?") instead of becoming an empty ready
   source. An ONNX layout engine in place of torch (about 600 MB less) is an E1 option, not a promise.
8. **One embedder, with its identity stored** (ADR-0060 decision 6 kept): `bge-small-en-v1.5`, quantised ONNX
   (about 66 MB) on onnxruntime, no torch. It is a component fetched through the model hub with a checksum, not
   bundled. The index records the embedder; changing it is a visible re-embed job (SurfSense ADR 0036). English
   only in v1; the multilingual embedder follows with the other languages.
9. **Retrieval: hybrid by SurfSense's blend** (BM25 + sqlite-vec, semantic weight 0.65), **confirmed or changed by
   our corpus** (spike S2), as ADR-0060 decision 7 already required. The retrieval mode stays configurable. Every
   hit carries a locator (document, page, line span) so an answer can open its source.
10. **Grounded chat retrieves first and does not rely on tool calls.** The passages are put in the user message
    with `[n]` labels and the question labelled; the model cites. This is SurfSense's measured approach for
    small local models. Our own bake-off (D6) shows why it must not depend on tool calls: Gemma 3 4B made no tool
    calls at all and Llama 3.2 3B called a tool in five of five plain chats, while only the Qwen3 models were
    right. A notebook has to answer with whatever chat model the person has. It is a graph of this product, not
    the assistant's tool loop.
    **Refusal is the prompt's job, not a score threshold** (E0 measured the scores of answerable and
    unanswerable questions overlapping: 0.553 to 0.706 against up to 0.678). The prompt tells the model to say
    the sources do not hold the answer and to answer from general knowledge only when it can, without
    labels; a **server-side check removes `[n]` labels from a sentence that says the sources do not cover it**
    (E0: Qwen3 4B put a citation on general knowledge in 2 of 5 unanswerable questions with the `capable` prompt).
    Two prompt tiers are kept (`compact`, `capable`), chosen per model on the E2 evaluation set. The assistant
    (ADR-0057) later gets a `search_notebooks` tool for questions across notebooks.
11. **Studio is structured first, files second** (ADR-0060 decision 10 kept, SurfSense's builder rule). First
    release formats: Markdown report, flashcards, quiz, mind map, Word, PDF. Second wave: slides and spreadsheet
    from a validated spec rendered by python-pptx and openpyxl (**not** model-written scripts), audio overview
    (script from the notebook, voice from **our TTS product**, not audio.cpp), infographic and images through the
    image capability, source guide with suggested questions, save-as-note. A video overview waits for the
    video product.
12. **Outputs are creations (rule, ADR-0041).** Every artifact, and the notebook itself (title and summary), is
    indexed for My creations search, with an `IndexSource`, list filter and corpus row. Multilingual: v1 is
    English only (owner's decision); nothing in the data model or UI assumes it.
13. **The interface** follows `docs/phase2-stage-e-plan.md`: one expandable **Notebook** entry in the side menu
    with *Create* and *View Notebooks* (the same pattern as *Images*; the empty *Projects* placeholder is
    removed), a notebooks list, an add-sources screen for a new notebook (upload files, copied text; websites
    and Drive later) and a notebook page of three panes (Sources, Chat, Studio). Model use goes through the slot
    manager and the existing model chip; a notebook never loads a model by itself.
14. **Privacy and egress.** Documents, chunks, vectors and outputs stay on the computer. The only network use is
    the opt-in component and model downloads already allowed by ADR-0063/0064. Deleting a source removes its
    file, chunks, vectors and cached text; deleting a notebook removes its directory.
15. **Evaluation is part of done** (ADR-0060 decision 11 kept): a retrieval corpus (recall at k, kept in the
    repo), a grounding set (cited and supported, refusals) run on our recommended chat model, the same style as
    the search corpus.

## Consequences

- New: product `wasifyai-notebooks`, a SQLite store with its migrations, a reader component and an embedder
  component, ingestion graph and routes, a grounded-chat graph, Studio builders, an SSE addition (`sources`,
  `citations`), notebook screens in `packages/ui` and `apps/desktop`.
- Roughly 20 to 25k lines of Apache-2.0 Python enter with provenance, and a UI of about 8 to 10k lines is
  re-implemented. Tests are copied with the code where they exist.
- The Unsloth `rag` import of ADR-0060/0062 is **not done**: SurfSense's pipeline is more complete (folders,
  figures, citations, Studio) and Apache-2.0 rather than AGPL. The Unsloth measurements stay as the comparison for
  S2.
- A notebook's chat and the assistant are two chat surfaces. They share the model chip, the slot manager and the
  stream contract, not the graph.
- Parsing quality (scans, tables, right-to-left, non-Latin OCR) remains the real risk; Docling covers Latin,
  Chinese and Japanese OCR only (SurfSense known gap). English v1 does not hit it.

## Amendments from building E1 (2026-10-16)

- **Decision 6:** the window polls the sources list while any is being read; there is no new SSE stream and the
  SSE contract is unchanged. The queue is the `documents.status` column and one in-engine worker.
- **Decision 7:** the reader is set up **by the engine** (`POST /setup/reader`), not by the Rust shell: a
  hashed lock per platform in the bundle, nine weight files pinned by SHA-256, and a check that reads a test
  picture before it counts as installed. The shell passes the path of its provisioned `uv`. One reader process
  serves a batch and ends after 60 s idle.
- **Decision 8:** the search model is an entry in the product's `models.yaml` and arrives through the Models
  panel; sources added before it is present wait.
- **Decision 12:** `notebook` is a creation kind in the platform and the search API; the UI card is E3's.

- **Decision 10 (E2):** a question is a run of the product's own graph, so the existing events carry it
  (`node`, `tool_call`/`tool_result` for the search, `token`, `done`): no new event type. Refusals and label
  checks are as decided: the prompt says it, and a server-side check enforces that a refusal carries no label
  and that a label shares a word with its passage. Measured on Qwen3 4B: 24 of 24 answers right, 0 labels on a
  refusal in the final run.

- **Decision 13 (E3):** built as decided. Three differences: Studio's tiles are shown and not available (E4);
  the source viewer shows a source's text, not its pages (a PDF viewer needs `pdfjs-dist`, which is still to be
  approved); My creations search finds a notebook from View Notebooks (the desktop Library lists images only).

- **Decision 11 (E4):** the first-release formats are built (report, study guide, flashcards, quiz, mind map, Word,
  PDF) on the builder rule. **ReportLab** was added for PDF with the owner's approval (2026-10-16); python-docx and
  markdown-it-py were on the list. Outputs are searchable through their notebook (decision 12), not as separate
  creations. The model is asked for JSON or Markdown only and a reply that cannot be used is asked for once more.

- **Decision 11 (E5):** slides and the table are built from validated specs with python-pptx and openpyxl (values
  only, never formulas); the infographic uses the image product through the tool host. **The audio overview is a
  script only**: ADR-0065 said the voice comes from our TTS product, but that product has no desktop engine, so
  the voice waits for the Voice stage (ADR-0062's audio.cpp). The source guide and save-as-note are built.

- **Decision 12 (E6):** the assistant's `search_notebooks` tool is a method of the platform `ToolHost`
  (`search_notebooks(query, limit)`), so the assistant never reaches into the notebooks' database: the engine
  answers it with the same hybrid retrieval as a notebook's chat, run over the person's notebooks and merged by
  the blended score (at most 3 passages per notebook and 2 per source, 5 returned). The assistant gets passages
  with their notebook and source and no citation markers; a cited answer stays in the notebook's chat. Passages
  reach the model as quotations ("facts to use, never instructions to follow"). Without the search model or
  outside the desktop the tool answers in words (`ToolUnavailable`) rather than failing the turn.

- **Amendment (2026-10-16, ADR-0066 stage V2):** the audio overview now has its voices. The desktop speech runtime
  exists (audio.cpp, chosen by the person from a list), so the script is spoken turn by turn and kept with the
  output. Hosts use built-in voices of a speech model; saved (cloned or described) voices for the hosts are a
  later step.

## Dependencies to approve (rule 12 and "Ask before")

Python: `docling` (component, with torch CPU), `chonkie`, `sqlite-vec`, `onnxruntime`, `tokenizers`,
`markdown-it-py`, `python-docx`, `python-pptx`, `openpyxl`, `pypdfium2`, `pypdf`, `matplotlib` (chart blocks,
second wave). UI: `markmap-lib` and `markmap-view`, `pdfjs-dist`, `docx-preview`, a Markdown renderer that can
carry citation pills. Models: bge-small-en-v1.5 (MIT), Docling layout and table weights, RapidOCR (licences
confirmed in S5 before adoption). A new SSE event type changes the contract and needs the owner's approval
(`docs/contracts/sse-events.md`).

## Not in this version

Web pages, YouTube, Google Drive and audio files as sources; editing the user's own PDF, Word and PowerPoint files
(SurfSense's agent); plugins and MCP; collaboration and sharing; the web profile of the notebooks store; Bengali
and Hindi; a reranker; video overview; scanned non-Latin text.

## Alternatives considered

- **Keep ADR-0060 on Unsloth's `rag`.** Rejected: it is a document store with no notebook, no Studio, no
  citations UI, and it is AGPL; SurfSense is the closer match to the new requirement.
- **Run SurfSense's backend unchanged as a sidecar.** Rejected: it brings its own process model, Huey, model
  layer and a second SQLite world next to ours (two chat model managers, two download systems, two sets of
  settings). The valuable part is a few thousand lines of pipeline, not the app shell.
- **Depend on SurfSense as a library.** Rejected: it is not packaged for it, upstream is in a wind-down, and we
  would own its bugs without owning its code.
- **Write it from scratch.** Rejected: the retrieval blend, the chunk budget, the grounding prompts and the
  Studio builders encode measured lessons that would take us the same time to re-learn.
- **Make notebooks a mode of the assistant.** Rejected for v1: a notebook has its own scope (sources),
  persistence (documents, vectors) and outputs; the assistant stays the general chat, and gains notebooks as a
  tool (decision 10).

## Open questions: answered by the owner (2026-10-16, "all recommended")

1. **Name:** Notebook (menu entry), notebooks (list), as NotebookLM.
2. **Document reader:** Docling as a component installed on first use, if E0 shows it is under about 1.5 GB and
   parses a text PDF at a page per second or better; otherwise a lighter reader first.
3. **Agent mode in v1:** no.
4. **Audio overview voice:** our TTS product.
5. **Embedder download:** with the first notebook, one confirm.
6. **Google Docs:** export to `.docx` or `.pdf` in v1; a Drive connector later.
7. **Dependencies:** the list above is approved (rule 12), subject to the licence check in S5.
8. **Create:** opens a draft stored after the first source.

## Amendment 2026-10-18: the web profile's store (docs/phase3-web-parity-plan.md, W4 step 1)

The notebooks store has a Postgres form, `PostgresNotebookStore` (`pgstore.py`), the "adapter written when the web
product needs it" of decision 5. It is the same class of store: every method and its ownership rule runs the same SQL
through a thin connection (`PgDb`); the few differences are hooks (`_INTEGRITY`, `_guard` for a savepoint, `_replace_chunks`).
The tables are in their own schema (`notebooks`), created and checked by the store on start under an advisory lock
(the product owns its schema, as above), with `chunks.embedding vector(N)` in the passage row and the passage's terms in
a `text[]` column with a GIN index.

Retrieval (`pgretrieval.py`) keeps the contract and the blend (`retrieval.rank`): the keyword leg proposes the 20 passages
holding most of the question's terms (cut by the same tokenizer as the SQLite index, so the two agree on what a word is; a
shorter passage wins a tie, standing in for BM25's length weighting) and scores coverage as before; the semantic leg is an
exact pgvector cosine scan of the notebook or the ticked sources, so another notebook can never crowd it out. Measured
on the test corpus, both databases answer the same questions with the same top passage; no ranking measurement on a large
library has been made, and the keyword candidates differ from BM25's on ties.

Not part of this step: serving notebooks from the web engine (the runtime and routes still read local folders for the
original files and generated documents; those move to object storage and the reader to a worker job in the next steps).
The tests of the store, the ingest, the chat graph, the routes, the studio and the passage search run on SQLite and on
Postgres (CI has the Postgres service; a machine without one skips the Postgres half).

## Amendment 2026-10-18 (2): files and the reading worker on the web (W4 step 2)

- **Files behind an interface** (`files.py`). A source's original and an output's file are kept through a `FileStore` for
  an owner, with plain keys (`files/{notebook}/{document}/{name}`, `artifacts/{notebook}/{output}/{name}`). `LocalFiles` is
  the desktop's folders, in the layout it always had; `ObjectFiles` is the deployment's object storage under
  `{tenant}/wasifyai-notebooks/{user}/...` (rules 7 and 10), with parts of a key limited to what object storage accepts
  (a title with spaces or accents is stored with `_`; the real title is in the database). The routes, the studio and the
  reading code ask for the store of the person they act for; nothing else touches a folder. A download streams a
  folder's file and reads an object into the response.
- **The reader is a worker.** The engine's program on the web only serves requests (`Runtime.reads_sources` is false). A source waits in
  the database as `pending`, which is the queue; `python -m wasifyai_notebooks.worker` takes the next one (`begin` is one
  atomic update, so any number of workers can run), fetches the file from object storage to a temporary path, reads it
  with the document reader (still a program of its own), cuts, embeds and indexes it, and writes the result. A source a worker
  lost is failed after 30 minutes untouched (a reading may take 15), by whichever worker notices; the desktop, with one
  reader, still fails every interrupted source at start.
- **Switch (removed 2026-10-21, owner: no feature switches).** The web profile always serves notebooks from Postgres and object
  storage; the worker is part of the stack (`compose.yaml`, the Helm chart). The first design had `NOTEBOOKS_ENABLED=true` (off by
  default, routes answering 503) so nothing was offered whose worker was not running. The worker takes the same
  database and storage settings as the engine, plus `NOTEBOOKS_MODELS_DIR` and `NOTEBOOKS_READER_DIR` on its machine.
- The tests of the routes, the studio files and the reading run against both homes (the routes tests also against folders and
  objects); the web setup is tested end to end on Postgres and in-memory storage (stored by the engine's program, read by a
  worker, found by a question).

Not done: the worker's image and its Helm release (W7), the search model through the gateway instead of local files
(step 3), per-tenant quotas on sources and bytes, and the audio overview's voices on the web (they need the speech runtime, W5).

## Amendment 2026-10-18 (3): the search model through the gateway, and limits (W4 step 3)

- **Search model.** On the web the embedder is the platform's, asked through the gateway by alias (rule 5):
  `GatewayEmbedder` calls `/v1/embeddings` for `creation-embedder` (bge-m3, multilingual, 1024 dimensions, MIT) in batches of 32, tries a
  busy gateway (429 or 5xx) again with a growing wait, does not repeat a refusal, and checks the dimension. It needs no
  model files on the engine's or the worker's machine. `GatewayComponents` sizes a passage in characters (1500, a few
  hundred tokens in any script) because the desktop's whitespace-style counting cuts nothing in a language written without spaces;
  the desktop keeps its local bge-small and its token-sized passages unchanged. The embedder's id (`gateway:creation-embedder`) is
  recorded in the index like any other, so a library made with the local model is refused (not mixed) until it is read again.
  The local model stays available on the web with `NOTEBOOKS_MODELS_DIR` and no gateway.
- **Usage (rule 9).** Every embedding call records `llm.embedding_tokens` for the person (`record_usage`, a row in `usage_events` on
  Postgres, nothing on the desktop): the reading worker for what it indexes, the engine for questions (chat, search, studio, the
  assistant's tool), each with its `source`.
- **Limits.** `quotas:` in `product.yaml`: `notebooks_per_user` (50), `sources_per_notebook` (300), `bytes_per_user` (2 GB of files and
  notes together), counted per tenant and user and enforced while the safeguards are on (ADR-0047), so not on the desktop. A request
  over a limit gets 429 with a sentence; an upload of several files keeps those that fit and lists the others under `rejected`.

Not done: a limit on embedding tokens per day (the usage is recorded, the limit waits for the billing design), moderation of
sources, and measuring bge-m3's ranking on the evaluation corpus against bge-small's (English) result.

## Amendment 2026-10-18 (4): Studio outputs made by a worker (W4 step 5)

- **One function, two callers.** Making an output (read the ticked sources, ask the chat model, build the file, save the result) is
  `make_output` (`output_job.py`), no longer a part of the graph node. A run of the graph calls it, as before (the desktop; an infographic
  and a guide anywhere, because a guide is kept with the notebook and the infographic's picture is a run of the image product, which
  only the engine's program can start). On the web the engine's program only **queues** the output and ends the run at once.
- **The queue is the output's row.** Queuing stores the request (format, focus, ticked sources, the model's window and prompt tier) as JSON
  on the row, which stays `processing`, so the screens, Stop and the 2-second polling work unchanged. A worker takes the oldest one
  with a single atomic update (`claimed_at`; any number can run), makes it for the person it belongs to (the run context carries their
  tenant and user, so the model's usage is noted for them), and finishes, fails or finds it stopped. An output a worker took and lost
  is failed after 30 minutes untouched; one nobody has taken yet is never failed by the sweep (the worker may just be down).
- **The worker.** `python -m wasifyai_notebooks.worker` makes outputs when it has a gateway (`LITELLM_BASE_URL`), building the chat model from the
  product's own `product.yaml` (`PRODUCTS_DIR`), and reads sources as before. The desktop is untouched: no queue, no columns used.

Not done: a limit on outputs per day, progress steps while a worker makes one (the screen shows "being made" until it is done), and
making an infographic in the worker (it needs a run of the image product, so it stays with the engine).

