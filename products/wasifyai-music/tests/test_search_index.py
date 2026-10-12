"""Songs are searchable (ADR-0041): what is indexed, indexing on save, the `ids=` list filter."""

from conftest import make_rig
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_routes import identity, song
from test_song_graph import Story
from wasifyai_music.index import SongIndexSource, index_text
from wasifyai_music.routes import build_routes
from wasifyai_music.songs import InMemorySongStore
from wasifyai_platform_sdk import RouteDeps, ScopedStorage, memory_storage


class Recorder:
    def __init__(self):
        self.calls: list[tuple[str, str, str]] = []

    async def index(self, kind, item_id, text):
        self.calls.append((kind, item_id, text))


def test_a_song_is_found_by_its_title_style_and_lyrics_without_the_section_tags():
    text = index_text(
        "Rain in Madrid", "pop, mellow", "[verse]\nwalking home\n\n[chorus]\nin the rain"
    )
    assert text.startswith("Rain in Madrid. pop, mellow. ")
    assert "walking home" in text and "in the rain" in text and "\n" not in text
    assert "[verse]" not in text and "[chorus]" not in text
    assert len(index_text("t", "s", "word " * 5000)) <= 6000


def test_the_product_registers_an_index_source():
    from wasifyai_music import register
    from wasifyai_platform_sdk import GraphRegistry

    registry = GraphRegistry()
    register(registry)
    assert registry.index_sources() == {"wasifyai-music": SongIndexSource}
    assert (SongIndexSource.product_id, SongIndexSource.kind) == ("wasifyai-music", "song")


async def test_a_finished_song_is_indexed(tmp_path, ctx):
    rig = make_rig(tmp_path)
    recorder = Recorder()
    rig.caps.indexer = recorder
    s = await (await Story(rig).to_approval()).approve()
    await s.finish_job("audio", "mp3")
    await s.finish_job("image", "png")
    ((kind, item_id, text),) = recorder.calls
    assert kind == "song" and item_id == s.state["song_id"]
    assert "Sing It Out Loud" in text and "[verse]" not in text


def test_the_list_can_be_asked_for_these_songs_in_this_order():
    store = InMemorySongStore()
    store.songs = [song(1), song(2), song(3), song(5, user="someone-else")]
    app = FastAPI()
    app.state.storage = ScopedStorage(memory_storage())
    app.include_router(
        build_routes(RouteDeps(app.state, identity), store), prefix="/products/wasifyai-music"
    )
    c = TestClient(app)
    one, two, three, theirs = (f"00000000-0000-0000-0000-{n:012d}" for n in (1, 2, 3, 5))
    got = c.get("/products/wasifyai-music/songs", params={"ids": f"{three},{one}"}).json()
    assert [s["id"] for s in got["songs"]] == [three, one] and got["next_before"] is None
    # someone else's song, and a song that does not exist, are simply not there
    got = c.get(
        "/products/wasifyai-music/songs",
        params={"ids": f"{theirs},{two},{'9' * 8}-0000-0000-0000-000000000000"},
    ).json()
    assert [s["id"] for s in got["songs"]] == [two]
    assert c.get("/products/wasifyai-music/songs", params={"ids": "nope"}).status_code == 422
    too_many = ",".join(f"00000000-0000-0000-0000-{n:012d}" for n in range(51))
    assert c.get("/products/wasifyai-music/songs", params={"ids": too_many}).status_code == 422
