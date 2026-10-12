"""Search over My creations (ADR-0041): the index logic, the route and the background indexer,
with a scripted embedder and the in-memory store: no model, no database."""

import hashlib
import time

import jwt
import pytest
from fastapi.testclient import TestClient
from wasifyai_api.admin import InMemoryAdminStore
from wasifyai_api.config import get_settings
from wasifyai_api.creation_index import (
    ContextIndexer,
    CreationIndex,
    InMemoryIndexStore,
    like_patterns,
    query_words,
)
from wasifyai_api.users import InMemoryUserStore
from wasifyai_platform_sdk import (
    IndexItem,
    InMemoryUploadLimiter,
    InMemoryUsageRecorder,
    RunContext,
    reset_context,
    set_context,
)

from tests.test_auth import SECRET
from tests.test_runs import hello_registry, mem_app

DIMS = 64


def vec(text: str) -> list[float]:
    """A stand-in embedder: words that are shared make vectors that are close."""
    v = [0.0] * DIMS
    for w in text.lower().replace(".", " ").split():
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIMS] += 1.0
    return v


async def fake_embed(texts: list[str]) -> list[list[float]]:
    return [vec(t) for t in texts]


def make_index(store=None, embed=fake_embed, floor=0.3, model="m1"):
    return CreationIndex(store or InMemoryIndexStore(), embed, model, floor)


def item(n, text, user="u1", tenant="t1", kind="song", product="wasifyai-music"):
    return IndexItem(tenant, product, user, kind, f"id-{n}", text)


async def fill(index, *items):
    for it in items:
        await index.index_item(it)


# ---- the logic ----------------------------------------------------------------------------


def test_one_character_is_enough_in_chinese_japanese_and_korean_only():
    from wasifyai_api.creation_index import long_enough

    assert not long_enough("a") and not long_enough(" a ") and long_enough("ab")
    assert long_enough("龙") and long_enough("の") and long_enough("カ") and long_enough("한")
    assert not long_enough("é") and not long_enough("")


def test_words_are_split_and_escaped_for_like():
    assert query_words("  Rain   in MADRID ") == ["rain", "in", "madrid"]
    assert like_patterns(["50%", "a_b", "c\\d"]) == ["%50\\%%", "%a\\_b%", "%c\\\\d%"]
    assert len(query_words(" ".join(["w"] * 40))) == 12


async def test_exact_words_come_first_then_meaning_above_the_floor():
    index = make_index(floor=0.25)
    await fill(
        index,
        item(1, "rain in the city at night a sad song"),
        item(2, "a night of rain falling on a quiet city"),
        item(3, "red fox in the snow"),
    )
    hits, degraded = await index.search("t1", "u1", "sad song", None, 10)
    assert not degraded
    assert [(h.item_id, h.match) for h in hits][0] == ("id-1", "words")  # contains both words
    assert "id-3" not in [h.item_id for h in hits]  # nothing in common: under the floor
    # meaning-only results follow, in similarity order
    assert [h.match for h in hits[1:]] == ["meaning"] * (len(hits) - 1)


async def test_nothing_found_is_a_possible_answer():
    index = make_index(floor=0.9)
    await fill(index, item(1, "rain in the city"), item(2, "fox in snow"))
    hits, _ = await index.search("t1", "u1", "submarine trench", None, 10)
    assert hits == []


async def test_an_exact_word_below_the_floor_is_still_found():
    index = make_index(floor=0.95)  # nothing is similar enough
    await fill(index, item(1, "una calle de Paris con lluvia"))
    hits, _ = await index.search("t1", "u1", "paris", None, 10)
    assert [(h.item_id, h.match) for h in hits] == [("id-1", "words")]


async def test_search_never_crosses_users_or_tenants_and_can_filter_by_kind():
    index = make_index(floor=0.0)
    await fill(
        index,
        item(1, "rain city", user="u1"),
        item(2, "rain city", user="u2"),
        item(3, "rain city", tenant="other"),
        item(4, "rain city", kind="image", product="wasifyai-image"),
    )
    hits, _ = await index.search("t1", "u1", "rain city", None, 10)
    assert sorted(h.item_id for h in hits) == ["id-1", "id-4"]
    only, _ = await index.search("t1", "u1", "rain city", "image", 10)
    assert [h.item_id for h in only] == ["id-4"]
    assert await index.search("t1", "nobody", "rain city", None, 10) == ([], False)


async def test_limit_and_removal():
    index = make_index(floor=0.0)
    await fill(index, *[item(n, f"rain {n}") for n in range(5)])
    hits, _ = await index.search("t1", "u1", "rain", None, 3)
    assert len(hits) == 3
    await index.remove("t1", "wasifyai-music", "id-0")
    hits, _ = await index.search("t1", "u1", "rain", None, 10)
    assert "id-0" not in [h.item_id for h in hits]


