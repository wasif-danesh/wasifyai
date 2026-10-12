from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from media_samples import FAKE_FRAMES, png
from wasifyai_music.routes import build_routes
from wasifyai_music.songs import InMemorySongStore, SongRecord
from wasifyai_platform_sdk import Identity, RouteDeps, ScopedStorage, memory_storage

T0 = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def identity(x_user: str = Header("u1"), x_tenant: str = Header("t1")) -> Identity:
    return Identity(tenant_id=x_tenant, user_id=x_user)


def song(n: int, user="u1", tenant="t1", cover=True) -> SongRecord:
    return SongRecord(
        id=f"00000000-0000-0000-0000-{n:012d}", tenant_id=tenant, product_id="wasifyai-music",
        user_id=user,
        thread_id=None, run_id=None, title=f"Song {n}", lyrics=f"[verse]\nlyrics {n}", style="pop",
        audio_key=f"s{n}/audio.mp3", cover_key=f"s{n}/cover.png" if cover else None,
        created_at=T0 + timedelta(minutes=n),
    )  # fmt: skip


@pytest.fixture
def client():
    store = InMemorySongStore()
    store.songs = [
        song(1), song(2, cover=False), song(3), song(4),
        song(5, user="someone-else"), song(6, tenant="other-tenant"),
    ]  # fmt: skip
    app = FastAPI()
    app.state.storage = ScopedStorage(memory_storage())
    app.include_router(
        build_routes(RouteDeps(app.state, identity), store), prefix="/products/wasifyai-music"
    )
    return TestClient(app)


def test_lists_only_my_songs_newest_first_with_fresh_links(client):
    page = client.get("/products/wasifyai-music/songs").json()
    assert [s["title"] for s in page["songs"]] == ["Song 4", "Song 3", "Song 2", "Song 1"]
    first = page["songs"][0]
    assert first["audio_url"].endswith(
        "t1/wasifyai-music/u1/s4/audio.mp3"
    )  # signed for this user's prefix
    assert first["cover_url"].endswith("s4/cover.png") and "lyrics" not in first
    assert page["songs"][2]["cover_url"] is None  # the cover job failed for song 2
    assert page["next_before"] is None


def test_pagination_walks_the_whole_list_once(client):
    seen, before = [], None
    for _ in range(5):
        params = {"limit": 3, **({"before": before} if before else {})}
        page = client.get("/products/wasifyai-music/songs", params=params).json()
        seen += [s["title"] for s in page["songs"]]
        before = page["next_before"]
        if before is None:
            break
    assert seen == ["Song 4", "Song 3", "Song 2", "Song 1"]


@pytest.mark.parametrize("limit", [0, 51, "x"])
def test_limit_is_validated(client, limit):
    assert client.get("/products/wasifyai-music/songs", params={"limit": limit}).status_code == 422


def test_detail_includes_the_lyrics(client):
    s = client.get("/products/wasifyai-music/songs/00000000-0000-0000-0000-000000000003").json()
    assert s["lyrics"] == "[verse]\nlyrics 3" and s["audio_url"] and s["title"] == "Song 3"


@pytest.mark.parametrize(
    "song_id",
    [
        "00000000-0000-0000-0000-000000000005",
        "00000000-0000-0000-0000-000000000006",
        "nope",
        "../x",
    ],
)
def test_other_users_other_tenants_and_junk_ids_are_all_just_404(client, song_id):
    # someone else's song, another tenant's song, and nonsense look identical: no existence leak
    assert client.get(f"/products/wasifyai-music/songs/{song_id}").status_code == 404


def test_each_user_sees_only_their_own(client):
    other = client.get("/products/wasifyai-music/songs", headers={"x-user": "someone-else"}).json()
    assert [s["title"] for s in other["songs"]] == ["Song 5"]


# ---- downloads ----------------------------------------------------------------------------

AUDIO, COVER = FAKE_FRAMES, png()
ID1 = "00000000-0000-0000-0000-000000000001"
BASE = "/products/wasifyai-music/songs"


def stored(client, rel: str, data: bytes, ctype: str):
    """Put bytes where the routes will look: under the owner's prefix."""
    import asyncio

    from wasifyai_platform_sdk import RunContext, reset_context, set_context

    async def put():
        token = set_context(RunContext("t1", "wasifyai-music", "u1"))
        try:
            await client.app.state.storage.put(rel, data, ctype)
        finally:
            reset_context(token)

    asyncio.run(put())


@pytest.fixture
def files(client):
    stored(client, "s1/audio.mp3", AUDIO, "audio/mpeg")
    stored(client, "s1/cover.png", COVER, "image/png")
    return client


def tag_frames(mp3: bytes) -> dict[str, bytes]:
    from test_id3 import frames_of

    return frames_of(mp3)


def test_audio_downloads_with_its_cover_and_lyrics_inside(files):
    r = files.get(f"{BASE}/{ID1}/download/audio")
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.headers["content-disposition"] == 'attachment; filename="song-1.mp3"'
    assert r.headers["cache-control"] == "private, no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    frames = tag_frames(r.content)
    assert {"TIT2", "TPE1", "TALB", "USLT", "COMM", "APIC"} <= set(frames)
    assert frames["TIT2"][3:].decode("utf-16-le") == "Song 1"
    assert frames["APIC"].startswith(b"\x00image/jpeg\x00\x03\x00\xff\xd8")  # a small JPEG
    assert r.content.endswith(AUDIO)  # the audio itself is untouched


