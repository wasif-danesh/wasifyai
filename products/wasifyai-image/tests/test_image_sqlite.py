"""Image records and their search source on the desktop profile SQLite file (ADR-0056)."""

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
