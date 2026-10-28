"""Motion graphics (ADR-0077, ADR-0079) on stand-ins: the store, the routes, the render manager with
the exact-text check, the actions and the library kind, with a real SQLite store, real storage and a
stand-in render engine (the real browser: `services/api/tests/test_video_builder_hostile.py` and
`test_video_builder_templates.py`). The templates themselves are in `test_templates.py`."""

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from video_rig import mp4, png
from wasifyai_platform_sdk import (
    EngineServices,
    Identity,
    InMemoryUsageRecorder,
    RouteDeps,
    RunError,
    ScopedStorage,
    memory_storage,
)
from wasifyai_platform_sdk.actions import ActionExecutor, ActionRegistry, builtin_actions
from wasifyai_platform_sdk.actions.model import Readiness, need_runtime
from wasifyai_platform_sdk.actions.testing import FakeActionHost
from wasifyai_platform_sdk.sqlite import create_sqlite_engine
from wasifyai_video.actions import actions, library_kinds
from wasifyai_video.builder import projects, templates
from wasifyai_video.builder.index import BuilderIndexSource
from wasifyai_video.builder.store import LEFT_RUNNING, BuilderStore, NotFound, NothingToUndo
from wasifyai_video.index import video_index_source
from wasifyai_video.routes import build_routes
from wasifyai_video.videos import video_store

BASE = "/products/wasifyai-video/builder"
ME = Identity("t1", "u1")
SLOTS = {"title": "Launch day", "subtitle": "Wasify AI is here", "theme": "sunrise"}


# ---- the project folder and the store ------------------------------------------------------------


def test_a_project_folder_is_rewritten_from_its_slots_and_its_path_is_safe(tmp_path):
    gsap = tmp_path / "gsap.min.js"
    gsap.write_text("//gsap")
    font = tmp_path / "inter.woff2"
    font.write_bytes(b"wOF2")
    folder = projects.project_dir(tmp_path, "desktop:local", "../../etc", "a" * 32)
    assert tmp_path in folder.parents and ".." not in folder.parts
    slots = templates.normalize_slots("title", SLOTS)
    projects.write_project(folder, "title", slots, gsap, {"inter.woff2": font})
    assert (folder / "vendor" / "gsap.min.js").read_text() == "//gsap"
    assert (folder / "vendor" / "fonts" / "inter.woff2").read_bytes() == b"wOF2"
    assert "Launch day" in projects.read_page(folder) and not (folder / "index.html.part").exists()
    assert json.loads((folder / "slots.json").read_text())["template"] == "title"
    with pytest.raises(ValueError):
        projects.project_dir(tmp_path, "t", "u", "../../x")


def test_the_store_keeps_compositions_per_person_and_renders_with_them(tmp_path):
    store = BuilderStore.in_folder(tmp_path)
    a = store.add_composition("t1", "u1", title="One", template="title", slots={"title": "One"})
    store.add_composition("t1", "u2", title="Two", template="title", slots={"title": "Two"})
    assert [c["title"] for c in store.list_compositions("t1", "u1")] == ["One"]
    with pytest.raises(NotFound):
        store.get_composition("t1", "u2", a["id"])  # not another person's
    store.update_composition("t1", "u1", a["id"], title="One!", slots={"title": "One!"})
    assert store.get_composition("t1", "u1", a["id"])["slots"] == {"title": "One!"}
    r = store.add_render("t1", "u1", a["id"], {"fps": 30})
    store.set_progress(r["id"], 0.5)
    assert store.get_render("t1", "u1", r["id"])["progress"] == 0.5
    store.set_check(r["id"], {"ok": True, "checked": 2, "problems": [], "message": "Checked."})
    store.finish_render(r["id"], "done", video_id="v1", elapsed_s=3.2, peak_mb=700)
    row = store.get_render("t1", "u1", r["id"])
    assert row["progress"] == 1 and row["check"]["ok"] is True
    gone = store.delete_composition("t1", "u1", a["id"])
    assert [g["video_id"] for g in gone] == ["v1"]
    with pytest.raises(NotFound):
        store.get_composition("t1", "u1", a["id"])
    assert store.list_renders("t1", "u1", a["id"]) == [] and store.version_count(a["id"]) == 0


def test_every_change_is_a_version_that_undo_brings_back_one_at_a_time(tmp_path):
    store = BuilderStore.in_folder(tmp_path)
    a = store.add_composition("t1", "u1", title="One", template="title", slots={"title": "One"})
    cid = a["id"]
    with pytest.raises(NothingToUndo):
        store.undo_composition("t1", "u1", cid)
    store.update_composition("t1", "u1", cid, title="Two", slots={"title": "Two"})
    store.update_composition("t1", "u1", cid, title="Two", slots={"title": "Two"})  # no change
    store.update_composition("t1", "u1", cid, title="Three", slots={"title": "Three"})
    assert store.version_count(cid) == 2
    back = store.undo_composition("t1", "u1", cid)
    assert back["title"] == "Two" and back["slots"] == {"title": "Two"}
    back = store.undo_composition("t1", "u1", cid)
    assert back["title"] == "One" and store.version_count(cid) == 0
    with pytest.raises(NotFound):
        store.undo_composition("t1", "u2", cid)  # not another person's


def test_only_the_last_versions_are_kept(tmp_path):
    store = BuilderStore.in_folder(tmp_path)
    cid = store.add_composition("t1", "u1", title="0", template="title", slots={"n": 0})["id"]
    for n in range(1, 31):
        store.update_composition("t1", "u1", cid, title=str(n), slots={"n": n})
    assert store.version_count(cid) == 20
    assert store.undo_composition("t1", "u1", cid)["slots"] == {"n": 29}


def test_a_render_left_working_by_a_process_that_is_gone_is_failed_when_the_store_opens(tmp_path):
    store = BuilderStore.in_folder(tmp_path)
    a = store.add_composition("t1", "u1", title="One", template="title", slots={})
    r = store.add_render("t1", "u1", a["id"], {})
    again = BuilderStore.in_folder(tmp_path)
    row = again.get_render("t1", "u1", r["id"])
    assert row["status"] == "failed" and row["error"] == LEFT_RUNNING