async def test_when_the_embedder_is_down_exact_words_still_work_and_it_says_so():
    async def broken(texts):
        raise ConnectionError("embedder down")

    store = InMemoryIndexStore()
    await fill(make_index(store), item(1, "fox in snow"))
    degraded_index = make_index(store, embed=broken)
    hits, degraded = await degraded_index.search("t1", "u1", "snow", None, 10)
    assert degraded and [(h.item_id, h.match) for h in hits] == [("id-1", "words")]


async def test_indexing_the_same_item_again_replaces_it():
    store = InMemoryIndexStore()
    index = make_index(store)
    await fill(index, item(1, "old words"))
    await fill(index, item(1, "new words"))
    assert len(store.rows) == 1 and next(iter(store.rows.values()))[0].text == "new words"


async def test_the_context_indexer_indexes_for_the_user_of_the_run():
    store = InMemoryIndexStore()
    indexer = ContextIndexer(make_index(store))
    token = set_context(RunContext("t9", "wasifyai-image", "u9", "run", "thread"))
    try:
        await indexer.index("image", "img-1", "a red fox")
    finally:
        reset_context(token)
    ((it, model, _),) = store.rows.values()
    assert (it.tenant_id, it.product_id, it.user_id, it.kind, it.item_id) == (
        "t9", "wasifyai-image", "u9", "image", "img-1",
    )  # fmt: skip
    assert model == "m1"


# ---- Capabilities.index_creation never fails a run ----------------------------------------


async def test_index_creation_is_best_effort(tmp_path):
    from wasifyai_platform_sdk import ProviderDeps, build_capabilities, load_product_config

    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "product.yaml").write_text("id: p\ncapabilities: {}\n")
    caps = build_capabilities(
        load_product_config(tmp_path, "p", environ={}), ProviderDeps(tmp_path)
    )
    await caps.index_creation("song", "x", "words")  # no indexer: nothing happens

    calls = []

    class Indexer:
        async def index(self, kind, item_id, text):
            calls.append((kind, item_id, text))
            if text == "boom":
                raise ConnectionError("down")

    caps.indexer = Indexer()
    await caps.index_creation("song", "a", "words")
    await caps.index_creation("song", "b", "   ")  # nothing to index
    await caps.index_creation("song", "c", "boom")  # raises inside: swallowed
    assert calls == [("song", "a", "words"), ("song", "c", "boom")]


# ---- the background indexer ---------------------------------------------------------------


class Source:
    def __init__(self, product: str, kind: str, items: list[IndexItem]):
        self.product_id, self.kind = product, kind
        self.items = sorted(items, key=lambda i: i.item_id)

    async def page(self, after, limit):
        return [i for i in self.items if after is None or i.item_id > after][:limit]

    async def present(self, item_ids):
        return {i.item_id for i in self.items} & set(item_ids)


async def test_reconcile_backfills_missing_items_within_a_budget_and_finishes_later():
    store = InMemoryIndexStore()
    index = make_index(store)
    src = Source("wasifyai-music", "song", [item(n, f"song number {n}") for n in range(5)])
    first = await index.reconcile([src], budget=3)
    assert first == {"embedded": 3, "removed": 0} and len(store.rows) == 3
    second = await index.reconcile([src], budget=3)
    assert second == {"embedded": 2, "removed": 0} and len(store.rows) == 5
    assert await index.reconcile([src]) == {"embedded": 0, "removed": 0}  # nothing left to do


async def test_reconcile_removes_rows_whose_item_is_gone_and_skips_other_products():
    store = InMemoryIndexStore()
    index = make_index(store)
    await fill(
        index,
        item(1, "kept"),
        item(2, "deleted"),
        item(9, "other", product="wasifyai-image", kind="image"),
    )
    src = Source("wasifyai-music", "song", [item(1, "kept")])
    assert await index.reconcile([src]) == {"embedded": 0, "removed": 1}
    assert sorted(k[2] for k in store.rows) == ["id-1", "id-9"]


async def test_reconcile_re_embeds_what_another_embedder_made():
    store = InMemoryIndexStore()
    await fill(make_index(store, model="old"), item(1, "words"))
    report = await make_index(store, model="new").reconcile(
        [Source("wasifyai-music", "song", [item(1, "words")])]
    )
    assert report["embedded"] == 1 and next(iter(store.rows.values()))[1] == "new"


