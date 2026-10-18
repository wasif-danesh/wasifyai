"""The notebooks database: ownership, dedup, folders, status moves and what deletion removes."""

import sqlite3

import pytest
from notebooks_rig import SPEC
from wasifyai_notebooks.chunking import Passage
from wasifyai_notebooks.store import (
    Conflict,
    NotebookStore,
    NotFound,
)

T, U = "t1", "u1"


@pytest.fixture
def store(new_store):
    return new_store(dimension=SPEC.dimension, embedder_id=SPEC.id)


def file_doc(store, nb, name="a.pdf", sha="s1", folder=None):
    return store.add_file(
        T, U, nb["id"], title=name, suffix=".pdf", mime="application/pdf", size_bytes=10,
        sha256=sha, folder_id=folder,
    )  # fmt: skip


def vec(i):
    v = [0.0] * SPEC.dimension
    v[i % SPEC.dimension] = 1.0
    return v


def index(store, did, texts):
    assert store.begin(did) is not None
    ok = store.finish(
        did, markdown="\n".join(texts), pages=1,
        passages=[Passage(t, i + 1, i + 1) for i, t in enumerate(texts)],
        vectors=[vec(i) for i in range(len(texts))], embedder=SPEC.id,
    )  # fmt: skip
    assert ok


def test_a_notebook_belongs_to_one_user(store):
    nb = store.create_notebook(T, U, "Mine")
    assert store.get_notebook(T, U, nb["id"])["title"] == "Mine"
    for who in ((T, "u2"), ("t2", U)):
        with pytest.raises(NotFound):
            store.get_notebook(*who, nb["id"])
        with pytest.raises(NotFound):
            store.list_documents(*who, nb["id"])
        with pytest.raises(NotFound):
            store.add_note(*who, nb["id"], title="x", content="y")
    assert store.list_notebooks(T, "u2") == []
    renamed = store.rename_notebook(T, U, nb["id"], "Renamed")
    assert renamed["title"] == "Renamed"


def test_the_same_bytes_in_one_folder_are_one_document(store):
    nb = store.create_notebook(T, U, "n")
    first, existed = file_doc(store, nb)
    again, existed2 = file_doc(store, nb, name="copy.pdf")
    assert not existed and existed2 and again["id"] == first["id"]
    folder = store.create_folder(T, U, nb["id"], "Reports")
    third, existed3 = file_doc(store, nb, folder=folder["id"])  # another folder: kept
    assert not existed3 and third["id"] != first["id"]
    other = store.create_notebook(T, U, "n2")
    fourth, existed4 = file_doc(store, other)  # another notebook: kept
    assert not existed4 and fourth["id"] not in (first["id"], third["id"])


def test_folders_are_unique_by_folded_name_and_limited_in_depth(store):
    nb = store.create_notebook(T, U, "n")
    a = store.create_folder(T, U, nb["id"], "Été")
    with pytest.raises(Conflict):
        store.create_folder(T, U, nb["id"], "ÉTÉ")
    parent = None
    for i in range(8):
        parent = store.create_folder(T, U, nb["id"], f"d{i}", parent["id"] if parent else None)
    assert parent is not None
    with pytest.raises(Conflict, match="levels"):
        store.create_folder(T, U, nb["id"], "too deep", parent["id"])
    with pytest.raises(NotFound):
        store.create_folder(T, U, nb["id"], "x", "no-such-folder")
    assert a["id"] in {f["id"] for f in store.list_folders(T, U, nb["id"])}


def test_status_moves_and_the_race_between_cancel_and_finish(store):
    nb = store.create_notebook(T, U, "n")
    d, _ = file_doc(store, nb)
    assert d["status"] == "pending"
    began = store.begin(d["id"])
    assert began is not None and began["status"] == "processing"
    assert store.begin(d["id"]) is None  # already taken
    store.cancel_document(T, U, nb["id"], d["id"])
    ok = store.finish(
        d["id"], markdown="x", pages=1, passages=[Passage("t", 1, 1)], vectors=[vec(0)],
        embedder=SPEC.id,
    )  # fmt: skip
    assert ok is False  # the cancel won; nothing was indexed
    assert store.get_document(T, U, nb["id"], d["id"])["status"] == "cancelled"
    store.retry_document(T, U, nb["id"], d["id"])
    assert store.get_document(T, U, nb["id"], d["id"])["status"] == "pending"
    with pytest.raises(Conflict):
        store.retry_document(T, U, nb["id"], d["id"])  # only failed or cancelled


def test_a_source_being_read_cannot_be_deleted(store):
    nb = store.create_notebook(T, U, "n")
    d, _ = file_doc(store, nb)
    store.begin(d["id"])
    with pytest.raises(Conflict):
        store.delete_document(T, U, nb["id"], d["id"])
    with pytest.raises(Conflict):
        store.delete_notebook(T, U, nb["id"])
    assert store.reset_interrupted() == 1
    got = store.get_document(T, U, nb["id"], d["id"])
    assert got["status"] == "failed" and "interrupted" in got["error"]
    store.delete_document(T, U, nb["id"], d["id"])


def test_deleting_a_notebook_removes_its_passages(store):
    nb = store.create_notebook(T, U, "n")
    d, _ = file_doc(store, nb)
    index(store, d["id"], ["alpha beta", "gamma delta"])

    def count(table):
        with store.connect() as db:
            return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    assert count("chunks") == 2
    store.delete_notebook(T, U, nb["id"])
    assert count("chunks") == 0 and count("documents") == 0


