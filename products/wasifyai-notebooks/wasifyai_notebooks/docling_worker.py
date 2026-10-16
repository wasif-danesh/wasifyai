# SPDX-License-Identifier: Apache-2.0
# pyright: reportMissingImports=false, reportMissingModuleSource=false
"""Runs inside the document reader's own Python environment (ADR-0065 decision 7), never in the
engine: reads files with Docling and writes `{"markdown": ..., "pages": N}` for each.

    python -I docling_worker.py --models DIR --serve            # lines on stdin, answers on stdout
    python -I docling_worker.py --models DIR --file F --out JSON  # one file

A served process keeps the converter loaded, so a batch of files pays the 3 to 4 s start once
(E1 measured 72 s for 14 files started one by one against 33 s in one process). The protocol is one
JSON object per line: `{"id": n, "file": path, "out": path}` in, `{"id": n, "ok": true}` or
`{"id": n, "ok": false, "error": "..."}` out. Anything the libraries print goes to stderr.

Options follow SurfSense's (Apache-2.0, `worker/ingestion/parsing.py`, commit 622c1ded8): OCR on,
table structure on, one thread per physical core up to 8, the line classifier off (it turned noisy
scans upside down and cut OCR errors 8x when dropped). No network: the weights are on disk.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def build_converter(models: Path) -> Any:
    import psutil
    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
    from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption

    options = PdfPipelineOptions()
    options.do_ocr = True
    options.do_table_structure = True
    options.accelerator_options = AcceleratorOptions(
        num_threads=min(8, psutil.cpu_count(logical=False) or 4)
    )
    options.artifacts_path = models
    options.ocr_options = RapidOcrOptions(use_cls=False)
    return DocumentConverter(
        allowed_formats=[
            InputFormat.PDF,
            InputFormat.DOCX,
            InputFormat.PPTX,
            InputFormat.XLSX,
            InputFormat.HTML,
            InputFormat.CSV,
            InputFormat.MD,
            InputFormat.IMAGE,
        ],
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=options),
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=options),
        },
    )


def read_one(converter: Any, file: str, out: str) -> None:
    document = converter.convert(file).document
    pages = len(getattr(document, "pages", {}) or {}) or None
    Path(out).write_text(json.dumps({"markdown": document.export_to_markdown(), "pages": pages}))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", required=True)
    ap.add_argument("--file")
    ap.add_argument("--out")
    ap.add_argument("--serve", action="store_true")
    args = ap.parse_args()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("HF_HOME", str(Path(args.models) / "hf"))
    # keep the protocol channel clean: library output goes to stderr
    protocol = os.fdopen(os.dup(1), "w", buffering=1)
    os.dup2(2, 1)
    try:
        converter = build_converter(Path(args.models))
    except Exception as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        if args.serve:
            protocol.write(
                json.dumps({"id": 0, "ok": False, "error": f"{type(e).__name__}: {e}"}) + "\n"
            )
        return 2
    if not args.serve:
        try:
            read_one(converter, args.file, args.out)
        except Exception as e:
            print(f"{type(e).__name__}: {e}", file=sys.stderr)
            return 2
        return 0
    protocol.write(json.dumps({"id": 0, "ok": True, "ready": True}) + "\n")
    for line in sys.stdin:
        if not line.strip():
            continue
        request = json.loads(line)
        try:
            read_one(converter, request["file"], request["out"])
            answer = {"id": request["id"], "ok": True}
        except Exception as e:
            answer = {"id": request["id"], "ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
        protocol.write(json.dumps(answer) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
