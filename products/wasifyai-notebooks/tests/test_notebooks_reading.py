"""Turning files into Markdown: the built-in readers and the reader subprocess."""

import asyncio
import sys
import textwrap

import pytest
from notebooks_rig import FakeComponents
from wasifyai_notebooks.components import Unavailable
from wasifyai_notebooks.reading import (
    BuiltinReader,
    DoclingReader,
    ReadError,
    RoutingReader,
    csv_to_markdown,
    html_to_markdown,
    needs_reader,
)


def test_html_keeps_headings_and_drops_scripts():
    md = html_to_markdown(
        "<html><head><title>Support FAQ</title><style>p{}</style></head><body>"
        "<script>alert(1)</script><h2>Hours</h2><p>Open 8am to 6pm UTC.</p>"
        "<h2>Refunds</h2><p>Within <b>30</b> days.</p></body></html>"
    )
    assert md.startswith("# Support FAQ")
    assert "## Hours" in md and "Open 8am to 6pm UTC." in md and "Within 30 days." in md
    assert "alert" not in md and "p{}" not in md


def test_csv_becomes_a_markdown_table_with_escaped_cells():
    md = csv_to_markdown('ticket,topic\n101,"antenna | calibration"\n102,billing\n')
    assert md.splitlines()[0] == "| ticket | topic |"
    assert md.splitlines()[1] == "|---|---|"
    assert "antenna \\| calibration" in md and csv_to_markdown("") == ""


def test_which_files_need_the_reader():
    assert not any(needs_reader(s) for s in (".txt", ".md", ".csv", ".html", ".HTM"))
    assert all(needs_reader(s) for s in (".pdf", ".docx", ".pptx", ".xlsx", ".png"))


async def test_the_builtin_reader_reads_text_with_a_bom(tmp_path):
    p = tmp_path / "n.md"
    p.write_bytes("﻿# Title\n\nbody".encode())
    out = await BuiltinReader().read(p, ".md")
    assert out.markdown == "# Title\n\nbody"


async def test_a_pdf_without_the_reader_says_what_to_do(tmp_path):
    c = FakeComponents(tmp_path, reader_ready=False)
    p = tmp_path / "a.pdf"
    p.write_bytes(b"%PDF-1.7")
    with pytest.raises(Unavailable) as e:
        await RoutingReader(c).read(p, ".pdf")
    assert e.value.code == "reader_missing" and "Settings" in e.value.message
    p2 = tmp_path / "a.txt"
    p2.write_text("plain text still works")
    assert (await RoutingReader(c).read(p2, ".txt")).markdown == "plain text still works"


FAKE_WORKER = textwrap.dedent(
    """
    import json, os, sys, time
    marker = os.environ.get("FAKE_STARTS")
    if marker:
        open(marker, "a").write("start\\n")
    sys.stdout.write(json.dumps({"id": 0, "ok": True, "ready": True}) + "\\n")
    sys.stdout.flush()
    for line in sys.stdin:
        req = json.loads(line)
        text = open(req["file"]).read()
        if "die" in text:
            sys.exit(1)
        if "hang" in text:
            time.sleep(60)
        if "boom" in text:
            ans = {"id": req["id"], "ok": False, "error": "ValueError: bad header"}
        else:
            md = "# From the reader\\n\\n" + text
            json.dump({"markdown": md, "pages": 4}, open(req["out"], "w"))
            ans = {"id": req["id"], "ok": True}
        sys.stdout.write(json.dumps(ans) + "\\n")
        sys.stdout.flush()
    """
)


def reader_with(tmp_path, timeout: float = 20, idle: float = 60.0):
    c = FakeComponents(tmp_path, reader_ready=True)
    # the installed reader is this Python and the fake script
    from pathlib import Path

    from wasifyai_notebooks.components import ReaderInstall

    c.reader_install = lambda: ReaderInstall(Path(sys.executable), tmp_path)  # type: ignore[method-assign]
    script = tmp_path / "worker.py"
    script.write_text(FAKE_WORKER)
    return DoclingReader(c, timeout_s=timeout, script=script, idle_s=idle)


async def test_the_reader_process_returns_markdown_and_pages(tmp_path):
    p = tmp_path / "doc.pdf"
    p.write_text("hello")
    r = reader_with(tmp_path)
    try:
        out = await r.read(p, ".pdf")
    finally:
        await r.close()
    assert out.markdown.startswith("# From the reader") and out.pages == 4


async def test_one_process_reads_a_whole_batch_and_goes_when_idle(tmp_path, monkeypatch):
    starts = tmp_path / "starts.txt"
    monkeypatch.setenv("FAKE_STARTS", str(starts))
    r = reader_with(tmp_path, idle=0.3)
    try:
        for i in range(3):
            p = tmp_path / f"d{i}.pdf"
            p.write_text(f"file {i}")
            assert (await r.read(p, ".pdf")).markdown.endswith(f"file {i}")
        assert starts.read_text().count("start") == 1  # started once for the three files
        for _ in range(50):
            await asyncio.sleep(0.05)
            if r._proc is None:
                break
        assert r._proc is None  # the memory went back
        p = tmp_path / "again.pdf"
        p.write_text("again")
        await r.read(p, ".pdf")
        assert starts.read_text().count("start") == 2
    finally:
        await r.close()


async def test_a_failing_file_is_one_sentence_and_the_process_carries_on(tmp_path):
    r = reader_with(tmp_path)
    try:
        bad = tmp_path / "bad.pdf"
        bad.write_text("boom")
        with pytest.raises(ReadError, match="bad header"):
            await r.read(bad, ".pdf")
        ok = tmp_path / "ok.pdf"
        ok.write_text("fine")
        assert (await r.read(ok, ".pdf")).pages == 4
    finally:
        await r.close()


async def test_a_dead_or_hanging_reader_is_named_and_replaced(tmp_path):
    r = reader_with(tmp_path, timeout=0.8)
    try:
        die = tmp_path / "die.pdf"
        die.write_text("die")
        with pytest.raises(ReadError, match="stopped"):
            await r.read(die, ".pdf")
        hang = tmp_path / "hang.pdf"
        hang.write_text("hang")
        with pytest.raises(ReadError, match="too long"):
            await r.read(hang, ".pdf")
        ok = tmp_path / "ok.pdf"
        ok.write_text("back")
        assert (await r.read(ok, ".pdf")).markdown.endswith("back")  # a new process
    finally:
        await r.close()
