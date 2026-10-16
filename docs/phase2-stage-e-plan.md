# Phase 2, stage E: Notebooks, a NotebookLM-style workspace (plan)

Status: **Approved 2026-10-16** (all recommended answers). **E0 done the same day** (gate passed); E1 is next.
Replaces the old stage E ("documents and retrieval in chat", ADR-0060). Decision record: `docs/decisions/0065-notebooks-source-grounded-workspace.md`.
Evidence: `docs/spikes/surfsense-investigation.md`.

**Goal.** On the Mac, with no other tool installed: make a notebook, add PDF, Word, PowerPoint, Excel, text and
web-page files, ask questions that are answered from them with citations that open the passage, and turn the
sources into study material and documents (report, flashcards, quiz, mind map, slides, audio overview). All of it
on the computer, with the chat model the person already has.

**Not in this stage:** web, YouTube and Drive sources, editing the user's own office files (SurfSense's agent),
plugins and MCP, sharing, the web profile, Bengali and Hindi, video overview.

## What exists and what changes

| Today | After stage E |
|---|---|
| Side menu: New chat, Models, Library, Images, Train (Soon), an empty **Projects** block, Recents | an expandable **Notebook** entry (*Create*, *View Notebooks*); the empty *Projects* block goes |
| Routes: `home`, `create`, `edit`, `library`, `models`, `settings` | adds `notebooks` (the list), `notebooks/new` (a draft) and `notebooks/<id>` (a notebook) |
| The assistant searches My creations only | a notebook answers from its sources; the assistant gets `search_notebooks` (E6, done) |
| No document parsing, chunking, embedding or vector store in the engine | `wasifyai-notebooks` product, `notebooks.db`, a reader and an embedder component |
| Library shows images, songs, videos | and notebook outputs (reports, quizzes, decks, audio), searchable (ADR-0041) |

## The interface

### Left menu (the global one)

Decided by the owner (2026-10-16): one expandable **Notebook** entry with two items, the same pattern as *Images*
(whose items are Create and Edit).

```
 [w] Wasify AI                       [search]
 ───────────────────────────────
  New chat
  Notebook           v               <- new, expands
      Create                            makes a notebook and opens it
      View Notebooks                    the list of existing notebooks
  Library                               (My creations, now with notebook outputs)
  Images             v  Create / Edit / (Soon) ...
  Models
  Train  (Soon)
 ───────────────────────────────
  Recents                            (chats, as today)
 ───────────────────────────────
  [You]  Settings
```

- Clicking **Notebook** only expands or collapses it (like *Images*). **Create** opens a new notebook; **View
  Notebooks** opens the list (`#/notebooks`). Inside a notebook, *Notebook* stays expanded and the open notebook
  is shown as the current page.
- **Create does not save an empty notebook.** It opens `#/notebooks/new`, a draft named "Untitled notebook"
  with the add-sources dialog already open; the notebook is stored when the first source is added or the title
  is edited. Pressing Create ten times therefore leaves no ten empty notebooks.
- The empty *Projects* placeholder block is removed (nothing in v1 fills it).
- The other products (Video, Voice, Music) follow the same pattern; the whole menu is in
  `docs/desktop-profile.md` ("The side menu's final shape").
- The menu collapses (it already can). Opening a notebook on a window narrower than 1,280 px collapses it
  automatically; the person can pin it open.
- Items follow the existing look (`ITEM` buttons, `aria-current`, the **Soon** pill). No new colours.

### Adding sources (the first thing a new notebook shows)

Modelled on NotebookLM's "Let's start your notebook" screen, simplified for v1:

```
          Let's start your notebook
   Add documents, then ask questions about them. They stay on this computer.

   ┌─ Add sources ────────────────────────────────────────────────┐
   │   [ Upload files ]   [ Copied text ]   (Websites · Drive soon)│
   │  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐  │
   │  │  Drag and drop your files here.                       │  │
   │  │  PDF, Word, PowerPoint, Excel, text, Markdown, HTML    │  │
   │  └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘  │
   └──────────────────────────────────────────────────────────────┘
```