def test_a_file_made_before_versions_and_checks_is_upgraded_and_keeps_its_projects(tmp_path):
    db = sqlite3.connect(tmp_path / "builder.db")
    db.executescript(
        """
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO meta VALUES ('schema', '1');
        CREATE TABLE compositions(
          id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, title TEXT NOT NULL,
          template TEXT NOT NULL, slots TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL);
        CREATE TABLE renders(
          id TEXT PRIMARY KEY, composition_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
          user_id TEXT NOT NULL,
          status TEXT NOT NULL CHECK (status IN ('working', 'done', 'failed', 'cancelled')),
          video_id TEXT, error TEXT, progress REAL NOT NULL DEFAULT 0,
          settings TEXT NOT NULL DEFAULT '{}', elapsed_s REAL, peak_mb INTEGER,
          blocked INTEGER NOT NULL DEFAULT 0, started_at TEXT NOT NULL, finished_at TEXT);
        INSERT INTO compositions VALUES ('c1', 't1', 'u1', 'Old', 'title', '{"title": "Old"}',
          '2026-10-20T10:00:00.000+00:00', '2026-10-20T10:00:00.000+00:00');
        INSERT INTO renders VALUES ('r1', 'c1', 't1', 'u1', 'done', 'v1', NULL, 1.0, '{}', 3.0, 700,
          0, '2026-10-20T10:01:00.000+00:00', '2026-10-20T10:01:05.000+00:00');
        """
    )
    db.commit()
    db.close()
    store = BuilderStore.in_folder(tmp_path)
    assert store.get_composition("t1", "u1", "c1")["title"] == "Old"
    assert store.get_render("t1", "u1", "r1")["check"] is None
    store.update_composition("t1", "u1", "c1", title="New", slots={"title": "New"})
    assert store.undo_composition("t1", "u1", "c1")["title"] == "Old"


# ---- the routes and the render manager -----------------------------------------------------


class FakeEngine:
    """The component's side, scripted: what `state.video_builder` offers the product."""

    def __init__(self, tmp: Path):
        self.gsap_file = tmp / "gsap.min.js"
        self.gsap_file.write_text("//gsap")
        self.font_files = {}
        for name in templates.FONT_FILES:
            f = tmp / name
            f.write_bytes(b"wOF2")
            self.font_files[name] = f
        self.is_ready = True
        self.verdict = "fits"
        self.mode = "ok"
        self.screen: dict[str, str] = {}  # what the page "says" instead of what was typed
        self.rendered: list[tuple[Path, tuple[str, ...]]] = []
        self.snapshots: list[float] = []
        self.inspected: list[dict[str, Any]] = []
        self.release = asyncio.Event()
        self.hold = False
        self.answer: Any = None  # what the chat model says; None: there is no model
        self.asked: list[str] = []
        self.installer = SimpleNamespace(supported=True)

    def ready(self) -> bool:
        return self.is_ready

    async def complete(
        self, system: str, prompt: str, schema: dict[str, Any], max_tokens: int = 800
    ) -> str:
        self.asked.append(prompt)
        if self.answer is None:
            raise RunError("no_language_model", "Choose a language model first.")
        if isinstance(self.answer, str):
            return self.answer
        props = schema["properties"]
        if set(props) == {"template"}:
            return json.dumps({"template": self.answer["template"]})
        empty = {k: (0 if v["type"] == "integer" else "") for k, v in props.items()}
        return json.dumps({**empty, **self.answer["fields"]})

    def fit(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "reason": f"It {self.verdict}."}

    def gsap(self) -> Path:
        return self.gsap_file

    def fonts(self, wanted: dict[str, str]) -> dict[str, Path]:
        return {k: v for k, v in self.font_files.items() if k in wanted}

    def lint(self, project: Path) -> list[dict[str, Any]]:
        page = (project / "index.html").read_text()
        if "evil" not in page:
            return []
        return [{"file": "index.html", "line": 1, "code": "remote_url", "message": "x"}]

    async def inspect(self, project: Path, spec: dict[str, Any]) -> dict[str, Any]:
        """Report what the page draws: what the template expects, unless `screen` says otherwise."""
        self.inspected.append(spec)
        if self.mode == "flaky" and len(self.inspected) == 1:
            return {"ok": False, "message": "The browser did not start.", "items": []}
        if self.mode == "no_check":
            return {"ok": False, "message": "The browser did not start.", "items": []}
        info = json.loads((project / "slots.json").read_text())
        template = info.pop("template")
        wanted = {(e.slot, e.at): e.text for e in templates.expected(template, info)}
        items = []
        for item in spec["items"]:
            text = self.screen.get(item["slot"], wanted[(item["slot"], item["at"])])
            items.append(
                {
                    "slot": item["slot"], "at": item["at"], "found": True, "text": text,
                    "shown": True, "opacity": 1, "inked": 500, "clipped": 0, "inside": True,
                }
            )  # fmt: skip
        return {"ok": True, "message": "", "items": items, "fonts": []}

    async def render(self, project: Path, output: Path, on_progress=None, extra_args=()):
        self.rendered.append((project, tuple(extra_args)))
        if self.mode == "flaky" and len(self.rendered) == 1:
            return SimpleNamespace(
                ok=False, reason="failed", message="The video could not be made.", seconds=1.0,
                peak_rss_bytes=2**20, blocked_count=0, log_tail="render_cancelled_parent_exited",
            )  # fmt: skip
        if on_progress:
            for line in ("render 10%", "render 55%", "render 100%"):
                on_progress(line)
        if self.hold:
            await self.release.wait()
        if self.mode in ("fail", "memory"):
            message = {
                "fail": "The video could not be made.",
                "memory": "It asked for too much memory.",
            }
            return SimpleNamespace(
                ok=False, reason=self.mode, message=message[self.mode], seconds=1.0,
                peak_rss_bytes=5 * 2**30 if self.mode == "memory" else 2**20,
                blocked_count=3 if self.mode == "memory" else 0,
            )  # fmt: skip
        await asyncio.to_thread(self._write, output)
        return SimpleNamespace(
            ok=True, reason=None, message="Done.", seconds=2.5, peak_rss_bytes=700 * 2**20,
            blocked_count=2, output=output,
        )  # fmt: skip

    @staticmethod
    def _write_still(folder: Path, at: float) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"at-{at:g}s.png").write_bytes(png((64, 36)))

    @staticmethod
    def _write(output: Path) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(mp4())

    async def snapshot(self, project: Path, folder: Path, at: float):
        self.snapshots.append(at)
        if self.mode == "fail":
            return SimpleNamespace(ok=False, message="No preview.")
        await asyncio.to_thread(self._write_still, folder, at)
        return SimpleNamespace(ok=True, message="Done.")


