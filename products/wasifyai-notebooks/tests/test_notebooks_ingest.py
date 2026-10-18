"""Reading a source into the library, and finding passages again."""

import asyncio

import pytest
from notebooks_rig import SPEC, FakeComponents, FakeReader
from wasifyai_notebooks.chunking import chunk
from wasifyai_notebooks.embedding import Purpose
from wasifyai_notebooks.ingest import NO_TEXT, IngestWorker, ingest_one, original_path
from wasifyai_notebooks.reading import ReadError
from wasifyai_notebooks.retrieval import retrieve

T, U = "t1", "u1"


class Rig:
    def __init__(self, tmp_path, new_store, **kw):
        self.store = new_store(dimension=SPEC.dimension, embedder_id=SPEC.id)
        self.components = FakeComponents(tmp_path, **kw)
        self.reader = FakeReader()
        self.files = tmp_path / "files"
        self.nb = self.store.create_notebook(T, U, "n")
        self.worker = IngestWorker(
            self.store, self.components, self.reader, self.files, tokenizer_factory=lambda: "word"
        )

    def add(self, name, text, suffix=".txt", sha=None):
        """Put a file on disk the way the upload route does, and register it."""
        doc, _ = self.store.add_file(
            T, U, self.nb["id"], title=name, suffix=suffix, mime="text/plain", size_bytes=len(text),
            sha256=sha or name, doc_id=None,
        )  # fmt: skip
        path = original_path(self.files, self.nb["id"], doc)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return doc

    def search(self, q, **kw):
        vec = self.components.fake.embed([q], Purpose.QUERY)[0]
        with self.store.connect() as db:
            return retrieve(db, self.nb["id"], q, vec, weight=SPEC.semantic_weight, **kw)

    def status(self, did):
        return self.store.get_document(T, U, self.nb["id"], did)


@pytest.fixture
def rig(tmp_path, new_store):
    return Rig(tmp_path, new_store)


async def test_a_file_is_read_cut_embedded_and_found(rig):
    a = rig.add("budget.txt", "# Budget\n\nThe marketing budget for the launch is $350,000.\n")
    b = rig.add("hr.txt", "# People\n\nEngineering has 48 people and 5 open roles.\n")
    for d in (a, b):
        assert await ingest_one(rig.store, rig.components, rig.reader, rig.files, d,
                                tokenizer_factory=lambda: "word") == "ready"  # fmt: skip
    assert rig.status(a["id"])["status"] == "ready"
    assert rig.status(a["id"])["embedder"] == SPEC.id
    hits = rig.search("What is the marketing budget?")
    assert hits[0].title == "budget.txt" and "350,000" in hits[0].content
    assert rig.search("how many people in engineering")[0].title == "hr.txt"
    assert (hits[0].start_line, hits[0].end_line) == (1, 3)  # lines of the Markdown, for a citation


async def test_the_three_modes_and_a_scope(rig):
    a = rig.add("a.txt", "# A\n\nThe warranty period is eighteen months.\n")
    b = rig.add("b.txt", "# B\n\nBatteries are covered for six months only.\n")
    for d in (a, b):
        await ingest_one(
            rig.store, rig.components, rig.reader, rig.files, d, tokenizer_factory=lambda: "word"
        )
    assert rig.search("warranty period", mode="lexical")[0].title == "a.txt"
    assert rig.search("warranty period", mode="dense")[0].title == "a.txt"
    assert rig.search("covered months", document_ids=[b["id"]])[0].title == "b.txt"
    assert rig.search("covered months", document_ids=[]) == []  # nothing ticked, nothing searched
    assert {h.title for h in rig.search("months", document_ids=[a["id"]])} == {"a.txt"}
    assert rig.search("   ") == []


async def test_another_notebook_is_never_searched(rig):
    a = rig.add("a.txt", "# A\n\nThe secret code word is plum.\n")
    await ingest_one(
        rig.store, rig.components, rig.reader, rig.files, a, tokenizer_factory=lambda: "word"
    )
    other = rig.store.create_notebook(T, U, "other")
    vec = rig.components.fake.embed(["secret code word"], Purpose.QUERY)[0]
    with rig.store.connect() as db:
        assert retrieve(db, other["id"], "secret code word", vec, weight=0.65) == []
        assert retrieve(db, rig.nb["id"], "secret code word", vec, weight=0.65)


async def test_a_file_with_no_text_fails_in_words_instead_of_becoming_empty(rig):
    d = rig.add("scan.pdf", "x", suffix=".pdf")
    rig.reader.texts["scan.pdf"] = "<!-- image -->"
    assert await ingest_one(rig.store, rig.components, rig.reader, rig.files, d,
                            tokenizer_factory=lambda: "word") == "failed"  # fmt: skip
    got = rig.status(d["id"])
    assert got["status"] == "failed" and got["error"] == NO_TEXT