async def test_reconcile_stops_quietly_when_the_embedder_is_down():
    async def broken(texts):
        raise ConnectionError("down")

    index = make_index(embed=broken)
    src = Source("wasifyai-music", "song", [item(n, "x y") for n in range(3)])
    assert await index.reconcile([src]) == {"embedded": 0, "removed": 0}


# ---- the route ----------------------------------------------------------------------------


def token(sub="google:1", email="ann@example.com"):
    now = int(time.time())
    claims = {
        "iss": "wasifyai-web", "aud": "wasifyai-api", "iat": now, "exp": now + 300,
        "sub": sub, "email": email, "email_verified": True,
    }  # fmt: skip
    return {"authorization": "Bearer " + jwt.encode(claims, SECRET, algorithm="HS256")}


@pytest.fixture
def search_app(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_MODE", "stub")
    get_settings.cache_clear()
    (tmp_path / "hello").mkdir()
    (tmp_path / "hello" / "product.yaml").write_text(
        "id: hello\ncapabilities:\n  text.chat: { provider: fake, defaults: { reply: hi } }\n"
    )
    store = InMemoryIndexStore()
    usage = InMemoryUsageRecorder()
    app = mem_app(
        hello_registry(), tmp_path, usage, search_limiter=InMemoryUploadLimiter(4),
        creation_embedder=fake_embed, index_store=store,
    )  # fmt: skip
    with TestClient(app) as client:
        client.index = app.state.creation_index  # type: ignore[attr-defined]
        client.usage = usage  # type: ignore[attr-defined]
        yield client
    monkeypatch.undo()
    get_settings.cache_clear()


async def put(client, *items):
    for it in items:
        await client.index.index_item(it)  # type: ignore[attr-defined]


def test_the_route_returns_ranked_references_and_counts_the_search(search_app):
    import asyncio

    asyncio.run(
        put(
            search_app,
            item(1, "rain in madrid a sad song", user="dev-user", tenant="dev-tenant"),
            item(
                2,
                "fox in snow",
                user="dev-user",
                tenant="dev-tenant",
                kind="image",
                product="wasifyai-image",
            ),
            item(3, "rain in madrid", user="someone-else", tenant="dev-tenant"),
        )
    )
    r = search_app.get("/creations/search", params={"q": "rain madrid"})
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "rain madrid" and body["degraded"] is False
    assert [(h["kind"], h["product_id"], h["id"], h["match"]) for h in body["results"]] == [
        ("song", "wasifyai-music", "id-1", "words")
    ]  # someone else's creation is never in the results
    only_images = search_app.get(
        "/creations/search", params={"q": "fox snow", "kind": "image"}
    ).json()
    assert [h["id"] for h in only_images["results"]] == ["id-2"]
    events = [e for e in search_app.usage.events if e.kind == "creation.searched"]
    assert len(events) == 2 and events[0].quantity == 1 and events[0].product_id == "platform"


def test_the_route_validates_and_limits(search_app):
    assert search_app.get("/creations/search").status_code == 422
    assert search_app.get("/creations/search", params={"q": " a "}).status_code == 422
    assert search_app.get("/creations/search", params={"q": "龙"}).status_code == 200
    assert search_app.get("/creations/search", params={"q": "x" * 201}).status_code == 422
    assert (
        search_app.get("/creations/search", params={"q": "ab", "kind": "music"}).status_code == 422
    )
    assert search_app.get("/creations/search", params={"q": "ab", "limit": 51}).status_code == 422
    codes = [search_app.get("/creations/search", params={"q": "fox"}).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_searching_needs_a_signed_in_user(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("API_AUTH_SECRET", SECRET)
    get_settings.cache_clear()
    (tmp_path / "hello").mkdir()
    (tmp_path / "hello" / "product.yaml").write_text(
        "id: hello\ncapabilities:\n  text.chat: { provider: fake, defaults: { reply: hi } }\n"
    )
    try:
        app = mem_app(
            hello_registry(),
            tmp_path,
            InMemoryUsageRecorder(),
            users=InMemoryUserStore(),
            admin_store=InMemoryAdminStore(),
            creation_embedder=fake_embed,
        )
        with TestClient(app) as c:
            assert c.get("/creations/search", params={"q": "fox"}).status_code == 401
            assert (
                c.get("/creations/search", params={"q": "fox"}, headers=token()).status_code == 200
            )
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_indexed_text_runs_together_as_sentences():
    from wasifyai_platform_sdk import search_text

    assert search_text("Lluvia", "pop.", "walking\nhome\n\nin the rain") == (
        "Lluvia. pop. walking home in the rain"
    )
    assert search_text("  A fox ", None, "  ", "...") == "A fox"
    assert len(search_text("word " * 5000)) == 6000