def test_audio_without_a_cover_still_carries_its_tag(files):
    stored(files, "s2/audio.mp3", AUDIO, "audio/mpeg")  # song 2 has no cover
    r = files.get(f"{BASE}/00000000-0000-0000-0000-000000000002/download/audio")
    assert r.status_code == 200 and "APIC" not in tag_frames(r.content)
    assert tag_frames(r.content)["TIT2"][3:].decode("utf-16-le") == "Song 2"


def test_a_cover_that_cannot_be_read_does_not_stop_the_audio(client):
    stored(client, "s1/audio.mp3", AUDIO, "audio/mpeg")
    stored(client, "s1/cover.png", b"not an image", "image/png")
    r = client.get(f"{BASE}/{ID1}/download/audio")
    assert r.status_code == 200 and r.content == AUDIO  # served plain


def test_the_cover_downloads_as_it_was_stored(files):
    r = files.get(f"{BASE}/{ID1}/download/cover")
    assert r.status_code == 200 and r.content == COVER
    assert r.headers["content-type"] == "image/png"
    assert r.headers["content-disposition"] == 'attachment; filename="song-1.png"'


@pytest.mark.parametrize(
    "path",
    [
        "00000000-0000-0000-0000-000000000002/download/cover",  # this song has no cover
        "00000000-0000-0000-0000-000000000002/download/video",  # nor a video, which needs one
        "00000000-0000-0000-0000-000000000005/download/audio",  # someone else's song
        "00000000-0000-0000-0000-000000000006/download/video",  # another tenant's song
        "00000000-0000-0000-0000-000000000003/download/audio",  # a song whose file is missing
        "nope/download/audio",
        "..%2Fx/download/audio",
    ],
)
def test_no_file_for_the_wrong_song_user_or_object_is_just_404(files, path):
    assert files.get(f"{BASE}/{path}").status_code == 404


def test_only_audio_cover_and_video_can_be_downloaded(files):
    assert files.get(f"{BASE}/{ID1}/download/lyrics").status_code == 422


def test_file_names_are_safe():
    from wasifyai_music.routes import file_name

    assert file_name("Neon Rain!", "mp3") == "neon-rain.mp3"
    assert file_name('../../etc/passwd"; x', "png") == "etc-passwd-x.png"
    assert file_name("日本語のタイトル", "mp3") == "song.mp3"
    assert file_name("A" * 200, "mp3") == "a" * 60 + ".mp3"
    assert file_name("x", "") == "x"


# ---- the video ----------------------------------------------------------------------------


class Encoder:
    """Stands in for ffmpeg: counts calls, can be slow or fail."""

    def __init__(self, result: bytes | Exception = b"MP4DATA", delay: float = 0):
        self.calls: list[tuple[int, int, str]] = []
        self._result, self._delay = result, delay

    async def __call__(self, audio: bytes, cover: bytes, title: str) -> bytes:
        import asyncio

        self.calls.append((len(audio), len(cover), title))
        await asyncio.sleep(self._delay)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def video_client(encoder, with_files=True):
    store = InMemorySongStore()
    store.songs = [song(1), song(2, cover=False)]
    app = FastAPI()
    app.state.storage = ScopedStorage(memory_storage())
    app.include_router(
        build_routes(RouteDeps(app.state, identity), store, encoder),
        prefix="/products/wasifyai-music",
    )
    c = TestClient(app)
    if with_files:
        stored(c, "s1/audio.mp3", AUDIO, "audio/mpeg")
        stored(c, "s1/cover.png", COVER, "image/png")
    return c


def test_the_video_is_made_once_and_then_served_from_storage():
    enc = Encoder()
    c = video_client(enc)
    first = c.get(f"{BASE}/{ID1}/download/video")
    assert first.status_code == 200 and first.content == b"MP4DATA"
    assert first.headers["content-type"] == "video/mp4"
    assert first.headers["content-disposition"] == 'attachment; filename="song-1.mp4"'
    again = c.get(f"{BASE}/{ID1}/download/video")
    assert again.content == b"MP4DATA" and len(enc.calls) == 1  # no second encode
    assert enc.calls[0] == (len(AUDIO), len(COVER), "Song 1")


@pytest.fixture
def slow_encoder_and_client():
    enc = Encoder(delay=0.2)
    return enc, video_client(enc)  # built outside the event loop: it stores files with asyncio.run


async def test_simultaneous_requests_make_the_video_only_once(slow_encoder_and_client):
    import asyncio

    import httpx

    enc, c = slow_encoder_and_client
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=c.app), base_url="http://t"
    ) as http:
        replies = await asyncio.gather(
            *(http.get(f"{BASE}/{ID1}/download/video") for _ in range(4))
        )
    assert [r.status_code for r in replies] == [200] * 4
    assert len(enc.calls) == 1


def test_a_server_without_ffmpeg_says_so_plainly():
    from wasifyai_music.video import VideoUnavailable

    c = video_client(Encoder(VideoUnavailable("ffmpeg is not installed")))
    r = c.get(f"{BASE}/{ID1}/download/video")
    assert r.status_code == 503 and "not available" in r.json()["detail"]
    assert "ffmpeg" not in r.text


def test_a_failed_encode_is_a_clean_error_and_is_not_kept():
    from wasifyai_music.video import VideoError

    enc = Encoder(VideoError("the video could not be made"))
    c = video_client(enc)
    assert c.get(f"{BASE}/{ID1}/download/video").status_code == 502
    enc._result = b"OK"  # the next try runs the encoder again
    assert c.get(f"{BASE}/{ID1}/download/video").content == b"OK" and len(enc.calls) == 2