class Index:
    def __init__(self) -> None:
        self.items: dict[str, tuple[str, str]] = {}

    async def index(self, tenant, product, user, kind, item_id, text) -> None:
        self.items[item_id] = (kind, text)

    async def remove(self, tenant, product, item_id) -> None:
        self.items.pop(item_id, None)


def user_of(x_user: str = Header("u1"), x_tenant: str = Header("t1")) -> Identity:
    return Identity(tenant_id=x_tenant, user_id=x_user)


@pytest.fixture
def rig(tmp_path):
    engine = create_sqlite_engine(tmp_path / "wasifyai.db")
    app = FastAPI()
    app.state.services = EngineServices()
    app.state.services.engine = engine
    app.state.services.storage = ScopedStorage(memory_storage())
    app.state.services.desktop_dir = tmp_path
    app.state.services.video_builder = FakeEngine(tmp_path)
    app.state.services.creation_index = Index()
    prefix = "/products/wasifyai-video"
    app.include_router(build_routes(RouteDeps(app.state.services, user_of)), prefix=prefix)
    with TestClient(app) as client:
        client.app_state = app.state.services  # type: ignore[attr-defined]
        yield client
    asyncio.run(engine.dispose())


def create(client, template="title", **slots) -> dict[str, Any]:
    body = {**SLOTS, **slots} if template == "title" else slots
    r = client.post(f"{BASE}/projects", json={"template": template, "slots": body})
    assert r.status_code == 201, r.text
    return r.json()


def wait_for(
    client, rid: str, want=("done", "failed", "cancelled"), headers=None
) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for _ in range(200):
        row = client.get(f"{BASE}/renders/{rid}", headers=headers or {}).json()
        if row["status"] in want:
            return row
        time.sleep(0.02)
    raise AssertionError(f"still {row.get('status')}")


def test_a_project_is_created_listed_read_and_changed(rig):
    made = create(rig)
    assert made["title"] == "Launch day" and made["slots"]["theme"] == "sunrise"
    assert made["slots"]["font"] == "sans" and made["formats"] == ["mp4"]
    assert made["can_undo"] is False and "Wasify AI is here" in made["code"]  # the code view
    assert len(made["preview_times"]) == 3
    index = rig.app_state.creation_index.items
    assert index[made["id"]] == ("composition", "Launch day. Wasify AI is here")
    listed = rig.get(f"{BASE}/projects").json()["items"]
    assert [p["id"] for p in listed] == [made["id"]] and "code" not in listed[0]
    patched = rig.patch(
        f"{BASE}/projects/{made['id']}", json={"slots": {"title": "Big day"}}
    ).json()
    assert patched["title"] == "Big day" and patched["slots"]["subtitle"] == "Wasify AI is here"
    assert patched["can_undo"] is True
    assert rig.app_state.creation_index.items[made["id"]][1].startswith("Big day")
    by_id = rig.get(f"{BASE}/projects?ids={made['id']}").json()["items"]
    assert by_id[0]["title"] == "Big day"


def test_undo_brings_back_the_words_before_the_last_change(rig):
    made = create(rig)
    cid = made["id"]
    assert rig.post(f"{BASE}/projects/{cid}/undo").status_code == 409  # nothing yet
    rig.patch(f"{BASE}/projects/{cid}", json={"slots": {"title": "Big day"}})
    back = rig.post(f"{BASE}/projects/{cid}/undo").json()
    assert back["title"] == "Launch day" and back["can_undo"] is False
    assert rig.app_state.creation_index.items[cid][1].startswith("Launch day")
    r = rig.post(f"{BASE}/projects/{cid}/undo")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "nothing_to_undo"
    assert rig.post(f"{BASE}/projects/{cid}/undo", headers={"x-user": "u2"}).status_code == 404


@pytest.mark.parametrize(
    ("template", "slots", "title"),
    [
        ("quote", {"quote": "Make it simple.", "author": "Anon"}, "Make it simple."),
        ("chart", {"title": "Sales", "data": "North, 120\nSouth, 95"}, "Sales"),
        ("lower_third", {"name": "Maya Chen", "role": "Head of Design"}, "Maya Chen"),
        ("captions", {"lines": "Hello\nWorld", "per_line": "2"}, "Hello"),
    ],
)
def test_every_template_makes_a_project_the_library_can_find(rig, template, slots, title):
    made = create(rig, template, **slots)
    assert made["template"] == template and made["title"] == title
    assert templates.get(template).formats == tuple(made["formats"])
    found = rig.app_state.creation_index.items[made["id"]][1]
    assert title in found and found == templates.describe(template, made["slots"])


def test_bad_words_are_refused_in_words_and_another_person_sees_nothing(rig):
    r = rig.post(f"{BASE}/projects", json={"slots": {"title": ""}})
    assert r.status_code == 422 and r.json()["detail"]["message"] == "Write a title."
    bad = {"template": "chart", "slots": {"title": "T", "data": "North, 120"}}
    r = rig.post(f"{BASE}/projects", json=bad)
    assert r.status_code == 422 and "at least two lines" in r.json()["detail"]["message"]
    made = create(rig)
    other = {"x-user": "u2"}
    assert rig.get(f"{BASE}/projects/{made['id']}", headers=other).status_code == 404
    patch = rig.patch(f"{BASE}/projects/{made['id']}", json={"slots": {}}, headers=other)
    assert patch.status_code == 404
    assert rig.delete(f"{BASE}/projects/{made['id']}", headers=other).status_code == 204  # nothing
    assert rig.get(f"{BASE}/projects/{made['id']}").status_code == 200  # and it is still there


