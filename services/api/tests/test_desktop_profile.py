"""The desktop profile end to end (ADR-0056): SQLite, the in-process queue and worker, local files,
the shell's token. The image product runs with the stub image engine, so no GPU or model is needed.
"""

import json
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

import jwt
import pytest
from fastapi.testclient import TestClient
from wasifyai_api.config import get_settings
from wasifyai_api.main import create_app

from tests.test_runs import parse

SECRET = "desktop-launch-secret-0123456789abcdef"  # the shell makes a fresh one per launch
PRODUCTS = Path(__file__).resolve().parents[3] / "products"
PNG = b"\x89PNG\r\n\x1a\n"
BASE = "http://127.0.0.1:48123"


def token(secret: str = SECRET, sub: str = "desktop:local", **over) -> str:
    now = int(time.time())
    data = {"iss": "wasifyai-web", "aud": "wasifyai-api", "iat": now, "exp": now + 300, "sub": sub}
    return jwt.encode({**data, **over}, secret, algorithm="HS256")


def auth(**kw) -> dict[str, str]:
    return {"authorization": f"Bearer {token(**kw)}"}


@pytest.fixture
def data_dir(tmp_path, monkeypatch) -> Iterator[Path]:
    """The environment the shell would give the engine."""
    root = tmp_path / "app-data"
    for key, value in {
        "DEPLOYMENT_PROFILE": "desktop",
        "DESKTOP_DATA_DIR": str(root),
        "DESKTOP_PUBLIC_URL": BASE,
        "DESKTOP_IMAGE_ENGINE": "stub",
        "API_AUTH_SECRET": SECRET,
        "AUTH_MODE": "jwt",
        "PRODUCTS_DIR": str(PRODUCTS),
        "LITELLM_BASE_URL": "",
        "METRICS_PORT": "0",
        "SAFEGUARDS_FORCE_ON": "false",
    }.items():
        monkeypatch.setenv(key, value)
    # discovery looks in the person's home folder: give the engine an empty one
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    get_settings.cache_clear()
    yield root
    get_settings.cache_clear()


def make_image(c: TestClient, prompt: str = "a red teapot on a wooden table") -> list:
    r = c.post(
        "/products/wasifyai-image/runs",
        json={"input": {"mode": "text", "prompt": prompt, "size": "square"}},
        headers=auth(),
    )
    assert r.status_code == 200, r.text
    return parse(r.text)


def test_an_image_is_made_end_to_end_on_the_desktop_profile(data_dir):
    with TestClient(create_app()) as c:
        events = make_image(c)
        names = [e for e, _ in events]
        assert names[-1] == "done" and "error" not in names

        # the job went through the queue and the worker, and its progress reached the stream.
        # A fast worker (a Windows runner) can claim the job before the stream's first read,
        # so the first status seen is queued or running.
        jobs = [d for e, d in events if e == "job_progress"]
        statuses = [j["status"] for j in jobs]
        assert statuses[0] in ("queued", "running") and statuses[-1] == "completed"
        assert [d["seq"] for _, d in events] == sorted(d["seq"] for _, d in events)

        done = events[-1][1]["outputs"]
        assert (
            done["status"] == "done" and done["width"] == 256
        )  # the stub engine draws a small placeholder
        link = urlparse(done["image_url"])
        assert f"{link.scheme}://{link.netloc}" == BASE and link.path.startswith("/files/")

        # the link is signed: it opens the file without a token, and nothing else
        fetched = c.get(f"{link.path}?{link.query}")
        assert fetched.status_code == 200 and fetched.content.startswith(PNG)
        assert fetched.headers["content-type"] == "image/png"
        assert c.get(f"{link.path}?e=1&s={'0' * 64}").status_code == 403
        assert c.get(f"{link.path}x?{link.query}").status_code == 403

        # the creation is saved, listed, and searchable by its words (ADR-0041)
        listing = c.get("/products/wasifyai-image/images", headers=auth()).json()
        assert [i["id"] for i in listing["images"]] == [done["image_id"]]
        assert listing["images"][0]["prompt"] == "a red teapot on a wooden table"
        found = c.get("/creations/search", params={"q": "teapot"}, headers=auth())
        assert found.status_code == 200
        assert [h["id"] for h in found.json()["results"]] == [done["image_id"]]

        # a reconnect replays what the run said, from a given event
        run_id = events[0][1]["run_id"]
        again = c.get(f"/runs/{run_id}/events", headers={**auth(), "last-event-id": "1"})
        replay = parse(again.text)
        assert replay[0][1]["seq"] == 2 and replay[-1][0] == "done"


