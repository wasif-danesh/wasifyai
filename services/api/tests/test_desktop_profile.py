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

        # the job went through the queue and the worker, and its progress reached the stream
        jobs = [d for e, d in events if e == "job_progress"]
        assert [j["status"] for j in jobs][0] == "queued" and jobs[-1]["status"] == "completed"
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


def test_the_engine_refuses_requests_without_the_shells_token(data_dir):
    with TestClient(create_app()) as c:
        body = {"input": {"mode": "text", "prompt": "x"}}
        assert c.post("/products/wasifyai-image/runs", json=body).status_code == 401
        other = {"authorization": f"Bearer {token('another-secret-another-secret-123456')}"}
        assert c.post("/products/wasifyai-image/runs", json=body, headers=other).status_code == 401
        assert c.get("/health").json() == {"status": "ok"}  # the one open route


def test_only_the_enabled_products_are_served(data_dir):
    with TestClient(create_app()) as c:
        for product in ("wasifyai-music", "hello", "media-demo"):
            r = c.post(f"/products/{product}/runs", json={"input": {}}, headers=auth())
            assert r.status_code == 404
        assert c.get("/products/wasifyai-music/songs", headers=auth()).status_code == 404


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