def test_templates_and_status_tell_the_window_what_it_needs(rig):
    info = rig.get(f"{BASE}/templates").json()
    assert [t["id"] for t in info["templates"]] == list(templates.TEMPLATES)
    assert set(info["shapes"]) == {"landscape", "portrait", "square"}
    assert "midnight" in info["themes"]
    assert info["fonts"] == {"sans": "Inter", "serif": "Source Serif 4"}
    lower = next(t for t in info["templates"] if t["id"] == "lower_third")
    assert lower["transparent"] is True and {f["id"] for f in lower["fields"]} >= {"name", "role"}
    st = rig.get(f"{BASE}/status").json()
    assert st["ready"] is True and st["fit"]["verdict"] == "fits" and st["busy"] is False


def test_lint_reports_what_reaches_outside(rig):
    made = create(rig)
    assert rig.post(f"{BASE}/projects/{made['id']}/lint").json() == {"ok": True, "findings": []}


def test_a_preview_is_a_still_made_once_and_kept(rig):
    made = create(rig)
    cid = made["id"]
    r = rig.get(f"{BASE}/projects/{cid}/preview?at=1.5")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG") and rig.app_state.video_builder.snapshots == [1.5]
    again = rig.get(f"{BASE}/projects/{cid}/preview?at=1.5")
    assert again.content == r.content and rig.app_state.video_builder.snapshots == [1.5]  # once
    rig.get(f"{BASE}/projects/{cid}/preview?at=90")
    assert rig.app_state.video_builder.snapshots[-1] == 30.0  # not past the end of 30 seconds
    assert rig.get(f"{BASE}/projects/{cid}/preview?at=99").status_code == 422
    rig.get(f"{BASE}/projects/{cid}/preview")  # no time given: the middle of the three
    assert rig.app_state.video_builder.snapshots[-1] == made["preview_times"][1]


def test_the_fonts_travel_with_the_project(rig):
    made = create(rig)
    rig.get(f"{BASE}/projects/{made['id']}/preview?at=1")
    root = rig.app_state.desktop_dir / "video-builder"
    folder = projects.project_dir(root, "t1", "u1", made["id"])
    assert (folder / "vendor" / "fonts" / "inter.woff2").is_file()
    assert 'url("vendor/fonts/inter.woff2")' in (folder / "index.html").read_text()


def test_without_the_component_a_preview_a_check_and_a_render_say_what_to_do(rig):
    rig.app_state.video_builder.is_ready = False
    made = create(rig)
    for call in (
        lambda: rig.get(f"{BASE}/projects/{made['id']}/preview"),
        lambda: rig.post(f"{BASE}/projects/{made['id']}/check"),
    ):
        r = call()
        assert r.status_code == 409 and r.json()["detail"]["code"] == "not_ready"
    r = rig.post(f"{BASE}/projects/{made['id']}/render")
    assert r.status_code == 409 and "Set it up first" in r.json()["detail"]["message"]


def test_a_missing_ffmpeg_is_said_in_the_engines_own_words_everywhere(rig):
    engine = rig.app_state.video_builder
    engine.is_ready = False
    engine.problem = lambda: "Motion graphics also needs FFmpeg (with ffprobe)."  # type: ignore[attr-defined]
    made = create(rig)
    for call in (
        lambda: rig.get(f"{BASE}/projects/{made['id']}/preview"),
        lambda: rig.post(f"{BASE}/projects/{made['id']}/check"),
        lambda: rig.post(f"{BASE}/projects/{made['id']}/render"),
    ):
        r = call()
        assert r.status_code == 409 and r.json()["detail"]["code"] == "not_ready"
        assert "needs FFmpeg" in r.json()["detail"]["message"]


def test_a_component_without_the_new_fonts_asks_to_be_set_up_again(rig):
    rig.app_state.video_builder.font_files = {}
    made = create(rig)
    r = rig.post(f"{BASE}/projects/{made['id']}/render")
    assert r.status_code == 409 and "set up again" in r.json()["detail"]["message"]
    assert rig.get(f"{BASE}/projects/{made['id']}/preview").status_code == 409


def test_the_check_can_be_run_alone_and_says_what_it_found(rig):
    made = create(rig)
    ok = rig.post(f"{BASE}/projects/{made['id']}/check").json()
    assert ok["ok"] is True and ok["checked"] == 2 and "exactly what you wrote" in ok["message"]
    rig.app_state.video_builder.screen = {"title": "Launch dav"}
    bad = rig.post(f"{BASE}/projects/{made['id']}/check").json()
    assert bad["ok"] is False and bad["problems"][0]["code"] == "text_mismatch"
    assert "Launch dav" in bad["message"] and "Launch day" in bad["message"]


def test_a_render_becomes_a_clip_of_the_library_that_search_and_export_know(rig):
    made = create(rig)
    started = rig.post(f"{BASE}/projects/{made['id']}/render")
    assert started.status_code == 202 and started.json()["status"] == "working"
    done = wait_for(rig, started.json()["id"])
    assert done["status"] == "done" and done["progress"] == 1 and done["blocked"] == 2
    assert done["format"] == "mp4" and done["check"]["ok"] is True and done["check"]["checked"] == 2
    assert done["video_url"] and done["poster_url"]
    # the clip is in the video product's table, with its files, in its search index and in its list
    clip = rig.get(f"/products/wasifyai-video/videos/{done['video_id']}").json()
    assert clip["status"] == "done" and clip["mode"] == "composition" and clip["seconds"] == 30
    assert clip["prompt"] == "Launch day. Wasify AI is here" and clip["width"] == 128
    assert rig.app_state.creation_index.items[done["video_id"]][0] == "video"
    listed = [v["id"] for v in rig.get("/products/wasifyai-video/videos").json()["videos"]]
    assert listed == [done["video_id"]]
    download = rig.get(f"/products/wasifyai-video/videos/{done['video_id']}/download")
    assert download.content[4:8] == b"ftyp" and download.headers["content-type"] == "video/mp4"
    project = rig.get(f"{BASE}/projects/{made['id']}").json()
    assert project["renders"][0]["id"] == done["id"]
    # the render read the project folder with its page, the library and the fonts
    folder, args = rig.app_state.video_builder.rendered[0]
    assert (folder / "index.html").is_file() and (folder / "vendor" / "gsap.min.js").is_file()
    assert (folder / "vendor" / "fonts" / "inter.woff2").is_file() and args == ("--format", "mp4")
    assert not list((folder / "renders").glob("*.mp4"))  # the working copy is gone


