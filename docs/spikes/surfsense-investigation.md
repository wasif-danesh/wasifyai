# SurfSense investigation: what it is, what we can reuse, and what it costs

Date: 2026-10-16. Reference clone: `~/Projects/SurfSense`, commit `622c1ded8` (13 Oct 2026, `dev`, desktop app
`surfsense_local` version 2.2.1). Read, not run: nothing was installed or executed in this pass, so every number
below is a count taken from the source or a statement taken from SurfSense's own architecture documents, and is
marked as such. Section 7 lists what must be **measured** before the ADR is accepted.

Purpose: the owner's requirement changed from "documents (ADR-0060)" to "the features of Gemini NotebookLM". This
document answers three questions: what SurfSense already is, how much of it can enter wasifyai and at what
cost, and what NotebookLM has that SurfSense does not.

## 1. What SurfSense is today

| Fact | Evidence |
|---|---|
| "The air-gapped, open-source NotebookLM alternative": a **desktop app** (Electron + Vite/React + Python sidecars) for research over your own documents. The hosted web product is being wound down (export window closes 18 Oct 2026) | `README.md`, `docs/ROADMAP.md`, `docs/architecture/sunset.md` |
| The desktop app lives in its own tree, `surfsense_local/` (backend 52k lines of Python outside tests, frontend 78k lines of TS/TSX, Electron 6k). `surfsense_backend/` and `surfsense_web/` are the hosted stack (Postgres, Celery, Redis, Next.js) and are **not** what the desktop uses | `docs/adr/0004-desktop-app-is-its-own-tree.md` |
| One user, one machine, offline. Everything is in **one SQLite file**: FTS5 for keywords, sqlite-vec for vectors; a second SQLite file holds the Huey job queues | `docs/architecture/overview.md`, `data-model.md` |
| Parser **Docling** (layout, tables, RapidOCR for scans), chunker **Chonkie**, embedder **bge-small-en-v1.5 on onnxruntime** (no torch for embedding), text through **llama-server** (llama.cpp router mode), images through sd.cpp, podcasts through audio.cpp (Kokoro) | `documents.md`, `embedding.md`, `packaging.md` |
| Window: workspace rail, **Sources** tree on the left, **chat** in the middle, **Studio** and Artifacts on the right, a citation panel and a source preview that replaces the left column | `overview.md` (Frontend), the screenshot the owner sent |
| Two job queues (ingest: 1 thread, studio: 4 threads), events pushed to the window over SSE, cancel and retry on every job | `documents.md` (The queue), `overview.md` (Freshness) |

It is, in short, the same shape as the app we are building (a local engine, SQLite, llama.cpp, a React window), and
it already contains the notebook product.

## 2. Licence and what we may take

- Root `LICENSE`: **Apache-2.0**, except `surfsense_backend/app/proprietary/` and `plugins/remote/proprietary/`
  (Business Source License 1.1). Neither is in the desktop tree.
- `surfsense_local/` contains no Business Source files (searched for "Business Source" and "BUSL": no match in
  `surfsense_local`). It does contain a `license` module (an offline licence key that unlocks SurfSense's paid
  plugins, ADR 0019 and ADR 0047). **We do not take it.**
- Apache-2.0 code can enter our repository, including the AGPL-3.0 `apps/desktop` (ADR-0061 decision 8 and
  `CLAUDE.md`: `apps/desktop` is AGPL-3.0, the rest Apache-2.0). Obligations: keep the copyright and licence
  notices, state changes (our `PROVENANCE.md` convention, ADR-0061 decision 3), and carry a `NOTICE` entry.
- Third-party components keep their own licences (Docling MIT, Chonkie MIT, onnxruntime MIT, sqlite-vec MIT or
  Apache-2.0, the bge-small model MIT). These are **to be confirmed from the installed wheels** in the spike, not
  assumed (ADR-0060 decision 4 already requires it).
