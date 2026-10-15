"""Image records and their search source on the desktop profile SQLite file (ADR-0056)."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from wasifyai_image.images import ImageRecord, InMemoryImageStore, SqliteImageStore, image_store
from wasifyai_image.index import SqliteImageIndexSource, image_index_source
from wasifyai_platform_sdk.sqlite import create_sqlite_engine

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
async def engine(tmp_path):
    eng = create_sqlite_engine(tmp_path / "wasifyai.db")
    yield eng
    await eng.dispose()


def rec(user="u1", tenant="t1", prompt="a teapot", at=T0) -> ImageRecord:
    iid = str(uuid4())
    return ImageRecord(
        id=iid, tenant_id=tenant, product_id="wasifyai-image", user_id=user, thread_id="th",
        run_id="run", mode="text", prompt=prompt, width=1024, height=1024,
        image_key=f"{iid}/image.png", thumb_key=f"{iid}/thumb.jpg", created_at=at,
    )  # fmt: skip


async def check_store(store) -> None:
    old, mid, new = rec(at=T0), rec(at=T0 + timedelta(minutes=1)), rec(at=T0 + timedelta(minutes=2))
    other_user, other_tenant = rec(user="u2"), rec(tenant="t2")
    for r in (old, new, mid, other_user, other_tenant):
        await store.add(r)

    # newest first, only this user's, and `before` pages strictly older
    page = await store.list("t1", "u1", 10, None)
    assert [i.id for i in page] == [new.id, mid.id, old.id]
    assert page[0].created_at is not None and page[0].created_at.tzinfo is not None
    assert [i.id for i in await store.list("t1", "u1", 1, None)] == [new.id]
    assert [i.id for i in await store.list("t1", "u1", 10, new.created_at)] == [mid.id, old.id]

    # one image, with every field; another user's image is not found
    got = await store.get("t1", "u1", mid.id)
    assert got is not None
    assert (got.prompt, got.width, got.image_key, got.thread_id) == (
        "a teapot", 1024, mid.image_key, "th"
    )  # fmt: skip
    assert await store.get("t1", "u1", other_user.id) is None
    assert await store.get("t1", "u1", "not-an-id") is None

    # recipe and favourite round-trip; favourites can be listed on their own
    recipe = {"v": 1, "mode": "text", "prompt": "a teapot", "size": "square", "seed": 7}
    made = rec(at=T0 + timedelta(minutes=3))
    made = replace(made, recipe=recipe)
    await store.add(made)
    got = await store.get("t1", "u1", made.id)
    assert got is not None and got.recipe == recipe and got.favourite is False
    assert (await store.get("t1", "u1", old.id)).recipe is None  # type: ignore[union-attr]
    assert await store.set_favourite("t1", "u1", old.id, True) is True
    assert await store.set_favourite("t1", "u2", mid.id, True) is False  # not theirs
    assert await store.set_favourite("t1", "u1", "not-an-id", True) is False
    assert [i.id for i in await store.list("t1", "u1", 10, None, favourites_only=True)] == [old.id]
    assert await store.set_favourite("t1", "u1", old.id, False) is True
    assert await store.list("t1", "u1", 10, None, favourites_only=True) == []
    await store.delete("t1", "u1", made.id)

    # delete is scoped to the owner
    await store.delete("t1", "u2", mid.id)
    assert await store.get("t1", "u1", mid.id) is not None
    await store.delete("t1", "u1", mid.id)
    assert await store.get("t1", "u1", mid.id) is None


async def test_image_store_memory():
    await check_store(InMemoryImageStore())


async def test_image_store_sqlite(engine):
    await check_store(SqliteImageStore(engine))


async def test_the_factory_picks_the_store_by_the_database(engine):
    assert isinstance(image_store(engine), SqliteImageStore)
    assert isinstance(image_index_source(engine), SqliteImageIndexSource)


async def test_the_index_source_pages_and_reports_what_is_present(engine):
    store = SqliteImageStore(engine)
    made = [rec(prompt=f"picture {n}") for n in range(3)]
    for r in made:
        await store.add(r)
    source = image_index_source(engine)
    ids = sorted(r.id for r in made)

    first = await source.page(None, 2)
    assert [i.item_id for i in first] == ids[:2]
    assert (first[0].kind, first[0].product_id, first[0].tenant_id) == (
        "image", "wasifyai-image", "t1"
    )  # fmt: skip
    assert [i.item_id for i in await source.page(first[-1].item_id, 2)] == ids[2:]
    assert await source.present([ids[0], "gone"]) == {ids[0]}
    assert await source.present([]) == set()


async def test_a_database_from_before_recipes_gets_the_new_columns(engine):
    """A file made by the previous version has no recipe or favourite column."""
    old_table = """
        CREATE TABLE images (
            id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, product_id TEXT NOT NULL,
            user_id TEXT NOT NULL, thread_id TEXT, run_id TEXT, mode TEXT NOT NULL,
            prompt TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
            image_key TEXT NOT NULL, thumb_key TEXT NOT NULL, created_at TEXT NOT NULL
        )"""
    async with engine.begin() as conn:
        await conn.exec_driver_sql(old_table)
        await conn.exec_driver_sql(
            "INSERT INTO images VALUES ('i1','t1','wasifyai-image','u1',NULL,NULL,'text',"
            "'an old one',64,64,'i1/image.png','i1/thumb.jpg','2026-10-01T12:00:00.000000+00:00')"
        )
    store = SqliteImageStore(engine)
    (got,) = await store.list("t1", "u1", 10, None)
    assert got.prompt == "an old one" and got.recipe is None and got.favourite is False
    assert await store.set_favourite("t1", "u1", "i1", True) is True
