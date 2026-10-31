"""Motion graphics' rows on real Postgres (ADR-0087, P4): the same store as the desktop's, the same
SQL."""

from uuid import uuid4

import pytest
from wasifyai_video.builder.store import BuilderStore, NotFound, NothingToUndo


@pytest.fixture
def store(engine):
    from wasifyai_api.config import get_settings

    s = BuilderStore.on_postgres(get_settings().database_url, schema="builder_t_" + uuid4().hex[:8])
    yield s
    s.drop_schema()
    s.close()


async def test_compositions_renders_and_versions_work_per_person_on_postgres(store):
    a = store.add_composition("t1", "u1", title="One", template="title", slots={"title": "One"})
    store.add_composition("t1", "u2", title="Two", template="title", slots={"title": "Two"})
    assert [c["title"] for c in store.list_compositions("t1", "u1")] == ["One"]
    with pytest.raises(NotFound):
        store.get_composition("t1", "u2", a["id"])
    store.update_composition("t1", "u1", a["id"], title="One!", slots={"title": "One!"})
    assert store.version_count(a["id"]) == 1
    assert store.undo_composition("t1", "u1", a["id"])["title"] == "One"
    with pytest.raises(NothingToUndo):
        store.undo_composition("t1", "u1", a["id"])
    r = store.add_render("t1", "u1", a["id"], {"fps": 30})
    store.set_progress(r["id"], 0.5)
    store.set_check(r["id"], {"ok": True, "checked": 2, "problems": [], "message": "Checked."})
    store.finish_render(r["id"], "done", video_id="v1", elapsed_s=3.2, peak_mb=700)
    row = store.get_render("t1", "u1", r["id"])
    assert row["progress"] == 1 and row["check"]["ok"] is True and row["status"] == "done"
    gone = store.delete_composition("t1", "u1", a["id"])
    assert [g["video_id"] for g in gone] == ["v1"]


async def test_a_render_left_working_is_failed_by_the_sweep_not_by_opening_the_store(store):
    a = store.add_composition("t1", "u1", title="One", template="title", slots={})
    r = store.add_render("t1", "u1", a["id"], {})
    assert store.fail_stale("0000-01-01", "stopped") == 0  # newer than the cut: still working
    assert store.fail_stale("9999-01-01", "stopped") == 1
    assert store.get_render("t1", "u1", r["id"])["status"] == "failed"


async def test_a_template_project_becomes_scenes_and_undo_turns_it_back_on_postgres(store):
    a = store.add_composition("t1", "u1", title="One", template="title", slots={"title": "One"})
    doc = {"shape": "landscape", "font": "sans", "name": "", "seconds": 5, "scenes": []}
    now = store.update_composition("t1", "u1", a["id"], title="One", slots=doc, template="scenes")
    assert now["template"] == "scenes" and now["slots"] == doc
    back = store.undo_composition("t1", "u1", a["id"])
    assert back["template"] == "title" and back["slots"] == {"title": "One"}


async def test_tables_from_before_scenes_are_upgraded_on_postgres(store):
    from wasifyai_api.config import get_settings
    from wasifyai_video.builder.store import BuilderStore

    a = store.add_composition("t1", "u1", title="One", template="quote", slots={"quote": "One"})
    store.update_composition("t1", "u1", a["id"], title="Two", slots={"quote": "Two"})
    with store.db.transaction() as conn:
        conn.execute("ALTER TABLE versions DROP COLUMN template")
        conn.execute("ALTER TABLE compositions DROP COLUMN conversation_id")
        conn.execute("UPDATE meta SET value = '2' WHERE key = 'schema'")
    again = BuilderStore.on_postgres(get_settings().database_url, schema=store.schema)
    try:
        assert again.undo_composition("t1", "u1", a["id"])["template"] == "quote"
    finally:
        again.close()
