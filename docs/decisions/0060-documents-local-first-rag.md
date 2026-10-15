# ADR-0060: Documents: a local-first RAG product (ingest, search, grounded chat, generate)

- **Status:** Proposed
- **Date:** 2026-10-14
- **Depends on:** ADR-0017 (storage, `rag_chunks`), ADR-0035 (upload hardening), ADR-0041 (semantic search, the
  `creation-embedder`), ADR-0043 (media upload, long jobs), ADR-0056 (profiles, slot manager, utility models),
  ADR-0057 (assistant). The second vertical after image (ADR-0056).

## Context

The owner's requirement, in order: upload and ingest PDF, Word, Google Docs, TXT, CSV and similar files; extract
and chunk text; embed and store chunks in a vector database; semantic search; chat grounded in the retrieved
documents using local Ollama LLMs; generate summaries, PDFs and presentations. Local first: documents stay on the
device unless the user picks a cloud model.

What exists:

- wasifyai has `rag_chunks` in Postgres (HNSW, cosine, 768 dimensions, `nomic-embed-text`, fixed by migration 0003)
  and a separate `creation_index` with `bge-m3` (1024 dimensions, multilingual, ADR-0041). ADR-0041 already notes
  that moving RAG to the multilingual embedder needs its own migration.
- Unsloth's backend has a `rag` package (file names only, contents not read): parsers, `pdf_ocr`, `office_formats`,
  chunking, an embeddings server, a store, retrieval, locators, folder sync. Its PDF OCR notes: PyMuPDF plus
  Tesseract, off by default, 20 scanned pages per PDF, a failed scan fails the upload and lists the pages.
- The platform has no document parsers, no office-format generators and no PDF renderer yet.

## Decision

1. **A product `wasifyai-docs`** on the same engine (ADR-0056). Ingestion is a **job** (rule 6): parse, OCR when
   asked, chunk, embed, store; progress by SSE; the user can leave and come back. A collection ("Project") groups
   documents; a conversation can use one or more collections.
2. **Formats, first release:** PDF, DOCX, PPTX, TXT, Markdown, CSV, XLSX, HTML. **Google Docs:** the user exports
   or downloads a `.docx` or `.pdf` in the first release. A Drive connector (OAuth with PKCE, a Google Cloud
   client) is a later, separate decision because it adds an external dependency (ask first, `CLAUDE.md`).
3. **Hardening comes first and is always on** (extends ADR-0035/0043): size caps (100 MB, page and cell limits),
   content sniffing rather than names, zip-bomb checks for DOCX/PPTX/XLSX, no macros or scripts executed, parsers
   run in a **subprocess with a timeout and memory limit**, extracted text is capped, nothing is trusted.
4. **Parsing stack, permissive licences preferred.** Candidates, to be confirmed in a spike on a mixed corpus
   (English plus at least Bengali and Hindi): `pypdf` or `pdfminer.six`, `pdfplumber` for tables, `python-docx`,
   `python-pptx`, `openpyxl`/`csv`, an HTML text extractor, Tesseract for OCR (external binary, off by default,
   page-capped, language configurable). **PyMuPDF** (used by Unsloth) is AGPL-3.0; the owner accepts AGPL for the
   product (ADR-0061), so it is allowed, and Unsloth's parsers, chunker and locators are imported as a unit.
   Docling (layout and tables) is a heavier option to evaluate. Licences are confirmed before adoption.
5. **Chunking is structure-aware:** by heading, page and paragraph, about 300 to 500 tokens with small overlap,
   tables kept whole when they fit. Every chunk keeps a **locator** (document, page, heading path, character
   range) so an answer can cite and open the source.
6. **One embedder, with its identity stored.** v1 is English only (Bengali and Hindi come after release), so the
   desktop default is a small English model (`bge-small-en-v1.5`, about 130 MB, as Unsloth ships and as measured in
   Phase 0). The multilingual `bge-m3` (1024 dimensions) replaces it when languages are added. The `rag_chunks`
   table stores the embedder `model`, and changing it is a visible, migrated re-embed job (ADR-0041).
7. **Vector store behind an interface.** Web: pgvector (existing). Desktop: **SQLite with `sqlite-vec` and FTS5**
   in the same database file, so no new datastore (rule 12 spirit). LanceDB (embedded, ANN) is the fallback if
   brute-force search is too slow; Unsloth ships this exact SQLite + FTS5 + sqlite-vec design, and the spike still
   measures 10k, 100k and 1M chunks. **The retrieval mode is configurable and chosen by the evaluation corpus**
   (dense, hybrid by rank fusion, lexical): on paraphrased questions Phase 0 measured dense 10/10 at rank 1,
   hybrid 8/10 and lexical 8/10, so hybrid is not assumed better. A reranker may follow. A query returns chunks
   with scores and locators.
8. **Grounded chat is the assistant with tools** (ADR-0057): `search_documents(query, collection)` and
   `read_document(id, range)`. The answer cites `[n]` that open the locator. Below a score floor the assistant
   says it did not find it in the documents. Long documents are summarised map-reduce with structured output.
9. **Models.** Local through the engine's LLM gateway (ADR-0056): the user's **Ollama** is a first-class provider
   alongside the managed runtime; the default text alias stays Gemma 4 E4B (ADR-0018) until measured otherwise.
   The embedder is a **utility model** (CPU or exempt from the slot). Cloud models are opt-in per conversation
   and the UI shows which provider will see the text.
10. **Generation: structured first, files second.** The model writes a validated **document model** (title,
    sections, bullets, tables, figures, citations) and deterministic renderers produce the files: PDF
    (ReportLab or HTML to PDF with WeasyPrint, chosen in the spike) and PPTX (`python-pptx`) from templates. The
    model never writes binary files. Outputs are creations: saved, searchable (ADR-0041), downloadable.
11. **Evaluation is part of done:** a multilingual retrieval corpus (recall at k), a groundedness check (every
    claim cited and supported), a refusal set (not in the documents), kept in the repository like the search
    corpus.
12. **Privacy:** documents live in the user's storage (ADR-0017 keys); deleting a document removes its chunks,
    vectors and cached text. No telemetry. Content is never put in metric labels (ADR-0048).

## Consequences

- New: product `wasifyai-docs`, an ingestion worker with sandboxed parsers, tables for collections, documents,
  chunks and generated files, a migration for `rag_chunks`, vector-store adapters, two renderers, a documents
  library page and the assistant tools.
- Parsing quality is the real risk (scanned files, tables, multi-column layouts, right-to-left text). The spike
  and the eval corpus exist to measure it before promising it.
- A second embedding model size (1024) to download: about 1.2 GB.
- Presentation quality depends on templates; the first release offers a few fixed layouts.

## Not in this version

Bengali and Hindi (after release), Google Drive connector, folder watching and sync, web search, image extraction and captioning, audio and video
transcripts as documents (they arrive with their verticals, ADR-0043), editing documents in place, collaboration.

## Open questions

1. Is OCR on by default for scanned PDFs (it is off in Unsloth)? Measured: a scanned PDF fails with a clear
   message unless Tesseract and its language data are installed. Suggested: bundle Tesseract (English) and ask at
   upload, page-capped, or decline scanned files with that message.
2. Parsing stack and its licences (spike).
3. Vector store for desktop: `sqlite-vec` or LanceDB (spike, by measured latency).
4. Which presentation and PDF templates are in the first release.