- Upstream risk: the hosted business is closing and the licence server and plugins are SurfSense's revenue. The
  desktop app may keep moving or may slow down. This is a reason to **copy and own**, not to depend (ADR-0061
  decision 4), and not to track upstream except for security fixes.

## 3. How it is built, in the parts that matter to us

**Ingest** (`worker/ingestion/`, 688 lines in 12 files, plus `modules/documents/` 1.3k): upload streams to disk
with a SHA-256 and a 500 MB cap; the extension **and** the bytes must agree (PDF signature, OOXML zip with at most
10,000 entries and 2 GB unpacked, UTF-8 text, image magic numbers); dedup per folder by hash; a job per file:
parse (text read directly, everything else through Docling) → chunk (Chonkie recursive, at most 480 tokens by
bge-small's own tokenizer) → embed (onnxruntime, batches of 32) → index (chunks, FTS5 by trigger, vectors by
the job) → `ready`. Cancel is checked between steps; a failure is retried twice and then written on the row.

**Retrieval** (`shared/search.py`, `shared/tokenizer.py`): two legs of 20 candidates each, BM25 over FTS5 and
sqlite-vec nearest neighbours, blended `0.65 × cosine + 0.35 × fraction-of-terms-matched`, then `top_k`. Ranking was
**measured** by SurfSense on its own harness (`scripts/run_retrieval_eval.py`, a 266-query LIMIT-derived corpus plus
same-language slices); their own notes say the same-language slices are saturated at 100%. ADRs 0031, 0032, 0033
record why the blend is absolute-score based.

**Grounded chat** (`modules/chat/`, 2.5k lines): the retrieved passages go **into the user message**, numbered
`[n]` and grouped under their document, with the question labelled; the system prompt is one of three markdown
files by model tier (`compact`, `capable`, `frontier`); a token budget keeps the system prompt, the passages, the
question and an answer reserve and trims history; passages cannot forge a source (tags stripped). The chat model
**never calls tools** (ADR 0052): retrieval happens before the model is asked. SurfSense reports this on Qwen3
1.7B: the labelled question scored the expected facts in 24 of 24 answers. Citations are stored with the message
and open a citation panel with the passage and its neighbours.

**Studio** (`modules/artifacts/` 7.7k lines, `worker/studio/` 4.4k): twelve formats behind one job seam. The
builder rule (ADR 0010): the model writes **structured content** (JSON or Markdown) and committed builders render
it, so nothing the model wrote executes. Eight formats follow it (Markdown, mind map, flashcards, quiz, web page,
podcast script, image prompt, infographic brief). **Word and PDF** take a Markdown path for small models and a
script path for strong ones; **PPTX and XLSX** are model-written Python run by a script runner, which SurfSense
itself lists as a gap ("nothing confines a script's network or file access", `ROADMAP.md`).

**Agent** (`modules/agent/`, 10.5k lines): a chat thread can be answered in steps by **opencode**, a separate
coding-agent binary SurfSense stages and supervises. The screenshot's "Agentic" mode is this. It also makes
Word/PDF/PPTX/XLSX edits of the user's own files. It is the largest and most dependent part of the app.

**Local models** (`modules/llm/`, 18k lines): runtime, catalog, fit, downloads, connections to remote
endpoints, the model-type router. We already have our own equivalents (ADR-0063, ADR-0064, stage D), so this
module is a reference, not an import.

## 4. Measured coupling: can the parts be lifted?

Counted from the source (every non-test `.py` file, whether it imports `modules.llm`, `modules.agent`,
`modules.plugins`, `modules.license`, `modules.egress` or `api.*`):

