"""Motion graphics for the web (ADR-0087, P4): the product's routes and render manager, the API's
`RemoteBuilderEngine` and the worker's handlers between them. A fake queue runs each job on the
worker's own code at once, with a stand-in for the browser that draws."""

import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from wasifyai_api.engine_workers import WorkerDirectory
from wasifyai_api.remote_builder import RemoteBuilderEngine
from wasifyai_engine_worker.handlers import run_job
from wasifyai_platform_sdk import (
    EngineJob,
    EngineWorkerInfo,
    Identity,
    RouteDeps,
    ScopedStorage,
    builder_wire,
    memory_storage,
)
from wasifyai_platform_sdk.sqlite import create_sqlite_engine
from wasifyai_platform_sdk.storage import object_key

sys.path.insert(
    0, str(Path(__file__).resolve().parents[3] / "products" / "wasifyai-video" / "tests")
)
from video_rig import mp4, png  # noqa: E402
from wasifyai_video.builder import templates  # noqa: E402
from wasifyai_video.builder.store import BuilderStore  # noqa: E402
from wasifyai_video.routes import build_routes  # noqa: E402

BASE = "/products/wasifyai-video/builder"
SLOTS = {"title": "Launch day", "subtitle": "Wasify AI is here", "theme": "sunrise"}


class Service:
    """The Motion graphics component on the worker: the library, the fonts, the browser."""

    def __init__(self, tmp: Path) -> None:
        self.gsap_file = tmp / "gsap.min.js"
        self.gsap_file.write_text("//gsap")
        self.font_files = {}
        for name in templates.FONT_FILES:
            f = tmp / name
            f.write_bytes(b"wOF2")
            self.font_files[name] = f
        self.screen: dict[str, str] = {}
        self.rendered = 0
        self.hold = False
        self.release = asyncio.Event()

    def gsap(self) -> Path:
        return self.gsap_file

    def fonts(self, wanted: dict[str, str]) -> dict[str, Path]:
        return {k: v for k, v in self.font_files.items() if k in wanted}

    def lint(self, project: Path) -> list[dict[str, Any]]:
        evil = "evil" in (project / "index.html").read_text()  # noqa: ASYNC240
        return (
            [{"file": "index.html", "line": 1, "code": "remote_url", "message": "x"}]
            if evil
            else []
        )

    async def inspect(self, project: Path, spec: dict[str, Any]) -> dict[str, Any]:
        info = json.loads((project / "slots.json").read_text())  # noqa: ASYNC240
        template = info.pop("template")
        wanted = {(e.slot, e.at): e.text for e in templates.expected(template, info)}
        items = []
        for item in spec["items"]:
            text = self.screen.get(item["slot"], wanted[(item["slot"], item["at"])])
            items.append({"slot": item["slot"], "at": item["at"], "found": True, "text": text,
                          "shown": True, "opacity": 1, "inked": 500, "clipped": 0,
                          "inside": True})  # fmt: skip
        return {"ok": True, "message": "", "items": items, "fonts": []}

    async def render(self, project, output, on_progress=None, extra_args=()):
        self.rendered += 1
        if on_progress:
            for line in ("render 10%", "render 55%", "render 100%"):
                on_progress(line)
        if self.hold:
            await self.release.wait()
        output.write_bytes(mp4())  # noqa: ASYNC240
        return SimpleNamespace(ok=True, reason=None, message="Done.", seconds=2.5,
                               peak_rss_bytes=700 * 2**20, blocked_count=2)  # fmt: skip

    async def snapshot(self, project, folder, at):
        folder.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
        (folder / f"at-{at:g}s.png").write_bytes(png((64, 36)))  # noqa: ASYNC240
        return SimpleNamespace(ok=True, message="Done.", seconds=0.5)


class InlineQueue:
    def __init__(self, storage, service):
        self.storage, self.service = storage, service
        self.done: dict[str, Any] = {}
        self.reported: list[tuple[float, str]] = []
        self.kinds: list[str] = []
        self.cancelled: list[str] = []
        self.turns: list[str] = []

    async def resume_turn(self, job_id):
        self.turns.append(job_id)

    async def submit(self, job, timeout_s=3600):
        self.kinds.append(job.kind)

        async def report(fraction, label):
            self.reported.append((fraction, label))

        self.done[job.id] = await run_job(
            {"builder": self.service}, self.storage, job, "w1", report
        )

    async def wait(self, job_id, timeout_s, on_progress=None):
        for fraction, label in self.reported:
            if on_progress is not None:
                await on_progress(fraction, label)
        self.reported.clear()
        return self.done.pop(job_id)

    async def cancel(self, job_id):
        self.cancelled.append(job_id)

    async def status(self, job_id):
        return "done" if job_id in self.done else "lost"