async def test_a_reader_error_is_written_on_the_source(rig):
    class Broken:
        async def read(self, path, suffix):
            raise ReadError("The file could not be read (bad header).")

    d = rig.add("x.pdf", "x", suffix=".pdf")
    out = await ingest_one(
        rig.store, rig.components, Broken(), rig.files, d, tokenizer_factory=lambda: "word"
    )
    assert out == "failed" and "bad header" in rig.status(d["id"])["error"]


async def test_a_cancel_during_reading_leaves_nothing_indexed(rig):
    d = rig.add(
        "slow.txt", "# Slow\n\nA long document with enough words to be read properly here.\n"
    )
    rig.reader.gate = asyncio.Event()
    task = asyncio.create_task(
        ingest_one(
            rig.store, rig.components, rig.reader, rig.files, d, tokenizer_factory=lambda: "word"
        )
    )
    for _ in range(100):
        if rig.status(d["id"])["status"] == "processing":
            break
        await asyncio.sleep(0.01)
    rig.store.cancel_document(T, U, rig.nb["id"], d["id"])
    rig.reader.gate.set()
    assert await task == "cancelled"
    assert rig.status(d["id"])["status"] == "cancelled" and rig.search("long document") == []


async def test_a_note_is_indexed_and_its_text_is_not_overwritten(rig):
    n = rig.store.add_note(
        T, U, rig.nb["id"], title="Idea", content="# Idea\n\nUse a second supplier."
    )
    await ingest_one(
        rig.store, rig.components, rig.reader, rig.files, n, tokenizer_factory=lambda: "word"
    )
    assert rig.search("second supplier")[0].title == "Idea"
    rig.store.edit_note(T, U, rig.nb["id"], n["id"], "# Idea\n\nUse a different vendor instead.")
    nxt = rig.store.next_pending()
    await ingest_one(
        rig.store, rig.components, rig.reader, rig.files, nxt, tokenizer_factory=lambda: "word"
    )
    assert "supplier" not in " ".join(h.content for h in rig.search("vendor"))  # old passages gone
    assert rig.search("different vendor")[0].title == "Idea"


async def test_the_worker_waits_for_the_search_model_then_reads(tmp_path, new_store):
    rig = Rig(tmp_path, new_store, embedder_ready=False)
    d = rig.add("a.txt", "# A\n\nWaiting for the model to arrive on this computer.\n")
    rig.worker.start()
    try:
        await asyncio.sleep(0.3)
        assert rig.status(d["id"])["status"] == "pending"  # held, not failed
        rig.components.ready = True
        rig.worker.wake()
        await rig.worker.drain(10)
        assert rig.status(d["id"])["status"] == "ready"
    finally:
        await rig.worker.stop()


async def test_a_batch_is_read_one_at_a_time_highest_priority_first(tmp_path, new_store):
    rig = Rig(tmp_path, new_store)
    bulk = rig.add("bulk.txt", "# Bulk\n\nCopied with a whole folder, so it can wait its turn.\n")
    with rig.store._tx() as db:
        db.execute("UPDATE documents SET priority = 10 WHERE id = ?", (bulk["id"],))
    note = rig.store.add_note(
        T, U, rig.nb["id"], title="N", content="# N\n\nWritten during the copy, read first."
    )
    order = []
    original = rig.store.begin
    rig.store.begin = lambda did: (order.append(did), original(did))[1]  # type: ignore[method-assign]
    rig.worker.start()
    try:
        await rig.worker.drain(10)
    finally:
        await rig.worker.stop()
    assert order[0] == note["id"] and order[1] == bulk["id"]


async def test_work_in_progress_when_the_app_quit_is_failed_at_start(rig):
    d = rig.add("a.txt", "# A\n\nThis was being read when the app was closed.\n")
    rig.store.begin(d["id"])
    rig.worker.start()
    try:
        assert rig.status(d["id"])["status"] == "failed"
        assert "interrupted" in rig.status(d["id"])["error"]
        rig.store.retry_document(T, U, rig.nb["id"], d["id"])
        rig.worker.wake()
        await rig.worker.drain(10)
        assert rig.status(d["id"])["status"] == "ready"
    finally:
        await rig.worker.stop()


def test_markdown_is_cut_at_headings_and_paragraphs_with_line_numbers():
    md = "# One\n\n" + "alpha " * 30 + "\n\n# Two\n\n" + "beta " * 30 + "\n"
    ps = chunk(md, tokenizer="word", chunk_size=40)
    assert len(ps) >= 2
    assert ps[0].text.startswith("# One") and ps[0].start_line == 1
    assert any(p.text.startswith("# Two") for p in ps)
    assert all(p.end_line >= p.start_line for p in ps)
    assert chunk("   \n ", tokenizer="word") == []
