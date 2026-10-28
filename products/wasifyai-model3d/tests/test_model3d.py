"""3D models (ADR-0080, TD1) on stand-ins: the picture checks, the store, the routes, the job
manager, the action and the library kind, with a real SQLite store and a stand-in 3D engine (the
real engine: `services/api/tests/test_model3d_real.py`, run with `WASIFYAI_MODEL3D_HOME`)."""

import asyncio
import io
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from wasifyai_model3d import files, pictures
from wasifyai_model3d.actions import actions, library_kinds
from wasifyai_model3d.index import Model3dIndexSource
from wasifyai_model3d.routes import build_routes
from wasifyai_model3d.store import LEFT_RUNNING, Model3dStore, NotFound
from wasifyai_platform_sdk import EngineServices, Identity, RouteDeps
from wasifyai_platform_sdk.actions import ActionExecutor, ActionRegistry, builtin_actions
from wasifyai_platform_sdk.actions.model import Readiness, need_runtime
from wasifyai_platform_sdk.actions.testing import FakeActionHost
from wasifyai_platform_sdk.sqlite import create_sqlite_engine

BASE = "/products/wasifyai-model3d/m3d"
ME = Identity("t1", "u1")


# ---- pictures -----------------------------------------------------------------------------------


def blob(img: Image.Image, fmt: str = "PNG") -> bytes:
    out = io.BytesIO()
    img.save(out, fmt)
    return out.getvalue()


def photo(size=(600, 400)) -> bytes:
    return blob(Image.new("RGB", size, (200, 190, 170)))


