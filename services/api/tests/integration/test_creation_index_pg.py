"""The search index on real Postgres with pgvector, and the products' index sources on their real
tables (needs `make migrate` through 0011). Each test uses its own tenant and cleans up."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from wasifyai_api.creation_index import DIMENSIONS, CreationIndex, PostgresIndexStore
from wasifyai_platform_sdk import IndexItem


@pytest.fixture
async def store(engine):
    try:
        async with engine.connect() as c:
            await c.execute(text("select 1 from creation_index limit 1"))
    except Exception:
        pytest.skip("creation_index table missing (make migrate)")
    tenant = "it-" + uuid4().hex
    yield PostgresIndexStore(engine), tenant
    async with engine.begin() as c:
        await c.execute(text("DELETE FROM creation_index WHERE tenant_id = :t"), {"t": tenant})


def unit(i: int) -> list[float]:
    v = [0.0] * DIMENSIONS
    v[i] = 1.0
    return v


def item(tenant, n, body, user="u1", kind="song", product="wasifyai-music"):
    return IndexItem(tenant, product, user, kind, f"it-{n}", body)


async def test_nearest_is_ordered_by_similarity_and_scoped_to_the_user(store):
    s, tenant = store
    await s.upsert(item(tenant, 1, "a"), "m", unit(0))
    await s.upsert(item(tenant, 2, "b"), "m", [0.9, 0.5] + [0.0] * (DIMENSIONS - 2))
    await s.upsert(item(tenant, 3, "c", user="other"), "m", unit(0))
    hits = await s.nearest(tenant, "u1", unit(0), None, 10)
    assert [h.item_id for h in hits] == ["it-1", "it-2"]  # the other user's is never there
    assert hits[0].score == pytest.approx(1.0, abs=1e-4) and hits[1].score < hits[0].score
    only = await s.nearest(tenant, "u1", unit(0), "image", 10)
    assert only == []
    assert await s.nearest(tenant, "u2", unit(0), None, 10) == []


async def test_exact_words_work_in_any_script_ignore_case_and_treat_percent_literally(store):
    s, tenant = store
    bodies = {
        1: "Rain in MADRID tonight",
        2: "Un saxofón suspira en un club",
        3: "夜晚的城市街道下着大雨，灯塔",
        4: "50% off and a_b sale",
        5: "フォーク ジャズ",
    }
    for n, body in bodies.items():
        await s.upsert(item(tenant, n, body), "m", unit(n))

    async def found(*words):
        return [h.item_id for h in await s.with_words(tenant, "u1", list(words), None, 10)]

    assert await found("madrid", "rain") == ["it-1"]  # every word, any case
    assert await found("SAXOFÓN") == ["it-2"]  # accents are kept, case is not
    assert await found("灯塔") == ["it-3"]  # no word splitting needed
    assert await found("フォーク") == ["it-5"]
    assert await found("50%") == ["it-4"] and await found("a_b") == ["it-4"]
    assert await found("%") == ["it-4"]  # a percent sign is a character, not "anything"
    assert await found("_") == ["it-4"]
    assert await found("madrid", "tokyo") == []
    assert await found() == []


async def test_upsert_replaces_models_and_orphan_lookup_work(store):
    s, tenant = store
    await s.upsert(item(tenant, 1, "old"), "m1", unit(0))
    await s.upsert(item(tenant, 1, "new words"), "m2", unit(1))
    assert await s.models("wasifyai-music", ["it-1", "it-9"]) == {"it-1": "m2"}
    assert [h.item_id for h in await s.with_words(tenant, "u1", ["new"], None, 5)] == ["it-1"]
    await s.upsert(item(tenant, 2, "x"), "m2", unit(2))
    ids = await s.ids_after("wasifyai-music", None, 100)
    assert "it-1" in ids and "it-2" in ids and ids == sorted(ids)
    after = await s.ids_after("wasifyai-music", "it-1", 100)
    assert "it-1" not in after and "it-2" in after
    await s.delete_ids("wasifyai-music", ["it-1"])
    await s.delete(tenant, "wasifyai-music", "it-2")
    assert await s.models("wasifyai-music", ["it-1", "it-2"]) == {}


async def test_the_whole_index_with_a_scripted_embedder(store):
    s, tenant = store

    async def embed(texts):
        return [unit(len(t) % 50) for t in texts]

    index = CreationIndex(s, embed, "m", min_similarity=0.5)
    await index.index(tenant, "wasifyai-image", "u1", "image", "it-7", "a red fox")
    hits, degraded = await index.search(tenant, "u1", "fox", None, 5)
    assert not degraded and [(h.item_id, h.match) for h in hits] == [("it-7", "words")]


# ---- the products' index sources on their real tables ---------------------------------------


@pytest.fixture
async def tables(engine):
    try:
        async with engine.connect() as c:
            await c.execute(text("select 1 from videos limit 1"))
            await c.execute(text("select 1 from images limit 1"))
            await c.execute(text("select 1 from songs limit 1"))
    except Exception:
        pytest.skip("product tables missing (make migrate)")
    tenant = "it-" + uuid4().hex
    yield tenant
    async with engine.begin() as c:
        for t in ("songs", "images", "videos"):
            await c.execute(text(f"DELETE FROM {t} WHERE tenant_id = :t"), {"t": tenant})


async def test_the_sources_list_and_check_real_rows(engine, tables):
    from wasifyai_image.index import ImageIndexSource
    from wasifyai_music.index import SongIndexSource
    from wasifyai_video.index import VideoIndexSource

    tenant = tables
    ids = {k: str(uuid4()) for k in ("song", "image", "video", "working")}
    async with engine.begin() as c:
        await c.execute(
            text(
                "INSERT INTO songs (id, tenant_id, product_id, user_id, title, lyrics, style, "
                "audio_key) VALUES (:id, :t, 'wasifyai-music', 'u1', 'Lluvia', "
                "'[verse]\nhola mundo', 'pop', 'k')"
            ),
            {"id": ids["song"], "t": tenant},
        )
        await c.execute(
            text(
                "INSERT INTO images (id, tenant_id, product_id, user_id, mode, prompt, width, "
                "height, image_key, thumb_key) VALUES (:id, :t, 'wasifyai-image', 'u1', 'text', "
                "'a red fox', 1, 1, 'k', 'k')"
            ),
            {"id": ids["image"], "t": tenant},
        )
        for key, status in (("video", "done"), ("working", "working")):
            await c.execute(
                text(
                    "INSERT INTO videos (id, tenant_id, product_id, user_id, mode, status, prompt, "
                    "seconds, frames, fps) VALUES (:id, :t, 'wasifyai-video', 'u1', 'text', :s, "
                    "'fox walks', 2, 49, 24)"
                ),
                {"id": ids[key], "t": tenant, "s": status},
            )

    (song,) = [i for i in await SongIndexSource(engine).page(None, 1000) if i.tenant_id == tenant]
    assert (song.item_id, song.user_id, song.kind) == (ids["song"], "u1", "song")
    assert "Lluvia" in song.text and "hola mundo" in song.text and "[verse]" not in song.text
    (image,) = [i for i in await ImageIndexSource(engine).page(None, 1000) if i.tenant_id == tenant]
    assert (image.item_id, image.text) == (ids["image"], "a red fox")
    mine = [i for i in await VideoIndexSource(engine).page(None, 1000) if i.tenant_id == tenant]
    assert [i.item_id for i in mine] == [ids["video"]]  # a clip still being made is not indexed
    assert await VideoIndexSource(engine).present([ids["video"], ids["working"]]) == {ids["video"]}
    assert await SongIndexSource(engine).present([ids["song"], str(uuid4())]) == {ids["song"]}
    after = await ImageIndexSource(engine).page(ids["image"], 1000)
    assert ids["image"] not in [i.item_id for i in after]
