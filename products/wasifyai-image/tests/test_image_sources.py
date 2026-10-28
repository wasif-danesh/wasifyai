"""What a picture was made from (ADR-0093, stage U8): a change started from a picture of the
person's library keeps that picture as its source; the list can give the pictures made from one;
old database files get the column. Fake models and an in-memory queue, as in test_image_graph.py."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from image_rig import make_rig, mask_png, put_upload
from test_image_graph import Story
from wasifyai_image.images import ImageRecord, InMemoryImageStore, SqliteImageStore
from wasifyai_platform_sdk.sqlite import create_sqlite_engine

T0 = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


def rec(at=T0, user="u1", source=None) -> ImageRecord:
    iid = str(uuid4())
    return ImageRecord(
        id=iid, tenant_id="t1", product_id="wasifyai-image", user_id=user, thread_id=None,
        run_id=None, mode="image" if source else "text", prompt="a teapot", width=64, height=64,
        image_key=f"{iid}/image.png", thumb_key=f"{iid}/thumb.jpg", created_at=at,
        source_id=source,
    )  # fmt: skip


async def library_picture(story: Story, user: str = "u1") -> ImageRecord:
    made = replace(rec(user=user), tenant_id="t1")
    await story.images.add(made)
    return made


@pytest.mark.parametrize("mode", ["image", "inpaint", "reference"])
async def test_a_change_of_a_library_picture_keeps_it_as_the_source(tmp_path, ctx, mode):
    rig = make_rig(tmp_path)
    story = Story(rig)
    first = await library_picture(story)
    a = await put_upload(rig)
    extra = (
        {"mask_key": (await put_upload(rig, data=mask_png())).key}
        if mode == "inpaint"
        else {"image2_key": (await put_upload(rig)).key}
        if mode == "reference"
        else {}
    )
    await story.start(
        {"mode": mode, "prompt": "make it blue", "image_key": a.key, "source_id": first.id, **extra}
    )
    await story.finish_job()
    assert story.state["status"] == "done"
    made = next(i for i in story.images.images if i.id != first.id)
    assert made.source_id == first.id


async def test_no_source_for_words_a_file_or_a_picture_that_is_not_theirs(tmp_path, ctx):
    rig = make_rig(tmp_path)
    story = Story(rig)
    someone_elses = await library_picture(story, user="u2")
    a = await put_upload(rig)
    # a picture of another person: not kept
    await story.start(
        {"mode": "image", "prompt": "x", "image_key": a.key, "source_id": someone_elses.id}
    )
    await story.finish_job()
    (made,) = [i for i in story.images.images if i.user_id == "u1"]
    assert made.source_id is None
    # words only: a source is ignored
    words = Story(make_rig(tmp_path / "words"))
    mine = await library_picture(words)
    await words.start({"mode": "text", "prompt": "a lighthouse", "source_id": mine.id})
    await words.finish_job()
    new = next(i for i in words.images.images if i.id != mine.id)
    assert new.source_id is None


async def check_sources(store) -> None:
    first = rec(at=T0)
    a, b = (
        rec(at=T0 + timedelta(minutes=1), source=first.id),
        rec(at=T0 + timedelta(minutes=2), source=first.id),
    )
    other = rec(at=T0 + timedelta(minutes=3))
    for r in (first, a, b, other):
        await store.add(r)
    got = await store.get("t1", "u1", a.id)
    assert got is not None and got.source_id == first.id
    assert (await store.get("t1", "u1", first.id)).source_id is None  # type: ignore[union-attr]
    made_from = await store.list("t1", "u1", 10, None, source_id=first.id)
    assert [i.id for i in made_from] == [b.id, a.id]
    assert await store.list("t1", "u2", 10, None, source_id=first.id) == []  # only the person's own
    assert await store.list("t1", "u1", 10, None, source_id=other.id) == []
    assert len(await store.list("t1", "u1", 10, None)) == 4  # no filter: everything


async def test_sources_in_memory():
    await check_sources(InMemoryImageStore())


async def test_sources_on_sqlite(tmp_path):
    engine = create_sqlite_engine(tmp_path / "wasifyai.db")
    try:
        await check_sources(SqliteImageStore(engine))
    finally:
        await engine.dispose()


async def test_a_file_from_before_sources_gets_the_column(tmp_path):
    engine = create_sqlite_engine(tmp_path / "wasifyai.db")
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                """CREATE TABLE images (
                    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, product_id TEXT NOT NULL,
                    user_id TEXT NOT NULL, thread_id TEXT, run_id TEXT, mode TEXT NOT NULL,
                    prompt TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
                    image_key TEXT NOT NULL, thumb_key TEXT NOT NULL, recipe TEXT,
                    favourite INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)"""
            )
            await conn.exec_driver_sql(
                "INSERT INTO images VALUES ('i1','t1','wasifyai-image','u1',NULL,NULL,'text',"
                "'old',64,64,'i1/image.png','i1/thumb.jpg',NULL,0,"
                "'2026-10-01T12:00:00.000000+00:00')"
            )
        store = SqliteImageStore(engine)
        (old,) = await store.list("t1", "u1", 10, None)
        assert old.source_id is None
        await store.add(rec(source="i1"))
        assert [i.prompt for i in await store.list("t1", "u1", 10, None, source_id="i1")] == [
            "a teapot"
        ]
    finally:
        await engine.dispose()