def test_the_words_are_checked_before_anything_is_drawn(rig):
    engine = rig.app_state.video_builder
    engine.screen = {"title": "Launch dav"}  # the page says something else
    made = create(rig)
    row = wait_for(rig, rig.post(f"{BASE}/projects/{made['id']}/render").json()["id"])
    assert row["status"] == "failed" and row["check"]["ok"] is False
    assert row["error"].startswith("The words on the screen are not exactly what you wrote")
    assert engine.rendered == []  # nothing was drawn
    assert rig.get("/products/wasifyai-video/videos").json()["videos"] == []
    engine.screen = {}
    engine.mode = "no_check"  # a check that cannot run is not a pass
    row = wait_for(rig, rig.post(f"{BASE}/projects/{made['id']}/render").json()["id"])
    assert (
        row["status"] == "failed" and "could not be run" in row["error"] and engine.rendered == []
    )


def test_a_transparent_overlay_is_made_as_webm_and_kept_as_one(rig):
    made = create(rig, "lower_third", name="Maya Chen", role="Head of Design")
    started = rig.post(f"{BASE}/projects/{made['id']}/render", json={"format": "webm"})
    done = wait_for(rig, started.json()["id"])
    assert done["status"] == "done" and done["format"] == "webm"
    assert rig.app_state.video_builder.rendered[0][1] == ("--format", "webm")
    clip = rig.get(f"/products/wasifyai-video/videos/{done['video_id']}").json()
    assert clip["prompt"] == "Maya Chen. Head of Design"
    download = rig.get(f"/products/wasifyai-video/videos/{done['video_id']}/download")
    assert download.headers["content-type"] == "video/webm"
    assert ".webm" in download.headers["content-disposition"]
    rig.app_state.export_dir = rig.app_state.desktop_dir / "exports"
    exported = rig.post(f"/products/wasifyai-video/videos/{done['video_id']}/export").json()
    assert exported["name"].endswith(".webm")