def test_recipes_favourites_and_saving_a_copy_on_the_desktop_profile(data_dir, monkeypatch):
    export = data_dir / "Downloads"
    monkeypatch.setenv("WASIFYAI_EXPORT_DIR", str(export))
    path = "/products/wasifyai-image/images"
    with TestClient(create_app()) as c:
        r = c.post(
            "/products/wasifyai-image/runs",
            json={"input": {"mode": "text", "prompt": "a fox", "size": "wide", "seed": 4242}},
            headers=auth(),
        )
        assert r.status_code == 200, r.text
        made = parse(r.text)[-1][1]["outputs"]
        assert made["status"] == "done"

        # the recipe was kept with the seed that was asked for
        item = c.get(f"{path}/{made['image_id']}", headers=auth()).json()
        assert item["recipe"]["seed"] == 4242 and item["recipe"]["size"] == "wide"
        assert item["favourite"] is False

        # the window may PATCH from its own origin (the browser asks first)
        pre = c.options(
            f"{path}/{made['image_id']}",
            headers={
                "origin": "tauri://localhost",
                "access-control-request-method": "PATCH",
                "access-control-request-headers": "authorization,content-type",
            },
        )
        assert pre.status_code == 200
        assert "PATCH" in pre.headers["access-control-allow-methods"]

        fav = c.patch(f"{path}/{made['image_id']}", json={"favourite": True}, headers=auth())
        assert fav.status_code == 200 and fav.json()["favourite"] is True
        only = c.get(path, params={"favourites": "true"}, headers=auth()).json()
        assert [i["id"] for i in only["images"]] == [made["image_id"]]

        # "Save a copy" puts the file in the export folder and says where
        out = c.post(f"{path}/{made['image_id']}/export", headers=auth())
        assert out.status_code == 200
        saved = export / out.json()["name"]
        assert saved.read_bytes().startswith(PNG) and out.json()["path"] == str(saved)


def test_models_already_on_the_computer_are_found_and_used_in_place(data_dir):
    import struct

    home = data_dir.parent / "home"
    folder = home / "ComfyUI-Shared" / "models" / "loras"
    folder.mkdir(parents=True)
    tensors = ["lora_down.0.weight", "lora_up.0.weight"]  # a LoRA, by its tensor names
    head = json.dumps(
        {n: {"dtype": "F16", "shape": [1], "data_offsets": [0, 2]} for n in tensors}
    ).encode()
    (folder / "style.safetensors").write_bytes(
        struct.pack("<Q", len(head)) + head + b"\0" * 2_000_000
    )

    with TestClient(create_app()) as c:
        # the first scan runs by itself shortly after start; ask for it now and wait
        assert c.get("/desktop/discovery").status_code == 401  # a token is needed like anywhere
        c.post("/desktop/discovery/scan", headers=auth())
        state: dict = {}
        for _ in range(100):
            state = c.get("/desktop/discovery", headers=auth()).json()
            if state["scanned_at"] and not state["running"]:
                break
            time.sleep(0.05)
        assert state["enabled"] is True
        kinds = {(i["name"], i["kind"], i["state"]) for i in state["items"]}
        assert kinds == {("style", "lora", "can_use")}
        assert any(s["tool"] == "ComfyUI" for s in state["scanned"])

        # the switch and an added folder are kept
        put = c.put(
            "/desktop/discovery/settings",
            json={"enabled": False, "folders": [str(home / "elsewhere")]},
            headers=auth(),
        )
        assert put.status_code == 200 and put.json()["enabled"] is False
        assert (
            c.post("/desktop/discovery/use", json={"id": "nope"}, headers=auth()).status_code == 404
        )


