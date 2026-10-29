"""The search model through the gateway, the usage it records, and what one person may hold."""

import asyncio
import json

import httpx
import pytest
from notebooks_rig import SPEC, FakeReader, HashEmbedder, pg_dsn
from wasifyai_notebooks.components import GatewayComponents
from wasifyai_notebooks.embedding import EmbedError, GatewayEmbedder, Purpose, embed_counted
from wasifyai_notebooks.files import ObjectFiles, original_key
from wasifyai_notebooks.ingest import IngestWorker
from wasifyai_platform_sdk import memory_storage

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
