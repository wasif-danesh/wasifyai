"""The web profile's notebooks: Postgres for the library, object storage for the files, and a worker
that reads what the engine's program only stores."""

import asyncio
import hashlib
import io

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from notebooks_rig import SPEC, FakeComponents, pg_dsn
from wasifyai_notebooks.embedding import Purpose
from wasifyai_notebooks.files import original_key
from wasifyai_notebooks.retrieval import retrieve
from wasifyai_notebooks.routes import build_routes
from wasifyai_notebooks.runtime import STALE_AFTER_S, WebSetup, runtime_for
from wasifyai_notebooks.worker import setup_from_environment
from wasifyai_platform_sdk import EngineServices, Identity, RouteDeps, memory_storage

T, U = "t1", "u1"


@pytest.fixture
def setup(tmp_path, new_store):
    if new_store.backend != "postgres":
        pytest.skip("the web profile is Postgres")
    store = new_store(dimension=SPEC.dimension, embedder_id=SPEC.id, name="web")
    return WebSetup(
        dsn=pg_dsn(),
        storage=memory_storage(),
        models_dir=tmp_path / "models",
        reader_dir=tmp_path / "reader",
        tmp_dir=tmp_path / "tmp",
        schema=store.schema,
    )


def test_the_engines_program_stores_a_source_and_a_worker_reads_it(setup, tmp_path):
    comps = FakeComponents(tmp_path)
    engine_side = setup.build(reads_sources=False, components=comps)
    worker_side = setup.build(
        reads_sources=True, components=comps, tokenizer_factory=lambda: "word"
    )
    try:
        nb = engine_side.store.create_notebook(T, U, "Launch")
        text = b"# Budget\n\nThe marketing budget for the launch is $350,000.\n"
        doc, _ = engine_side.store.add_file(
            T, U, nb["id"], title="budget plan.txt", suffix=".txt", mime="text/plain",
            size_bytes=len(text), sha256=hashlib.sha256(text).hexdigest(),
        )  # fmt: skip
        engine_side.files_for(T, U).put_bytes(original_key(nb["id"], doc), text)
        assert engine_side.worker._task is None  # the engine's program reads nothing

        async def read_it():
            worker_side.worker.start()
            try:
                await worker_side.worker.drain(20)
            finally:
                await worker_side.worker.stop()

        asyncio.run(read_it())

        # the engine's program sees the result: the source is ready and a question finds it
        got = engine_side.store.get_document(T, U, nb["id"], doc["id"])
        assert got["status"] == "ready" and got["embedder"] == SPEC.id
        vec = comps.fake.embed(["marketing budget"], Purpose.QUERY)[0]
        with engine_side.store.connect() as db:
            hits = retrieve(db, nb["id"], "marketing budget", vec, weight=SPEC.semantic_weight)
        assert hits and "350,000" in hits[0].content and hits[0].title == "budget plan.txt"
    finally:
        engine_side.store.close()  # type: ignore[attr-defined]
        worker_side.store.close()  # type: ignore[attr-defined]


def test_a_source_a_reader_lost_is_failed_only_when_it_is_stale(setup, tmp_path):
    runtime = setup.build(reads_sources=False, components=FakeComponents(tmp_path))
    store = runtime.store
    try:
        nb = store.create_notebook(T, U, "n")
        a, _ = store.add_file(
            T, U, nb["id"], title="a.txt", suffix=".txt", mime="x", size_bytes=1, sha256="a"
        )
        b, _ = store.add_file(
            T, U, nb["id"], title="b.txt", suffix=".txt", mime="x", size_bytes=1, sha256="b"
        )
        store.begin(a["id"])
        store.begin(b["id"])
        with store._tx() as db:  # noqa: SLF001 - age one of them
            db.execute(
                "UPDATE documents SET updated_at = '2020-01-01T00:00:00.000+00:00' WHERE id = ?",
                (a["id"],),
            )
        assert store.reset_interrupted(STALE_AFTER_S) == 1  # another reader may be on b
        assert store.get_document(T, U, nb["id"], a["id"])["status"] == "failed"
        assert store.get_document(T, U, nb["id"], b["id"])["status"] == "processing"
        assert store.reset_interrupted() == 1  # a program that is alone fails every one it had
    finally:
        store.close()  # type: ignore[attr-defined]


def test_the_engine_serves_notebooks_through_the_web_runtime_and_reads_none(setup, tmp_path):
    setup.components = FakeComponents(tmp_path)

    state = EngineServices(notebooks_web=setup)
    runtime = runtime_for(state)
    assert runtime_for(state) is runtime and runtime.reads_sources is False
    try:

        async def identity(x_user: str = Header("u1"), x_tenant: str = Header("t1")) -> Identity:
            return Identity(x_tenant, x_user)

        app = FastAPI()
        app.include_router(
            build_routes(RouteDeps(state, identity), runtime), prefix="/products/wasifyai-notebooks"
        )
        with TestClient(app) as c:
            c.base_url = c.base_url.join("/products/wasifyai-notebooks/")
            nb = c.post("notebooks", json={}).json()
            up = c.post(
                f"notebooks/{nb['id']}/documents/upload",
                files=[("files", ("notes ünï.txt", io.BytesIO(b"Words for the notebook here.")))],
            ).json()
            doc = up["created"][0]
            assert doc["status"] == "pending"  # waiting for the worker
            assert runtime.worker._task is None  # nothing was read by this program
            dl = c.get(f"notebooks/{nb['id']}/documents/{doc['id']}/original")
            assert dl.status_code == 200 and dl.content == b"Words for the notebook here."
            assert c.delete(f"notebooks/{nb['id']}").status_code == 204
            assert not runtime.files_for(T, U).exists(original_key(nb["id"], doc))
    finally:
        runtime.store.close()  # type: ignore[attr-defined]


def test_the_worker_is_set_up_from_the_environment(tmp_path):
    env = {
        "DATABASE_URL": "postgresql+asyncpg://u:p@db/x",
        "STORAGE_ENDPOINT": "http://s3:8333",
        "STORAGE_ACCESS_KEY": "k",
        "STORAGE_SECRET_KEY": "s",
        "NOTEBOOKS_MODELS_DIR": str(tmp_path / "m"),
        "NOTEBOOKS_READER_DIR": str(tmp_path / "r"),
    }
    got = setup_from_environment(env)
    assert got.schema == "notebooks" and got.models_dir == tmp_path / "m"
    assert got.dsn.endswith("@db/x")
    with pytest.raises(SystemExit, match="STORAGE_ACCESS_KEY"):
        setup_from_environment({k: v for k, v in env.items() if k != "STORAGE_ACCESS_KEY"})


def test_the_worker_builds_the_chat_model_from_the_products_own_configuration(tmp_path):
    from pathlib import Path

    from wasifyai_notebooks.worker import capabilities_for

    products = Path(__file__).resolve().parents[2]  # the repository's products folder
    setup = WebSetup(
        dsn="postgresql://u:p@localhost/x",
        storage=memory_storage(),
        models_dir=tmp_path,
        reader_dir=tmp_path,
        tmp_dir=tmp_path,
        gateway_url="http://gateway:4000",
        gateway_key="k",
    )
    caps = capabilities_for(setup, {"PRODUCTS_DIR": str(products)})
    assert caps.config is not None and caps.config.id == "wasifyai-notebooks"
    assert "chat" in caps.text._bound  # the same binding a run of the graph uses
    assert caps.config.quotas["notebooks_per_user"] == 50