def cutout(box=(200, 100, 400, 300), size=(600, 400), extra=None) -> Image.Image:
    """A transparent picture with one opaque ellipse (and perhaps another)."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse(box, fill=(40, 160, 70, 255))
    if extra:
        d.ellipse(extra, fill=(160, 40, 70, 255))
    return img


def codes(img: Image.Image) -> list[str]:
    return [c["code"] for c in pictures.check_cutout(img)]


def test_a_picture_is_read_brought_to_a_size_the_engine_takes_and_stripped_of_its_orientation():
    img = pictures.open_picture(blob(Image.new("RGB", (4000, 3000), "white"), "JPEG"))
    assert img.mode == "RGBA" and max(img.size) == pictures.LONG_SIDE and img.size == (2048, 1536)
    assert pictures.open_picture(blob(Image.new("RGB", (300, 200), "white"), "WEBP")).size == (
        300,
        200,
    )


@pytest.mark.parametrize(
    ("data", "words"),
    [  # explicit ids: a parameter is part of the test's name, and the 20 MB one was printed whole
        pytest.param(b"", "empty", id="empty"),
        pytest.param(b"not a picture at all", "could not be read", id="not-a-picture"),
        pytest.param(blob(Image.new("RGB", (60, 60), "white")), "too small", id="too-small"),
        pytest.param(b"x" * (pictures.MAX_BYTES + 1), "under 20 MB", id="too-big"),
        pytest.param(blob(Image.new("P", (300, 300)), "GIF"), "PNG, JPEG or WebP", id="gif"),
    ],
)
def test_a_file_that_cannot_be_used_is_refused_in_words(data, words):
    with pytest.raises(pictures.BadPicture, match=words):
        pictures.open_picture(data)


def test_a_picture_that_is_already_cut_out_is_noticed():
    assert pictures.has_real_alpha(cutout()) is True
    assert pictures.has_real_alpha(Image.new("RGBA", (300, 200), (10, 10, 10, 255))) is False


def test_a_good_cutout_says_so_and_always_ends_with_the_tip():
    checks = pictures.check_cutout(cutout())
    assert [c["code"] for c in checks] == ["one_object", "tip"]
    assert checks[0]["level"] == "ok" and "all of it showing" in checks[0]["message"]
    assert "straight-on" in checks[-1]["message"] and "Glass, mirrors" in checks[-1]["message"]


def test_nothing_in_the_picture_stops_it():
    checks = pictures.check_cutout(Image.new("RGBA", (300, 200), (0, 0, 0, 0)))
    assert [c["level"] for c in checks] == ["stop", "ok"] and checks[0]["code"] == "no_object"
    assert "No object was found" in checks[0]["message"]


@pytest.mark.parametrize(
    ("img", "code"),
    [
        (cutout(box=(-40, 100, 160, 300)), "cut_off"),
        (cutout(box=(280, 180, 320, 220)), "small"),
        (cutout(box=(0, 0, 80, 80), size=(1000, 1000)), "off_centre"),
        (cutout(box=(80, 120, 240, 280), extra=(340, 120, 500, 280)), "several"),
    ],
)
def test_each_problem_with_the_object_is_a_warning_in_its_own_words(img, code):
    got = pictures.check_cutout(img)
    warn = [c for c in got if c["code"] == code]
    assert warn and warn[0]["level"] == "warn" and "one_object" not in codes(img)


def test_a_small_second_blob_does_not_count_as_a_second_object():
    assert "several" not in codes(cutout(box=(150, 80, 450, 320), extra=(470, 340, 480, 350)))


def test_the_thumbnail_is_a_square_picture_of_the_object_on_a_light_ground():
    jpg = pictures.thumbnail(cutout())
    img = Image.open(io.BytesIO(jpg))
    assert img.format == "JPEG" and img.size == (384, 384)
    rgb = img.convert("RGB")
    assert rgb.getpixel((2, 2)) == (242, 242, 240)  # the ground, not the object
    r, g, b = rgb.getpixel((192, 192))  # type: ignore[misc]
    assert g > r and g > b  # the green object in the middle


# ---- the store ---------------------------------------------------------------------------------


def test_the_store_keeps_models_per_person_and_renames_them(tmp_path):
    store = Model3dStore(tmp_path)
    a = store.add_model("t1", "u1", title="Frog mug", prompt="a frog mug", input_id=None,
                        detail="standard", seed=7, recipe={"seed": 7})  # fmt: skip
    store.add_model("t1", "u2", title="Other", prompt="", input_id=None, detail="light", seed=1,
                    recipe={})  # fmt: skip
    assert [m["title"] for m in store.list_models("t1", "u1")] == ["Frog mug"]
    with pytest.raises(NotFound):
        store.get_model("t1", "u2", a["id"])  # not another person's
    assert store.get_model("t1", "u1", a["id"])["recipe"] == {"seed": 7}
    assert store.rename_model("t1", "u1", a["id"], "Green frog")["title"] == "Green frog"
    with pytest.raises(NotFound):
        store.rename_model("t1", "u2", a["id"], "mine now")
    store.set_progress(a["id"], 0.4, "Building the shape")
    assert store.get_model("t1", "u1", a["id"])["progress"] == 0.4
    store.finish_model(a["id"], "done", elapsed_s=600.0, peak_gb=18.7, glb_bytes=35_000_000)
    done = store.get_model("t1", "u1", a["id"])
    assert done["status"] == "done" and done["progress"] == 1 and done["glb_bytes"] == 35_000_000
    store.set_progress(a["id"], 0.2, "late")  # a finished model does not move back
    assert store.get_model("t1", "u1", a["id"])["progress"] == 1
    assert store.delete_model("t1", "u1", a["id"]) is True and store.list_models("t1", "u1") == []


def test_a_model_left_working_by_a_process_that_is_gone_is_failed_when_the_store_opens(tmp_path):
    store = Model3dStore(tmp_path)
    row = store.add_model("t1", "u1", title="x", prompt="", input_id=None, detail="light",
                          seed=1, recipe={})  # fmt: skip
    pic = store.add_input("t1", "u1", "p.png", 300, 200)
    again = Model3dStore(tmp_path)
    assert again.get_model("t1", "u1", row["id"])["status"] == "failed"
    assert again.get_model("t1", "u1", row["id"])["error"] == LEFT_RUNNING
    assert again.get_input("t1", "u1", pic["id"])["status"] == "failed"


def test_old_pictures_nobody_made_a_model_from_are_purged_but_a_used_one_stays(tmp_path):
    store = Model3dStore(tmp_path)
    used = store.add_input("t1", "u1", "a", 300, 200)
    spare = store.add_input("t1", "u1", "b", 300, 200)
    store.add_model("t1", "u1", title="x", prompt="", input_id=used["id"], detail="light", seed=1,
                    recipe={})  # fmt: skip
    gone = store.purge_inputs("9999-01-01")
    assert gone == [("t1", "u1", spare["id"])]
    assert store.get_input("t1", "u1", used["id"])["id"] == used["id"]
    with pytest.raises(NotFound):
        store.get_input("t1", "u1", spare["id"])


def test_the_folder_of_an_item_is_inside_the_store_and_refuses_a_path(tmp_path):
    store = Model3dStore(tmp_path)
    folder = store.folder_of("desktop:local", "../../etc", "models", "a" * 32)
    assert tmp_path in folder.parents and ".." not in folder.parts
    with pytest.raises(ValueError):
        store.folder_of("t", "u", "models", "../../x")


# ---- the routes and the job manager ------------------------------------------------------


class FakeEngine:
    """The engine's side, scripted: what `state.model3d` offers the product."""

    def __init__(self) -> None:
        self.ok = True
        self.verdict = "fits"
        self.mode = "ok"
        self.hold = False
        self.release = asyncio.Event()
        self.matted: list[Path] = []
        self.made: list[dict[str, Any]] = []
        self.installer = SimpleNamespace(supported=True)

    def ready(self) -> bool:
        return self.ok

    def problem(self) -> str | None:
        return None if self.ok else "The 3D component is not set up yet. Set it up first."

    def fit(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "reason": f"It {self.verdict}."}

    async def matte(self, picture: Path, out_dir: Path, on_line=None):
        self.matted.append(picture)
        if self.mode == "cutout_fails":
            return SimpleNamespace(ok=False, output=None, message="The cut-out did not work.")
        img = {"empty": Image.new("RGBA", (600, 400), (0, 0, 0, 0)),
               "cut_off": cutout(box=(-50, 100, 150, 300))}.get(self.mode, cutout())  # fmt: skip
        out = out_dir / "unused_cutout.png"
        await asyncio.to_thread(img.save, out, "PNG")
        return SimpleNamespace(ok=True, output=out, message="", seconds=1.0, peak_gb=5.5)

    async def generate(self, cutout_path, out_glb, *, seed=42, detail="standard", on_line=None,
                       on_progress=None):  # fmt: skip
        self.made.append({"cutout": cutout_path, "glb": out_glb, "seed": seed, "detail": detail})
        for fraction, words in ((0.1, "Placing the object in space"), (0.5, "Building the shape")):
            if on_progress:
                on_progress(fraction, words)
        if self.hold:
            await self.release.wait()
        if self.mode == "fails":
            return SimpleNamespace(
                ok=False, output=None, message="The 3D engine stopped with an error.",
                seconds=2.0, peak_gb=1.0,
            )  # fmt: skip
        await asyncio.to_thread(out_glb.write_bytes, b"glTF" + str(seed).encode())
        return SimpleNamespace(
            ok=True, output=out_glb, message="Done.", seconds=611.0, peak_gb=18.7
        )


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
    app = FastAPI()
    app.state.services = EngineServices()
    app.state.services.desktop_dir = tmp_path
    app.state.services.model3d = FakeEngine()
    app.state.services.creation_index = Index()
    app.state.services.export_dir = tmp_path / "exports"
    app.include_router(
        build_routes(RouteDeps(app.state.services, user_of)), prefix="/products/wasifyai-model3d"
    )
    with TestClient(app) as client:
        client.app_state = app.state.services  # type: ignore[attr-defined]
        yield client


