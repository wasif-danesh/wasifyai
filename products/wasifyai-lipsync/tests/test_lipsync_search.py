"""Videos are searchable (ADR-0041): what is indexed, indexing on save, removal on delete, and the
`ids=` list filter."""

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from lipsync_rig import make_rig, put_image
from test_lipsync_graph import SCRIPT, Story
from test_lipsync_routes import identity, video
from wasifyai_lipsync.index import LipSyncIndexSource, index_text
from wasifyai_lipsync.lipsyncs import InMemoryLipSyncStore
from wasifyai_lipsync.routes import build_routes
from wasifyai_platform_sdk import RouteDeps, ScopedStorage, memory_storage


class Recorder:
    def __init__(self):
        self.calls: list[tuple[str, str, str]] = []

    async def index(self, kind, item_id, text):
        self.calls.append((kind, item_id, text))


def test_a_lip_sync_is_found_by_what_is_said_and_its_style():
    assert index_text("  Hello there  ", "", " calm ") == "Hello there calm"
    # an uploaded voice has no script: its words are the transcript
    assert index_text("", "good morning", "") == "good morning"
    assert index_text("typed", "heard", "") == "typed"


def test_the_product_registers_an_index_source():
    from wasifyai_lipsync import register
    from wasifyai_platform_sdk import GraphRegistry

    registry = GraphRegistry()
    register(registry)
    assert registry.index_sources() == {"wasifyai-lipsync": LipSyncIndexSource}
    assert (LipSyncIndexSource.product_id, LipSyncIndexSource.kind) == (
        "wasifyai-lipsync",
        "lipsync",
    )


async def test_a_finished_clip_is_indexed_but_a_failed_one_is_not(tmp_path, ctx):
    rig = make_rig(tmp_path)
    recorder = Recorder()
    rig.caps.indexer = recorder
    s = await Story(rig).start({**SCRIPT, "image_key": (await put_image(rig)).key, "style": "calm"})
    await s.speech()
    await s.clip()
    assert recorder.calls == [("lipsync", s.state["lipsync_id"], f"{SCRIPT['script']} calm")]

    rig2 = make_rig(tmp_path / "b")
    recorder2 = Recorder()
    rig2.caps.indexer = recorder2
    s2 = await Story(rig2).start({**SCRIPT, "image_key": (await put_image(rig2)).key})
    try:
        await s2.speech(status="failed")
    except Exception:
        pass
    assert recorder2.calls == []


def uid(n):
    return f"00000000-0000-0000-0000-{n:012d}"


def make_client(removed):
    store = InMemoryLipSyncStore()
    working = video(3, status="working", created_at=datetime.now(UTC) - timedelta(minutes=1))
    store.videos = [video(1), video(2), working, video(5, user="someone-else")]
    app = FastAPI()
    app.state.storage = ScopedStorage(memory_storage())

    class Index:
        async def remove(self, tenant_id, product_id, item_id):
            removed.append((tenant_id, product_id, item_id))

    app.state.creation_index = Index()
    app.include_router(
        build_routes(RouteDeps(app.state, identity), store), prefix="/products/wasifyai-lipsync"
    )
    return TestClient(app)


def test_the_list_can_be_asked_for_these_clips_in_this_order():
    c = make_client([])
    got = c.get("/products/wasifyai-lipsync/lipsyncs", params={"ids": f"{uid(2)},{uid(1)}"}).json()
    assert [v["id"] for v in got["lipsyncs"]] == [uid(2), uid(1)] and got["next_before"] is None
    got = c.get("/products/wasifyai-lipsync/lipsyncs", params={"ids": f"{uid(5)},{uid(1)}"}).json()
    assert [v["id"] for v in got["lipsyncs"]] == [uid(1)]
    assert c.get("/products/wasifyai-lipsync/lipsyncs", params={"ids": "nope"}).status_code == 422


def test_deleting_a_clip_takes_it_out_of_search_and_a_working_clip_cannot_be_deleted():
    removed: list = []
    c = make_client(removed)
    assert c.delete(f"/products/wasifyai-lipsync/lipsyncs/{uid(1)}").status_code == 204
    assert removed == [("t1", "wasifyai-lipsync", uid(1))]
    assert c.delete(f"/products/wasifyai-lipsync/lipsyncs/{uid(3)}").status_code == 409
    assert len(removed) == 1
