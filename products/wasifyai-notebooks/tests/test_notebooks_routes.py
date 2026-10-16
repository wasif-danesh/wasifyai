"""The notebooks API: ownership, upload, reading, search and deletion, through HTTP."""

import io
import time
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from notebooks_rig import SPEC, FakeComponents, FakeReader
from wasifyai_notebooks.ingest import IngestWorker
from wasifyai_notebooks.routes import Runtime, build_routes
from wasifyai_notebooks.store import NotebookStore
from wasifyai_platform_sdk import Identity, RouteDeps


class Indexed:
    """What My creations search was told, by `index` and `remove`."""

    def __init__(self) -> None:
        self.items: dict[str, str] = {}

    async def index(self, tenant, product, user, kind, item_id, text) -> None:
        assert (tenant, product, user, kind) == ("t1", "wasifyai-notebooks", "u1", "notebook")
        self.items[item_id] = text

    async def remove(self, tenant, product, item_id) -> None:
        self.items.pop(item_id, None)


class State:
    creation_index = None
    engine = None
    storage = None


def make_app(tmp_path, **components):
    store = NotebookStore(tmp_path / "nb", dimension=SPEC.dimension, embedder_id=SPEC.id)
    comps = FakeComponents(tmp_path, **components)
    reader = FakeReader()
    files = tmp_path / "nb" / "files"
    tmp = tmp_path / "nb" / "tmp"
    files.mkdir(parents=True)
    tmp.mkdir()
    worker = IngestWorker(store, comps, reader, files, tokenizer_factory=lambda: "word")
    runtime = Runtime(store, comps, worker, files, tmp)

    async def identity(x_user: str = Header("u1"), x_tenant: str = Header("t1")) -> Identity:
        return Identity(x_tenant, x_user)

    app = FastAPI()
    app.include_router(
        build_routes(RouteDeps(State(), identity), runtime), prefix="/products/wasifyai-notebooks"
    )
    return app, runtime, comps, reader


@pytest.fixture
def api(tmp_path):
    app, runtime, comps, reader = make_app(tmp_path)
    with TestClient(app) as c:
        c.base_url = c.base_url.join("/products/wasifyai-notebooks/")
        yield c, runtime, comps, reader
        # the worker was started in the client's own loop by the first request: stop it there
        assert c.portal is not None
        c.portal.call(runtime.worker.stop)