class Index:
    def __init__(self) -> None:
        self.items: dict[str, tuple[str, str]] = {}

    async def index(self, tenant, product, user, kind, item_id, text) -> None:
        self.items[item_id] = (kind, text)

    async def remove(self, tenant, product, item_id) -> None:
        self.items.pop(item_id, None)


def user_of(x_user: str = Header("u1"), x_tenant: str = Header("t1")) -> Identity:
    return Identity(tenant_id=x_tenant, user_id=x_user)


def listing() -> EngineWorkerInfo:
    comp = {"ready": True, "problem": None, "fit": {"verdict": "fits", "reason": "ok"}, "state": {}}
    return EngineWorkerInfo(id="w1", kinds=builder_wire.KINDS, models=[],
                            components={builder_wire.COMPONENT: comp})  # fmt: skip


@pytest.fixture
def web(tmp_path):
    raw = memory_storage()
    service = Service(tmp_path)
    queue = InlineQueue(raw, service)
    directory = WorkerDirectory(None)  # type: ignore[arg-type]
    directory.workers = [listing()]
    sql = create_sqlite_engine(tmp_path / "wasifyai.db")
    app = FastAPI()
    app.state.engine = sql  # the video library's rows
    app.state.storage = ScopedStorage(raw)
    app.state.builder_store = BuilderStore(tmp_path / "rows")
    app.state.builder_scratch = tmp_path / "scratch"
    app.state.video_builder = RemoteBuilderEngine(queue, raw, directory)  # type: ignore[arg-type]
    app.state.creation_index = Index()
    app.include_router(
        build_routes(RouteDeps(app.state, user_of)), prefix="/products/wasifyai-video"
    )
    with TestClient(app) as client:
        client.service, client.queue, client.raw = service, queue, raw  # type: ignore[attr-defined]
        client.app_state_items = lambda: app.state.creation_index.items  # type: ignore[attr-defined]
        yield client
    asyncio.run(sql.dispose())


