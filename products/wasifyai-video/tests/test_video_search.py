"""Videos are searchable (ADR-0041): what is indexed, indexing on save, removal on delete, and the
`ids=` list filter."""

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_video_graph import Story
from test_video_routes import identity, video
from video_rig import make_rig
from wasifyai_platform_sdk import RouteDeps, ScopedStorage, memory_storage
from wasifyai_video.index import VideoIndexSource, index_text, video_index_source
from wasifyai_video.routes import build_routes
from wasifyai_video.videos import InMemoryVideoStore


class Recorder:
    def __init__(self):
        self.calls: list[tuple[str, str, str]] = []

    async def index(self, kind, item_id, text):
        self.calls.append((kind, item_id, text))


def test_a_clip_is_found_by_its_prompt():
    assert index_text("  A fox walks through snow  ") == "A fox walks through snow"


def test_the_product_registers_an_index_source():
    from wasifyai_platform_sdk import GraphRegistry
    from wasifyai_video import register

    registry = GraphRegistry()
    register(registry)
    assert registry.index_sources() == {"wasifyai-video": video_index_source}
    assert (VideoIndexSource.product_id, VideoIndexSource.kind) == ("wasifyai-video", "video")


async def test_a_finished_clip_is_indexed_but_a_failed_one_is_not(tmp_path, ctx):
    rig = make_rig(tmp_path)
    recorder = Recorder()
    rig.caps.indexer = recorder
    s = await Story(rig).start({"mode": "text", "prompt": "a red fox in the snow"})
    await s.finish_job()
    assert recorder.calls == [("video", s.state["video_id"], "a red fox in the snow")]

    rig2 = make_rig(tmp_path / "b")
    recorder2 = Recorder()
    rig2.caps.indexer = recorder2
    s2 = await Story(rig2).start({"mode": "text", "prompt": "a fox"})
    try:
        await s2.finish_job("failed")
    except Exception:
        pass
    assert recorder2.calls == []


def uid(n):
    return f"00000000-0000-0000-0000-{n:012d}"


def make_client(removed):
    store = InMemoryVideoStore()
    working = video(3, status="working", created_at=datetime.now(UTC) - timedelta(minutes=1))
    store.videos = [video(1), video(2), working, video(5, user="someone-else")]
    app = FastAPI()
    app.state.storage = ScopedStorage(memory_storage())

    class Index:
        async def remove(self, tenant_id, product_id, item_id):
            removed.append((tenant_id, product_id, item_id))

    app.state.creation_index = Index()
    app.include_router(
        build_routes(RouteDeps(app.state, identity), store), prefix="/products/wasifyai-video"
    )
    return TestClient(app)


def test_the_list_can_be_asked_for_these_clips_in_this_order():
    c = make_client([])
    got = c.get("/products/wasifyai-video/videos", params={"ids": f"{uid(2)},{uid(1)}"}).json()
    assert [v["id"] for v in got["videos"]] == [uid(2), uid(1)] and got["next_before"] is None
    got = c.get("/products/wasifyai-video/videos", params={"ids": f"{uid(5)},{uid(1)}"}).json()
    assert [v["id"] for v in got["videos"]] == [uid(1)]
    assert c.get("/products/wasifyai-video/videos", params={"ids": "nope"}).status_code == 422


def test_deleting_a_clip_takes_it_out_of_search_and_a_working_clip_cannot_be_deleted():
    removed: list = []
    c = make_client(removed)
    assert c.delete(f"/products/wasifyai-video/videos/{uid(1)}").status_code == 204
    assert removed == [("t1", "wasifyai-video", uid(1))]
    assert c.delete(f"/products/wasifyai-video/videos/{uid(3)}").status_code == 409
    assert len(removed) == 1
