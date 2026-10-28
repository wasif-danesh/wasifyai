"""The search model through the gateway, the usage it records, and what one person may hold."""

import asyncio
import io
import json

import httpx
import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from notebooks_rig import SPEC, FakeReader, HashEmbedder, pg_dsn
from wasifyai_notebooks.components import GatewayComponents
from wasifyai_notebooks.embedding import EmbedError, GatewayEmbedder, Purpose, embed_counted
from wasifyai_notebooks.files import ObjectFiles, original_key
from wasifyai_notebooks.ingest import IngestWorker
from wasifyai_notebooks.quotas import Limits, QuotaExceeded, check_new_notebook, check_new_source
from wasifyai_notebooks.routes import Runtime, build_routes
from wasifyai_platform_sdk import EngineServices, Identity, RouteDeps, memory_storage

T, U = "t1", "u1"
DIM = SPEC.dimension


class Gateway:
    """A stand-in for the gateway's /v1/embeddings: the test embedder's vectors, tokens in words."""

    def __init__(self, fail: list[int] | None = None):
        self.calls: list[dict] = []
        self.fail = fail or []  # statuses to answer before success
        self.hash = HashEmbedder()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append({"headers": dict(request.headers), "body": body})
        if self.fail:
            return httpx.Response(self.fail.pop(0), json={"error": "no"})
        vectors = self.hash.embed(body["input"], Purpose.DOCUMENT)
        data = [{"index": i, "embedding": v} for i, v in reversed(list(enumerate(vectors)))]
        words = sum(len(t.split()) for t in body["input"])
        return httpx.Response(200, json={"data": data, "usage": {"prompt_tokens": words}})


def embedder(gateway: Gateway, **kw) -> GatewayEmbedder:
    client = httpx.Client(transport=httpx.MockTransport(gateway))
    return GatewayEmbedder("http://gw/", "secret", dimension=DIM, client=client, **kw)


def test_texts_go_to_the_gateway_by_alias_in_batches_and_come_back_in_order():
    gw = Gateway()
    e = embedder(gw, batch=2)
    texts = [f"text number {i}" for i in range(5)]
    vectors, tokens = e.embed_counted(texts, Purpose.DOCUMENT)
    assert len(vectors) == 5 and tokens == 15
    assert [len(c["body"]["input"]) for c in gw.calls] == [2, 2, 1]
    first = gw.calls[0]
    assert first["body"]["model"] == "creation-embedder"
    assert first["body"]["encoding_format"] == "float"
    assert first["headers"]["authorization"] == "Bearer secret"
    assert vectors == gw.hash.embed(texts, Purpose.DOCUMENT)  # answered out of order, put back
    assert e.spec.id == "gateway:creation-embedder" and e.spec.dimension == DIM