def wait(rig, path: str, until, headers=None) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for _ in range(300):
        row = rig.get(f"{BASE}{path}", headers=headers or {}).json()
        if until(row):
            return row
        time.sleep(0.02)
    raise AssertionError(f"never: {row}")


def add_picture(rig, data: bytes | None = None, **headers) -> dict[str, Any]:
    r = rig.post(f"{BASE}/inputs?name=frog.png", content=data or photo(), headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def ready_picture(rig, data=None) -> dict[str, Any]:
    made = add_picture(rig, data)
    return wait(rig, f"/inputs/{made['id']}", lambda r: r["status"] != "checking")


def make(rig, input_id: str, **body: Any):
    body = {"input_id": input_id, "rights": True, **body}
    return rig.post(f"{BASE}/models", json=body)


def test_a_picture_is_cut_out_and_looked_at_and_its_checks_are_said_in_words(rig):
    row = ready_picture(rig)
    assert row["status"] == "ready" and row["can_go_on"] is True and row["width"] == 600
    assert [c["code"] for c in row["checks"]] == ["one_object", "tip"]
    engine = rig.app_state.model3d
    assert len(engine.matted) == 1 and engine.matted[0].name == "picture.png"
    cut = rig.get(f"{BASE}/inputs/{row['id']}/cutout")
    assert cut.status_code == 200 and cut.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(cut.content)).mode == "RGBA"
    assert rig.get(f"{BASE}/inputs/{row['id']}/picture").status_code == 200
    assert rig.get(f"{BASE}/inputs/{row['id']}/other").status_code == 404


