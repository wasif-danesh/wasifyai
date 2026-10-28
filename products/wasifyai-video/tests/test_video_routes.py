import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from video_rig import frame_count, mp4
from wasifyai_platform_sdk import (
    EngineServices,
    Identity,
    RouteDeps,
    RunContext,
    ScopedStorage,
    memory_storage,
    reset_context,
    set_context,
)
from wasifyai_video.routes import build_routes, file_name
from wasifyai_video.videos import (
    STALE_AFTER,
    STALE_MESSAGE,
    InMemoryVideoStore,
    VideoRecord,
)

T0 = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
BASE = "/products/wasifyai-video/videos"


def identity(x_user: str = Header("u1"), x_tenant: str = Header("t1")) -> Identity:
    return Identity(tenant_id=x_tenant, user_id=x_user)


def uid(n: int) -> str:
    return f"00000000-0000-0000-0000-{n:012d}"


def video(n, user="u1", tenant="t1", status="done", **kw) -> VideoRecord:
    done = status == "done"
    base = dict(
        id=uid(n), tenant_id=tenant, product_id="wasifyai-video", user_id=user, thread_id=None,
        run_id=None, mode="text", status=status, prompt=f"Clip number {n}", seconds=2,
        frames=49, fps=24, width=768 if done else None, height=512 if done else None,
        video_key=f"{uid(n)}/video.mp4" if done else None,
        poster_key=f"{uid(n)}/poster.jpg" if done else None,
        created_at=T0 + timedelta(minutes=n),
    )  # fmt: skip
    return VideoRecord(**{**base, **kw})


def put(client, user: str, rel: str, data: bytes):
    async def go():
        token = set_context(RunContext("t1", "wasifyai-video", user))
        try:
            await client.app.state.services.storage.put(rel, data, "video/mp4")
        finally:
            reset_context(token)

    asyncio.run(go())


@pytest.fixture
def client(tmp_path):
    store = InMemoryVideoStore()
    making = video(3, status="working", created_at=datetime.now(UTC) - timedelta(minutes=1))
    store.videos = [
        video(1),
        video(2),
        making,
        video(4, status="failed", error="It failed."),
        video(5, user="someone-else"),
        video(6, tenant="other-tenant"),
    ]
    app = FastAPI()
    app.state.services = EngineServices()
    app.state.services.storage = ScopedStorage(memory_storage())
    app.state.services.export_dir = (
        tmp_path / "Downloads"
    )  # the desktop app sets one; the web does not
    app.include_router(
        build_routes(RouteDeps(app.state.services, identity), store),
        prefix="/products/wasifyai-video",
    )
    c = TestClient(app)
    c.store = store  # type: ignore[attr-defined]
    return c


def test_the_list_is_the_callers_own_newest_first_with_links_only_for_finished_clips(client):
    body = client.get(BASE).json()
    ids = [v["id"] for v in body["videos"]]
    assert ids == [
        uid(3),
        uid(4),
        uid(2),
        uid(1),
    ]  # the clip being made is the newest and body["next_before"] is None
    by_id = {v["id"]: v for v in body["videos"]}
    assert by_id[uid(1)]["status"] == "done" and by_id[uid(1)]["video_url"].endswith("video.mp4")
    assert by_id[uid(1)]["poster_url"].endswith("poster.jpg")
    assert by_id[uid(3)]["status"] == "working" and by_id[uid(3)]["video_url"] is None
    assert by_id[uid(4)]["error"] == "It failed." and by_id[uid(4)]["video_url"] is None
    assert by_id[uid(1)]["error"] is None


def test_the_site_can_ask_for_just_the_clips_being_made(client):
    working = client.get(BASE, params={"status": "working"}).json()["videos"]
    assert [v["id"] for v in working] == [uid(3)]
    assert client.get(BASE, params={"status": "bogus"}).status_code == 422
    assert client.get(BASE, headers={"x-user": "nobody"}).json()["videos"] == []


def test_paging(client):
    page = client.get(BASE, params={"limit": 2}).json()
    assert [v["id"] for v in page["videos"]] == [uid(3), uid(4)] and page["next_before"]
    rest = client.get(BASE, params={"limit": 2, "before": page["next_before"]}).json()
    assert [v["id"] for v in rest["videos"]] == [uid(2), uid(1)] and rest["next_before"] is None


def test_one_clip_and_no_existence_leak(client):
    assert client.get(f"{BASE}/{uid(1)}").json()["prompt"] == "Clip number 1"
    assert client.get(f"{BASE}/{uid(5)}").status_code == 404  # someone else's
    assert client.get(f"{BASE}/{uid(6)}").status_code == 404  # another tenant's
    assert client.get(f"{BASE}/not-a-uuid").status_code == 404