| NotebookLM has | v1 |
|---|---|
| Upload files, drag and drop, Copied text | **yes** |
| Create note | **yes** (Sources pane: *+ Add* › New note) |
| Websites, YouTube | later (needs the network; ADR-0065 "Not in this version"); shown as a disabled "Soon" chip |
| Drive, Play Books | not planned (Google accounts); Google Docs are exported to `.docx` or `.pdf` first |
| "Search the web for new sources" with Fast Research | not planned (network, a search provider) |
| Suggested prompts ("Learn about a new topic") | no; replaced by the source guide's suggested questions (E5) |
| Banner promotions ("New: Interactive Reports") | no |

The dialog appears over the chat pane while the notebook has no sources, and from **+ Add** later. Files start
reading at once; the dialog closes on drop and the Sources pane shows each file's progress. Sources pane header
has **Add sources** and **Create note**, as in the screenshot.

### Notebooks list, *View Notebooks* (`#/notebooks`)

```
  Notebooks                                              [ + New notebook ]
  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐
  │ Q3 planning    │ │ Thesis reading │ │ + New notebook │
  │ 12 sources     │ │ 31 sources     │ │                │
  │ 3 outputs      │ │ 8 outputs      │ │                │
  │ Opened today   │ │ 2 days ago     │ │                │
  └────────────────┘ └────────────────┘ └────────────────┘
```

- Empty state: one sentence ("Add documents and ask questions about them. They stay on this computer."), a
  button, and the formats it reads.
- First use: if the *Document reader* or *Search model* component is missing, a card "Set up reading documents"
  with the size, one confirm, and progress (the same card pattern as "Set up image generation").
- Card menu: Rename, Duplicate, Delete (names how many sources and outputs go with it).

### A notebook (`#/notebooks/<id>`): three panes

```
 ┌ Q3 planning  ▾   (rename)     12 of 14 sources     [Qwen3 4B · ready]   ⋯ ┐
 ├──────────────┬──────────────────────────────────────┬──────────────────────┤
 │ SOURCES      │  CHAT                                │  STUDIO              │
 │ [search] [+] │  ┌ Source guide ──────────────────┐  │  ┌────┐┌────┐┌────┐  │
 │ ☑ Budget/    │  │ 12 documents about...          │  │  │Repo││Cards││Quiz│  │
 │   ☑ q3.xlsx  │  │ Topics: pricing · hiring · ... │  │  └────┘└────┘└────┘  │
 │   ☑ plan.pdf │  │ Try: "What changed in Q3?"     │  │  ┌────┐┌────┐┌────┐  │
 │ ☐ old.docx   │  └────────────────────────────────┘  │  │Map ││Deck││Audio│ │
 │ ◌ new.pdf…   │                                      │  └────┘└────┘└────┘  │
 │              │  You: What is the Q3 budget?         │                      │
 │              │  Answer ... [1] ... [2]              │  Outputs             │
 │              │  [Copy] [Save as note] [Regenerate]  │  Q3 summary   ready  │
 │              │                                      │  Quiz         ready  │
 │              │  ┌ Ask about your sources ─── [Send]┐│  Audio…  writing 40% │
 │ + Add source │  └ 12 of 14 sources · Qwen3 4B     ┘│                      │
 └──────────────┴──────────────────────────────────────┴──────────────────────┘
```

**Header.** Notebook name (inline rename), "12 of 14 sources" (the ticked scope, the same words as the chat's
scope chip), the chat model chip (the same chip as the assistant: name, memory, link to Models), a menu (Rename,
Export all outputs, Delete).

**Sources pane** (left, 280 to 340 px, collapsible):
- Header: count, a filter field, **+ Add** menu: *Files…*, *Folder…*, *Paste text* (a note), *New note*. The
  pane is also a drop target ("Drop files to add them as sources").
- A tree with folders and files; each row has a tri-state tick (a folder ticks everything under it, as in
  SurfSense `scope-state.ts`); a status mark per file (reading with percent, ready, could not read with the
  reason and **Retry**); a row menu (Rename, Move to…, Open, Delete). Keyboard: arrows, space ticks, F2 renames.
- Click a source: the pane becomes the **source viewer** (PDF by page, text, Markdown, image; the cited passage
  is highlighted) with a back arrow. From a citation the viewer opens at the passage.
- Select all / none at the foot of the header.

**Chat pane** (centre, flexible):
- The **source guide** card on top of an empty thread (summary, topics, three suggested questions; E5). Before
  E5 an empty notebook shows a short hint and the drop zone.