def test_a_format_the_template_does_not_make_is_refused_in_words(rig):
    made = create(rig)  # a title is an mp4
    r = rig.post(f"{BASE}/projects/{made['id']}/render", json={"format": "webm"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "bad_format"
    assert "Animated title can be made as mp4, not webm" in r.json()["detail"]["message"]


def test_one_render_at_a_time_and_a_cancel_stops_it_and_keeps_nothing(rig):
    engine = rig.app_state.video_builder
    engine.hold = True
    a, b = create(rig), create(rig, title="Second")
    first = rig.post(f"{BASE}/projects/{a['id']}/render").json()
    second = rig.post(f"{BASE}/projects/{b['id']}/render")
    assert second.status_code == 409 and second.json()["detail"]["code"] == "busy"
    assert rig.get(f"{BASE}/status").json()["busy"] is True
    live: dict[str, Any] = {}
    for _ in range(100):  # progress, and what it is doing, are followed while it runs
        live = rig.get(f"{BASE}/renders/{first['id']}").json()
        if live["progress"] > 0.5:
            break
        time.sleep(0.02)
    assert live["status"] == "working" and live["progress"] >= 0.55 and live["stage"] == "drawing"
    stopped = rig.post(f"{BASE}/renders/{first['id']}/cancel").json()
    assert stopped["stopped"] is True and stopped["status"] == "cancelled"
    assert rig.get("/products/wasifyai-video/videos").json()["videos"] == []  # no clip was kept
    assert rig.get(f"{BASE}/status").json()["busy"] is False
    assert rig.post(f"{BASE}/renders/{first['id']}/cancel").json()["stopped"] is False  # over


def test_a_failed_or_stopped_render_says_why_and_keeps_no_clip(rig):
    made = create(rig)
    engine = rig.app_state.video_builder
    engine.mode = "fail"
    row = wait_for(rig, rig.post(f"{BASE}/projects/{made['id']}/render").json()["id"])
    assert row["status"] == "failed" and row["error"] == "The video could not be made."
    assert row["check"]["ok"] is True  # the words were fine; the drawing failed
    engine.mode = "memory"
    row = wait_for(rig, rig.post(f"{BASE}/projects/{made['id']}/render").json()["id"])
    assert row["status"] == "failed" and "too much memory" in row["error"]
    assert row["peak_mb"] == 5120
    assert rig.get("/products/wasifyai-video/videos").json()["videos"] == []


def test_a_browser_that_gave_up_once_is_tried_once_more_for_the_check_and_for_the_drawing(rig):
    engine = rig.app_state.video_builder
    engine.mode = "flaky"
    made = create(rig)
    row = wait_for(rig, rig.post(f"{BASE}/projects/{made['id']}/render").json()["id"])
    assert row["status"] == "done" and row["check"]["ok"] is True
    assert len(engine.inspected) == 2 and len(engine.rendered) == 2


def test_a_limit_or_a_refusal_is_not_tried_again(rig):
    engine = rig.app_state.video_builder
    engine.mode = "memory"
    made = create(rig)
    row = wait_for(rig, rig.post(f"{BASE}/projects/{made['id']}/render").json()["id"])
    assert row["status"] == "failed" and len(engine.rendered) == 1


def test_a_computer_that_cannot_fit_a_render_refuses_before_starting(rig):
    rig.app_state.video_builder.verdict = "too_big"
    made = create(rig)
    r = rig.post(f"{BASE}/projects/{made['id']}/render")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "too_big"
    assert rig.app_state.video_builder.rendered == []


def test_deleting_a_project_removes_its_clips_files_and_search_entries(rig):
    made = create(rig)
    done = wait_for(rig, rig.post(f"{BASE}/projects/{made['id']}/render").json()["id"])
    folder, _ = rig.app_state.video_builder.rendered[0]
    assert rig.delete(f"{BASE}/projects/{made['id']}").status_code == 204
    assert rig.get(f"{BASE}/projects/{made['id']}").status_code == 404
    assert rig.get(f"/products/wasifyai-video/videos/{done['video_id']}").status_code == 404
    assert not folder.exists()
    index = rig.app_state.creation_index.items
    assert made["id"] not in index and done["video_id"] not in index


def test_deleting_a_project_while_it_renders_stops_the_render_first(rig):
    rig.app_state.video_builder.hold = True
    made = create(rig)
    rig.post(f"{BASE}/projects/{made['id']}/render")
    assert rig.delete(f"{BASE}/projects/{made['id']}").status_code == 204
    assert rig.get(f"{BASE}/status").json()["busy"] is False
    assert rig.get("/products/wasifyai-video/videos").json()["videos"] == []


def said(template: str, **fields: Any) -> dict[str, Any]:
    return {"template": template, "fields": fields}


def test_a_description_is_drafted_into_a_form_and_nothing_is_saved(rig):
    rig.app_state.video_builder.answer = said("lower_third", name="Maya Chen", role="Head")
    r = rig.post(f"{BASE}/draft", json={"prompt": 'Lower third for "Maya Chen", Head'})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["template"] == "lower_third" and out["fields"]["name"] == "Maya Chen"
    assert out["warnings"] == [] and out["summary"].startswith("Lower third:")
    assert rig.get(f"{BASE}/projects").json()["items"] == []  # drafting saves nothing


def test_a_csv_is_read_by_the_app_and_a_bad_one_is_refused_in_words(rig):
    rig.app_state.video_builder.answer = said("chart", title="Sales")
    ok = {"prompt": "chart it", "attachment": {"name": "s.csv", "text": "a,1\nb,$2"}}
    out = rig.post(f"{BASE}/draft", json=ok).json()
    assert out["template"] == "chart" and out["fields"]["data"] == "a, 1\nb, $2"
    bad = {"prompt": "", "attachment": {"name": "s.csv", "text": "a,1"}}
    r = rig.post(f"{BASE}/draft", json=bad)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_file"
    assert "at least two rows" in r.json()["detail"]["message"]


def test_without_a_language_model_the_draft_says_what_to_do(rig):
    r = rig.post(f"{BASE}/draft", json={"prompt": "a title"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_language_model"
    assert "Choose a language model" in r.json()["detail"]["message"]


def test_a_description_the_model_cannot_answer_for_is_a_plain_422(rig):
    rig.app_state.video_builder.answer = "not json"
    r = rig.post(f"{BASE}/draft", json={"prompt": "a title"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "bad_answer"


class Safeguards:
    """The safeguards switched on, with a moderator that says what it is told to and the usage the
    product recorded: the pieces `RouteGuard` reads from the app's state (P6)."""

    def __init__(self, state, *, allow=True, quota=None, used=0):
        self.verdicts: list[str] = []
        self.allow, self.used = allow, used
        outer = self

        class On:
            async def enabled(self) -> bool:
                return True

        class Text:
            async def complete(self, name, system, user, schema=None):
                outer.verdicts.append(str(user))
                if outer.allow:
                    return '{"allowed": true, "category": "ok", "reason": ""}'
                return '{"allowed": false, "category": "hate", "reason": "x"}'

        state.safeguards = On()
        state.caps = {
            "wasifyai-video": SimpleNamespace(
                text=Text(), db=object(), config=SimpleNamespace(quotas=quota or {})
            )
        }
        state.usage = InMemoryUsageRecorder()

    def counted(self, monkeypatch) -> None:
        async def used(db, tenant, product, user, kind, since):
            return self.used

        monkeypatch.setattr("wasifyai_platform_sdk.route_guard.sum_usage", used)


def test_while_the_safeguards_are_on_the_words_of_a_video_are_checked_before_it_is_drawn(rig):
    on = Safeguards(rig.app_state, allow=False)
    made = create(rig)
    r = rig.post(f"{BASE}/projects/{made['id']}/render")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "hate"
    assert "hatred" in r.json()["detail"]["message"]
    assert rig.app_state.video_builder.rendered == []  # nothing was drawn
    assert "Launch day" in on.verdicts[0]  # the moderator read the words on the screen


def test_a_description_is_checked_before_the_model_sees_it(rig):
    Safeguards(rig.app_state, allow=False)
    rig.app_state.video_builder.answer = said("title", title="Hi")
    r = rig.post(f"{BASE}/draft", json={"prompt": "a title"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "hate"
    assert rig.app_state.video_builder.asked == []


def test_with_no_moderator_nothing_is_drawn(rig):
    Safeguards(rig.app_state)
    rig.app_state.caps = {}  # the product has no capabilities built
    made = create(rig)
    r = rig.post(f"{BASE}/projects/{made['id']}/render")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "moderation_unavailable"


def test_a_video_that_passes_is_drawn_and_counted_and_the_daily_limit_stops_the_next(
    rig, monkeypatch
):
    on = Safeguards(rig.app_state, quota={"renders_per_user_per_day": 2})
    on.counted(monkeypatch)
    made = create(rig)
    first = rig.post(f"{BASE}/projects/{made['id']}/render")
    assert first.status_code == 202, first.text
    assert wait_for(rig, first.json()["id"])["status"] == "done"
    events = rig.app_state.usage.events
    assert [(e.kind, e.quantity, e.unit) for e in events] == [("builder.render", 1, "videos")]
    assert events[0].product_id == "wasifyai-video" and events[0].user_id == "u1"
    on.used = 2  # the day's usage as the database would count it
    again = rig.post(f"{BASE}/projects/{made['id']}/render")
    assert again.status_code == 409 and again.json()["detail"]["code"] == "quota_exceeded"
    assert "limit of 2 videos" in again.json()["detail"]["message"]


def test_the_desktop_with_safeguards_off_checks_nothing_but_still_counts(rig):
    made = create(rig)
    r = rig.post(f"{BASE}/projects/{made['id']}/render")
    assert r.status_code == 202
    assert wait_for(rig, r.json()["id"])["status"] == "done"


def test_where_there_is_no_component_the_routes_are_not_there(tmp_path):
    app = FastAPI()
    app.state.services = EngineServices()
    app.state.services.engine = create_sqlite_engine(tmp_path / "x.db")
    app.state.services.desktop_dir = tmp_path
    prefix = "/products/wasifyai-video"
    app.include_router(build_routes(RouteDeps(app.state.services, user_of)), prefix=prefix)
    with TestClient(app) as c:
        assert c.get(f"{BASE}/status").status_code == 404
        assert c.get(f"{BASE}/projects").status_code == 404


# ---- search ----------------------------------------------------------------------------------


async def test_compositions_and_clips_are_one_source_found_by_every_word_on_the_screen(tmp_path):
    engine = create_sqlite_engine(tmp_path / "wasifyai.db")
    store = BuilderStore.in_folder(tmp_path / "video-builder")
    q = templates.normalize_slots("quote", {"quote": "Make it simple.", "author": "Anon"})
    a = store.add_composition("t1", "u1", title="Make it simple.", template="quote", slots=q)
    c = templates.normalize_slots("chart", {"title": "Sales", "data": "North, 120\nSouth, 95"})
    b = store.add_composition("t1", "u1", title="Sales", template="chart", slots=c)
    source = video_index_source(engine)
    items = await source.page(None, 50)
    by_id = {i.item_id: (i.kind, i.text) for i in items}
    assert by_id[a["id"]] == ("composition", "Make it simple.. Anon")
    assert by_id[b["id"]][1] == "Sales. North 120. South 95"
    assert await source.present([a["id"], "nope"]) == {a["id"]}
    assert await BuilderIndexSource(engine).page(max(a["id"], b["id"]), 50) == []
    store.delete_composition("t1", "u1", a["id"])
    assert await source.present([a["id"]]) == set()
    await engine.dispose()


# ---- the actions and the library kind ------------------------------------------------------------


class ActionRig:
    def __init__(self, tmp_path: Path, engine):
        self.unindexed: list[str] = []
        rig = self

        class Idx(Index):
            async def remove(self, tenant, product, item_id) -> None:
                rig.unindexed.append(item_id)
                await super().remove(tenant, product, item_id)

        self.state = EngineServices(
            engine=engine, storage=ScopedStorage(memory_storage()), desktop_dir=tmp_path,
            video_builder=FakeEngine(tmp_path), creation_index=Idx(),
        )  # fmt: skip
        self.host = FakeActionHost(RouteDeps(self.state, lambda: ME))
        self.ex = ActionExecutor(
            ActionRegistry([*builtin_actions(), *actions()]), self.host,
            library={k.kind: k for k in library_kinds()},
        )  # fmt: skip

    async def go(self, action_id: str, params: dict, origin="window", **kw):
        return await self.ex.run_action(action_id, params, origin, actor=ME, **kw)

    def store(self) -> BuilderStore:
        return self.state.builder_store


@pytest.fixture
async def arig(tmp_path):
    engine = create_sqlite_engine(tmp_path / "wasifyai.db")
    yield ActionRig(tmp_path, engine)
    await engine.dispose()


async def title(arig: ActionRig, **fields: Any) -> str:
    made = await arig.go(
        "video_builder.create", {"template": "title", "fields": {"title": "Hi", **fields}}
    )
    return made.output["composition_id"]


async def test_a_project_is_written_checked_and_made_through_the_catalogue(arig):
    fields = {"title": "Launch day", "theme": "forest"}
    made = await arig.go("video_builder.create", {"template": "title", "fields": fields})
    assert made.status == "ok" and made.output["uri"].startswith("wasify://creation/composition/")
    cid = made.output["composition_id"]
    assert made.output["template"] == "title" and "Nothing has been made yet" in made.text
    assert arig.state.creation_index.items[cid][1] == "Launch day"
    lint = await arig.go("video_builder.lint", {"composition_id": cid})
    assert lint.status == "ok" and lint.output["ok"] is True
    render = await arig.go("video_builder.render", {"composition_id": cid})
    assert render.status == "ok", render
    assert render.output["uri"] == f"wasify://creation/video/{render.output['video_id']}"
    assert render.output["checked"] is True and render.output["format"] == "mp4"
    assert "checked word for word" in render.text
    clip = await video_store(arig.state.engine).get("t1", "u1", render.output["video_id"])
    assert clip is not None and clip.mode == "composition" and clip.status == "done"


async def test_motion_make_writes_checks_and_makes_in_one_step(arig):
    fields = {"name": "Maya Chen", "role": "Head of Design"}
    r = await arig.go(
        "motion.make", {"template": "lower_third", "fields": fields, "format": "webm"}
    )
    assert r.status == "ok", r
    assert r.output["title"] == "Maya Chen" and r.output["checked"] is True
    assert r.output["video_uri"].startswith("wasify://creation/video/")
    assert "checked" in r.text and "lower third" in r.text
    assert arig.state.video_builder.rendered[0][1] == ("--format", "webm")
    clip = await video_store(arig.state.engine).get("t1", "u1", r.output["video_id"])
    assert clip is not None and (clip.video_key or "").endswith("video.webm")
    # the project stays, editable, and is in the library
    listed = await arig.go("library.list", {"kind": "composition"})
    assert [i["id"] for i in listed.output["items"]] == [r.output["composition_id"]]


async def test_motion_make_without_a_video_only_writes_the_project(arig):
    fields = {"title": "Sales", "data": "North, 120\nSouth, 95"}
    r = await arig.go("motion.make", {"template": "chart", "fields": fields, "render": False})
    assert r.status == "ok" and r.output.get("video_id") is None and r.output["checked"] is False
    assert arig.state.video_builder.rendered == []


async def test_motion_make_refuses_bad_words_and_a_page_that_does_not_say_them(arig):
    r = await arig.go(
        "motion.make", {"template": "chart", "fields": {"title": "T", "data": "North, 120"}}
    )
    assert r.status == "refused" and "at least two lines" in r.text
    arig.state.video_builder.screen = {"name": "Maya Chan"}
    fields = {"template": "lower_third", "fields": {"name": "Maya Chen"}}
    bad = await arig.go("motion.make", fields)
    assert bad.status == "error" and "Maya Chan" in bad.text and "Maya Chen" in bad.text
    assert "project was kept" in bad.text and arig.state.video_builder.rendered == []
    other = await arig.go("motion.make", {"template": "poster", "fields": {}})
    assert other.status in ("error", "refused")  # not one of the five: the request is invalid


async def test_motion_revise_changes_only_what_is_given_and_makes_it_again(arig):
    fields = {"title": "Launch day", "subtitle": "Here"}
    made = await arig.go("motion.make", {"template": "title", "fields": fields})
    cid = made.output["composition_id"]
    change = {"composition_id": cid, "fields": {"theme": "paper"}}
    asked = await arig.go("motion.revise", change, origin="assistant")
    assert asked.status == "needs_approval"  # a change always asks, from the assistant
    r = await arig.go("motion.revise", change, person_approved=True)
    assert r.status == "ok", r
    found = arig.store().get_composition("t1", "u1", cid)
    assert found["slots"]["theme"] == "paper" and found["slots"]["subtitle"] == "Here"
    assert len(arig.state.video_builder.rendered) == 2 and arig.store().version_count(cid) == 1
    too_long = {"composition_id": cid, "fields": {"seconds": 999}}
    bad = await arig.go("motion.revise", too_long, person_approved=True)
    assert bad.status == "refused" and "between 3 and 90" in bad.text
    assert arig.store().get_composition("t1", "u1", cid)["slots"]["theme"] == "paper"  # unchanged
    nothing = {"composition_id": "0" * 32, "fields": {}}
    assert (await arig.go("motion.revise", nothing, person_approved=True)).status == "refused"


async def test_requests_the_product_cannot_take_are_refused_in_words(arig):
    fields = {"template": "title", "fields": {"title": "Hi", "seconds": 999}}
    r = await arig.go("video_builder.create", fields)
    assert r.status == "refused" and "between 3 and 90 seconds" in r.text
    gone = await arig.go("video_builder.render", {"composition_id": "0" * 32})
    assert gone.status == "refused" and "does not exist" in gone.text
    bad = await arig.go("video_builder.render", {"composition_id": "x"})
    assert bad.status == "refused"


async def test_a_render_that_fails_is_an_error_with_the_reason(arig):
    arig.state.video_builder.mode = "fail"
    cid = await title(arig)
    r = await arig.go("video_builder.render", {"composition_id": cid})
    assert r.status == "error" and r.text == "The video could not be made."


async def test_the_component_must_be_set_up_before_checking_or_rendering(arig):
    arig.host.not_ready(
        need_runtime("video-builder"),
        Readiness.needs_setup("Set up Motion graphics first.", ui="motion"),
    )
    cid = await title(arig)  # writing a project needs no component
    for action, params in (
        ("video_builder.lint", {"composition_id": cid}),
        ("video_builder.render", {"composition_id": cid}),
        ("motion.make", {"template": "title", "fields": {"title": "Hi"}}),
    ):
        r = await arig.go(action, params)
        assert r.status == "needs_setup" and "Set up Motion graphics" in r.text


async def test_a_render_asks_first_when_asked_and_a_model_is_told_every_template(arig):
    cid = await title(arig)
    asked = await arig.go("video_builder.render", {"composition_id": cid}, origin="assistant")
    assert asked.status == "needs_approval" and arig.state.video_builder.rendered == []
    ids = ("video_builder.create", "video_builder.lint", "video_builder.render", "motion.make",
           "motion.revise")  # fmt: skip
    for action_id in ids:
        action = arig.ex.registry.get(action_id)
        assert action and action.ui == "motion" and action.product == "wasifyai-video"
    for action_id in ("motion.make", "video_builder.create"):
        text = arig.ex.registry.get(action_id).description
        for template in templates.TEMPLATES:
            assert f"{template}:" in text
        assert "lines like 'Sales, 120'" in text and "one caption per line" in text
    assert arig.ex.registry.get("motion.make").effect == "make"
    assert arig.ex.registry.get("motion.revise").effect == "change"
    render = arig.ex.registry.get("video_builder.render")
    assert render and render.long and "costly" in render.flags


async def test_the_library_lists_renames_and_deletes_compositions(arig):
    cid = await title(arig, title="Launch day")
    quote = await arig.go(
        "video_builder.create", {"template": "quote", "fields": {"quote": "Be kind."}}
    )
    listed = await arig.go("library.list", {"kind": "composition"})
    assert listed.status == "ok" and {i["id"] for i in listed.output["items"]} >= {cid}
    rename = {"kind": "composition", "id": cid, "title": "Big day"}
    assert (await arig.go("library.rename", rename, person_approved=True)).status == "ok"
    assert arig.state.creation_index.items[cid][1] == "Big day"
    quote_id = quote.output["composition_id"]
    other = {"kind": "composition", "id": quote_id, "title": "X"}  # a quote has no name to change
    assert (await arig.go("library.rename", other, person_approved=True)).status == "refused"
    got = await arig.go("library.get", {"kind": "composition", "id": cid})
    assert got.output["item"]["title"] == "Big day"
    gone = {"kind": "composition", "id": cid}
    assert (await arig.go("library.delete", gone)).status == "needs_approval"  # destroy asks
    deleted = await arig.go("library.delete", gone, person_approved=True)
    assert deleted.status == "ok" and cid in arig.unindexed
    assert (await arig.go("library.get", gone)).status == "refused"


async def test_while_the_safeguards_are_on_the_assistant_cannot_draw_what_is_not_allowed(arig):
    Safeguards(arig.state, allow=False)
    made = await arig.go("video_builder.create", {"template": "title", "fields": {"title": "Hi"}})
    assert made.status == "ok"  # words are only stored
    r = await arig.go("motion.make", {"template": "title", "fields": {"title": "Hi"}})
    assert r.status != "ok" and "hatred" in r.text  # the moderator's refusal, in fixed words
    assert arig.state.video_builder.rendered == []
