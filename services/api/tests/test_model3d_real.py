# ruff: noqa: ASYNC230, ASYNC240  (the tests read and write files on purpose)
"""3D models through the real engine and the real pinned `trellis-cli` (ADR-0080, TD1): a picture is
cut out, looked at, made into a GLB through the product's routes, and a second run is cancelled.

Skipped unless the component is there: set `WASIFYAI_MODEL3D_HOME` to a folder holding `bin/`,
`models/pixal3d-sv/` and `models/matte/`, and `WASIFYAI_MODEL3D_PICTURE` to a picture of one
object. The whole run takes about 10 minutes and holds about 19 GB, so it is also opt-in
(`WASIFYAI_MODEL3D_RUN=1`): no ordinary test run starts it by accident."""

import io
import json
import os
import struct
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from PIL import Image
from wasifyai_api import model3d_runtime as m3
from wasifyai_api.desktop_model3d import Model3dService
from wasifyai_api.services import ApiServices
from wasifyai_model3d.routes import build_routes
from wasifyai_platform_sdk import Identity, RouteDeps

HOME = os.environ.get("WASIFYAI_MODEL3D_HOME")
PICTURE = os.environ.get("WASIFYAI_MODEL3D_PICTURE")
INSTALL = m3.find_install(Path("/nonexistent")) if HOME else None
pytestmark = pytest.mark.skipif(
    INSTALL is None
    or not PICTURE
    or not Path(PICTURE).is_file()
    or os.environ.get("WASIFYAI_MODEL3D_RUN") != "1",
    reason="the 3D component, a picture and WASIFYAI_MODEL3D_RUN=1 are needed (about 10 minutes)",
)

BASE = "/products/wasifyai-model3d/m3d"


def user_of(x_user: str = Header("u1"), x_tenant: str = Header("t1")) -> Identity:
    return Identity(tenant_id=x_tenant, user_id=x_user)


@pytest.fixture(scope="module")
def rig(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("m3d")
    app = FastAPI()
    app.state.services = ApiServices()
    app.state.services.desktop_dir = tmp
    app.state.services.model3d = Model3dService(tmp)
    app.state.services.export_dir = tmp / "exports"
    app.include_router(
        build_routes(RouteDeps(app.state.services, user_of)), prefix="/products/wasifyai-model3d"
    )
    with TestClient(app) as client:
        client.app_state = app.state.services  # type: ignore[attr-defined]
        yield client


def follow(rig, path: str, until, limit_s: float):
    deadline = time.monotonic() + limit_s
    row = {}
    while time.monotonic() < deadline:
        row = rig.get(f"{BASE}{path}").json()
        if until(row):
            return row
        time.sleep(2)
    raise AssertionError(f"never finished: {row}")


def glb_json(data: bytes) -> dict:
    magic, version, length = struct.unpack("<4sII", data[:12])
    assert magic == b"glTF" and version == 2 and length == len(data)
    chunk_len, chunk_type = struct.unpack("<I4s", data[12:20])
    assert chunk_type == b"JSON"
    return json.loads(data[20 : 20 + chunk_len])


def engine_processes() -> list[str]:
    out = subprocess.run(["ps", "-A", "-o", "comm="], capture_output=True, text=True).stdout
    return [line for line in out.splitlines() if Path(line.strip()).name == "trellis-cli"]


def test_a_picture_becomes_a_checked_cutout_and_then_a_real_glb(rig):
    assert PICTURE is not None
    status = rig.get(f"{BASE}/status").json()
    assert status["ready"] is True and status["fit"]["verdict"] in ("fits", "tight")
    added = rig.post(f"{BASE}/inputs?name=object.png", content=Path(PICTURE).read_bytes())
    assert added.status_code == 201, added.text
    picture = follow(rig, f"/inputs/{added.json()['id']}", lambda r: r["status"] != "checking", 300)
    assert picture["status"] == "ready", picture
    assert picture["can_go_on"] is True, picture["checks"]
    cut = Image.open(io.BytesIO(rig.get(f"{BASE}/inputs/{picture['id']}/cutout").content))
    assert cut.mode == "RGBA" and cut.getchannel("A").getextrema() == (0, 255)
    assert [c["code"] for c in picture["checks"]][-1] == "tip"

    started = rig.post(
        f"{BASE}/models",
        json={
            "input_id": picture["id"],
            "title": "Real object",
            "detail": "light",
            "seed": 5,
            "rights": True,
        },
    )
    assert started.status_code == 202, started.text
    mid = started.json()["id"]
    seen: list[tuple[float, str]] = []

    def watch(row):
        seen.append((row["progress"], row["stage"]))
        return row["status"] != "working"

    done = follow(rig, f"/models/{mid}", watch, 40 * 60)
    assert done["status"] == "done", done
    assert done["peak_gb"] and 5 < done["peak_gb"] < 40 and done["elapsed_s"] > 30
    progress = [p for p, _ in seen]
    assert progress == sorted(progress) and any(0.05 < p < 0.99 for p in progress)
    assert {w for _, w in seen if w} & {
        "Building the shape",
        "Painting the surface",
        "Placing the object in space",
    }
    glb = rig.get(f"{BASE}/models/{mid}/file")
    assert glb.status_code == 200 and len(glb.content) > 500_000
    meta = glb_json(glb.content)
    assert "EXT_texture_webp" in meta.get("extensionsRequired", []) and len(meta["meshes"]) == 1
    thumb = Image.open(io.BytesIO(rig.get(f"{BASE}/models/{mid}/thumb").content))
    assert thumb.size == (384, 384)
    leftovers = [
        p.name for p in Path(rig.app_state.desktop_dir).rglob("*") if p.suffix in (".ply",)
    ]
    assert leftovers == []  # the engine's extra files were deleted
    assert engine_processes() == []  # and its memory is free again


def test_a_run_that_is_cancelled_stops_the_engine_and_frees_the_memory(rig):
    items = rig.get(f"{BASE}/models").json()["items"]
    source = next(m for m in items if m["status"] == "done")["input_id"]
    started = rig.post(
        f"{BASE}/models", json={"input_id": source, "detail": "light", "seed": 9, "rights": True}
    )
    assert started.status_code == 202, started.text
    mid = started.json()["id"]
    follow(rig, f"/models/{mid}", lambda r: r["progress"] > 0, 120)
    assert engine_processes() != []
    t = time.monotonic()
    stopped = rig.post(f"{BASE}/models/{mid}/cancel").json()
    assert stopped["stopped"] is True and stopped["status"] == "cancelled"
    assert time.monotonic() - t < 15
    for _ in range(20):
        if not engine_processes():
            break
        time.sleep(0.5)
    assert engine_processes() == []
    assert rig.get(f"{BASE}/status").json()["busy"] is False
    assert SimpleNamespace  # keep the import used when the module is skipped