def test_a_picture_that_is_already_cut_out_is_not_cut_again(rig):
    row = ready_picture(rig, blob(cutout()))
    assert row["status"] == "ready" and rig.app_state.model3d.matted == []
    assert (
        Image.open(io.BytesIO(rig.get(f"{BASE}/inputs/{row['id']}/cutout").content)).mode == "RGBA"
    )


def test_bad_pictures_and_pictures_with_nothing_in_them_are_refused_in_words(rig):
    r = rig.post(f"{BASE}/inputs", content=b"nope")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_picture"
    assert "could not be read" in r.json()["detail"]["message"]
    rig.app_state.model3d.mode = "empty"
    row = ready_picture(rig)
    assert row["status"] == "ready" and row["can_go_on"] is False
    assert row["checks"][0]["code"] == "no_object"
    made = make(rig, row["id"])
    assert made.status_code == 422 and made.json()["detail"]["code"] == "unusable"


def test_a_cutout_that_fails_says_so_and_leaves_nothing_to_make(rig):
    rig.app_state.model3d.mode = "cutout_fails"
    row = ready_picture(rig)
    assert row["status"] == "failed" and row["error"] == "The cut-out did not work."
    assert make(rig, row["id"]).status_code == 409


def test_a_warning_does_not_stop_the_person_it_is_told(rig):
    rig.app_state.model3d.mode = "cut_off"
    row = ready_picture(rig)
    assert row["can_go_on"] is True
    assert "cut_off" in [c["code"] for c in row["checks"]]
    assert make(rig, row["id"]).status_code == 202


def test_a_model_needs_the_person_to_say_they_may_use_the_picture(rig):
    row = ready_picture(rig)
    r = rig.post(f"{BASE}/models", json={"input_id": row["id"]})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "no_rights"
    assert "not a photo of a real person" in r.json()["detail"]["message"]


def test_a_model_is_made_with_progress_and_becomes_a_creation_the_library_can_find(rig):
    row = ready_picture(rig)
    r = make(
        rig, row["id"], title="Frog mug", prompt="a ceramic frog mug", detail="detailed", seed=7
    )
    assert r.status_code == 202, r.text
    started = r.json()
    assert started["status"] == "working" and started["title"] == "Frog mug"
    assert rig.app_state.creation_index.items[started["id"]] == (
        "model3d",
        "Frog mug. a ceramic frog mug",
    )
    done = wait(rig, f"/models/{started['id']}", lambda m: m["status"] != "working")
    assert done["status"] == "done" and done["progress"] == 1 and done["glb_bytes"] == 5
    assert done["elapsed_s"] == 611.0 and done["peak_gb"] == 18.7 and done["live"] is False
    assert done["recipe"]["detail"] == "detailed" and done["recipe"]["seed"] == 7
    assert done["recipe"]["licence"].endswith("Built with DINOv3")
    glb = rig.get(f"{BASE}/models/{started['id']}/file")
    assert glb.content == b"glTF7" and glb.headers["content-type"] == "model/gltf-binary"
    assert 'filename="frog-mug.glb"' in glb.headers["content-disposition"]
    thumb = rig.get(f"{BASE}/models/{started['id']}/thumb")
    assert thumb.headers["content-type"] == "image/jpeg" and Image.open(
        io.BytesIO(thumb.content)
    ).size == (384, 384)
    assert rig.get(f"{BASE}/models/{started['id']}/source").status_code == 200
    made = rig.app_state.model3d.made[0]
    assert (
        made["seed"] == 7 and made["detail"] == "detailed" and made["cutout"].name == "cutout.png"
    )
    folder = made["glb"].parent
    assert sorted(p.name for p in folder.iterdir()) == [
        "cutout.png",
        "model.glb",
        "source.png",
        "thumb.jpg",
    ]
    listed = rig.get(f"{BASE}/models").json()["items"]
    assert [m["id"] for m in listed] == [started["id"]]
    assert rig.get(f"{BASE}/models?ids={started['id']}").json()["items"][0]["title"] == "Frog mug"