def test_download_is_an_attachment_for_a_finished_clip_only(client):
    put(client, "u1", f"{uid(1)}/video.mp4", b"MP4DATA")
    r = client.get(f"{BASE}/{uid(1)}/download")
    assert r.status_code == 200 and r.content == b"MP4DATA"
    assert r.headers["content-type"] == "video/mp4"
    assert r.headers["content-disposition"] == 'attachment; filename="clip-number-1.mp4"'
    assert r.headers["cache-control"] == "private, no-store"
    assert client.get(f"{BASE}/{uid(3)}/download").status_code == 404  # still being made
    assert client.get(f"{BASE}/{uid(5)}/download").status_code == 404
    assert client.get(f"{BASE}/{uid(2)}/download").status_code == 404  # file missing


def test_export_copies_a_finished_clip_and_never_overwrites(client, tmp_path):
    put(client, "u1", f"{uid(1)}/video.mp4", b"MP4DATA")
    first = client.post(f"{BASE}/{uid(1)}/export")
    assert first.status_code == 200 and first.json()["name"] == "clip-number-1.mp4"
    saved = tmp_path / "Downloads" / "clip-number-1.mp4"
    assert saved.read_bytes() == b"MP4DATA" and first.json()["path"] == str(saved)
    second = client.post(f"{BASE}/{uid(1)}/export").json()
    assert second["name"] == "clip-number-1-2.mp4" and saved.exists()


def test_export_writes_where_the_save_as_box_chose_and_says_so_when_it_cannot(client, tmp_path):
    put(client, "u1", f"{uid(1)}/video.mp4", b"MP4DATA")
    chosen = tmp_path / "Movies" / "my-fox.mp4"
    chosen.parent.mkdir()
    r = client.post(f"{BASE}/{uid(1)}/export", json={"path": str(chosen)})
    assert r.status_code == 200 and r.json() == {"name": "my-fox.mp4", "path": str(chosen)}
    assert chosen.read_bytes() == b"MP4DATA"
    assert not (tmp_path / "Downloads").exists()  # the folder of the assistant was not used
    gone = client.post(f"{BASE}/{uid(1)}/export", json={"path": str(tmp_path / "nope" / "a.mp4")})
    assert gone.status_code == 422 and "does not exist" in gone.json()["detail"]
    del client.app.state.services.export_dir  # no export folder, but a chosen path still works
    again = client.post(f"{BASE}/{uid(1)}/export", json={"path": str(chosen)})
    assert again.status_code == 200


def test_export_is_for_the_owner_a_finished_clip_and_only_where_a_folder_is_set(client):
    put(client, "u1", f"{uid(1)}/video.mp4", b"x")
    assert client.post(f"{BASE}/{uid(1)}/export", headers={"x-user": "other"}).status_code == 404
    assert client.post(f"{BASE}/{uid(3)}/export").status_code == 404  # still being made
    assert client.post(f"{BASE}/{uid(2)}/export").status_code == 404  # file missing
    del client.app.state.services.export_dir  # the web profile never sets one
    assert client.post(f"{BASE}/{uid(1)}/export").status_code == 404


def test_delete_removes_the_files_then_the_row_and_a_working_clip_is_kept(client):
    put(client, "u1", f"{uid(1)}/video.mp4", b"x")
    put(client, "u1", f"{uid(1)}/poster.jpg", b"y")
    assert client.delete(f"{BASE}/{uid(1)}").status_code == 204
    assert client.get(f"{BASE}/{uid(1)}").status_code == 404

    async def left():
        token = set_context(RunContext("t1", "wasifyai-video", "u1"))
        try:
            return await client.app.state.services.storage.exists(f"{uid(1)}/video.mp4")
        finally:
            reset_context(token)

    assert asyncio.run(left()) is False
    assert client.delete(f"{BASE}/{uid(3)}").status_code == 409  # its job is running
    assert client.delete(f"{BASE}/{uid(5)}").status_code == 404
    assert client.delete(f"{BASE}/{uid(4)}").status_code == 204  # dismissing a failed one


async def test_a_run_that_died_is_marked_failed_instead_of_working_forever():
    store = InMemoryVideoStore()
    old = video(
        1, status="working", created_at=datetime.now(UTC) - STALE_AFTER - timedelta(minutes=1)
    )
    fresh = video(2, status="working", created_at=datetime.now(UTC))
    store.videos = [old, fresh]
    assert await store.working_count("t1", "u1") == 1
    rows = {v.id: v for v in await store.list("t1", "u1", 10, None)}
    assert rows[old.id].status == "failed" and rows[old.id].error == STALE_MESSAGE
    assert rows[fresh.id].status == "working"


