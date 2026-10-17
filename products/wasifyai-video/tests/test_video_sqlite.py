"""Video records and their search source on the desktop profile SQLite file (ADR-0056)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from wasifyai_platform_sdk.sqlite import create_sqlite_engine
from wasifyai_video.index import SqliteVideoIndexSource, video_index_source
from wasifyai_video.videos import (
    STALE_AFTER,
    InMemoryVideoStore,
    SqliteVideoStore,
    VideoRecord,
    video_store,
)

T0 = datetime.now(UTC) - timedelta(minutes=10)  # recent: an old "working" clip counts as dead


@pytest.fixture
async def engine(tmp_path):
    eng = create_sqlite_engine(tmp_path / "wasifyai.db")
    yield eng
    await eng.dispose()


def rec(user="u1", tenant="t1", prompt="a fox in the snow", at=T0, status="working") -> VideoRecord:
    return VideoRecord(
        id=str(uuid4()), tenant_id=tenant, product_id="wasifyai-video", user_id=user,
        thread_id="th", run_id="run", mode="text", status=status, prompt=prompt, seconds=2,
        frames=49, fps=24, created_at=at,
    )  # fmt: skip


async def check_store(store) -> None:
    old, mid, new = rec(at=T0), rec(at=T0 + timedelta(minutes=1)), rec(at=T0 + timedelta(minutes=2))
    other_user, other_tenant = rec(user="u2"), rec(tenant="t2")
    for r in (old, new, mid, other_user, other_tenant):
        await store.add(r)

    # a new clip is "working", is counted, and has no files yet
    assert await store.working_count("t1", "u1") == 3
    got = await store.get("t1", "u1", mid.id)
    assert got is not None and got.status == "working" and got.video_key is None

    # finishing and failing; a failure does not overwrite a finished clip
    await store.finish("t1", old.id, 768, 512, f"{old.id}/video.mp4", f"{old.id}/poster.jpg")
    await store.fail("t1", mid.id, "It broke.")
    await store.fail("t1", old.id, "late failure")
    done = await store.get("t1", "u1", old.id)
    assert done is not None and (done.status, done.width, done.height, done.error) == (
        "done", 768, 512, None
    )  # fmt: skip
    assert (done.video_key, done.poster_key) == (f"{old.id}/video.mp4", f"{old.id}/poster.jpg")
    failed = await store.get("t1", "u1", mid.id)
    assert failed is not None and (failed.status, failed.error) == ("failed", "It broke.")
    assert await store.working_count("t1", "u1") == 1

    # newest first, only this user's; `before` pages strictly older; status filters
    page = await store.list("t1", "u1", 10, None)
    assert [v.id for v in page] == [new.id, mid.id, old.id]
    assert page[0].created_at is not None and page[0].created_at.tzinfo is not None
    assert [v.id for v in await store.list("t1", "u1", 1, None)] == [new.id]
    assert [v.id for v in await store.list("t1", "u1", 10, new.created_at)] == [mid.id, old.id]
    assert [v.id for v in await store.list("t1", "u1", 10, None, "done")] == [old.id]
    assert [v.id for v in await store.list("t1", "u1", 10, None, "working")] == [new.id]

    # another user's clip is not found, and cannot be deleted
    assert await store.get("t1", "u1", other_user.id) is None
    assert await store.get("t1", "u1", "not-an-id") is None
    await store.delete("t1", "u2", mid.id)
    assert await store.get("t1", "u1", mid.id) is not None
    await store.delete("t1", "u1", mid.id)
    assert await store.get("t1", "u1", mid.id) is None


async def test_video_store_memory():
    await check_store(InMemoryVideoStore())


async def test_video_store_sqlite(engine):
    await check_store(SqliteVideoStore(engine))


async def test_a_clip_that_stays_working_too_long_is_marked_failed(engine):
    store = SqliteVideoStore(engine)
    stale = rec(at=datetime.now(UTC) - STALE_AFTER - timedelta(minutes=1))
    fresh = rec(at=datetime.now(UTC))
    await store.add(stale)
    await store.add(fresh)
    assert await store.working_count("t1", "u1") == 1
    got = await store.get("t1", "u1", stale.id)
    assert got is not None and got.status == "failed" and "too long" in (got.error or "")


async def test_the_factory_picks_the_store_by_the_database(engine):
    assert isinstance(video_store(engine), SqliteVideoStore)
    assert isinstance(video_index_source(engine), SqliteVideoIndexSource)


async def test_the_index_source_lists_only_finished_clips(engine):
    store = SqliteVideoStore(engine)
    made = [rec(prompt=f"clip {n}") for n in range(3)]
    pending = rec(prompt="not finished yet")
    for r in (*made, pending):
        await store.add(r)
    for r in made:
        await store.finish("t1", r.id, 768, 512, f"{r.id}/video.mp4", f"{r.id}/poster.jpg")
    source = video_index_source(engine)
    ids = sorted(r.id for r in made)

    first = await source.page(None, 2)
    assert [i.item_id for i in first] == ids[:2]
    assert (first[0].kind, first[0].product_id, first[0].tenant_id) == (
        "video", "wasifyai-video", "t1"
    )  # fmt: skip
    assert [i.item_id for i in await source.page(first[-1].item_id, 2)] == ids[2:]
    assert await source.present([ids[0], pending.id, "gone"]) == {ids[0]}
    assert await source.present([]) == set()
