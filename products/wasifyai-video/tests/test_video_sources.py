"""What a clip was made from (ADR-0093, stage U8): an Extend keeps the clip it carries on, an
Animate keeps the picture of the library it sets moving; the list can give the clips made from one;
old database files get the column."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from test_video_extend import make_source
from test_video_graph import Story
from video_rig import make_rig, mp4, put_upload
from wasifyai_platform_sdk.sqlite import create_sqlite_engine
from wasifyai_video.schemas import LENGTHS
from wasifyai_video.videos import InMemoryVideoStore, SqliteVideoStore, VideoRecord

T0 = datetime.now(UTC) - timedelta(minutes=10)
PICTURE = "0b7c1f9e-0000-4000-8000-000000000001"


async def test_an_extension_keeps_the_clip_it_carries_on(tmp_path, ctx):
    rig, store = make_rig(tmp_path), InMemoryVideoStore()
    vid = await make_source(rig, store, frames=49)
    s = await Story(rig, videos=store).start(
        {"mode": "extend", "prompt": "the fox keeps walking", "source_id": vid}
    )
    await s.finish_job(data=mp4(frames=LENGTHS[5]))
    made = next(v for v in store.videos if v.id != vid)
    assert made.source_id == vid


async def test_an_animation_keeps_the_picture_only_when_it_is_an_id(tmp_path, ctx):
    for given, kept in ((PICTURE, PICTURE), ("not an id", None), (None, None)):
        rig, store = make_rig(tmp_path / str(kept)), InMemoryVideoStore()
        up = await put_upload(rig)
        request = {"mode": "image", "prompt": "snow falls", "image_key": up.key}
        if given is not None:
            request["source_image_id"] = given
        s = await Story(rig, videos=store).start(request)
        await s.finish_job()
        (made,) = store.videos
        assert made.source_id == kept


async def test_words_make_a_clip_with_no_source(tmp_path, ctx):
    rig, store = make_rig(tmp_path), InMemoryVideoStore()
    s = await Story(rig, videos=store).start(
        {"mode": "text", "prompt": "a fox", "source_image_id": PICTURE, "source_id": PICTURE}
    )
    await s.finish_job()
    (made,) = store.videos
    assert made.source_id is None


def rec(at=T0, user="u1", source=None) -> VideoRecord:
    return VideoRecord(
        id=str(uuid4()), tenant_id="t1", product_id="wasifyai-video", user_id=user,
        thread_id=None, run_id=None, mode="extend" if source else "text", status="done",
        prompt="a fox", seconds=2, frames=49, fps=24, created_at=at, source_id=source,
    )  # fmt: skip


async def check_sources(store) -> None:
    first = rec(at=T0)
    a = rec(at=T0 + timedelta(minutes=1), source=first.id)
    b = rec(at=T0 + timedelta(minutes=2), source=first.id)
    for r in (first, a, b, rec(at=T0 + timedelta(minutes=3))):
        await store.add(r)
    got = await store.get("t1", "u1", a.id)
    assert got is not None and got.source_id == first.id
    made_from = await store.list("t1", "u1", 10, None, source_id=first.id)
    assert [v.id for v in made_from] == [b.id, a.id]
    assert await store.list("t1", "u2", 10, None, source_id=first.id) == []
    assert len(await store.list("t1", "u1", 10, None)) == 4


async def test_sources_in_memory():
    await check_sources(InMemoryVideoStore())


async def test_sources_on_sqlite(tmp_path):
    engine = create_sqlite_engine(tmp_path / "wasifyai.db")
    try:
        await check_sources(SqliteVideoStore(engine))
    finally:
        await engine.dispose()


async def test_a_file_from_before_sources_gets_the_column(tmp_path):
    engine = create_sqlite_engine(tmp_path / "wasifyai.db")
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                """CREATE TABLE videos (
                    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, product_id TEXT NOT NULL,
                    user_id TEXT NOT NULL, thread_id TEXT, run_id TEXT, mode TEXT NOT NULL,
                    status TEXT NOT NULL, prompt TEXT NOT NULL, seconds INTEGER NOT NULL,
                    frames INTEGER NOT NULL, fps INTEGER NOT NULL, width INTEGER, height INTEGER,
                    video_key TEXT, poster_key TEXT, error TEXT, created_at TEXT NOT NULL)"""
            )
        store = SqliteVideoStore(engine)
        old = replace(rec(), id="v-old")
        await store.add(old)
        assert (await store.get("t1", "u1", "v-old")).source_id is None  # type: ignore[union-attr]
        await store.add(rec(source="v-old"))
        assert len(await store.list("t1", "u1", 10, None, source_id="v-old")) == 1
    finally:
        await engine.dispose()