def test_a_busy_gateway_is_tried_again_and_a_refusal_is_not(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    busy = Gateway(fail=[503, 429])
    assert embedder(busy).embed(["a b"], Purpose.QUERY)
    assert len(busy.calls) == 3
    refused = Gateway(fail=[400])
    with pytest.raises(EmbedError, match="400"):
        embedder(refused).embed(["a"], Purpose.QUERY)
    assert len(refused.calls) == 1
    down = Gateway(fail=[500, 500, 500])
    with pytest.raises(EmbedError, match="500"):
        embedder(down).embed(["a"], Purpose.QUERY)


def test_an_unreachable_gateway_and_a_wrong_dimension_are_told_in_words(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)

    def refuse(request):
        raise httpx.ConnectError("no route")

    e = GatewayEmbedder(
        "http://gw", client=httpx.Client(transport=httpx.MockTransport(refuse)), dimension=DIM
    )
    with pytest.raises(EmbedError, match="could not be reached"):
        e.embed(["a"], Purpose.QUERY)
    wrong = embedder(Gateway(), batch=8)
    wrong.spec = wrong.spec.__class__(**{**wrong.spec.__dict__, "dimension": DIM + 1})
    with pytest.raises(EmbedError, match="dimensions"):
        wrong.embed(["a"], Purpose.QUERY)


def test_a_local_embedder_spends_no_billed_tokens():
    vectors, tokens = embed_counted(HashEmbedder(), ["a b c"], Purpose.QUERY)
    assert len(vectors) == 1 and tokens == 0


def test_the_gateway_components_need_no_files_and_size_a_passage_in_characters(tmp_path):
    comps = GatewayComponents(embedder(Gateway()), tmp_path / "reader")
    assert comps.embedder_paths() is not None and comps.tokenizer() == "character"
    assert comps.chunk_size == 1500 and comps.state()["embedder"]["ready"] is True
    assert comps.spec.dimension == DIM


async def test_a_text_without_spaces_is_cut_read_and_its_tokens_are_recorded(new_store, tmp_path):
    gw = Gateway()
    comps = GatewayComponents(embedder(gw), tmp_path / "reader")
    store = new_store(dimension=comps.spec.dimension, embedder_id=comps.spec.id)
    library = ObjectFiles(memory_storage())
    worker = IngestWorker(store, comps, FakeReader(), library)
    nb = store.create_notebook(T, U, "n")
    text = "東京は日本の首都です。" * 400  # 4000 characters, not one space
    doc, _ = store.add_file(
        T, U, nb["id"], title="tokyo.txt", suffix=".txt", mime="text/plain",
        size_bytes=len(text), sha256="h",
    )  # fmt: skip
    await asyncio.to_thread(
        library.for_owner(T, U).put_bytes, original_key(nb["id"], doc), text.encode()
    )  # as the engine does: from a thread
    worker.start()
    try:
        await worker.drain(20)
    finally:
        await worker.stop()
    got = store.get_document(T, U, nb["id"], doc["id"])
    assert got["status"] == "ready" and got["embedder"] == "gateway:creation-embedder"
    with store.connect() as db:
        sizes = [len(r[0]) for r in db.execute("SELECT content FROM chunks")]
    assert len(sizes) >= 3 and max(sizes) <= 1500  # cut in characters, so a language without
    # spaces is still cut into passages of a sensible size
    if new_store.backend == "postgres":  # what billing reads
        import psycopg

        with psycopg.connect(pg_dsn()) as conn:
            row = conn.execute(
                "SELECT SUM(quantity), MIN(unit) FROM usage_events "
                "WHERE tenant_id = %s AND user_id = %s AND kind = 'llm.embedding_tokens' "
                "AND product_id = 'wasifyai-notebooks'",
                (T, U),
            ).fetchone()
            conn.execute(
                "DELETE FROM usage_events "
                "WHERE tenant_id = %s AND product_id = 'wasifyai-notebooks'",
                (T,),
            )
        assert row is not None and row[0] and row[1] == "tokens"


def test_the_limits_stop_a_person_at_their_notebooks_sources_and_bytes(new_store):
    store = new_store(dimension=DIM, embedder_id="e")
    limits = Limits(notebooks=2, sources_per_notebook=2, bytes=1000)
    a = store.create_notebook(T, U, "a")
    check_new_notebook(limits, store, T, U)  # one of two held
    store.create_notebook(T, U, "b")
    with pytest.raises(QuotaExceeded, match="2 notebooks"):
        check_new_notebook(limits, store, T, U)
    check_new_notebook(limits, store, T, "someone-else")  # another person has their own

    store.add_note(T, U, a["id"], title="n1", content="x" * 400)
    check_new_source(limits, store, T, U, a["id"], 100)
    store.add_note(T, U, a["id"], title="n2", content="y" * 400)
    with pytest.raises(QuotaExceeded, match="at most 2 sources"):
        check_new_source(limits, store, T, U, a["id"], 1)
    c = store.create_notebook(T, "u3", "c")
    store.add_note(T, "u3", c["id"], title="n", content="z" * 900)
    with pytest.raises(QuotaExceeded, match="MB|GB"):
        check_new_source(limits, store, T, "u3", c["id"], 200)  # 900 + 200 > 1000
    check_new_source(limits, store, T, "u3", c["id"], 100)  # exactly 1000 fits
    assert store.usage(T, U) == {"notebooks": 2, "sources": 2, "bytes": 800}
    assert not Limits()  # no limits: nothing applies
    check_new_source(Limits(), store, T, U, a["id"], 10**9)


class Caps:
    def __init__(self, quotas, on=True):
        self.config = type("C", (), {"quotas": quotas})()
        self._on = on

    async def safeguards_on(self):
        return self._on


def quota_app(tmp_path, caps):
    from notebooks_rig import FakeComponents
    from wasifyai_notebooks.store import NotebookStore

    store = NotebookStore.in_folder(tmp_path / "nb", dimension=SPEC.dimension, embedder_id=SPEC.id)
    comps = FakeComponents(tmp_path)
    files, tmp = tmp_path / "nb" / "files", tmp_path / "nb" / "tmp"
    files.mkdir(parents=True)
    tmp.mkdir()
    worker = IngestWorker(store, comps, FakeReader(), files, tokenizer_factory=lambda: "word")
    runtime = Runtime(store, comps, worker, files, tmp, reads_sources=False)

    state = EngineServices(caps={"wasifyai-notebooks": caps} if caps is not None else {})

    async def identity(x_user: str = Header("u1"), x_tenant: str = Header("t1")) -> Identity:
        return Identity(x_tenant, x_user)

    app = FastAPI()
    app.include_router(
        build_routes(RouteDeps(state, identity), runtime), prefix="/products/wasifyai-notebooks"
    )
    return app


def upload(c, nid, name, data):
    return c.post(
        f"notebooks/{nid}/documents/upload", files=[("files", (name, io.BytesIO(data)))]
    ).json()


def test_the_routes_refuse_what_is_over_the_limits_only_while_safeguards_are_on(tmp_path):
    quotas = {"notebooks_per_user": 1, "sources_per_notebook": 2, "bytes_per_user": 120}
    app = quota_app(tmp_path, Caps(quotas))
    with TestClient(app) as c:
        c.base_url = c.base_url.join("/products/wasifyai-notebooks/")
        nb = c.post("notebooks", json={}).json()
        refused = c.post("notebooks", json={})
        assert refused.status_code == 429 and "1 notebooks" in refused.json()["detail"]

        assert (
            c.post(
                f"notebooks/{nb['id']}/documents", json={"title": "n", "content": "a" * 50}
            ).status_code
            == 201
        )
        big = c.post(f"notebooks/{nb['id']}/documents", json={"title": "m", "content": "b" * 90})
        assert big.status_code == 429 and "your" in big.json()["detail"]

        # an upload says which files it took and which went over, instead of failing whole
        got = upload(c, nb["id"], "a.txt", b"first words here " * 2)
        assert [d["title"] for d in got["created"]] == ["a.txt"]
        again = upload(c, nb["id"], "b.txt", b"second words " * 2)
        assert again["created"] == [] and "at most 2 sources" in again["rejected"][0]["reason"]


def test_the_limits_do_not_apply_with_the_safeguards_off_or_without_configuration(tmp_path):
    for caps in (Caps({"notebooks_per_user": 1}, on=False), Caps({}), None):
        sub = tmp_path / f"c{id(caps)}"
        sub.mkdir()
        app = quota_app(sub, caps)
        with TestClient(app) as c:
            c.base_url = c.base_url.join("/products/wasifyai-notebooks/")
            assert c.post("notebooks", json={}).status_code == 201
            assert c.post("notebooks", json={}).status_code == 201


def test_the_worker_asks_for_a_gateway_or_model_files():
    from wasifyai_notebooks.worker import setup_from_environment

    base = {
        "DATABASE_URL": "postgresql://x",
        "STORAGE_ENDPOINT": "http://s",
        "STORAGE_ACCESS_KEY": "k",
        "STORAGE_SECRET_KEY": "s",
        "NOTEBOOKS_READER_DIR": "/r",
    }
    with pytest.raises(SystemExit, match="LITELLM_BASE_URL"):
        setup_from_environment(base)
    got = setup_from_environment(
        {**base, "LITELLM_BASE_URL": "http://gw:4000", "LITELLM_API_KEY": "k"}
    )
    assert got.gateway_url == "http://gw:4000" and got.embed_model == "creation-embedder"
    assert got.embed_dimension == 1024
    assert asyncio  # the module's async tests are collected above