def test_deleting_removes_passages_vectors_and_keyword_entries_in_sqlite(tmp_path):
    store = NotebookStore(tmp_path, dimension=SPEC.dimension, embedder_id=SPEC.id)
    nb = store.create_notebook(T, U, "n")
    d, _ = file_doc(store, nb)
    index(store, d["id"], ["alpha beta", "gamma delta"])
    db = sqlite3.connect(store.path)
    db.enable_load_extension(True)
    import sqlite_vec

    sqlite_vec.load(db)
    count = lambda t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: E731
    assert count("chunks") == 2 and count("chunk_vectors") == 2
    assert (
        db.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH 'alpha'").fetchone()[0]
        == 1
    )
    store.delete_notebook(T, U, nb["id"])
    assert count("chunks") == 0 and count("chunk_vectors") == 0 and count("documents") == 0
    assert (
        db.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH 'alpha'").fetchone()[0]
        == 0
    )
    db.close()


def test_deleting_a_folder_takes_its_documents_and_names_their_ids(store):
    nb = store.create_notebook(T, U, "n")
    f = store.create_folder(T, U, nb["id"], "f")
    sub = store.create_folder(T, U, nb["id"], "sub", f["id"])
    a, _ = file_doc(store, nb, "a.pdf", "s1", f["id"])
    b, _ = file_doc(store, nb, "b.pdf", "s2", sub["id"])
    keep, _ = file_doc(store, nb, "c.pdf", "s3")
    gone = store.delete_folder(T, U, nb["id"], f["id"])
    assert sorted(gone) == sorted([a["id"], b["id"]])
    left = store.list_documents(T, U, nb["id"])
    assert [d["id"] for d in left] == [keep["id"]]


def test_a_note_is_pending_until_indexed_and_editing_it_requeues(store):
    nb = store.create_notebook(T, U, "n")
    n = store.add_note(T, U, nb["id"], title="Idea", content="first text")
    assert n["kind"] == "note" and n["status"] == "pending"
    store.begin(n["id"])
    store.finish(
        n["id"], markdown=None, pages=None, passages=[Passage("first text", 1, 1)],
        vectors=[vec(1)], embedder=SPEC.id,
    )  # fmt: skip
    got = store.get_document(T, U, nb["id"], n["id"], content=True)
    assert got["status"] == "ready" and got["content"] == "first text"
    store.edit_note(T, U, nb["id"], n["id"], "second text")
    assert store.get_document(T, U, nb["id"], n["id"])["status"] == "pending"
    f, _ = file_doc(store, nb)
    with pytest.raises(Conflict):
        store.edit_note(T, U, nb["id"], f["id"], "nope")


def test_an_index_built_with_another_embedder_is_refused(new_store):
    new_store(dimension=64, embedder_id="a")
    with pytest.raises(Conflict, match="indexed with a"):
        new_store(dimension=64, embedder_id="b")
    assert new_store(dimension=64, embedder_id="a").stats()["embedder"] == "a"


def test_a_passage_comes_with_its_neighbours(store):
    nb = store.create_notebook(T, U, "n")
    d, _ = file_doc(store, nb)
    index(store, d["id"], ["one", "two", "three", "four"])
    with store.connect() as db:
        cid = db.execute("SELECT id FROM chunks WHERE position = 2").fetchone()[0]
    got = store.get_chunk(T, U, nb["id"], cid, around=1)
    assert [p["content"] for p in got["passages"]] == ["two", "three", "four"]
    assert got["title"] == "a.pdf"
    with pytest.raises(NotFound):
        store.get_chunk(T, "u2", nb["id"], cid)


def test_moving_a_document_next_to_its_twin_is_skipped_and_the_rest_still_move(store):
    nb = store.create_notebook(T, U, "n")
    target = store.create_folder(T, U, nb["id"], "Target")
    a, _ = file_doc(store, nb, "a.pdf", "same")
    twin, _ = file_doc(store, nb, "twin.pdf", "same", target["id"])  # the same bytes, already there
    b, _ = file_doc(store, nb, "b.pdf", "other")
    moved = store.move_documents(T, U, nb["id"], [a["id"], b["id"]], target["id"])
    assert moved == 1  # a would be a duplicate; b moved; nothing broke for the next statement
    by_id = {d["id"]: d for d in store.list_documents(T, U, nb["id"])}
    assert by_id[a["id"]]["folder_id"] is None
    assert by_id[b["id"]]["folder_id"] == target["id"] and twin["id"] in by_id


def test_a_question_in_a_script_without_spaces_or_with_marks_finds_its_passage(store):
    from wasifyai_notebooks.retrieval import retrieve

    nb = store.create_notebook(T, U, "n")
    d, _ = file_doc(store, nb)
    texts = ["स्कैनर का उपयोग कैसे करें", "the quarterly budget is approved", "東京の天気は晴れです"]
    index(store, d["id"], texts)
    with store.connect() as db:
        hindi = retrieve(db, nb["id"], "स्कैनर", vec(7), weight=0.65, mode="lexical")
        latin = retrieve(db, nb["id"], "Budget approved", vec(7), weight=0.65, mode="lexical")
    assert [h.content for h in hindi] == [texts[0]]
    assert [h.content for h in latin] == [texts[1]]
    assert latin[0].blended == 1.0  # both terms of the question are in the passage
