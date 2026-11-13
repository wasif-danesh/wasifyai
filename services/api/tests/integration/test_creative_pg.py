"""Creative Studio's projects on real Postgres (ADR-0090, the web): the same store as the
desktop's, the same SQL, and the projects found by My creations search through the `creative`
schema."""

from uuid import uuid4

import pytest
from wasifyai_creative.index import CreativeIndexSource
from wasifyai_creative.store import CreativeStore, NotFound

BRIEF = {
    "track_id": "t",
    "idea": "A drive to the sea",
    "cast": [{"name": "Mira", "look": "red hair"}],
}


@pytest.fixture
def store(engine):
    from wasifyai_api.config import get_settings

    s = CreativeStore.on_postgres(
        get_settings().database_url, schema="creative_t_" + uuid4().hex[:8]
    )
    yield s
    s.drop_schema()
    s.close()


async def test_projects_plans_takes_and_cuts_work_per_person_on_postgres(store):
    a = store.add("t1", "u1", "One", BRIEF)
    store.add("t1", "u2", "Two", BRIEF)
    assert [p["title"] for p in store.list_projects("t1", "u1")] == ["One"]
    with pytest.raises(NotFound):
        store.get("t1", "u2", a["id"])
    store.begin(a["id"], "Finding the beats")
    store.keep_checkpoint(a["id"], "say-1", {"speech_id": "s1"})
    store.keep_checkpoint(a["id"], "part-1", {"shots": []})
    store.add_log(a["id"], "part-1", "asked", "said")
    assert store.save_plan(a["id"], {"shots": [{"id": "s1"}]}, "The plan was written") == 1
    store.clear_checkpoints(a["id"], ("say-",))
    assert set(store.checkpoints(a["id"])) == {"say-1"}  # the narration is kept
    store.drop_checkpoints(a["id"], "say-")
    assert store.checkpoints(a["id"]) == {}
    store.finish(a["id"], "planned", None, 3.5)
    row = store.get("t1", "u1", a["id"])
    assert (
        row["status"] == "planned"
        and row["plan"]["shots"][0]["id"] == "s1"
        and row["elapsed_s"] == 3.5
    )
    store.add_media(a["id"], "image", "i1", "s1", made=True)
    take = store.add_take(a["id"], "s1", "lipsync", "c1", "x|0-2", "", "sing", 2.0, 1, choose=False)
    assert store.chosen_of(a["id"]) == {"s1": take}
    store.save_cut(a["id"], {"items": [], "titles": []}, "The first cut")
    assert store.cut_of(a["id"])["cut"]["items"] == []
    store.keep_characters(
        "t1", "u1", [{"name": "Mira", "look": "red hair", "pictures": [], "photos_only": False}]
    )
    assert [c["name"] for c in store.characters("t1", "u1")] == ["Mira"]
    assert store.delete("t1", "u1", a["id"])


async def test_work_a_gone_replica_left_going_is_interrupted_by_the_sweep_not_by_opening(store):
    a = store.add("t1", "u1", "One", BRIEF)
    store.begin(a["id"], "Writing")
    store.begin_run(a["id"], "stills", "Making stills", 4)
    assert store.fail_stale("0000-01-01") == 0  # newer than the cut: still working
    assert store.fail_stale("9999-01-01") == 2
    assert store.get("t1", "u1", a["id"])["status"] == "interrupted"
    assert store.run_of(a["id"])["status"] == "interrupted"


async def test_projects_are_found_by_search_from_the_creative_schema(engine):
    from wasifyai_api.config import get_settings

    store = CreativeStore.on_postgres(get_settings().database_url)  # the schema the web uses
    tenant = "it-" + uuid4().hex[:8]
    try:
        a = store.add(
            tenant, "u1", "The Key and the Clock", {**BRIEF, "idea": "Opening grandmother's house"}
        )
        source = CreativeIndexSource(engine)
        found = [i for i in await source.page(None, 1000) if i.tenant_id == tenant]
        assert len(found) == 1 and "grandmother" in found[0].text.lower()
        assert await source.present([a["id"], "gone"]) == {a["id"]}
    finally:
        for p in store.list_projects(tenant, "u1"):
            store.delete(tenant, "u1", p["id"])
        store.close()