| Area | Lines | "Pure" files (no import of those) | Coupled files | Meaning |
|---|---|---|---|---|
| `worker/ingestion/` | 745 | 12 files, 688 lines | 1 (57 lines, a slide-count helper) | lifts almost whole |
| `modules/documents/` | 1,259 | 13 files, 720 lines | router and dependencies (539 lines, `api.*`) | store and rules lift; routes are re-written on our FastAPI |
| `modules/embedding/` | 1,121 | 15 files, 650 lines | 7 files, 471 lines (Hugging Face picker, tied to the SurfSense catalog) | encoder, pooling, spec, vector table lift; model picking is replaced by our hub |
| `shared/` (`search`, `tokenizer`, `db`) | 934 | 11 files, 740 lines | `db.py`, `queue.py` | retrieval lifts; engine and queue are replaced |
| `modules/chat/` | 2,479 | 15 files, 723 lines (budget, citations, prompts, images, runs) | router (893), prompt, errors, history (provider types) | prompts, budget, citation logic lift; the stream route is rewritten on our SSE contract |
| `modules/artifacts/` | 7,749 | 52 files, 6,329 lines | 12 files, 1,420 lines (job service, podcast brief, script documents) | formats, schemas, versions lift; job creation is rewritten |
| `worker/studio/` | 4,446 | 55 files, 2,695 lines | 21 files, 1,751 lines (generation seam, podcast drafting) | builders lift; the model call is the seam |
| `modules/pdf_tools/`, `worker/document_script/` | 1,044 + 826 | all | none | lift as they are (PDF merge/split/stamp; script runner) |

The seam is one thing: **every coupled file reaches the model through `modules.llm`** (`resolution`,
`providers.types`, `model_route.client`). In wasifyai the same seam is `ProviderDeps.text_provider` and the slot
manager (ADR-0056). So the reuse work is "write one adapter that gives their code a `generate(messages)` and a
`resolve(model_type)`", not "untangle a monolith".

Frontend (78k lines): the stack differs from ours, so UI code is **re-implemented to the same behaviour**, not
copied.

| | SurfSense | wasifyai |
|---|---|---|
| Components | shadcn `base-nova` on **Base UI**, hugeicons | shadcn on **Radix**, lucide |
| Server state | TanStack Query | own hooks (`useImageFlow`, `usePicture`) |
| Chat runtime | assistant-ui | own stream hook and `ImageWorkspace`-style components |
| Strings | react-intl, ten locales | plain English (v1 is English only) |
| Router | none (one dashboard) | hash router, `apps/desktop/src/router.ts` |

Pure logic that does lift: the tri-state source selection (`sources/tree/scope-state.ts`, 186 lines and its
149-line test), the visible-row and index builders, the SSE parser (`chat/sse.ts`, 171), citation markdown
(`citation-markdown.ts`, 45), the study-text parser (103), flashcard and quiz state machines. UI to re-implement:
sources tree (3.3k lines incl. tests), Studio panel (534), viewers (flashcards 482, quiz 383+166+344, mind map
122), citation panel (188), composer.

## 5. Feature parity with NotebookLM

NotebookLM as I know it (Sources, chat with citations, Notes, Studio with Audio Overview, Video Overview, Mind
Map, Reports, Flashcards, Quiz, Infographic, Slide Deck, Data Table, source guide with suggested questions,
Discover sources from the web). The product changes quickly; the owner should check this column against the
current Gemini Notebook before the plan is final.

| NotebookLM feature | SurfSense desktop | Our plan |
|---|---|---|
| Sources: PDF, Word, Slides, Sheets, text, Markdown, images | yes (PDF, DOCX, PPTX, XLSX, HTML, CSV, MD, TXT, images with OCR) | take as is (E1) |
| Sources: Google Docs/Drive, web page, YouTube, audio | no (web was hosted-only) | Drive/web/YouTube later, each its own decision (network, ADR-0060 Not in this version) |
| Chat grounded in sources, inline citations that open the passage | yes | take (E2) |
| Select which sources count | yes (tri-state ticks, folders) | take (E3) |
| Source guide: summary, key topics, **suggested questions** on adding a source | **no** | build (E5): one structured model call per source, cached |
| Save a response as a note; notes as sources | partly (notes are sources; no "save answer") | build (E5) |
| Audio Overview (two hosts) | yes, WAV, local voices | take the script writer; voice through our TTS product (E5) |
| Video Overview | no | later (our video product, ADR-0062) |
| Mind map | yes (Markmap) | take (E4) |
| Report / study guide / briefing | yes (Markdown, Word, PDF) | take (E4) |
| Flashcards, Quiz | yes | take (E4) |
| Infographic, images | yes (needs an image model) | our ComfyUI image engine (E5) |
| Slide deck | yes (model-written script) | **structured spec + python-pptx** instead of a script (E5) |
| Data table | partial (XLSX) | structured table spec (E5) |
| Customise chat (goal, length) | modes (Agentic/Fast) | a short "style" setting, later |
| Share, public notebooks, collaboration | no | not planned (one person, one machine) |