def test_styles_the_image_engine_can_apply_are_listed_and_one_click_away(data_dir):
    import struct

    home = data_dir.parent / "home"
    tensors = ["lora_down.0.weight", "lora_up.0.weight"]
    head = json.dumps(
        {n: {"dtype": "F16", "shape": [1], "data_offsets": [0, 2]} for n in tensors}
    ).encode()
    lora = home / "ComfyUI-Shared" / "models" / "loras" / "ink.safetensors"
    lora.parent.mkdir(parents=True)
    lora.write_bytes(struct.pack("<Q", len(head)) + head + b"\0" * 2_000_000)

    with TestClient(create_app()) as c:
        c.post("/desktop/discovery/scan", headers=auth())
        for _ in range(100):
            state = c.get("/desktop/discovery", headers=auth()).json()
            if state["scanned_at"] and not state["running"]:
                break
            time.sleep(0.05)
        listing = c.get("/desktop/loras", headers=auth()).json()
        assert listing["ready"] == []
        (one,) = listing["available"]
        assert one["name"] == "ink.safetensors" and one["use"] == "folder"

        used = c.post("/desktop/discovery/use", json={"id": one["id"]}, headers=auth())
        assert used.status_code == 200
        assert Path(used.json()["folder"]).parts[-2:] == ("ComfyUI-Shared", "models")  # any OS
        ready: list[dict] = []
        for _ in range(100):
            ready = c.get("/desktop/loras", headers=auth()).json()["ready"]
            if ready:
                break
            time.sleep(0.05)
        assert [r["name"] for r in ready] == ["ink.safetensors"]


def test_a_look_taught_for_the_video_model_is_found_but_not_offered_as_a_picture_style(data_dir):
    import struct

    home = data_dir.parent / "home"
    tensors = [
        "transformer_blocks.0.attn1.to_q.lora_A.weight",
        "transformer_blocks.0.attn2.to_q.lora_B.weight",
    ]
    head = json.dumps(
        {n: {"dtype": "BF16", "shape": [1], "data_offsets": [0, 2]} for n in tensors}
    ).encode()
    look = home / "ComfyUI-Shared" / "models" / "loras" / "wasify-video-ena-12345678.safetensors"
    look.parent.mkdir(parents=True)
    look.write_bytes(struct.pack("<Q", len(head)) + head + b"\0" * 2_000_000)

    with TestClient(create_app()) as c:
        c.post("/desktop/discovery/scan", headers=auth())
        state: dict = {}
        for _ in range(100):
            state = c.get("/desktop/discovery", headers=auth()).json()
            if state["scanned_at"] and not state["running"]:
                break
            time.sleep(0.05)
        (one,) = [i for i in state["items"] if i["kind"] == "lora"]
        assert one["family"] == "ltx-video" and "video engine" in one["reason"]
        listing = c.get("/desktop/loras", headers=auth()).json()
        assert listing == {"ready": [], "available": []}  # not offered as a style for pictures


def test_the_engine_refuses_requests_without_the_shells_token(data_dir):
    with TestClient(create_app()) as c:
        body = {"input": {"mode": "text", "prompt": "x"}}
        assert c.post("/products/wasifyai-image/runs", json=body).status_code == 401
        other = {"authorization": f"Bearer {token('another-secret-another-secret-123456')}"}
        assert c.post("/products/wasifyai-image/runs", json=body, headers=other).status_code == 401
        assert c.get("/health").json() == {"status": "ok"}  # the one open route


def test_only_the_enabled_products_are_served(data_dir):
    with TestClient(create_app()) as c:
        for product in ("hello", "media-demo"):
            r = c.post(f"/products/{product}/runs", json={"input": {}}, headers=auth())
            assert r.status_code == 404


def test_creations_and_users_survive_a_restart(data_dir):
    with TestClient(create_app()) as c:
        first = make_image(c)[-1][1]["outputs"]
    with TestClient(create_app()) as c:  # a new process would start the same way
        listing = c.get("/products/wasifyai-image/images", headers=auth()).json()
        assert [i["id"] for i in listing["images"]] == [first["image_id"]]
        link = urlparse(listing["images"][0]["image_url"])
        assert c.get(f"{link.path}?{link.query}").content.startswith(PNG)
        second = make_image(c, "a blue cup")[-1][1]["outputs"]
        ids = [
            i["id"]
            for i in c.get("/products/wasifyai-image/images", headers=auth()).json()["images"]
        ]
        assert ids == [second["image_id"], first["image_id"]]  # newest first, same user


def test_auto_makes_placeholders_until_the_image_engine_is_installed(data_dir, monkeypatch):
    monkeypatch.setenv("DESKTOP_IMAGE_ENGINE", "auto")
    get_settings.cache_clear()
    with TestClient(create_app()) as c:
        out = make_image(c)[-1][1]["outputs"]
    assert out["status"] == "done" and out["width"] == 256  # the placeholder engine's picture


