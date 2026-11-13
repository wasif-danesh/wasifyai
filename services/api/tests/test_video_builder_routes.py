"""The Motion graphics component through the desktop engine's routes (V1a): what the window is told,
what a confirmation must carry, and that the routes need the shell's token."""

from dataclasses import replace

from fastapi.testclient import TestClient
from wasifyai_api.main import create_app

from tests.test_desktop_profile import auth, data_dir  # noqa: F401 (the fixture)


def test_the_window_is_told_what_setting_it_up_would_fetch(data_dir, monkeypatch):  # noqa: F811
    monkeypatch.delenv("WASIFYAI_VIDEO_BUILDER_HOME", raising=False)
    with TestClient(create_app()) as c:
        state = c.get("/desktop/video-builder", headers=auth()).json()
        assert state["installed"] is False and state["source"] is None
        plan = state["plan"]
        assert {p["name"] for p in plan["parts"]} == {
            "Node.js",
            "Chrome headless shell",
            "HyperFrames and GSAP",
            "FFmpeg and ffprobe",
        }
        assert plan["bytes"] == sum(p["bytes"] for p in plan["parts"]) or not plan["supported"]
        assert state["progress"]["state"] == "idle"
        assert "nothing outside its own folder" in state["sandbox"]["network"]


def test_nothing_is_fetched_unless_the_confirmation_carries_the_size_that_was_shown(
    data_dir,  # noqa: F811
    monkeypatch,
):
    monkeypatch.delenv("WASIFYAI_VIDEO_BUILDER_HOME", raising=False)
    app = create_app()
    with TestClient(app) as c:
        service = app.state.services.video_builder
        service.installer.pins = replace(service.installer.pins, platforms=(_here(),))
        wrong = c.post("/desktop/video-builder/install", json={"confirm_bytes": 1}, headers=auth())
        assert wrong.status_code == 409 and "changed since it was shown" in wrong.json()["detail"]
        assert not service.installer.running
        assert not (data_dir / "components").exists()  # not even the folder


def test_a_computer_it_was_not_measured_on_is_told_so(data_dir, monkeypatch):  # noqa: F811
    monkeypatch.delenv("WASIFYAI_VIDEO_BUILDER_HOME", raising=False)
    app = create_app()
    with TestClient(app) as c:
        service = app.state.services.video_builder
        service.installer.pins = replace(service.installer.pins, platforms=("some-other-system",))
        r = c.post("/desktop/video-builder/install", json={"confirm_bytes": 0}, headers=auth())
        assert (
            r.status_code == 409 and "not available on this kind of computer" in r.json()["detail"]
        )


def test_removing_what_is_not_there_frees_nothing(data_dir, monkeypatch):  # noqa: F811
    monkeypatch.delenv("WASIFYAI_VIDEO_BUILDER_HOME", raising=False)
    with TestClient(create_app()) as c:
        r = c.post("/desktop/video-builder/uninstall", headers=auth())
        assert (
            r.status_code == 200 and r.json()["freed_bytes"] == 0 and r.json()["installed"] is False
        )


def test_the_routes_need_the_shells_token(data_dir):  # noqa: F811
    with TestClient(create_app()) as c:
        assert c.get("/desktop/video-builder").status_code in (401, 403)
        assert c.post("/desktop/video-builder/install", json={"confirm_bytes": 1}).status_code in (
            401,
            403,
        )
        assert c.post("/desktop/video-builder/uninstall").status_code in (401, 403)


def _here() -> str:
    from wasifyai_api.audio_runtime import platform_key

    return platform_key()