def test_progress_and_the_stage_are_followed_while_it_works(rig):
    engine = rig.app_state.model3d
    engine.hold = True
    started = make(rig, ready_picture(rig)["id"], title="Slow").json()
    live = wait(rig, f"/models/{started['id']}", lambda m: m["progress"] >= 0.5)
    assert (
        live["status"] == "working"
        and live["stage"] == "Building the shape"
        and live["live"] is True
    )
    status = rig.get(f"{BASE}/status").json()
    assert status["busy"] is True and status["active"] == {"kind": "model", "id": started["id"]}
    engine.release.set()
    wait(rig, f"/models/{started['id']}", lambda m: m["status"] == "done")
    assert rig.get(f"{BASE}/status").json()["busy"] is False


def test_only_one_job_at_a_time_and_the_reason_is_said(rig):
    engine = rig.app_state.model3d
    engine.hold = True
    first = ready_picture(rig)
    started = make(rig, first["id"]).json()
    second = make(rig, first["id"])
    assert second.status_code == 409 and second.json()["detail"]["code"] == "busy"
    assert "already being made" in second.json()["detail"]["message"]
    busy_picture = rig.post(f"{BASE}/inputs", content=photo())
    assert busy_picture.status_code == 409 and busy_picture.json()["detail"]["code"] == "busy"
    engine.release.set()
    wait(rig, f"/models/{started['id']}", lambda m: m["status"] == "done")


def test_cancel_stops_it_keeps_no_file_and_frees_the_slot(rig):
    engine = rig.app_state.model3d
    engine.hold = True
    started = make(rig, ready_picture(rig)["id"]).json()
    wait(rig, f"/models/{started['id']}", lambda m: m["progress"] > 0)
    stopped = rig.post(f"{BASE}/models/{started['id']}/cancel").json()
    assert stopped["stopped"] is True and stopped["status"] == "cancelled"
    assert rig.get(f"{BASE}/models/{started['id']}/file").status_code == 404
    assert rig.get(f"{BASE}/status").json()["busy"] is False
    assert rig.post(f"{BASE}/models/{started['id']}/cancel").json()["stopped"] is False  # over


def test_a_run_that_fails_says_why_and_keeps_no_file(rig):
    rig.app_state.model3d.mode = "fails"
    started = make(rig, ready_picture(rig)["id"]).json()
    row = wait(rig, f"/models/{started['id']}", lambda m: m["status"] != "working")
    assert row["status"] == "failed" and row["error"] == "The 3D engine stopped with an error."
    assert rig.get(f"{BASE}/models/{started['id']}/file").status_code == 404


