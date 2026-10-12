import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from wasifyai_platform_sdk import (
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
            await client.app.state.storage.put(rel, data, "video/mp4")
        finally:
            reset_context(token)

    asyncio.run(go())


@pytest.fixture
def client():
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
    app.state.storage = ScopedStorage(memory_storage())
    app.include_router(
        build_routes(RouteDeps(app.state, identity), store), prefix="/products/wasifyai-video"
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


def test_delete_removes_the_files_then_the_row_and_a_working_clip_is_kept(client):
    put(client, "u1", f"{uid(1)}/video.mp4", b"x")
    put(client, "u1", f"{uid(1)}/poster.jpg", b"y")
    assert client.delete(f"{BASE}/{uid(1)}").status_code == 204
    assert client.get(f"{BASE}/{uid(1)}").status_code == 404

    async def left():
        token = set_context(RunContext("t1", "wasifyai-video", "u1"))
        try:
            return await client.app.state.storage.exists(f"{uid(1)}/video.mp4")
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