Beyond NotebookLM, SurfSense also edits your own PDFs, Word and PowerPoint files as copies. That is attractive but
it is the agent (section 3), not the notebook. Out of v1.

## 6. Reuse matrix

Levels as in ADR-0061: **A** run it as an engine, **B** import and own, **C** reference only, **D** do not take.

| SurfSense part | Level | Notes |
|---|---|---|
| `worker/ingestion` pipeline, `modules/documents` rules (hashing, hardening, dedup, statuses) | **B** | the core of E1 |
| `modules/embedding` (encoder, pooling, spec, vector table), bundled bge-small ONNX | **B** | model file comes through our hub/components with a checksum, not bundled in the installer |
| `shared/search.py`, `tokenizer.py` | **B** | retrieval; eval corpus kept in the repo |
| `modules/folders`, `source_scope`, `source_roots` | **B** | folders and ticks; the "managed root" is simplified to one root per notebook |
| `modules/chat` prompts, budget, citations, history window, title | **B** | stream route rewritten (our SSE contract, run store, cancel) |
| `modules/artifacts` + `worker/studio` content, web, office/markdown builders | **B** | the structured formats; the job seam is rewritten |
| `office/` PPTX/XLSX script paths, `worker/document_script` | **C / D** | replaced by structured specs (ADR-0010's rule, which ADR-0060 decision 10 already chose) |
| `modules/pdf_tools` | **B, later** | PDF merge/split/stamp, only when a feature needs it |
| podcast drafting (`worker/studio/media/audio/podcast`) | **B** | script writer; voice goes to our TTS product |
| `modules/agent`, opencode, `plugins`, `plugin-registry`, MCP | **D** (v1) | a separate, large decision; the assistant (ADR-0057) already has tools |
| `modules/llm`, `runtime_packs`, `resource_usage`, `egress` | **C** | we have ADR-0063/0064/stage D and our own egress rules |
| `modules/license`, `migration` (cloud import), `updates`, `feedback`, Electron shell | **D** | not our product |
| Frontend `sources`, `chat`, `studio`, `dashboard` | **C** | behaviour and layout reference; logic files **B** where pure |

## 7. What to measure before the ADR is accepted (the spike)

These are the questions the code cannot answer. Same method as ADR-0061 Phase 0: install in isolation, run,
write numbers here.

| # | Question | Why it decides something |
|---|---|---|
| S1 | Install size and first-run time of the Docling stack (torch CPU, layout model, RapidOCR) on this Mac, and the time per page for a text PDF, a scanned PDF, a 30-slide PPTX, a DOCX with tables, an XLSX | decides "Docling as an optional component" versus a light parser (pypdf, python-docx) first |
| S2 | Their retrieval eval and our own mixed English corpus, dense versus their blend, against the Unsloth numbers (dense 10/10, hybrid 8/10, lexical 8/10 at rank 1) | ADR-0060 decision 7 said "chosen by the corpus"; this is that corpus |
| S3 | Grounded answers with the model we recommend (Qwen3 4B, stage D6), 20 questions over 5 documents: cited, supported, refusals | their prompts were tuned on Qwen3 1.7B and others; ours must hold on our model |
| S4 | Memory: chat model + embedder + (ComfyUI idle) on a 16 GB Mac, per our slot manager | ingestion while a chat model is loaded must not fall over |
| S5 | Licence of every wheel and model file in the closed set | ADR-0060 decision 4 |
| S6 | Does the ingest copy run when lifted into a product package with our SQLite engine and in-process queue (no Huey, no second process)? | confirms the adapter claim in section 4 |

## 8. Risks

- **Docling weight.** torch and the layout models are the heaviest thing we would add (SurfSense excludes them
  from the API process and runs them in a worker for this reason). Handled by making the reader a component
  installed on demand, as ComfyUI and llama.cpp are, and by S1.
- **Small-model quality.** Citations and refusals depend on the model. SurfSense's chat eval and tiered prompts
  are the best available evidence; S3 re-measures on our recommended model.
- **Maintenance.** We would own roughly 25k lines of imported Python and a re-implemented UI. Mitigation: import
  by area, each with `PROVENANCE.md` and tests copied with the code; do not import what no feature needs.
- **Scope.** NotebookLM is a large product. The plan ships it in slices that each work alone (a notebook that
  answers questions is useful before Studio exists).
- **Dependencies need approval** (`CLAUDE.md`: ask before adding a new one): `docling`, `chonkie`,
  `sqlite-vec`, `onnxruntime`, `tokenizers`, `markdown-it-py`, `python-pptx`, `python-docx`, `openpyxl`,
  `pypdfium2`; on the UI side `markmap-lib`/`markmap-view`, `pdfjs-dist`, `docx-preview`, a Markdown renderer
  with citations. The list is repeated in the ADR.

## 9. E0 results (measured 2026-10-16, MacBook Pro M5 Pro, 64 GB, macOS)

Method: SurfSense's Docling options, chunker, embedder code and retrieval SQL, run in a scratch virtual
environment outside both repositories (Python 3.12.11, `docling 2.139.0`, `chonkie 1.7.0`, `onnxruntime 1.31.0`,
`sqlite-vec 0.1.9`, `torch 2.14.1`; SurfSense's lock file pins docling 2.125.0). Corpus: 7 real public PDFs
(AWS exam guides and architecture diagrams, a university course guide, a keyboard-shortcut sheet; 66 pages) and 7
generated files with invented facts (DOCX with a table, a 30-slide PPTX, XLSX, HTML, Markdown, CSV, a 2-page
scanned PDF). 29 questions: 24 answerable (15 synthetic, 9 real), 5 not in the sources. Scripts, questions and raw
results: `docs/spikes/surfsense-e0/`. Personal files were not used.

### S1: the document reader (Docling)

| Measure | Result |
|---|---|
| Python packages installed (everything the harness needed) | 1.2 GB; of it torch 528 MB, OpenCV 121, onnxruntime 77, scipy 72, transformers 55, pandas 41, RapidOCR 33, docling-parse 31 |
| Model weights, pruned as SurfSense prunes them | layout (heron) 164 MB, table structure 203 MB, RapidOCR 31 MB = **398 MB** (a full download is 699 MB; the ONNX layout copy and the fast table model are unused) |
| Disk for the reader component | about 1.0 GB packages + 0.4 GB weights = **about 1.4 GB**; with the embedder 1.5 GB |
| Cold start, first PDF | 3.5 s to import and build the converter, then 6.4 s for a 16-page PDF; peak memory 2.2 GB |
| Warm, text PDFs | 0.15 to 0.6 s per page (19 pages in 10.5 s on the first file, 21 pages in 3.1 s, 6 pages in 1.4 s); a one-page, table-heavy sheet 3.7 s |
| Office and web formats | DOCX, PPTX (30 slides), XLSX, HTML, CSV: 0.0 to 0.1 s each; tables came out as Markdown tables; slides as headed sections |
| Peak memory over the run | 3.7 GB (grows with the files parsed; the process should be a subprocess that exits when idle) |
| Scanned PDF, OCR | read correctly once the scan is an ordinary embedded image; **my first synthetic scan came back as an empty `<!-- image -->` with no error**, because Docling could not use how that PDF stored the picture |
| XLSX formulas | a cell with a formula and no cached value reads empty (a file saved by Excel has cached values; my generated one did not) |

Verdict against the ADR gate: size **passes narrowly** (1.4 GB against about 1.5 GB), speed **passes** (a page
every 0.15 to 0.6 s). Docling stays the reader, installed as a component. Two things follow:
- **A parse that yields no text must fail visibly**, not become an empty "ready" document (the empty-scan
  case above). A page-bearing file with almost no characters is "could not read the text; is it a scan?".
- **Memory:** the reader runs as its own process, started when there is a file and stopped when idle, owner `reader`
  in the slot manager, so its 2 to 4 GB is returned.
- Not measured: an ONNX-only layout engine (the unused `layout-heron-onnx` weights) in place of torch, which
  could remove about 600 MB (torch 528 + transformers 55). Worth a day if the size matters in E1.

### S2: retrieval

69 chunks from 14 documents (480 tokens at most), bge-small ONNX, answer found by chunk text and source:

| Mode | Rank 1 | Top 3 | Top 5 |
|---|---|---|---|
| dense only | 17 / 24 | 23 / 24 | 24 / 24 |
| lexical only (FTS5 BM25 and term coverage) | 19 / 24 | 20 / 24 | 22 / 24 |
| **hybrid (SurfSense's blend, weight 0.65)** | **22 / 24** | **24 / 24** | 24 / 24 |

- **Hybrid is confirmed** on this corpus (ADR-0060 decision 7 asked for the corpus to decide). The corpus
  rewards the lexical leg because it asks for numbers, names and shortcuts; Unsloth's earlier measurement
  (dense 10 of 10, hybrid 8 of 10) used paraphrased questions and is not comparable.
- **Ingest:** 69 chunks embedded in 2.2 s (CPU, onnxruntime), whole ingest 2.6 s after the parse; peak 620 MB
  without Docling.
- **Latency:** about 3 ms per question (embedding included) at 69 chunks; both legs together **52 ms at
  100,000 chunks** (brute force, `sqlite-vec`) and 5 ms at 10,000. LanceDB is not needed for a personal library.
- **There is no usable score floor.** The blended score of the best chunk was 0.553 to 0.706 for answerable
  questions and up to **0.678** for questions not in the sources. The two ranges overlap, so "below a score
  floor, say it was not found" (ADR decision 10) cannot be a threshold; the refusal has to come from the prompt,
  as in SurfSense, and be checked (S3).

### S3: grounded answers (Qwen3 4B Q4_K_M, our llama.cpp b11655, context 8192, temperature 0.2, no thinking)

Top 5 hybrid chunks, SurfSense's prompt format with its two tiers:

| Prompt tier | Correct | Correct with a supporting citation | Not in sources: said so | Not in sources: put a citation on it anyway |
|---|---|---|---|---|
| `compact` | 23 / 24 | 22 to 23 / 24 | 5 / 5 | 0 |
| `capable` | 24 / 24 (23 by exact string; the 24th said "50 scored questions") | 23 / 24 | 4 / 5 | 2 |

- The answers took 1.1 s median, 1.5 s at most.
- `compact` followed the refusal rule exactly, but once said "the sources don't cover this" and then gave the
  right number from them without a label (the beta programme question). `capable` answered everything, but gave
  "The capital of Australia is Canberra [1]" (a made-up citation on general knowledge) and cited five sources on
  "the document does not mention the chief financial officer". **A server-side rule is needed** either way: remove
  labels from an answer or a sentence that says the sources do not hold the answer (SurfSense's own post-step
  already drops numbers that are not in the list; this one is new).
- n is small (29). The tier is chosen again in E2 on a larger set; both prompts are kept.

### S4: memory

| Process | Measured |
|---|---|
| Embedding and retrieval (no Docling) | 620 MB |
| Reader (Docling) | 2.2 GB for one PDF, 3.7 GB after a mixed batch |
| llama-server, Qwen3 4B Q4_K_M, context 8192, `-np 1` | footprint 1.3 GB (weights are mapped, 2.5 GB file) after one request, but **10.4 GB after about 58 long prompts**, because llama.cpp's default prompt cache (`--cache-ram`, 8 GiB) fills |
| the same with `--cache-ram 0` | stays at 1.3 GB |

**Finding for stage D:** our llama component (`services/api/src/wasifyai_api/llama_server.py`) passes `-np 1` and
no `--cache-ram`, so a long chat can grow the server far beyond the 3.9 GB the model hub's fit check estimates.
The cache helps repeated prefixes, but a small default is the right one for a 16 GB Mac. **Fixed 2026-10-16:** the
component now passes `--cache-ram 512` (`PROMPT_CACHE_MIB`); the same 58 prompts left the server at 1.8 GB
(peak 2.7 GB) with unchanged answers.

On a 16 GB Mac: chat model about 4 GB + reader 2 to 4 GB (only while ingesting) + embedder 0.6 GB + the app is
within budget if the reader is not resident and ComfyUI is not generating (the slot manager already refuses
that combination).

### S5: licences (from the installed wheels' metadata and the model cards)

| Component | Licence |
|---|---|
| docling, docling-core, docling-ibm-models, docling-parse | MIT |
| chonkie | MIT; chonkie-core MIT or Apache-2.0 |
| onnxruntime | MIT |
| sqlite-vec | MIT or Apache-2.0 |
| tokenizers, transformers, rapidocr, huggingface-hub, OpenCV | Apache-2.0 |
| torch | Apache-2.0 AND BSD AND MIT AND BSL-1.0 (and others) |
| numpy, scipy, pandas, torchvision, reportlab, psutil | BSD |
| python-docx, python-pptx, openpyxl, markdown-it-py, pydantic | MIT |
| pypdfium2 | BSD-3-Clause, Apache-2.0 (PDFium) |
| Models: bge-small-en-v1.5 (BAAI and the Qdrant ONNX build) | MIT |
| Models: docling layout (heron) | Apache-2.0 |
| Models: docling table structure | CDLA-Permissive-2.0 and Apache-2.0 |
| Models: RapidOCR PP-OCR weights | Apache-2.0 per the RapidOCR project; the model card API refused an unauthenticated read, so **confirm from the project's licence before shipping** |

All are permissive and allow commercial use (rule 12). PyMuPDF (AGPL) is not in this stack.

### S6: does the lifted code run without SurfSense's process model?

Six files were copied into a scratch package: `spec.py`, `pooling.py`, `encoder.py`, `bundled.py`,
`tokenizer.py` (shared) and the ingest `chunking.py`: 349 lines, **20 changed** (import paths and two lookups of
their `shared.config`; `spec`, `tokenizer` unchanged). Ingest, FTS5, vector index and the retrieval SQL then ran
on a plain `sqlite3` connection, with no SQLAlchemy models, no Huey queue and no second process. What was **not**
lifted yet and must be ported in E1: the SQLAlchemy document and folder models (SQLite via our own store), the
upload hardening and dedup (`modules/documents`), the `retrieve()` wrapper (rewritten here with `sqlite3`, about
80 lines), and the job state transitions (`worker/jobs.py`) onto our job queue.

### What the measurements change

1. **ADR decision 10:** the "score floor" is replaced by "prompt rules plus a post-check that removes citations from
   a refusal", measured above.
2. **ADR decision 7:** Docling as a component is kept, with a visible failure for empty parses and a reader
   subprocess. The ONNX-layout shrink is an E1 option.
3. **Stage D follow-up:** `--cache-ram` on the llama component.
4. Decisions 8 and 9 are confirmed (embedder 65 MB, checksum verified; hybrid retrieval, no vector database).