- Messages stream. A citation is a small numbered pill `[1]`; hover shows title, page and a two-line preview;
  click opens the source viewer at the passage. Several `[n]` for one claim collapse to a group.
- Under each answer: Copy, **Save as note** (E5), Regenerate, a thumbs pair is not planned.
- "Not found in your sources": the answer says so as the first words, then (optionally) a clearly labelled
  general-knowledge part. The scope chip shows what was searched.
- Composer: placeholder "Ask about your sources", the scope chip (click to open the Sources pane focus), the
  model chip, Send/Stop. A conversation list is a menu in the pane header ("Chats in this notebook", New chat).
- Errors use the existing notices (model not ready, memory too tight, nothing ready to search yet).

**Studio pane** (right, 300 to 360 px, collapsible):
- A grid of format tiles: **Report** (Markdown), **Study guide**, **Flashcards**, **Quiz**, **Mind map**,
  **Word**, **PDF**, **Slides**, **Spreadsheet**, **Audio overview**, **Infographic**, **Image**. Tiles whose
  needs are missing are dimmed with the reason ("Needs a chat model", "Set up image generation"), as SurfSense
  does.
- A tile opens a small brief: an optional instruction, the sources it will use (the ticked ones), format
  options (e.g. quiz length), **Create**. Studio jobs run in the background; the notebook stays usable.
- *Outputs* list: title, format, status (queued, writing with percent, ready, failed + Retry), version, ⋯ (Open,
  Rename, Download, Regenerate, Refine, Delete). Opening an output replaces the Studio pane with its viewer
  (reader, flashcards, quiz, mind map, document, deck, audio player) and a back arrow; "Add to sources" turns an
  output into a source.
- Every output also appears in **Library** (My creations), searchable.

**Narrow windows** (under about 1,100 px): the panes become three tabs (*Sources · Chat · Studio*) in a segmented
control under the header; the global menu is hidden. Under 700 px the same, one pane at a time.

### Behaviours worth stating

