"""Notebooks in My creations search: the source the platform pages through."""

import pytest
from notebooks_rig import SPEC
from wasifyai_notebooks.index import notebook_index_source
from wasifyai_notebooks.store import NotebookStore
from wasifyai_platform_sdk.sqlite import create_sqlite_engine


async def test_a_notebook_is_listed_with_its_title_and_source_names(tmp_path):
    engine = create_sqlite_engine(tmp_path / "wasifyai.db")  # the main database sits beside it
    try:
        src = notebook_index_source(engine)
        assert await src.page(None, 10) == []  # no notebooks file yet: nothing to list
        store = NotebookStore.in_folder(
            tmp_path / "notebooks", dimension=SPEC.dimension, embedder_id=SPEC.id
        )
        a = store.create_notebook("t1", "u1", "Q3 planning")
        b = store.create_notebook("t1", "u2", "Thesis reading")
        store.add_file(
            "t1", "u1", a["id"], title="budget.xlsx", suffix=".xlsx", mime="x", size_bytes=1,
            sha256="s",
        )  # fmt: skip
        items = await src.page(None, 10)
        by_id = {i.item_id: i for i in items}
        assert set(by_id) == {a["id"], b["id"]}
        one = by_id[a["id"]]
        assert (one.tenant_id, one.user_id, one.kind) == ("t1", "u1", "notebook")
        assert "Q3 planning" in one.text and "budget.xlsx" in one.text
        assert by_id[b["id"]].user_id == "u2"
        first, second = sorted(by_id)
        assert [i.item_id for i in await src.page(first, 10)] == [second]  # paging by id
        assert await src.present([a["id"], "gone"]) == {a["id"]}
        store.delete_notebook("t1", "u1", a["id"])
        assert await src.present([a["id"]]) == set()  # the platform removes the row
    finally:
        await engine.dispose()


async def test_postgres_notebooks_are_listed_the_same_way(new_store):
    if new_store.backend != "postgres":
        pytest.skip("the SQLite file is covered above")
    from notebooks_rig import pg_dsn
    from sqlalchemy.ext.asyncio import create_async_engine
    from wasifyai_notebooks.index import PgNotebookIndexSource

    store = new_store(dimension=SPEC.dimension, embedder_id=SPEC.id)
    engine = create_async_engine(pg_dsn().replace("postgresql://", "postgresql+asyncpg://", 1))
    try:
        src = PgNotebookIndexSource(engine, store.schema)
        assert await src.page(None, 10) == []
        a = store.create_notebook("t1", "u1", "Q3 planning")
        b = store.create_notebook("t1", "u2", "Thesis reading")
        store.add_file(
            "t1", "u1", a["id"], title="budget.xlsx", suffix=".xlsx", mime="x", size_bytes=1,
            sha256="s",
        )  # fmt: skip
        by_id = {i.item_id: i for i in await src.page(None, 10)}
        assert set(by_id) == {a["id"], b["id"]}
        one = by_id[a["id"]]
        assert (one.tenant_id, one.user_id, one.kind) == ("t1", "u1", "notebook")
        assert "Q3 planning" in one.text and "budget.xlsx" in one.text
        first, second = sorted(by_id)
        assert [i.item_id for i in await src.page(first, 10)] == [second]  # paging by id
        assert await src.present([a["id"], "gone"]) == {a["id"]}
        assert await src.present([]) == set()
        store.delete_notebook("t1", "u1", a["id"])
        assert await src.present([a["id"]]) == set()
        # a schema that was never made has nothing to list
        assert await PgNotebookIndexSource(engine, "nbt_missing").page(None, 5) == []
    finally:
        await engine.dispose()
