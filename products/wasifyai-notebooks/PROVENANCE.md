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