def wait_ready(c, nid, count, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        docs = c.get(f"notebooks/{nid}/documents").json()
        if len(docs) >= count and all(
            d["status"] in ("ready", "failed", "cancelled") for d in docs
        ):
            return docs
        time.sleep(0.05)
    raise AssertionError(c.get(f"notebooks/{nid}/documents").json())


def upload(c, nid, name, data: bytes, **form):
    return c.post(
        f"notebooks/{nid}/documents/upload", files=[("files", (name, io.BytesIO(data)))], data=form
    )


def test_create_list_rename_and_delete_a_notebook(api):
    c, *_ = api
    nb = c.post("notebooks", json={}).json()
    assert nb["title"] == "Untitled notebook" and nb["sources"] == 0
    assert (
        c.patch(f"notebooks/{nb['id']}", json={"title": "  Q3 planning "}).json()["title"]
        == "Q3 planning"
    )
    assert [n["id"] for n in c.get("notebooks").json()] == [nb["id"]]
    assert c.patch(f"notebooks/{nb['id']}", json={"title": ""}).status_code == 422
    assert c.delete(f"notebooks/{nb['id']}").status_code == 204
    assert c.get(f"notebooks/{nb['id']}").status_code == 404


def test_another_person_gets_not_found_everywhere(api):
    c, *_ = api
    nb = c.post("notebooks", json={"title": "Mine"}).json()
    up = upload(c, nb["id"], "a.txt", b"# A\n\nThe secret is plum and it is long enough.\n")
    did = up.json()["created"][0]["id"]
    wait_ready(c, nb["id"], 1)
    other = {"x-user": "u2"}
    n = nb["id"]
    for method, path, kw in [
        ("get", f"notebooks/{n}", {}),
        ("patch", f"notebooks/{n}", {"json": {"title": "x"}}),
        ("delete", f"notebooks/{n}", {}),
        ("get", f"notebooks/{n}/documents", {}),
        ("get", f"notebooks/{n}/documents/{did}", {}),
        ("get", f"notebooks/{n}/documents/{did}/original", {}),
        ("post", f"notebooks/{n}/search", {"json": {"query": "secret"}}),
        ("get", f"notebooks/{n}/folders", {}),
    ]:
        r = getattr(c, method)(path, headers=other, **kw)
        assert r.status_code == 404, (method, path, r.status_code)
    assert c.get("notebooks", headers=other).json() == []


def test_upload_reads_the_file_and_search_finds_it(api):
    c, *_ = api
    nb = c.post("notebooks", json={"title": "n"}).json()
    r = upload(
        c, nb["id"], "budget.md", b"# Budget\n\nThe marketing budget for the launch is $350,000.\n"
    )
    assert r.status_code == 201
    body = r.json()
    assert (
        body["created"][0]["status"] == "pending" and body["created"][0]["mime"] == "text/markdown"
    )
    docs = wait_ready(c, nb["id"], 1)
    assert docs[0]["status"] == "ready"
    hits = c.post(f"notebooks/{nb['id']}/search", json={"query": "marketing budget"}).json()["hits"]
    assert hits[0]["title"] == "budget.md" and "350,000" in hits[0]["content"]
    p = c.get(f"notebooks/{nb['id']}/passages/{hits[0]['chunk_id']}").json()
    assert p["passages"][0]["content"].startswith("# Budget")
    got = c.get(f"notebooks/{nb['id']}/documents/{docs[0]['id']}").json()
    assert got["content"].startswith("# Budget")
    n = c.get(f"notebooks/{nb['id']}").json()
    assert (n["sources"], n["ready"], n["reading"]) == (1, 1, 0)


def test_upload_splits_a_batch_into_created_duplicates_and_rejected(api):
    c, *_ = api
    nb = c.post("notebooks", json={}).json()
    same = b"# Same\n\nThe same bytes twice in one folder are one document.\n"
    r = c.post(
        f"notebooks/{nb['id']}/documents/upload",
        files=[
            ("files", ("one.txt", io.BytesIO(same))),
            ("files", ("two.txt", io.BytesIO(same))),
            ("files", ("tool.exe", io.BytesIO(b"MZ"))),
            ("files", ("fake.pdf", io.BytesIO(b"not a pdf at all"))),
        ],
    ).json()
    assert len(r["created"]) == 1 and len(r["duplicates"]) == 1
    reasons = {x["name"]: x["reason"] for x in r["rejected"]}
    assert set(reasons) == {"tool.exe", "fake.pdf"} and "cannot be added" in reasons["tool.exe"]


def test_a_note_is_a_source_and_can_be_edited(api):
    c, *_ = api
    nb = c.post("notebooks", json={}).json()
    n = c.post(
        f"notebooks/{nb['id']}/documents",
        json={"title": "Idea", "content": "Use a second supplier."},
    ).json()
    wait_ready(c, nb["id"], 1)
    r = c.patch(
        f"notebooks/{nb['id']}/documents/{n['id']}", json={"content": "Use a different vendor."}
    )
    assert r.status_code == 200
    wait_ready(c, nb["id"], 1)
    hits = c.post(f"notebooks/{nb['id']}/search", json={"query": "different vendor"}).json()["hits"]
    assert hits[0]["title"] == "Idea"
    assert c.patch(f"notebooks/{nb['id']}/documents/{n['id']}", json={}).status_code == 422


def test_scope_narrows_search_and_delete_removes_the_source(api):
    c, *_ = api
    nb = c.post("notebooks", json={}).json()
    a = upload(
        c, nb["id"], "a.txt", b"# A\n\nAlpha warranty is eighteen months in total here.\n"
    ).json()["created"][0]
    b = upload(
        c, nb["id"], "b.txt", b"# B\n\nBravo warranty is six months in total here.\n"
    ).json()["created"][0]
    wait_ready(c, nb["id"], 2)
    q = {"query": "warranty months"}
    titles = {h["title"] for h in c.post(f"notebooks/{nb['id']}/search", json=q).json()["hits"]}
    assert titles == {"a.txt", "b.txt"}
    only = c.post(f"notebooks/{nb['id']}/search", json={**q, "document_ids": [b["id"]]}).json()[
        "hits"
    ]
    assert {h["title"] for h in only} == {"b.txt"}
    assert c.delete(f"notebooks/{nb['id']}/documents/{a['id']}").status_code == 204
    after = c.post(f"notebooks/{nb['id']}/search", json=q).json()["hits"]
    assert {h["title"] for h in after} == {"b.txt"}


def test_the_original_downloads_as_an_attachment(api):
    c, *_ = api
    nb = c.post("notebooks", json={}).json()
    d = upload(
        c, nb["id"], "n.html", b"<h1>Hi</h1><p>This page has a few more words in it.</p>"
    ).json()["created"][0]
    r = c.get(f"notebooks/{nb['id']}/documents/{d['id']}/original")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert r.headers["content-type"].startswith("text/html")


def test_folders_and_moves(api):
    c, *_ = api
    nb = c.post("notebooks", json={}).json()
    f = c.post(f"notebooks/{nb['id']}/folders", json={"name": "Reports"}).json()
    assert c.post(f"notebooks/{nb['id']}/folders", json={"name": "reports"}).status_code == 409
    d = upload(
        c, nb["id"], "a.txt", b"# A\n\nSome words in a file that will be moved around.\n"
    ).json()["created"][0]
    assert c.post(
        f"notebooks/{nb['id']}/documents/move",
        json={"document_ids": [d["id"]], "folder_id": f["id"]},
    ).json() == {"moved": 1}
    wait_ready(c, nb["id"], 1)
    assert (
        c.get(f"notebooks/{nb['id']}/documents", params={"folder_id": f["id"]}).json()[0]["id"]
        == d["id"]
    )
    assert c.delete(f"notebooks/{nb['id']}/folders/{f['id']}").status_code == 204
    assert c.get(f"notebooks/{nb['id']}/documents").json() == []


def test_a_pdf_without_the_reader_fails_with_a_sentence_and_a_retry_works_later(tmp_path):
    app, runtime, comps, reader = make_app(tmp_path, reader_ready=False)
    # use the real routing reader so a missing reader component is what happens
    from wasifyai_notebooks.reading import RoutingReader

    runtime.worker._reader = RoutingReader(comps)
    with TestClient(app) as c:
        c.base_url = c.base_url.join("/products/wasifyai-notebooks/")
        nb = c.post("notebooks", json={}).json()
        pdf = b"%PDF-1.7\n" + b"x" * 50
        d = upload(c, nb["id"], "a.pdf", pdf).json()["created"][0]
        docs = wait_ready(c, nb["id"], 1)
        assert docs[0]["status"] == "failed" and "document reader" in docs[0]["error"]
        assert c.post(f"notebooks/{nb['id']}/documents/{d['id']}/retry").status_code == 202
        assert c.portal is not None
        c.portal.call(runtime.worker.stop)


def test_status_says_what_is_set_up(api):
    c, *_ = api
    s = c.get("status").json()
    assert s["embedder"]["ready"] is True and s["reader"]["ready"] is False
    assert "pdf" in s["reader"]["needed_for"]


def test_search_without_the_model_says_which_piece_is_missing(tmp_path):
    app, *_ = make_app(tmp_path, embedder_ready=False)
    with TestClient(app) as c:
        c.base_url = c.base_url.join("/products/wasifyai-notebooks/")
        nb = c.post("notebooks", json={}).json()
        r = c.post(f"notebooks/{nb['id']}/search", json={"query": "anything"})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "embedder_missing"


def test_an_office_file_must_be_a_real_one(api):
    c, *_ = api
    nb = c.post("notebooks", json={}).json()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<x/>")
        z.writestr("ppt/presentation.xml", "<x/>")
    r = upload(c, nb["id"], "deck.docx", buf.getvalue()).json()
    assert r["created"] == [] and r["rejected"][0]["name"] == "deck.docx"
    assert Path  # keep the import used


def test_setting_up_the_reader_through_the_api(tmp_path):
    from test_notebooks_reader_install import Rig as InstallRig

    app, runtime, *_ = make_app(tmp_path)
    with TestClient(app) as c:
        c.base_url = c.base_url.join("/products/wasifyai-notebooks/")
        # not part of this build: said in words, and the setup is refused
        s = c.get("status").json()["reader"]["setup"]
        assert s == {"available": False, "message": ""} or s["available"] is False
        r = c.post("setup/reader", json={"confirm_bytes": 1})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "reader_unavailable"

        rig = InstallRig(tmp_path)
        runtime.installer = rig.installer
        offer = c.get("status").json()["reader"]["setup"]
        assert offer["available"] and offer["installed"] is False
        size = offer["offer"]["size_bytes"]
        assert c.post("setup/reader", json={"confirm_bytes": size + 1}).status_code == 409
        ok = c.post("setup/reader", json={"confirm_bytes": size})
        assert ok.status_code == 202 and ok.json()["state"] == "installing"
        prog: dict = {}
        for _ in range(100):
            prog = c.get("status").json()["reader"]["setup"]["progress"]
            if prog["state"] != "installing":
                break
            time.sleep(0.02)
        assert prog["state"] == "ready"
        assert c.get("status").json()["reader"]["setup"]["installed"] is True
        assert c.portal is not None
        c.portal.call(runtime.worker.stop)


def test_conversations_are_listed_read_renamed_and_deleted(api):
    c, runtime, *_ = api
    nb = c.post("notebooks", json={}).json()
    conv = runtime.store.create_conversation("t1", "u1", nb["id"], "First question")
    runtime.store.add_message("t1", "u1", nb["id"], conv["id"], "user", "What is the budget?")
    runtime.store.add_message(
        "t1", "u1", nb["id"], conv["id"], "assistant", "It is $350,000 [1].",
        [{"n": 1, "title": "budget.txt", "text": "The budget is $350,000."}],
    )  # fmt: skip
    listed = c.get(f"notebooks/{nb['id']}/conversations").json()
    assert [x["title"] for x in listed] == ["First question"]
    got = c.get(f"notebooks/{nb['id']}/conversations/{conv['id']}").json()
    assert [m["role"] for m in got["messages"]] == ["user", "assistant"]
    assert got["messages"][1]["citations"][0]["title"] == "budget.txt"
    path = f"notebooks/{nb['id']}/conversations/{conv['id']}"
    assert c.patch(path, json={"title": "Budget"}).status_code == 204
    assert c.get(path).json()["title"] == "Budget"
    # another person sees nothing of it
    assert c.get(path, headers={"x-user": "u2"}).status_code == 404
    assert c.get(f"notebooks/{nb['id']}/conversations", headers={"x-user": "u2"}).status_code == 404
    assert c.delete(path).status_code == 204
    assert c.get(path).status_code == 404
    # deleting the notebook takes its conversations
    conv2 = runtime.store.create_conversation("t1", "u1", nb["id"], "Again")
    assert c.delete(f"notebooks/{nb['id']}").status_code == 204
    with pytest.raises(Exception):  # noqa: B017  the notebook, so the conversation, is gone
        runtime.store.get_conversation("t1", "u1", nb["id"], conv2["id"])


def test_a_notebook_is_in_search_at_once_with_its_sources_and_leaves_with_it(tmp_path):
    app, runtime, *_ = make_app(tmp_path)
    index = Indexed()
    State.creation_index = index  # type: ignore[assignment]  # read from the state per request
    try:
        with TestClient(app) as c:
            c.base_url = c.base_url.join("/products/wasifyai-notebooks/")
            nb = c.post("notebooks", json={"title": "Q3 planning"}).json()
            assert index.items[nb["id"]] == "Q3 planning"
            upload(c, nb["id"], "budget.md", b"# Budget\n\nThe launch budget is a round number.\n")
            assert "budget.md" in index.items[nb["id"]]
            c.patch(f"notebooks/{nb['id']}", json={"title": "Plans"})
            assert index.items[nb["id"]].startswith("Plans")
            assert c.delete(f"notebooks/{nb['id']}").status_code == 204
            assert nb["id"] not in index.items
            assert c.portal is not None
            c.portal.call(runtime.worker.stop)
    finally:
        State.creation_index = None
