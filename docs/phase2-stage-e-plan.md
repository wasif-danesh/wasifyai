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
| The assistant searches My creations only | a notebook answers from its sources; later the assistant gets `search_notebooks` |
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
| **E4** | Studio text formats: report, study guide, flashcards, quiz, mind map, Word, PDF; outputs as creations and searchable (ADR-0041 checklist) | builder and route tests, a real run of each |
| **E5** | Studio second wave and extras: source guide and suggested questions, save as note, slides and spreadsheet from specs, audio overview (our TTS), infographic and image | real runs, listening check |
| **E6** | Assistant tool `search_notebooks`; hardening pass; docs | tool test, `docs/desktop-profile.md` |

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
