# Provenance of imported code

Source: SurfSense, <https://github.com/MODSetter/SurfSense>, folder `surfsense_local/backend` (the desktop
app's backend), commit `622c1ded8` (13 Oct 2026). Licence: Apache-2.0 (root `LICENSE`; the files taken are
outside `surfsense_backend/app/proprietary/` and `plugins/remote/proprietary/`, which are Business Source
License and are not used). Imported on 2026-10-16 (ADR-0065, decision 2; method ADR-0061 decision 3).

## Imported files (code kept, changes listed)

| File here | Source file | Changes |
|---|---|---|
| `wasifyai_notebooks/tokenizer.py` | `shared/tokenizer.py` | Header added. Code unchanged. |
| `wasifyai_notebooks/chunking.py` | `worker/ingestion/chunking.py` | Header added. The pinned tokenizer comes from the caller (a path), not from SurfSense's bundled folder; the `word` tokenizer is allowed for tests. Rules and 480-token size unchanged. |
| `wasifyai_notebooks/embedding.py` | `modules/embedding/pooling.py`, `encoder.py`, `bundled.py` (the BGE spec) | Merged into one module. The model files are named by the caller; the spec is a plain dataclass. Pooling and the ONNX session code are unchanged. |
| `wasifyai_notebooks/retrieval.py` | `shared/search.py` | The two legs, the coverage score and the blend are the same SQL and arithmetic; rewritten on `sqlite3` instead of SQLAlchemy, with a `mode` (dense, lexical, hybrid) for evaluation. |

## Adapted, not copied

| File here | Source | What was taken |
|---|---|---|
| `hardening.py` | `modules/documents/` (upload rules), `docs/architecture/documents.md` | The extension list, the byte check against the extension, the OOXML entry and size limits. |
| `ingest.py` | `worker/ingestion/pipeline.py`, `worker/jobs.py` | The steps (parse, chunk, embed, index), cancel checks between steps, interrupted work failed at start, priority for interactive work. |
| `store.py` | `docs/architecture/data-model.md` | Table design: documents, chunks, FTS5 by trigger, vectors in sqlite-vec, dedup by SHA-256 per folder. |
| `docling_worker.py` | `worker/ingestion/parsing.py` | The Docling options (OCR, table structure, threads, the line classifier off). A serve loop is new. |
| `reader/models.yaml` | `scripts/fetch_docling_models.py`, `rapidocr/default_models.yaml` | Which weight files are needed and which are pruned; the RapidOCR file URLs and SHA-256 are RapidOCR's own. |

## Read and not taken

The agent (`modules/agent`), plugins, the model layer (`modules/llm`), licence, import, updates and the
Electron shell (ADR-0065 decision 4).

## Added for E2 (the grounded chat)

| File here | Source file | Changes |
|---|---|---|
| `prompts/compact.md`, `prompts/capable.md` | `modules/chat/prompts/compact.md`, `capable.md` | Copied unchanged. |
| `prompts/no_sources.md` | `modules/chat/prompt.py` (`_NO_SOURCES`) | Reworded: "notebook" for "knowledge base", and no labels at all. |
| `grounding.py` | `modules/chat/prompt.py` | The excerpt block (`<retrieved_context>`, documents grouped, numbered passages, tags defanged, the question labelled) and `resolve_citations` (invented numbers dropped, code left literal). The refusal and unsupported-label rules are new (E0 measurements). The history budget follows `modules/chat/budget.py` (prices and the answer reserve). |

## Added for E4 (Studio)

| File here | Source file | Changes |
|---|---|---|
| `studio/prompts/{report,flashcards,quiz,mindmap}/{compact,capable}.md` | `worker/studio/content/{summary,flashcards,quiz,mindmap}/prompts/{compact,capable}.md` | Copied unchanged (the `frontier` tier is not used). `report` is SurfSense's `summary`. |
| `studio/formats.py` | `worker/studio/content/*/schema.py`, `pipeline.py`, `shared/text.py` | The reply schemas for flashcards and quiz, the ceilings (20 cards, 10 questions, 10 branches), what is dropped from a loose reply (a card with no back, a question without four distinct options or whose answer is not one), the mind map as an outline, tolerant JSON parsing. The format table, the study guide, the Word and PDF paths and the retry are new. |
| `studio/context.py` | `worker/studio/shared/gather.py` | Whole if it fits, an even share each, else the best passages; written on this store's `sqlite3` and retrieval. The budget from the model's window is new. |
| `studio/blocks.py`, `studio/markdown.py`, `studio/links.py` | `worker/studio/office/markdown/{blocks,parse,links}.py` | Header added. Chart and figure support removed (a `chart` fence is code). |
| `studio/word.py`, `studio/pdf.py` | `worker/studio/office/markdown/{word,pdf}.py` | Header added. Chart blocks removed; figures optional (none yet). |
| `studio/pdf_text.py` | `worker/studio/office/markdown/pdf_fonts.py` | Replaced: Latin-1 only, anything else becomes `?` (v1 is English); SurfSense's DejaVu and CJK fonts need matplotlib. |

## Added for E5

| File here | Source file | Changes |
|---|---|---|
| `studio/prompts/infographic/{compact,capable}.md` | `worker/studio/media/visual/infographic/prompts/{compact,capable}.md` | Copied unchanged. |
| `studio/formats.py` (`infographic_prompt`, the infographic brief) | `worker/studio/media/visual/infographic/pipeline.py` | The brief (title, summary, up to 8 label/value/detail sections) and the sketchnote style; the prompt is cut to the image product's 500-character limit. |

Written here, with SurfSense's formats as the starting point and no code from them: the slide deck and
table prompts and builders (`slides.py`, `sheet.py`; SurfSense has the model write a Python script for these
two and run it, which this product does not do), the audio script prompt (SurfSense drafts a podcast segment
by segment and voices it with audio.cpp; here one call writes the script and nothing is voiced), and the guide.

## Added for E6

Nothing was copied. `across.py` (searching all of a person's notebooks for the assistant) is written here on top
of `retrieval.py`; SurfSense searches one search space at a time and has no cross-notebook search. The change in
`retrieval.py` (a `blended` score on each hit, and a NULL cosine distance counted as no evidence) is ours.

