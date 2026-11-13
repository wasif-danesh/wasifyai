"""What a picture or a clip was made from, on real Postgres (ADR-0093, stage U8, migration 0026):
the source is kept as a UUID, read back as the id, and the list can give what was made from one,
only for its owner."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from wasifyai_image.images import ImageRecord, PostgresImageStore
from wasifyai_video.videos import PostgresVideoStore, VideoRecord

T0 = datetime.now(UTC) - timedelta(minutes=5)


def picture(tenant: str, at: datetime, source: str | None = None) -> ImageRecord:
    iid = str(uuid4())
    return ImageRecord(
        id=iid, tenant_id=tenant, product_id="wasifyai-image", user_id="u1", thread_id=None,
        run_id=None, mode="image" if source else "text", prompt="a teapot", width=64, height=64,
        image_key=f"{iid}/image.png", thumb_key=f"{iid}/thumb.jpg", source_id=source,
    )  # fmt: skip


def clip(tenant: str, source: str | None = None) -> VideoRecord:
    return VideoRecord(
        id=str(uuid4()), tenant_id=tenant, product_id="wasifyai-video", user_id="u1",
        thread_id=None, run_id=None, mode="extend" if source else "text", status="working",
        prompt="a fox", seconds=2, frames=49, fps=24, source_id=source,
    )  # fmt: skip


async def test_pictures_keep_their_source_and_list_what_was_made_from_one(engine):
    store, tenant = PostgresImageStore(engine), f"t-{uuid4().hex[:8]}"
    first = picture(tenant, T0)
    made = picture(tenant, T0, source=first.id)
    try:
        await store.add(first)
        await store.add(made)
        got = await store.get(tenant, "u1", made.id)
        assert got is not None and got.source_id == first.id
        assert (await store.get(tenant, "u1", first.id)).source_id is None  # type: ignore[union-attr]
        assert [i.id for i in await store.list(tenant, "u1", 10, None, source_id=first.id)] == [
            made.id
        ]
        assert await store.list(tenant, "u2", 10, None, source_id=first.id) == []
        assert await store.list(tenant, "u1", 10, None, source_id="not-an-id") == []
    finally:
        for r in (made, first):
            await store.delete(tenant, "u1", r.id)


async def test_clips_keep_their_source_and_list_what_was_made_from_one(engine):
    store, tenant = PostgresVideoStore(engine), f"t-{uuid4().hex[:8]}"
    first = clip(tenant)
    made = clip(tenant, source=first.id)
    try:
        await store.add(first)
        await store.add(made)
        got = await store.get(tenant, "u1", made.id)
        assert got is not None and got.source_id == first.id
        assert [v.id for v in await store.list(tenant, "u1", 10, None, source_id=first.id)] == [
            made.id
        ]
        assert await store.list(tenant, "u2", 10, None, source_id=first.id) == []
    finally:
        for r in (made, first):
            await store.delete(tenant, "u1", r.id)