def test_file_names_are_safe():
    assert file_name("A fox! In the snow...", "mp4") == "a-fox-in-the-snow.mp4"
    assert file_name("../../etc/passwd", "mp4") == "etc-passwd.mp4"
    assert file_name("", "mp4") == "video.mp4"


# ---- adding a video of the person's own -------------------------------------------------------


def stored(client, rel: str, user: str = "u1") -> bytes:
    async def go() -> bytes:
        token = set_context(RunContext("t1", "wasifyai-video", user))
        try:
            return await client.app.state.services.storage.get(rel)
        finally:
            reset_context(token)

    return asyncio.run(go())


class Indexed:
    def __init__(self) -> None:
        self.items: dict[str, str] = {}

    async def index(self, tenant, product, user, kind, item_id, text) -> None:
        self.items[item_id] = f"{kind}:{text}"


def test_a_video_file_is_added_to_the_library_made_to_fit_and_found_in_search(client):
    client.app.state.services.creation_index = Indexed()
    r = client.post(
        f"{BASE}/import", files={"file": ("holiday_clip-1.mp4", mp4((200, 150), 24), "video/mp4")}
    )
    assert r.status_code == 201, r.text
    made = r.json()
    # multiples of 32 on each side, the shape kept to within a crop, one second at 24 a second
    assert (made["width"], made["height"], made["seconds"]) == (192, 128, 1)
    assert made["mode"] == "import" and made["status"] == "done"
    assert made["prompt"] == "holiday clip 1"  # the file's name, made readable
    clip = stored(client, f"{made['id']}/video.mp4")
    assert frame_count(clip) == 24 and stored(client, f"{made['id']}/poster.jpg")
    assert client.app.state.services.creation_index.items[made["id"]] == "video:holiday clip 1"
    ids = [v["id"] for v in client.get(BASE).json()["videos"]]
    assert made["id"] in ids
    assert made["id"] not in [
        v["id"] for v in client.get(BASE, headers={"x-user": "someone-else"}).json()["videos"]
    ]


def test_a_small_clip_keeps_its_size_and_a_big_one_is_brought_down(client):
    small = client.post(
        f"{BASE}/import", files={"file": ("a.mp4", mp4((128, 96), 24), "video/mp4")}
    )
    assert (small.json()["width"], small.json()["height"]) == (128, 96)
    big = client.post(
        f"{BASE}/import", files={"file": ("b.mp4", mp4((1920, 1080), 12 + 12), "video/mp4")}
    )
    assert (big.json()["width"], big.json()["height"]) == (768, 416)  # 768 x 432, down to 32s


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("notes.txt", b"just some text, not a video at all", "not a video"),
        ("empty.mp4", b"", "No file was sent"),
    ],
)
def test_a_file_that_is_not_a_video_is_refused_in_words(client, name, data, message):
    r = client.post(f"{BASE}/import", files={"file": (name, data, "video/mp4")})
    assert r.status_code == 422 and message in r.json()["detail"]
    assert [v["id"] for v in client.get(BASE).json()["videos"]] == [uid(3), uid(4), uid(2), uid(1)]


def test_a_video_longer_than_thirty_seconds_is_refused(client):
    long = mp4((64, 64), 24 * 31)
    r = client.post(f"{BASE}/import", files={"file": ("long.mp4", long, "video/mp4")})
    assert r.status_code == 422 and "longer than 30 seconds" in r.json()["detail"]


def test_a_video_of_a_moment_is_refused(client):
    r = client.post(f"{BASE}/import", files={"file": ("blink.mp4", mp4((64, 64), 4), "video/mp4")})
    assert r.status_code == 422 and "too short" in r.json()["detail"]


def test_a_clip_says_what_it_was_made_from_and_the_list_finds_what_was_made_from_one(client):
    client.store.videos.append(video(8, mode="extend", source_id=uid(1)))
    put(client, "u1", f"{uid(8)}/video.mp4", b"mp4")
    put(client, "u1", f"{uid(8)}/poster.jpg", b"jpg")
    assert client.get(f"{BASE}/{uid(8)}").json()["source_id"] == uid(1)
    assert client.get(f"{BASE}/{uid(1)}").json()["source_id"] is None
    made_from = client.get(BASE, params={"source": uid(1)}).json()["videos"]
    assert [v["id"] for v in made_from] == [uid(8)]
    assert client.get(BASE, params={"source": "not-an-id"}).json()["videos"] == []
    other = client.get(BASE, params={"source": uid(1)}, headers={"x-user": "u2"}).json()
    assert other["videos"] == []