def test_the_real_engine_not_being_set_up_is_said_in_plain_words(data_dir, monkeypatch):
    monkeypatch.setenv("DESKTOP_IMAGE_ENGINE", "comfyui")
    get_settings.cache_clear()
    with TestClient(create_app()) as c:
        events = make_image(c)
    last_name, last = events[-1]
    assert last_name == "error"
    assert (
        "not set up" in last["message"]
        and last["retryable"] is False
        or "set up" in last["message"]
    )


def test_the_engine_mode_must_be_known(data_dir, monkeypatch):
    monkeypatch.setenv("DESKTOP_IMAGE_ENGINE", "magic")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="DESKTOP_IMAGE_ENGINE"):
        with TestClient(create_app()):
            pass


def test_a_second_person_does_not_see_the_first_ones_images(data_dir):
    with TestClient(create_app()) as c:
        make_image(c)
        other = auth(sub="desktop:someone-else")
        assert c.get("/products/wasifyai-image/images", headers=other).json()["images"] == []


def test_the_files_route_is_not_there_on_the_web_profile(monkeypatch, tmp_path):
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "web")
    get_settings.cache_clear()
    try:
        app = create_app()
        assert "/files/{key:path}" not in {getattr(r, "path", "") for r in app.routes}
    finally:
        get_settings.cache_clear()


def test_the_profile_must_be_known(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "laptop")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_the_ready_line_is_one_json_object():
    from wasifyai_api.desktop import READY_EVENT

    line = json.dumps({"event": READY_EVENT, "port": 1, "pid": 2})
    assert json.loads(line)["event"] == "wasifyai.engine.ready"


def test_the_launcher_starts_serves_and_exits_when_the_shell_goes(tmp_path):
    """The real entry point the shell starts: a process on a loopback port that prints one ready
    line, serves with the shell's token, and stops when its stdin closes."""
    import os
    import subprocess
    import sys

    import httpx

    env = {
        **os.environ,
        "DESKTOP_DATA_DIR": str(tmp_path / "data"),
        "API_AUTH_SECRET": SECRET,
        "AUTH_MODE": "jwt",
        "PRODUCTS_DIR": str(PRODUCTS),
        "WASIFYAI_EXIT_ON_STDIN_EOF": "1",
        "DESKTOP_IMAGE_ENGINE": "stub",
        "LOG_LEVEL": "WARNING",
    }
    env.pop("DATABASE_URL", None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "wasifyai_api.desktop"],
        env=env,
        cwd=tmp_path,  # as the shell runs it: a development .env must not be picked up
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        assert proc.stdout is not None
        ready = json.loads(proc.stdout.readline())
        assert ready["event"] == "wasifyai.engine.ready"
        # not `proc.pid`: on Windows a venv's python.exe is a launcher that starts the real one
        assert isinstance(ready["pid"], int) and ready["pid"] > 0
        base = f"http://127.0.0.1:{ready['port']}"
        assert httpx.get(f"{base}/health", timeout=5).json() == {"status": "ok"}

        # a run over real HTTP, through the in-process worker
        with httpx.stream(
            "POST",
            f"{base}/products/wasifyai-image/runs",
            json={"input": {"mode": "text", "prompt": "a lighthouse", "size": "wide"}},
            headers=auth(),
            timeout=30,
        ) as r:
            body = "".join(r.iter_text())
        events = parse(body)
        assert events[-1][0] == "done" and events[-1][1]["outputs"]["status"] == "done"
        assert httpx.get(f"{base}/products/wasifyai-image/images").status_code == 401

        proc.stdin.close()  # type: ignore[union-attr]
        assert proc.wait(timeout=15) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)


