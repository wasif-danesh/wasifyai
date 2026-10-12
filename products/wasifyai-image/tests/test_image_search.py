"""Images are searchable (ADR-0041): what is indexed, indexing on save, removal on delete, and the
`ids=` list filter."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from image_rig import make_rig
from test_image_graph import Story
from test_image_routes import identity, image
from wasifyai_image.images import InMemoryImageStore
from wasifyai_image.index import ImageIndexSource, index_text
from wasifyai_image.routes import build_routes
from wasifyai_platform_sdk import RouteDeps, ScopedStorage, memory_storage


class Recorder:
    def __init__(self):
        self.calls: list[tuple[str, str, str]] = []

    async def index(self, kind, item_id, text):
        self.calls.append((kind, item_id, text))


def test_an_image_is_found_by_its_prompt():
    assert index_text("  A red fox in the snow  ") == "A red fox in the snow"
    assert len(index_text("word " * 5000)) <= 6000


def test_the_product_registers_an_index_source():
    from wasifyai_image import register
    from wasifyai_platform_sdk import GraphRegistry

    registry = GraphRegistry()
    register(registry)
    assert registry.index_sources() == {"wasifyai-image": ImageIndexSource}
    assert (ImageIndexSource.product_id, ImageIndexSource.kind) == ("wasifyai-image", "image")


async def test_a_finished_image_is_indexed(tmp_path, ctx):
    rig = make_rig(tmp_path)
    recorder = Recorder()
    rig.caps.indexer = recorder
    s = await Story(rig).start({"mode": "text", "prompt": "a red fox in the snow"})
    await s.finish_job()
    assert recorder.calls == [("image", s.state["image_id"], "a red fox in the snow")]


def make_client(removed):
    store = InMemoryImageStore()
    store.images = [image(1), image(2), image(3), image(5, user="someone-else")]
    app = FastAPI()
    app.state.storage = ScopedStorage(memory_storage())

    class Index:
        async def remove(self, tenant_id, product_id, item_id):
            removed.append((tenant_id, product_id, item_id))

    app.state.creation_index = Index()
    app.include_router(
        build_routes(RouteDeps(app.state, identity), store), prefix="/products/wasifyai-image"
    )
    return TestClient(app)


def uid(n):
    return f"00000000-0000-0000-0000-{n:012d}"


def test_the_list_can_be_asked_for_these_images_in_this_order():
    c = make_client([])
    got = c.get("/products/wasifyai-image/images", params={"ids": f"{uid(3)},{uid(1)}"}).json()
    assert [i["id"] for i in got["images"]] == [uid(3), uid(1)] and got["next_before"] is None
    got = c.get("/products/wasifyai-image/images", params={"ids": f"{uid(5)},{uid(2)}"}).json()
    assert [i["id"] for i in got["images"]] == [uid(2)]  # someone else's is not there
    assert c.get("/products/wasifyai-image/images", params={"ids": "nope"}).status_code == 422


def test_deleting_an_image_takes_it_out_of_search():
    removed: list = []
    c = make_client(removed)
    assert c.delete(f"/products/wasifyai-image/images/{uid(1)}").status_code == 204
    assert removed == [("t1", "wasifyai-image", uid(1))]
    assert c.delete(f"/products/wasifyai-image/images/{uid(5)}").status_code == 404
    assert len(removed) == 1  # a refused delete removes nothing from search
