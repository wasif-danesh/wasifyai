"""Rules every IndexStore must follow (ADR-0041); run against memory, SQLite and Postgres."""

from wasifyai_platform_sdk import IndexItem


def item(tenant: str, user: str, item_id: str, words: str, kind="image", product="p-img"):
    return IndexItem(tenant, product, user, kind, item_id, words)


async def check_contract(store, tenant: str) -> None:
    a = item(tenant, "u1", "a", "a red teapot on a wooden table")
    b = item(tenant, "u1", "b", "a blue Teapot, 100% glazed_ceramic", kind="song", product="p-song")
    other = item(tenant, "u2", "c", "a red teapot for another user")
    await store.upsert(a, "m1", [1.0, 0.0])
    await store.upsert(b, "m1", [0.0, 1.0])
    await store.upsert(other, "m1", [1.0, 0.0])

    # meaning: nearest first, only this user's rows, optionally one kind
    hits = await store.nearest(tenant, "u1", [0.9, 0.1], None, 10)
    assert [h.item_id for h in hits] == ["a", "b"] and hits[0].match == "meaning"
    assert hits[0].score > hits[1].score
    assert [h.item_id for h in await store.nearest(tenant, "u1", [0.9, 0.1], "song", 10)] == ["b"]
    assert len(await store.nearest(tenant, "u1", [0.9, 0.1], None, 1)) == 1
    assert await store.nearest(tenant + "-x", "u1", [1.0, 0.0], None, 10) == []

    # words: every word, any case, in any order; LIKE characters are literal
    assert {h.item_id for h in await store.with_words(tenant, "u1", ["teapot"], None, 10)} == {
        "a",
        "b",
    }
    assert [
        h.item_id for h in await store.with_words(tenant, "u1", ["red", "table"], None, 10)
    ] == ["a"]
    assert [h.item_id for h in await store.with_words(tenant, "u1", ["100%"], None, 10)] == ["b"]
    assert [h.item_id for h in await store.with_words(tenant, "u1", ["%"], None, 10)] == ["b"]
    assert [
        h.item_id for h in await store.with_words(tenant, "u1", ["glazed_ceramic"], None, 10)
    ] == ["b"]
    assert await store.with_words(tenant, "u1", ["glazedXceramic"], None, 10) == []
    assert [h.item_id for h in await store.with_words(tenant, "u1", ["teapot"], "song", 10)] == [
        "b"
    ]
    assert await store.with_words(tenant, "u1", [], None, 10) == []
    assert all(h.match == "words" and h.score == 1.0 for h in
               await store.with_words(tenant, "u1", ["teapot"], None, 10))  # fmt: skip

    # the same item again replaces the row (and records the model that made it)
    await store.upsert(item(tenant, "u1", "a", "a green frog"), "m2", [0.0, 1.0])
    assert [h.item_id for h in await store.with_words(tenant, "u1", ["frog"], None, 10)] == ["a"]
    assert await store.with_words(tenant, "u1", ["wooden"], None, 10) == []
    assert await store.models("p-img", ["a", "zzz"]) == {"a": "m2"}
    assert await store.models("p-img", []) == {}

    # paging through ids, for the reconciler
    assert await store.ids_after("p-img", None, 10) == ["a", "c"]
    assert await store.ids_after("p-img", "a", 10) == ["c"]
    assert await store.ids_after("p-img", None, 1) == ["a"]

    # removal
    await store.delete(tenant, "p-img", "a")
    assert "a" not in {h.item_id for h in await store.nearest(tenant, "u1", [0.0, 1.0], None, 10)}
    await store.delete_ids("p-img", ["c", "nope"])
    assert await store.ids_after("p-img", None, 10) == []
    await store.delete_ids("p-img", [])