def test_notebooks_work_on_the_desktop_profile_and_wait_for_the_search_model(data_dir):
    nb = "/products/wasifyai-notebooks"
    with TestClient(create_app()) as c:
        s = c.get(f"{nb}/status", headers=auth()).json()
        assert s["embedder"]["ready"] is False and s["reader"]["ready"] is False
        assert s["index"]["chunks"] == 0

        made = c.post(f"{nb}/notebooks", json={"title": "Plans"}, headers=auth()).json()
        up = c.post(
            f"{nb}/notebooks/{made['id']}/documents/upload",
            files=[("files", ("plan.md", b"# Plan\n\nLaunch in March with a small beta.\n"))],
            headers=auth(),
        )
        assert up.status_code == 201 and up.json()["created"][0]["status"] == "pending"
        time.sleep(1.5)  # the worker is up, but nothing is read before the search model is here
        docs = c.get(f"{nb}/notebooks/{made['id']}/documents", headers=auth()).json()
        assert [d["status"] for d in docs] == ["pending"]
        # the search needs the model too, and says which piece is missing
        r = c.post(f"{nb}/notebooks/{made['id']}/search", json={"query": "launch"}, headers=auth())
        assert r.status_code == 409 and r.json()["detail"]["code"] == "embedder_missing"
        # the model is listed in the Models panel like the others, with its files and sizes
        models = c.get("/desktop/models", headers=auth()).json()["models"]
        bge = next(m for m in models if m["id"] == "bge-small-en-v1.5")
        assert bge["product_id"] == "wasifyai-notebooks" and bge["bytes_total"] == 67_176_520
        # another person cannot see the notebook
        other = auth(sub="desktop:other")
        assert c.get(f"{nb}/notebooks/{made['id']}", headers=other).status_code == 404
        assert c.get(f"{nb}/notebooks", headers=other).json() == []


def test_a_video_is_made_end_to_end_on_the_desktop_profile(data_dir):
    """The video product is served by default and keeps its clips in the SQLite file."""
    with TestClient(create_app()) as c:
        r = c.post(
            "/products/wasifyai-video/runs",
            json={
                "input": {"mode": "text", "prompt": "a red fox walks through snow", "seconds": 5}
            },
            headers=auth(),
        )
        assert r.status_code == 200, r.text
        events = parse(r.text)
        assert [e for e, _ in events][-1] == "done", events[-1]
        done = events[-1][1]["outputs"]
        assert done["status"] == "done" and done["seconds"] == 5

        listing = c.get("/products/wasifyai-video/videos", headers=auth()).json()
        assert [v["id"] for v in listing["videos"]] == [done["video_id"]]
        assert listing["videos"][0]["status"] == "done"
        link = urlparse(listing["videos"][0]["video_url"])
        assert c.get(f"{link.path}?{link.query}").status_code == 200
        dl = c.get(f"/products/wasifyai-video/videos/{done['video_id']}/download", headers=auth())
        assert dl.status_code == 200 and dl.headers["content-type"] == "video/mp4"

        # one clip at a time, and a clip can be deleted
        assert c.delete(f"/products/wasifyai-video/videos/{done['video_id']}", headers=auth())
        assert c.get("/products/wasifyai-video/videos", headers=auth()).json()["videos"] == []


def test_the_video_model_is_in_the_catalogue_and_search_takes_every_kind(data_dir):
    with TestClient(create_app()) as c:
        models = c.get("/desktop/models", headers=auth()).json()["models"]
        ltx = next(m for m in models if m["id"] == "ltx-video-2b")
        assert ltx["product_id"] == "wasifyai-video" and ltx["approx_ram_gb"] == 14
        # the voice product indexes tracks and voices: a search that finds one must not fail
        for kind in ("track", "voice", "video"):
            r = c.get("/creations/search", params={"q": "fox", "kind": kind}, headers=auth())
            assert r.status_code == 200, (kind, r.text)


def test_the_assistant_is_offered_the_tools_the_desktop_can_run(data_dir):
    app = create_app()
    with TestClient(app):
        host = app.state.services.caps["wasifyai-assistant"].extras["tool_host"]
        # the meta-tools of ADR-0071 always; the notebooks and web search are served by the desktop
        # engine (the assistant offers the two web tools to the model only while Search is on);
        # the outside-tools pair of ADR-0070 on the desktop, where the MCP client lives
        assert host.available_tools() == {
            "how_to",
            "app_status",
            "propose_action",
            "open_screen",
            "search_creations",
            "search_notebooks",
            "web_search",
            "web_read",
            "external_tools",
            "call_external",
        }


def test_a_host_reports_exactly_the_tools_it_was_told_it_can_run(tmp_path, monkeypatch):
    from wasifyai_api.tool_host import ApiToolHost

    served = {
        "search_creations",
        "generate_image",
    }  # what the web's main.py computes: no speech, no notebooks
    host = ApiToolHost(lambda: None, lambda: None, available=lambda: served)
    assert host.available_tools() == served
    assert ApiToolHost(lambda: None, lambda: None).available_tools() is None
