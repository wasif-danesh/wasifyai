# E0 spike scripts and results (2026-10-16)

Scratch harness behind the numbers in `docs/spikes/surfsense-investigation.md` section 9. Run from a directory that
holds `venv/` (docling, chonkie, onnxruntime, sqlite-vec, tokenizers, python-docx, python-pptx, openpyxl,
reportlab), `models/docling` and `models/bge-small-en-v1.5`, and a `lifted/` folder with SurfSense's
`spec.py`, `pooling.py`, `encoder.py`, `bundled.py`, `tokenizer.py`, `chunking.py` (import paths and two config
lookups changed: 20 lines in all).

| File | Does |
|---|---|
| `gen.py` | builds the synthetic corpus (DOCX, PPTX, XLSX, HTML, MD, CSV, a scanned PDF) and `questions.json` |
| `parse_all.py` | S1: parses every file with SurfSense's Docling options, times each, records peak memory |
| `spike.py`, `nbcore.py` | S2/S6: chunk, embed, index (FTS5 + sqlite-vec), dense / lexical / hybrid ranking |
| `scale.py` | S2: both retrieval legs at 10k and 100k chunks |
| `s3.py` | S3: grounded answers through llama-server with SurfSense's `compact` and `capable` prompts |

The seven real PDFs of the spike are public documents (AWS exam guides and architecture diagrams, a university
course guide, a keyboard-shortcut sheet) kept outside the repository. The synthetic corpus is generated.
