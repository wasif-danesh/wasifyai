"""The 3D component and product through the desktop engine's routes (ADR-0080, TD1): what the window
is told, what a confirmation must carry, that the product's routes are served and need the shell's
token, and that the one big-model slot knows the 3D engine."""

from fastapi.testclient import TestClient
from wasifyai_api.main import create_app

from tests.test_desktop_profile import auth, data_dir  # noqa: F401 (the fixture)

PRODUCT = "/products/wasifyai-model3d/m3d"


def test_the_window_is_told_what_setting_up_3d_would_fetch(data_dir, monkeypatch):  # noqa: F811
    monkeypatch.delenv("WASIFYAI_MODEL3D_HOME", raising=False)
    with TestClient(create_app()) as c:
        state = c.get("/desktop/model3d", headers=auth()).json()
        assert state["installed"] is False and state["source"] is None and state["fit"] is None
        plan = state["plan"]
        assert [p["name"] for p in plan["parts"]] == [
            "3D engine (pixal3d.cpp)",
            "Pixal3D models",
            "Cut-out model (BiRefNet)",
        ]
        assert plan["bytes"] == sum(p["bytes"] for p in plan["parts"]) or not plan["supported"]
        assert any("Built with DINOv3" in p["licence"] for p in plan["parts"])
        assert state["progress"]["state"] == "idle"
        assert state["about"]["built_with"] == "Built with DINOv3"


def test_nothing_is_fetched_unless_the_confirmation_carries_the_size_that_was_shown(
    data_dir,  # noqa: F811
    monkeypatch,
):
    monkeypatch.delenv("WASIFYAI_MODEL3D_HOME", raising=False)
    with TestClient(create_app()) as c:
        r = c.post("/desktop/model3d/install", json={"confirm_bytes": 1}, headers=auth())
        assert r.status_code == 409
        assert "changed since it was shown" in r.text or "not available on this kind" in r.text
        assert c.get("/desktop/model3d", headers=auth()).json()["progress"]["state"] == "idle"


def test_the_routes_need_the_shells_token(data_dir):  # noqa: F811
    with TestClient(create_app()) as c:
        assert c.get("/desktop/model3d").status_code == 401
        assert c.get(f"{PRODUCT}/status").status_code == 401
        assert c.post(f"{PRODUCT}/inputs", content=b"x").status_code == 401


def test_the_product_is_served_and_says_what_to_do_without_the_component(data_dir, monkeypatch):  # noqa: F811
    monkeypatch.delenv("WASIFYAI_MODEL3D_HOME", raising=False)
    with TestClient(create_app()) as c:
        status = c.get(f"{PRODUCT}/status", headers=auth()).json()
        assert status["ready"] is False and status["busy"] is False and status["fit"] is None
        assert "not set up" in status["problem"] or "not available" in status["problem"]
        assert c.get(f"{PRODUCT}/models", headers=auth()).json() == {"items": []}
        r = c.post(f"{PRODUCT}/inputs", content=b"not a picture", headers=auth())
        assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_picture"
        assert c.get(f"{PRODUCT}/models/{'a' * 32}", headers=auth()).status_code == 404


def test_the_engine_knows_3d_as_an_owner_of_the_one_slot(data_dir):  # noqa: F811
    with TestClient(create_app()) as c:
        engine = c.app.state.model3d  # type: ignore[attr-defined]
        assert engine is not None and engine.installer.pins.need_gb >= 18
        assert engine.slot is not None and "model3d" in engine.slot._unloaders  # noqa: SLF001