- **Nothing blocks the window.** Add 40 files and chat with the ones already read (the scope chip says "9 of 40
  sources are still being read").
- **Same answer, new facts.** Adding or deleting a source does not rewrite old answers; their citations still
  open the stored passage text, and say "this source was removed" if it is gone.
- **Memory.** Reading a PDF and answering a question both use memory. The chip shows what is loaded; the slot
  manager (ADR-0056) refuses cleanly with the existing "needs more memory" wording rather than failing.
- **Resumable.** Quit during ingest: the job resumes or is shown as "interrupted, Retry" next launch (SurfSense's
  `interrupted_documents` rule).

## Engine design (summary; decisions are in the ADR)

```
upload ─► hardening ─► documents row (pending) ─► ingest job ─► parse ─► chunk (≤480 tokens)
       ─► embed (bge-small ONNX) ─► chunks + FTS5 + sqlite-vec ─► ready  ──► SSE "documents" events

question ─► scope (ticked sources) ─► retrieve (BM25 + vector blend) ─► prompt (tier by model)
         ─► stream tokens ─► citations [n] ─► stored message + stored passages

Studio job ─► sources text (+ retrieved passages) ─► model writes structured spec ─► builder renders file
           ─► artifact (+ files, versions) ─► creation index (ADR-0041) ─► SSE "artifacts" events
```

Routes (all under `/products/wasifyai-notebooks`, loopback token as everywhere): notebooks CRUD; folders;
documents (upload, note, list, get, rename, move, delete, retry, cancel, original); `chunks/{id}` with
neighbours; `conversations` and `messages` (stream); `artifacts` (create, list, get, files, regenerate, refine,
delete); `formats` (availability); `events` (SSE). Desktop profile first; the SDK store interface leaves room for
the web adapter.

## Order of work

| Step | What | Evidence |
|---|---|---|
| **E0** | **Done 2026-10-16.** Spike S1 to S6 on this Mac; numbers in `docs/spikes/surfsense-investigation.md` section 9, scripts in `docs/spikes/surfsense-e0/`. Gate passed; ADR decision 10 corrected (no score floor) | numbers |
| **E1** | **Done 2026-10-16.** Engine: `notebooks.db`, hardening, ingest, reader and search-model components, retrieval, routes; PROVENANCE for what was copied (evidence below) | route and pipeline tests, a real 14-file corpus through the app, retrieval eval |
| **E2** | **Done 2026-10-16.** Grounded chat: scope, prompt tiers, budget, stream with citations, stored passages, refusal; the eval set (evidence below) | grounding eval on Qwen3 4B (cited, supported, refused) |
| **E3** | **Done 2026-10-16.** Window: side menu change, notebooks list, notebook page (Sources, Chat, source viewer, Studio tiles as Soon), setup card, router parameters, self-test extended (evidence below) | component tests, real-window self-test, screenshots |
| **E4** | **Done 2026-10-16.** Studio text formats: report, study guide, flashcards, quiz, mind map, Word, PDF; outputs saved with the notebook and searchable through it (evidence below) | builder and route tests, a real run of each |
| **E5** | **Done 2026-10-16, with one change:** source guide and suggested questions, save as note, slides and data table from specs, infographic through the image engine, audio overview as a **script** (no voice engine exists on the desktop yet) (evidence below) | real runs |
| **E6** | **Done 2026-10-16.** Assistant tool `search_notebooks`; hardening pass; docs (evidence below) | tool tests, real runs, `docs/desktop-profile.md` |

Each step ends with the repo's usual gate: tests, lint, typecheck, the window self-test where the window changed,
`git add`, and a one-line commit message for the owner.

## Answers (2026-10-16)

All recommended: Notebook; menu *Notebook* › *Create*, *View Notebooks* (a draft stored after the first source);
first release E0 to E3 then Studio; reader as a component, size measured in E0; no agent mode; dependency list
approved subject to S5.

## E1 evidence (2026-10-16, the owner's Mac)

**What was built** (`products/wasifyai-notebooks`, `docs/desktop-profile.md` "Notebooks"): the store, upload
hardening, built-in readers (text, Markdown, CSV, HTML), the Docling reader as a process of its own, SurfSense's
chunker, the ONNX search model, SurfSense's hybrid retrieval, the ingest worker, 22 routes, the reader's installer,
and the creation kind `notebook` for My creations search. Imported code: six files, each with a header and a
`PROVENANCE.md` entry; 349 lines were lifted in E0 with 20 changed, and the rest is written here.

**Tests.** 60 product tests (hardening, store, ingest, reading, reader installer, routes, search source) and one
desktop-profile test; the whole suite passes (1009 Python tests, 40 skipped), ruff, pyright, the self-test of the
window and `cargo test` for the one Rust change (the shell tells the engine where its `uv` is).

**Real run through the engine** (clean data folder, the installer, the Models-panel download, then 14 files):

| Step | Result |
|---|---|
| Search model through the Models panel | 67 MB, checksum verified, 8 s |
| Reader setup through `POST /setup/reader` | 70 s (packages from the cache, 416 MB of weights downloaded 46 s, 22 s to check); the first try **failed at the check**: the lock lacked `onnxruntime`, which RapidOCR needs and Docling does not declare. The check stopped it and left nothing installed; the lock now names it |
| Upload of 14 files (66 pages), reader as one process | all searchable after 30 s (72 s when each file started its own process, 3.5 s of start each) |
| Passages | 69 from 14 files (the same as the E0 harness) |
| Retrieval over HTTP | hybrid 22 of 24 at rank 1, 24 of 24 in the top 3; dense 17 and 23; lexical 19 and 20; 10 ms per question |
| Not the owner | 404 on the notebook and on search |
| Delete the notebook | 204; no stored files left |

**Decisions made while building** (the ADR is amended to match):
- **Polling, not a new SSE stream.** The window polls the documents list while anything is reading, as SurfSense
  does between events; no change to the SSE contract.
- **The reader is installed by the engine, not the Rust shell.** The engine has the lock, the manifest and the
  network permission rules; the shell only passes the path of its provisioned `uv` (`WASIFYAI_UV`). This keeps
  the installer testable in Python and the same on any profile.
- **The scan failure is visible.** A source whose text comes back almost empty fails with a sentence and Retry
  (the E0 finding).
- **Sources wait for the search model.** Adding files before the model is on the computer leaves them pending;
  they are read when it arrives.
- **The `notebook` creation kind is added in the platform and the search API;** the card and filter in My
  creations (the window) and the corpus row are E3's checklist (ADR-0041).

**Not done in E1:** folder upload with relative paths (a dropped folder), source viewers, the chat (E2), any
window (E3), Studio (E4 and E5), the web profile's store.

## E2 evidence (2026-10-16, the owner's Mac)

**What was built** (`products/wasifyai-notebooks`): `graph.py` (one grounded turn, a LangGraph graph like the
assistant's), `grounding.py` (excerpts, labels, the two label rules, the history window), `prompts/`
(SurfSense's `compact.md` and `capable.md`, and `no_sources.md`), conversations in `notebooks.db` (schema 2,
applied to a file made by E1), and four conversation routes. A question is a run of the product's graph
(`POST /products/wasifyai-notebooks/runs` with `{text, notebook_id, conversation_id?, document_ids?}`); the
existing event types carry it, so **the SSE contract is unchanged**:

| Event | Here |
|---|---|
| `node` | `search` ("Searching sources"), `answer` ("Writing the answer") |
| `tool_call` / `tool_result` | the search as a step: `search_sources`, arguments `{query, sources}`, output `{hits: [{n, document_id, title, snippet}]}` |
| `token` | the answer as it is written (labels not yet checked) |
| `done` | outputs: `reply` (labels checked), `citations` (each cited passage with its text as it was), `conversation_id`, `message_id`, `title`, `labels_removed`, `searched` |
| refusal (`done` with `status: refused`) | `no_sources`, `sources_reading`, `no_scope`, `not_found`, `invalid_request`, each with a sentence; the model is never asked |
| `error` | `embedder_missing`, `language_failed` (retryable), `not_available` |

**Tests.** 29 new product tests (graph on a scripted model with a real store, grounding rules, conversation
routes); the whole suite passes (1029, 40 skipped), ruff, pyright, typecheck.

**Real run** (clean engine, Qwen3 4B Q4_K_M by the app's own llama.cpp, context 8192, the E0 corpus of 14
files and 29 questions, each question its own conversation; three runs, the last after the cue list was
completed):

| Measure | Result |
|---|---|
| Sources read | 14 of 14 in 33 s |
| Answerable, answer correct | 23 of 24 by exact string; the 24th ("50 scored questions" for "50 questions that affect your score") is correct in meaning: **24 of 24** |
| Answerable, answer correct and the cited passage holds the fact | 23 of 24 |
| Not in the sources | 4 of 5 said so; the 5th ("capital of Australia") answered from general knowledge with no label, which the prompt allows |
| Labels on an answer that says it was not found | 0 (run 1: 2, run 2: 3, before the cue list grew; 4 labels removed in the final run) |
| Time to answer | median 4.1 to 4.4 s, at most 8.9 s (search about 10 ms, the rest is the model) |
| Follow-up in the same conversation ("And Engineering?") | answered from the right passage (4 s) |
| Scope of one source (`document_ids`) | only that source searched and cited |
| Nothing ticked / notebook empty | refused in words, model not called |

**Found while measuring.**
- The prompt's own example label `[n]` was copied into an answer by the model; it is now removed (a test).
- Support check: a label stays only if its sentence shares a word with the passage. It passed
  "The capital of Australia is Canberra [3]" because that passage mentions Australia. Cheap and imperfect; the
  fix is a larger evaluation set in E4, not a stricter rule now.
- The refusal cues grew from E0's list ("none of the excerpts...", "cannot be answered...") as the model
  rephrased; the cue list will keep growing, which is why labels are also checked against passages.
- **Thinking is not switched off.** The provider has no way to pass `enable_thinking: false`; Qwen3 4B answered in
  about 4 s anyway, but a model that thinks at length will be slow. A switch in the language provider is a
  follow-up (SurfSense has a "thinking" setting).
- The reference clone was absent from `~/Projects` during E2 and was cloned again by the owner at the same
  commit (`622c1ded8`); the imported files match it byte for byte, and everything used is in this repository
  with its provenance (`PROVENANCE.md`).

**Not done in E2:** the window (E3), source guide and suggested questions, "save as note" (E5), the tier chosen
on a larger set, a `search_notebooks` tool for the assistant (E6), indexing of notebook conversations in My
creations (the notebook itself is indexed).

## E3 evidence (2026-10-16)

**What was built.** The side menu as approved (Notebook › Create, View Notebooks; Video, Voice, Music with their
items as Soon; the empty Projects block gone; one group open at a time); the router with notebook addresses and
drafts; View Notebooks; the notebook page with the add-sources screen, the sources tree, the conversation with
citations, the source viewer and Studio's tiles; the setup card. Details in `docs/desktop-profile.md`
("Notebooks in the window").

**Tests.** 24 new in `packages/ui` (the notebook screens and the tick logic), 6 in the client (the reducer of a
question and the API), 10 in the app (menu, router, setup), and a route test for search at once; ruff, pyright
and typecheck pass, the whole Python suite passes (1030, 40 skipped), the UI suites 39, 63, 44 and 280.

**Real window** (`WASIFYAI_SMOKE=1`, the real webview and engine): the self-test lists the menu groups, opens a
new notebook, adds a Markdown file through the file input, sees it in the sources list (it waits there because
the search model is not on a clean computer), finds the notebook's card with "1 source", deletes it, and the
image part still passes. Seen in the page with the engine replaced by a script: the three panes, the citation
pills opening the passage with the cited lines marked, the add-sources screen, the setup card, the narrow tabs.

**Found while building.**
- The first layout overlapped the "show the menu" button with the header and let a grid grow wider than the
  window (a `grid` item sizes to its content unless its track is `minmax(0, 1fr)`); both fixed.
- Markdown tables are now rendered (sources hold them; the answer's tables too), and the label callback keeps
  `[1](https://...)` a link.
- `errorMessage` read only a string `detail`; the product's `{code, message}` refusals are now read in words.
- A notebook is added to My creations search at once on create, rename and source changes, so the card is found
  without waiting for the platform's five-minute check.

**Not done in E3.** A PDF viewer by page (needs `pdfjs-dist`, not yet approved: sources show their text);
dropping a folder (the engine takes folder ids, the window has no relative-path upload yet); a Library card for
notebooks (the desktop Library is images only; notebooks are found from View Notebooks, and the creation kind is
in the API for the day Library lists every kind); Studio formats (E4); source guide and "save as note" (E5).

## E4 evidence (2026-10-16, the owner's Mac)

**What was built.** Seven formats made from a notebook's ticked sources by the chosen chat model:
Report and Study guide (Markdown), Flashcards and Quiz (validated JSON, with a viewer that turns cards over and
scores a quiz), Mind map (an outline shown as a tree), Word (`.docx`) and PDF, both rendered from the same
Markdown by committed builders. The model writes Markdown or JSON only; nothing it writes is run (ADR-0010).
Details in `docs/desktop-profile.md` ("Studio").

**How an output is made.** A run of the notebooks graph with `{notebook_id, studio: {format, prompt}, document_ids?}`
(no new event type; the same refusals as a question). The output row is saved at once as "making"; the sources
are cut to the model's window (`studio/context.py`); the reply is built and checked; a reply that cannot be used
is asked for once more with the reason; the result, its file and its data are saved. A stop or delete while it
runs wins: nothing is written over it.

**Tests.** 19 new engine tests (every builder, the Word and PDF files opened and checked, links and raw HTML kept
safe, the cut to the window, the run with a scripted model, the retry, the refusals, a stop mid-way, ownership,
the file route), 12 new UI tests (viewers, the Studio pane), 2 in the client; the Python suite passes (1049, 40
skipped), the UI suites 41, 71, 44 and 280, ruff, pyright, typecheck and the real-window self-test.

**Real run** (Qwen3 4B Q4_K_M, the app's llama.cpp, context 8192; the E0 corpus of 14 files; the seven generated
sources ticked for the first seven rows):

| Format | Time | Result |
|---|---|---|
| Report | 16.3 s | 574 characters, every figure from the sources (launch date, $350,000, headcount) |
| Study guide | 18.4 s | 1,635 characters with key terms and review questions |
| Flashcards | 14.1 s | 12 cards (the model made 12; none dropped) |
| Quiz | 36.0 s | 7 questions kept of 8 asked: one had no answer among its four options |
| Mind map | 26.1 s | three levels, 4 branches, labels with the figures |
| Word | 19.4 s | a `.docx` of 37 KB that python-docx opens, 16 paragraphs |
| PDF | 13.4 s | a 2.7 KB PDF (`%PDF-`) |
| Report from all 14 files (66 pages, far over the window) | 18.7 s | built from the best passages |

**Found while building.**
- **The engine bundle would have lacked the notebooks' packages** (found by reading the hashed lock): its lock is
  made from the API's dependencies and the notebooks product was not among them, so a packaged app would have
  failed to import the chunker, the search model runtime and the writers; it only worked from a development
  checkout. The API's `desktop` extra now names the product, and the lock contains chonkie, onnxruntime,
  tokenizers, python-docx, reportlab and the rest.
- The notebook search source read a notebooks file made before outputs existed and failed on the missing table
  (found by the real run); it now treats a missing table as no outputs.
- A new dependency was added with the owner's approval: **reportlab** (BSD) for PDF; `python-docx`,
  `markdown-it-py` and `pillow` were already on the approved list or are its requirements.

**Searchable.** Outputs are not separate creations: a notebook is found by its title, its sources' names and now
its outputs' titles, and an output opens from its notebook.

**Not done in E4.** Slides, spreadsheet, audio overview, infographic and data table (E5); Refine and versions of an
output; stopping the model mid-way when an output is stopped (the result is discarded instead); Bengali and Hindi
text in PDFs (Helvetica; other letters become `?`).

## E5 evidence (2026-10-16, the owner's Mac)

**What was built.**
- **Source guide.** A summary, up to eight topics and three questions, written once from the sources and
  saved with the notebook. The window makes it by itself the first time a chat model is chosen and there is
  none, shows it above an empty thread (a question fills the box), and offers "Sources changed, update" when
  a source was added, removed or read again (`GET /notebooks/{id}/guide` says `stale`).
- **Save as note.** Under an answer: it becomes a note in the sources (titled with the question, ending with
  the list of sources it cited), so Studio and later questions can use it.
- **Slide deck.** The model writes validated JSON (title, slides with up to six bullets, notes) and
  `python-pptx` renders a `.pptx`; a viewer steps through the slides.
- **Data table.** JSON columns and rows (at most 8 by 40) become an `.xlsx` of values with numbers as numbers;
  a cell that starts with `=` is stored as text, never a formula, so nothing the model wrote is calculated.
- **Infographic.** The model writes a factual brief; the image product draws a picture from a 500-character
  description (a child run, as the assistant's picture tool does); the viewer shows the picture **and the exact
  facts under it**.
- **Audio overview.** The model writes a two-host script (Alex and Sam, about two dozen turns). **The voices are
  not made:** the desktop has no speech engine (the TTS product runs in the web stack; ADR-0062's audio.cpp
  engine is the Voice stage). The viewer says so; the script is saved as Markdown.

**Tests.** 9 new engine tests (the five builders, the guide's saving and going stale, the infographic with a
scripted image run and without one, the guide route), 8 new UI tests (the new viewers, the guide, saving a note);
the Python suite passes (1058, 40 skipped), the UI suites 41, 77, 44 and 280, ruff, pyright, typecheck, the
real-window self-test.

**Real run** (Qwen3 4B, the app's llama.cpp, the 7 generated sources ticked; ComfyUI with FLUX.2 klein 4B):

| Output | Time | Result |
|---|---|---|
| Source guide | 14.5 s | summary, topics and questions from all the sources |
| Slide deck | 46.2 s | a 47 KB `.pptx` of 9 slides (title and 8), every figure from the sources |
| Data table | 15.8 s | headcount by team with open roles: 5 rows, 3 columns, an `.xlsx` that openpyxl opens |
| Audio overview script | 19.3 s | 1,607 characters of question and answer between the hosts, facts from the sources |
| Infographic | 84.7 s | the brief (5 sections) and an 864 x 1152 sketchnote picture; includes switching from the language model to the image model |

**Found while building.**
- **The picture's text is unreliable.** The 4B image model drew the sketchnote look well and the layout
  sensibly, but misspelled words and garbled numbers ("14 MANCH DATE", "$3550,2027"). A factual infographic with
  wrong numbers misleads, so the viewer always shows the exact facts beside it and says why. A larger image
  model or drawing the text ourselves over an illustration are the later options.
- **The audio script is a question-and-answer list, not yet a conversation.** Qwen3 4B follows the format and the
  facts, and writes short alternating turns; livelier dialogue needs the outline-then-segments method SurfSense
  uses, which is not worth building before there is a voice to play it.
- **The slide deck takes the longest of the text formats** (46 s): the JSON is long. A shorter default (six
  slides) would halve it; left at eight until slow machines are measured.

**Not done in E5.** Voices for the audio overview (needs the Voice stage), a picture style picker, editing a
deck or table in place, and Refine and versions of an output.

## E6 evidence (2026-10-16, the owner's Mac)

**What was built.**
- **`search_notebooks`, the assistant's third tool.** `ToolHost.search_notebooks` (platform SDK) is answered by
  `wasifyai_notebooks/across.py`: one query embedding, `retrieve` per notebook (up to 40 with a ready source, most
  recently used first), 3 passages each, merged by the blended score (`Hit.blended`, new), at most 2 per source,
  5 returned. The tool gives the model each passage with its notebook and source, marked as quotation and not
  instruction. `ToolUnavailable` carries "no search model" or "no notebooks here" back as words.
- **The window.** The assistant's tool card for `search_notebooks`: source, notebook, snippet and "Open notebook"
  (home opens `#/notebooks/<id>`); a failed search says why.
- **`search_creations` now names notebooks** by title (it returned bare ids, which the model then listed), and its
  description tells the model it does not read inside documents.

**Hardening pass.** Four things found and fixed, each with a test:
1. **Unknown output on cancel gave 409, not 404.** `POST .../artifacts/{aid}/cancel` for an id that does not exist
   said "not being made". Found by the new sweep below.
2. **A query with no direction crashed retrieval.** `vec_distance_cosine` is NULL when the query vector is all
   zeros (a query of only symbols, `*`), and the blend subtracted from `None`. NULL now counts as no evidence (distance 1).
3. **Passages are data for the assistant too.** The tool's text says they are facts to use, never instructions to
   follow, so a document that says "ignore your rules" is quoted, not obeyed (a test checks the wording is in what the model sees).
4. **Web build.** `ToolCard.tsx` uses hooks and is exported from the UI package's index, which the web app's
   server-rendered `not-found` page imports; it lacked `"use client"` and the web build failed. Added.

**The route sweep.** `test_every_route_under_a_notebook_is_swept_for_ownership_and_unknown_ids` calls every one of the
30 routes under `/notebooks/{nid}` twice: as another person (all 404) and as the owner with an unknown folder,
source, output or conversation id (404, never 500). It reads the route list from the OpenAPI document and fails if a
route is added and not listed, so a new route cannot skip the ownership check unnoticed. Also new: eight hostile
query strings (quotes, `NEAR(`, `OR`, `*`, column filters, a NUL, SQL) through the cross-notebook search.

**Tests.** 14 new engine tests for the search (order and location, ownership and empty notebooks, limits and
length, one source not filling the slots, no search model, hostile queries), 3 assistant tool tests, 2 tool-host
tests, the route sweep, 2 window tests. Python 1078 passed (40 skipped); client 41, UI 79, desktop 44, web 280;
ruff, pyright, typecheck, `pnpm build`, the real-window self-test (`SMOKE PASS`).

**Real run** (Qwen3 4B, the app's llama.cpp, the search model; two notebooks of generated files; the assistant product):

| Question | Tool the model chose | Time | Answer |
|---|---|---|---|
| "What is the marketing budget for the launch in my notebooks?" | `search_notebooks` | 5.5 s | $350,000, from launch-plan.pptx |
| "Search my notebooks: how many open roles does engineering have?" | `search_notebooks` | 5.9 s | 5, from headcount.xlsx |
| "What did the warranty scan say?" | `search_notebooks` (after the description fix) | 7.9 s | 18-month hardware warranty, 6-month batteries, lightning excluded, Lisbon service centre |
| "Which notebooks do I have about support?" | `search_notebooks` | 7.1 s | the FAQ's support hours and refund rule, by notebook |
| "Write me a haiku about autumn." / "What is the capital of France?" | none | 10.0 s / 1.4 s | answered directly, no search |

**Found.** Before the two description changes the 4B model picked `search_creations` for "What did the warranty
scan say?", which returned five notebook ids with no text, and it listed the ids. With notebooks named by title and
the description saying where to read documents, it chose `search_notebooks` and answered. A larger set of
tool-choice questions for notebooks (as for images in D6) has not been run.
The same document in two notebooks (my scratch library had a copy) shows up twice, once per notebook; that is
right, as they are two sources.

**Not done in E6.** Conversations of notebooks are not indexed in My creations (the notebook itself is); a cited
answer in the assistant (it quotes the notebook and source in words only); searching only some notebooks by name
("in my Budget notebook"); the tool-choice evaluation for notebooks.