def test_without_the_component_a_computer_that_cannot_fit_it_and_bad_choices_are_said(rig):
    engine = rig.app_state.model3d
    picture = ready_picture(rig)
    engine.verdict = "too_big"
    r = make(rig, picture["id"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "too_big"
    engine.verdict = "fits"
    assert make(rig, picture["id"], detail="huge").status_code == 422
    assert make(rig, picture["id"], seed=-1).status_code == 422
    engine.ok = False
    r = make(rig, picture["id"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_ready"
    assert "not set up" in r.json()["detail"]["message"]
    assert rig.post(f"{BASE}/inputs", content=photo()).status_code == 409
    status = rig.get(f"{BASE}/status").json()
    assert status["ready"] is False and "not set up" in status["problem"] and status["fit"] is None


def test_making_it_again_gives_the_same_model_as_a_new_one(rig):
    first = make(rig, ready_picture(rig)["id"], title="Frog", seed=9).json()
    wait(rig, f"/models/{first['id']}", lambda m: m["status"] == "done")
    again = rig.post(f"{BASE}/models/{first['id']}/again")
    assert again.status_code == 202
    second = again.json()
    assert second["id"] != first["id"] and second["seed"] == 9 and second["title"] == "Frog"
    wait(rig, f"/models/{second['id']}", lambda m: m["status"] == "done")
    one, two = (rig.get(f"{BASE}/models/{m['id']}/file").content for m in (first, second))
    assert one == two == b"glTF9"


def test_a_model_is_renamed_and_found_by_its_new_name(rig):
    started = make(rig, ready_picture(rig)["id"], title="Frog", prompt="a frog mug").json()
    wait(rig, f"/models/{started['id']}", lambda m: m["status"] == "done")
    renamed = rig.patch(f"{BASE}/models/{started['id']}", json={"title": "Green frog"}).json()
    assert renamed["title"] == "Green frog"
    assert rig.app_state.creation_index.items[started["id"]][1] == "Green frog. a frog mug"
    assert rig.patch(f"{BASE}/models/{started['id']}", json={"title": ""}).status_code == 422


def test_a_copy_is_saved_where_the_save_as_box_chose(rig, tmp_path_factory):
    started = make(rig, ready_picture(rig)["id"], title="Frog mug").json()
    wait(rig, f"/models/{started['id']}", lambda m: m["status"] == "done")
    chosen = tmp_path_factory.mktemp("Desktop") / "mine.glb"  # not in the app's own folder
    r = rig.post(f"{BASE}/models/{started['id']}/export", json={"path": str(chosen)})
    assert r.status_code == 200 and chosen.read_bytes() == b"glTF42"
    inside = rig.app_state.desktop_dir / "stolen.glb"  # the app's own data is never written
    bad = rig.post(f"{BASE}/models/{started['id']}/export", json={"path": str(inside)})
    assert bad.status_code == 422 and "belongs to the app" in bad.json()["detail"]


def test_a_copy_is_saved_to_the_export_folder_and_never_replaces_a_file(rig):
    started = make(rig, ready_picture(rig)["id"], title="Frog mug").json()
    wait(rig, f"/models/{started['id']}", lambda m: m["status"] == "done")
    first = rig.post(f"{BASE}/models/{started['id']}/export").json()
    second = rig.post(f"{BASE}/models/{started['id']}/export").json()
    assert first["name"] == "frog-mug.glb" and second["name"] == "frog-mug-2.glb"
    assert Path(first["path"]).read_bytes() == b"glTF42"
    rig.app_state.export_dir = None
    assert rig.post(f"{BASE}/models/{started['id']}/export").status_code == 404


def test_another_person_sees_nothing_and_deleting_another_persons_model_does_nothing(rig):
    other = {"x-user": "u2"}
    picture = ready_picture(rig)
    started = make(rig, picture["id"], title="Mine").json()
    wait(rig, f"/models/{started['id']}", lambda m: m["status"] == "done")
    for path in (
        f"/models/{started['id']}",
        f"/models/{started['id']}/file",
        f"/inputs/{picture['id']}",
    ):
        assert rig.get(f"{BASE}{path}", headers=other).status_code == 404
    assert rig.post(f"{BASE}/models/{started['id']}/cancel", headers=other).status_code == 404
    assert rig.get(f"{BASE}/models", headers=other).json()["items"] == []
    assert rig.delete(f"{BASE}/models/{started['id']}", headers=other).status_code == 204
    assert rig.get(f"{BASE}/models/{started['id']}").status_code == 200  # and it is still there


def test_deleting_a_model_removes_its_files_and_its_search_entry_and_stops_it_first(rig):
    engine = rig.app_state.model3d
    started = make(rig, ready_picture(rig)["id"], title="Gone").json()
    wait(rig, f"/models/{started['id']}", lambda m: m["status"] == "done")
    folder = engine.made[0]["glb"].parent
    assert folder.is_dir() and started["id"] in rig.app_state.creation_index.items
    assert rig.delete(f"{BASE}/models/{started['id']}").status_code == 204
    assert not folder.exists() and started["id"] not in rig.app_state.creation_index.items
    assert rig.get(f"{BASE}/models/{started['id']}").status_code == 404
    engine.hold = True  # one that is still being made
    running = make(rig, ready_picture(rig)["id"]).json()
    wait(rig, f"/models/{running['id']}", lambda m: m["progress"] > 0)
    assert rig.delete(f"{BASE}/models/{running['id']}").status_code == 204
    assert rig.get(f"{BASE}/status").json()["busy"] is False


def test_a_picture_can_be_thrown_away_and_a_missing_one_is_fine(rig):
    picture = ready_picture(rig)
    assert rig.delete(f"{BASE}/inputs/{picture['id']}").status_code == 204
    assert rig.get(f"{BASE}/inputs/{picture['id']}").status_code == 404
    assert rig.delete(f"{BASE}/inputs/{picture['id']}").status_code == 204


def test_where_there_is_no_engine_the_routes_are_not_there(tmp_path):
    app = FastAPI()
    app.state.services = EngineServices()
    app.state.services.desktop_dir = tmp_path
    app.include_router(
        build_routes(RouteDeps(app.state.services, user_of)), prefix="/products/wasifyai-model3d"
    )
    with TestClient(app) as c:
        assert c.get(f"{BASE}/status").status_code == 404
        assert c.get(f"{BASE}/models").status_code == 404


# ---- search ---------------------------------------------------------------------------------


async def test_models_are_found_by_their_title_and_the_words_they_were_made_from(tmp_path):
    engine = create_sqlite_engine(tmp_path / "wasifyai.db")
    store = Model3dStore(tmp_path / "model3d")
    a = store.add_model("t1", "u1", title="Frog mug", prompt="a ceramic frog mug", input_id=None,
                        detail="standard", seed=1, recipe={})  # fmt: skip
    b = store.add_model("t1", "u1", title="Chair", prompt="", input_id=None, detail="light",
                        seed=1, recipe={})  # fmt: skip
    source = Model3dIndexSource(engine)
    items = await source.page(None, 50)
    by_id = {i.item_id: (i.kind, i.text) for i in items}
    assert (
        by_id[a["id"]] == ("model3d", "Frog mug. a ceramic frog mug")
        and by_id[b["id"]][1] == "Chair"
    )
    assert await source.present([a["id"], "nope"]) == {a["id"]}
    assert await source.page(max(a["id"], b["id"]), 50) == []
    store.delete_model("t1", "u1", a["id"])
    assert await source.present([a["id"]]) == set()
    await engine.dispose()


# ---- the action and the library kind ----------------------------------------------------------


class ActionRig:
    def __init__(self, tmp_path: Path, pictures_: dict[str, bytes]):
        self.state = EngineServices(
            desktop_dir=tmp_path, model3d=FakeEngine(), creation_index=Index(),
            export_dir=tmp_path / "exports",
        )  # fmt: skip
        self.host = FakeActionHost(RouteDeps(self.state, lambda: ME))
        kinds = {k.kind: k for k in library_kinds()}

        async def read(ctx, item_id):
            return pictures_.get(item_id)

        from wasifyai_platform_sdk.actions import LibraryKind

        kinds["image"] = LibraryKind(
            "image", "wasifyai-image", "picture", _none, _none_get, _none_del, read=read
        )
        self.ex = ActionExecutor(
            ActionRegistry([*builtin_actions(), *actions()]), self.host, library=kinds
        )

    async def go(self, action_id: str, params: dict, origin="window", **kw):
        return await self.ex.run_action(action_id, params, origin, actor=ME, **kw)


async def _none(ctx, limit):
    return []


async def _none_get(ctx, item_id):
    return None


async def _none_del(ctx, item_id):
    return False


@pytest.fixture
def arig(tmp_path):
    return ActionRig(tmp_path, {"p1": photo(), "bad": b"junk"})


async def test_a_model_is_made_from_a_picture_of_the_library_through_the_catalogue(arig):
    r = await arig.go(
        "model3d.generate", {"image_id": "p1", "title": "Frog", "seed": 3}, person_approved=True
    )
    assert r.status == "ok", r
    assert r.output["uri"].startswith("wasify://creation/model3d/") and r.output["seconds"] == 611
    assert "about 10 minutes" in r.text and arig.state.model3d.made[0]["seed"] == 3
    listed = await arig.go("library.list", {"kind": "model3d"})
    assert [i["id"] for i in listed.output["items"]] == [r.output["model_id"]]
    got = await arig.go("library.get", {"kind": "model3d", "id": r.output["model_id"]})
    assert got.output["item"]["title"] == "Frog"


async def test_the_action_is_costly_long_asks_first_and_is_told_what_it_needs(arig):
    action = arig.ex.registry.get("model3d.generate")
    assert (
        action is not None and action.effect == "make" and action.long and "costly" in action.flags
    )
    assert action.ui == "model3d" and action.product == "wasifyai-model3d"
    assert "5 to 25 minutes" in action.description and "image.generate" in action.description
    asked = await arig.go("model3d.generate", {"image_id": "p1"}, origin="assistant")
    assert asked.status == "needs_approval" and arig.state.model3d.made == []
    arig.host.not_ready(
        need_runtime("model3d"), Readiness.needs_setup("Set up 3D first.", ui="model3d")
    )
    r = await arig.go("model3d.generate", {"image_id": "p1"}, person_approved=True)
    assert r.status == "needs_setup" and "Set up 3D" in r.text


async def test_a_picture_that_is_missing_or_not_a_picture_or_empty_is_refused_in_words(arig):
    gone = await arig.go("model3d.generate", {"image_id": "nope"}, person_approved=True)
    assert gone.status == "refused" and "not in the library" in gone.text
    bad = await arig.go("model3d.generate", {"image_id": "bad"}, person_approved=True)
    assert bad.status == "refused" and "could not be read" in bad.text
    arig.state.model3d.mode = "empty"
    empty = await arig.go("model3d.generate", {"image_id": "p1"}, person_approved=True)
    assert empty.status == "refused" and "No object was found" in empty.text
    arig.state.model3d.mode = "fails"
    failed = await arig.go("model3d.generate", {"image_id": "p1"}, person_approved=True)
    assert failed.status == "error" and "stopped with an error" in failed.text


async def test_the_library_renames_saves_a_copy_reads_and_deletes_a_model(arig):
    made = await arig.go(
        "model3d.generate", {"image_id": "p1", "title": "Frog"}, person_approved=True
    )
    mid = made.output["model_id"]
    renamed = await arig.go("library.rename", {"kind": "model3d", "id": mid, "title": "Green frog"},
                            person_approved=True)  # fmt: skip
    assert renamed.status == "ok" and arig.state.creation_index.items[mid][1].startswith(
        "Green frog"
    )
    saved = await arig.go("library.export", {"kind": "model3d", "id": mid}, person_approved=True)
    assert saved.status == "ok" and saved.output["name"] == "green-frog.glb"
    assert await asyncio.to_thread(Path(saved.output["path"]).read_bytes) == b"glTF42"
    kind = next(k for k in library_kinds() if k.kind == "model3d")
    assert kind.read is not None and kind.export is not None
    gone = {"kind": "model3d", "id": mid}
    assert (await arig.go("library.delete", gone)).status == "needs_approval"  # destroy asks
    deleted = await arig.go("library.delete", gone, person_approved=True)
    assert deleted.status == "ok" and mid not in arig.state.creation_index.items
    assert (await arig.go("library.get", gone)).status == "refused"


def test_a_copy_gets_a_safe_readable_name():
    assert files.file_stem("Frog mug! <3>") == "frog-mug-3"
    assert files.file_stem("") == "model" and len(files.file_stem("x" * 200)) <= 48
    assert json.dumps(files.file_stem("মগ")) == '"model"'  # no letters we can use: a plain name