def create(client, **headers) -> dict[str, Any]:
    r = client.post(f"{BASE}/projects", json={"template": "title", "slots": SLOTS}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def wait_for(client, rid: str, headers=None) -> dict[str, Any]:
    for _ in range(300):
        row = client.get(f"{BASE}/renders/{rid}", headers=headers or {}).json()
        if row["status"] in ("done", "failed", "cancelled"):
            return row
        time.sleep(0.02)
    raise AssertionError("still working")


def test_the_web_says_where_the_work_is_done_and_what_the_worker_offers(web):
    status = web.get(f"{BASE}/status").json()
    assert status["ready"] is True and status["place"] == "service" and status["problem"] is None


def test_the_words_are_checked_on_the_worker_and_a_wrong_screen_is_said_in_words(web):
    made = create(web)
    ok = web.post(f"{BASE}/projects/{made['id']}/check").json()
    assert ok["ok"] is True and ok["checked"] > 0
    web.service.screen = {"title": "Something else"}
    bad = web.post(f"{BASE}/projects/{made['id']}/check").json()
    assert bad["ok"] is False and "Something else" in bad["message"]
    assert web.queue.kinds == [builder_wire.INSPECT, builder_wire.INSPECT]


def test_a_video_is_made_on_the_worker_checked_first_and_becomes_a_library_clip(web):
    made = create(web)
    start = web.post(f"{BASE}/projects/{made['id']}/render")
    assert start.status_code == 202, start.text
    done = wait_for(web, start.json()["id"])
    assert done["status"] == "done", done
    assert done["video_url"] and done["poster_url"] and done["progress"] == 1
    assert web.queue.kinds == [builder_wire.INSPECT, builder_wire.RENDER]
    assert web.service.rendered == 1
    assert web.app_state_items()[done["video_id"]][0] == "video"


def test_a_preview_still_comes_from_the_worker_and_is_cached(web):
    made = create(web)
    first = web.get(f"{BASE}/projects/{made['id']}/preview?at=1")
    assert first.status_code == 200 and first.headers["content-type"] == "image/png"
    web.get(f"{BASE}/projects/{made['id']}/preview?at=1")
    assert web.queue.kinds.count(builder_wire.SNAPSHOT) == 1


def test_a_page_with_a_remote_address_is_stopped_by_the_lint_on_the_worker(web):
    made = create(web)
    assert web.post(f"{BASE}/projects/{made['id']}/lint").json()["ok"] is True
    assert web.queue.kinds[-1] == builder_wire.LINT


def test_each_person_renders_one_video_at_a_time_and_nobody_sees_anothers(web):
    web.service.hold = True
    a = create(web)
    first = web.post(f"{BASE}/projects/{a['id']}/render")
    assert first.status_code == 202
    again = web.post(f"{BASE}/projects/{a['id']}/render")
    assert again.status_code == 409 and again.json()["detail"]["code"] == "busy"
    b = create(web, **{"x-user": "u2"})
    other = web.post(f"{BASE}/projects/{b['id']}/render", headers={"x-user": "u2"})
    assert other.status_code == 202  # u2 is not held up by u1's render
    assert web.get(f"{BASE}/projects/{a['id']}", headers={"x-user": "u2"}).status_code == 404
    web.service.release.set()


def restarted(web, composition: dict[str, Any], *, checked=True, sent=True) -> str:
    """A render the service was waiting for when it went down: its row, and the drawing job that
    went out under the row's id (and whether the worker has finished it)."""
    store = web.app.state.builder_store
    row = store.add_render("t1", "u1", composition["id"], {"format": "mp4", "fit": "fits"})
    if checked:
        store.set_check(row["id"], {"ok": True, "message": "", "items": []})
    if sent:
        found = store.get_composition("t1", "u1", composition["id"])
        job = EngineJob(
            id=row["id"], kind=builder_wire.RENDER, tenant_id="t1", product_id="wasifyai-video",
            user_id="u1", prefix=object_key("t1", "wasifyai-video", "u1", "engine", row["id"]),
            params={"template": found["template"], "slots": found["slots"], "format": "mp4"},
        )  # fmt: skip
        web.portal.call(web.queue.submit, job)
    return row["id"]


def resume(web) -> int:
    from wasifyai_video.builder.runtime import manager_for

    return web.portal.call(manager_for(RouteDeps(web.app.state, user_of)).resume_all)


def test_a_video_the_worker_finished_while_the_service_was_down_is_saved_after_the_restart(web):
    rid = restarted(web, create(web))
    assert resume(web) == 1
    done = wait_for(web, rid)
    assert done["status"] == "done" and done["video_url"], done
    assert web.service.rendered == 1  # drawn once, by the worker before the restart
    assert builder_wire.INSPECT not in web.queue.kinds  # and the words were not checked again
    assert web.app_state_items()[done["video_id"]][0] == "video"


def test_a_render_that_never_got_to_drawing_is_failed_in_words_after_a_restart(web):
    rid = restarted(web, create(web), checked=False, sent=False)
    assert resume(web) == 0
    row = web.get(f"{BASE}/renders/{rid}").json()
    assert row["status"] == "failed" and "stopped" in row["error"]


def test_a_drawing_the_queue_has_lost_is_failed_in_words_not_waited_for(web):
    rid = restarted(web, create(web), sent=False)
    assert resume(web) == 1
    row = wait_for(web, rid)
    assert row["status"] == "failed" and "stopped" in row["error"]
    assert web.service.rendered == 0


def test_a_stopping_service_leaves_the_drawing_to_the_worker(web):
    web.service.hold = True
    made = create(web)
    engine = web.app.state.video_builder
    start = web.post(f"{BASE}/projects/{made['id']}/render")
    assert start.status_code == 202
    for _ in range(100):  # until the drawing has begun
        if web.service.rendered:
            break
        time.sleep(0.02)
    engine.closing = True  # the service is going down
    from wasifyai_video.builder.runtime import manager_for

    web.portal.call(manager_for(RouteDeps(web.app.state, user_of)).stop_all)
    row = web.get(f"{BASE}/renders/{start.json()['id']}").json()
    assert row["status"] == "working" and web.queue.cancelled == []
    engine.closing = False
    web.service.release.set()
