"""The 3D product on the web's home (ADR-0087, P3): the files in object storage and a worker's
engine, not folders on this computer. The same routes and job manager as the desktop's, on a
stand-in engine, a store and memory storage."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_model3d import BASE, FakeEngine, Index, make, photo, ready_picture, user_of, wait
from wasifyai_model3d.blobs import LocalBlobs, StorageBlobs
from wasifyai_model3d.routes import build_routes
from wasifyai_model3d.runtime import sweep
from wasifyai_model3d.store import Model3dStore
from wasifyai_platform_sdk import Identity, InMemoryUsageRecorder, RouteDeps, memory_storage
from wasifyai_platform_sdk.storage import ScopedStorage

ME = Identity("t1", "u1")


@pytest.fixture
def web(tmp_path):
    """No desktop folder at all: the store is a file only because SQLite is the test's database."""
    storage = memory_storage()
    app = FastAPI()
    app.state.model3d = FakeEngine()
    app.state.model3d_store = Model3dStore(tmp_path / "rows")
    app.state.model3d_blobs = StorageBlobs(ScopedStorage(storage))
    app.state.creation_index = Index()
    app.include_router(
        build_routes(RouteDeps(app.state, user_of)), prefix="/products/wasifyai-model3d"
    )
    with TestClient(app) as client:
        client.app_state = app.state  # type: ignore[attr-defined]
        client.storage = storage  # type: ignore[attr-defined]
        yield client


async def keys(web, who="t1") -> list[str]:
    return await web.storage.list(f"{who}/wasifyai-model3d")


def test_a_model_is_made_from_files_that_live_in_storage_and_is_served_from_there(web):
    pic = ready_picture(web)
    assert pic["status"] == "ready"
    for which in ("picture", "cutout"):
        assert web.get(f"{BASE}/inputs/{pic['id']}/{which}").headers["content-type"] == "image/png"
    started = make(web, pic["id"], title="Frog mug")
    assert started.status_code == 202, started.text
    done = wait(web, f"/models/{started.json()['id']}", lambda r: r["status"] == "done")
    assert done["glb_bytes"] == len(b"glTF42")
    glb = web.get(f"{BASE}/models/{done['id']}/file")
    assert glb.content == b"glTF42" and "frog-mug.glb" in glb.headers["content-disposition"]
    for which in ("thumb", "source", "cutout"):
        assert web.get(f"{BASE}/models/{done['id']}/{which}").status_code == 200


def test_the_engine_works_in_a_scratch_folder_that_is_gone_afterwards(web):
    pic = ready_picture(web)
    row = make(web, pic["id"]).json()
    wait(web, f"/models/{row['id']}", lambda r: r["status"] == "done")
    engine = web.app_state.model3d
    for path in [*engine.matted, *(m["cutout"] for m in engine.made)]:
        assert not Path(path).exists()  # nothing is left on the machine that ran it


def test_the_web_says_where_the_work_is_done_and_cannot_save_into_a_folder(web):
    assert web.get(f"{BASE}/status").json()["place"] == "service"
    pic = ready_picture(web)
    row = make(web, pic["id"]).json()
    wait(web, f"/models/{row['id']}", lambda r: r["status"] == "done")
    # no export folder on a service: the model is downloaded from its address instead
    assert (
        web.post(f"{BASE}/models/{row['id']}/export", json={"path": "/tmp/x.glb"}).status_code
        == 404
    )


def test_each_person_has_one_job_at_a_time_and_others_are_not_held_up(web):
    engine = web.app_state.model3d
    engine.hold = True
    a = ready_picture(web)
    first = make(web, a["id"])
    assert first.status_code == 202
    again = make(web, a["id"])
    assert again.status_code == 409 and again.json()["detail"]["code"] == "busy"
    # another person is not blocked by the first one's long run
    other = web.post(f"{BASE}/inputs?name=b.png", content=photo(), headers={"x-user": "u2"})
    assert other.status_code == 201
    engine.release.set()


@pytest.mark.asyncio
async def test_deleting_a_model_removes_every_file_of_it_and_nobody_elses(web):
    pic = ready_picture(web)
    row = make(web, pic["id"]).json()
    wait(web, f"/models/{row['id']}", lambda r: r["status"] == "done")
    other = web.post(f"{BASE}/inputs?name=c.png", content=photo(), headers={"x-user": "u2"}).json()
    wait(web, f"/inputs/{other['id']}", lambda r: r["status"] != "checking", {"x-user": "u2"})
    before = await keys(web)
    assert any(f"/m3d/models/{row['id']}/" in k for k in before)
    assert web.delete(f"{BASE}/models/{row['id']}").status_code == 204
    after = await keys(web)
    assert not any(f"/m3d/models/{row['id']}/" in k for k in after)
    assert any(f"/m3d/inputs/{other['id']}/" in k for k in after)  # u2's picture is untouched


def test_files_of_another_person_are_not_reachable_by_id(web):
    pic = ready_picture(web)
    assert web.get(f"{BASE}/inputs/{pic['id']}/cutout", headers={"x-user": "u2"}).status_code == 404


@pytest.mark.asyncio
async def test_the_start_up_sweep_fails_work_whose_owner_is_gone_and_drops_old_pictures(
    web, tmp_path
):
    state = web.app_state
    store = state.model3d_store
    row = store.add_model("t1", "u1", title="x", prompt="", input_id=None, detail="light",
                          seed=1, recipe={})  # fmt: skip
    await sweep(state)  # fresh: still working
    assert store.get_model("t1", "u1", row["id"])["status"] == "working"
    store.fail_stale("9999-01-01", "stopped")
    assert store.get_model("t1", "u1", row["id"])["status"] == "failed"


def test_the_same_names_work_on_the_desktop_folders(tmp_path):
    store = Model3dStore(tmp_path)
    local = LocalBlobs(store)
    assert local.local is True and StorageBlobs(ScopedStorage(memory_storage())).local is False
    with pytest.raises(ValueError):
        local.local_path(ME, "models", "../../x", "model.glb")


class Resumable(FakeEngine):
    """A worker's engine: a job goes by the row's id, so a restart can pick it up again."""

    resumable = True
    closing = False

    def __init__(self) -> None:
        super().__init__()
        self.keys: list[tuple[str | None, bool]] = []

    async def matte(self, picture, out_dir, on_line=None, *, job_key=None, resume=False):
        return await super().matte(picture, out_dir, on_line)

    async def generate(self, cutout_path, out_glb, *, job_key=None, resume=False, **kw):
        self.keys.append((job_key, resume))
        return await super().generate(cutout_path, out_glb, **kw)


def working_model(web, pic) -> dict:
    """A model that was being made when the service stopped: its row and the files it was started
    with (the start copies the picture's cut-out into the model's own folder)."""
    row = web.app_state.model3d_store.add_model(
        "t1", "u1", title="Frog", prompt="", input_id=pic["id"], detail="light", seed=7, recipe={}
    )
    blobs = web.app_state.model3d_blobs
    web.portal.call(blobs.copy, ME, "inputs", pic["id"], "cutout.png", row["id"], "cutout.png")
    return row


def test_a_restarted_service_waits_again_for_a_model_the_worker_was_making(web):
    web.app_state.model3d = engine = Resumable()
    pic = ready_picture(web)
    row = working_model(web, pic)
    picked = web.portal.call(manager(web).resume_all)
    assert picked == 1
    done = wait(web, f"/models/{row['id']}", lambda r: r["status"] == "done")
    assert done["glb_bytes"] == len(b"glTF7")
    assert engine.keys == [(row["id"], True)]  # the same job, awaited, not sent again


def test_stopping_the_service_leaves_the_model_working(web):
    web.app_state.model3d = engine = Resumable()
    engine.hold = True
    pic = ready_picture(web)
    row = working_model(web, pic)
    web.portal.call(manager(web).resume_all)
    engine.closing = True  # the service is going down: the worker goes on
    web.portal.call(manager(web).stop_all)
    assert web.app_state.model3d_store.get_model("t1", "u1", row["id"])["status"] == "working"


def test_pressing_stop_on_a_picked_up_model_ends_it(web):
    web.app_state.model3d = engine = Resumable()
    engine.hold = True
    pic = ready_picture(web)
    row = working_model(web, pic)
    web.portal.call(manager(web).resume_all)
    assert web.portal.call(manager(web).cancel, ME, row["id"]) is True
    assert web.app_state.model3d_store.get_model("t1", "u1", row["id"])["status"] == "cancelled"


def test_a_finished_model_is_not_undone_by_a_late_failure(web):
    pic = ready_picture(web)
    row = make(web, pic["id"]).json()
    wait(web, f"/models/{row['id']}", lambda r: r["status"] == "done")
    web.app_state.model3d_store.finish_model(row["id"], "failed", error="late")
    assert web.get(f"{BASE}/models/{row['id']}").json()["status"] == "done"


def manager(web):
    from wasifyai_model3d.runtime import manager_for

    return manager_for(RouteDeps(web.app_state, user_of))


# ---- safeguards and usage (P6) --------------------------------------------------------------


class Safeguards:
    """The safeguards on, a picture moderator that answers as told, and the usage recorded."""

    def __init__(self, state, *, category="ok", quota=None):
        self.category, self.used, self.seen = category, {}, 0
        outer = self

        class On:
            async def enabled(self) -> bool:
                return True

        class Text:
            async def complete(self, name, system, user, schema=None):
                outer.seen += 1
                ok = outer.category == "ok"
                return (
                    f'{{"allowed": {str(ok).lower()}, "category": "{outer.category}", '
                    '"reason": "x"}'
                )

        state.safeguards = On()
        state.caps = {
            "wasifyai-model3d": SimpleNamespace(
                text=Text(), db=object(), config=SimpleNamespace(quotas=quota or {})
            )
        }
        state.usage = InMemoryUsageRecorder()

    def counted(self, monkeypatch) -> None:
        async def used(db, tenant, product, user, kind, since):
            return self.used.get(kind, 0)

        monkeypatch.setattr("wasifyai_platform_sdk.route_guard.sum_usage", used)


def upload(web):
    return web.post(f"{BASE}/inputs?name=a.png", content=photo())


def test_while_the_safeguards_are_on_a_picture_of_a_real_person_is_refused_and_not_kept(web):
    on = Safeguards(web.app_state, category="real_person_photo")
    r = upload(web)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "real_person_photo"
    assert "photograph of a real person" in r.json()["detail"]["message"]
    assert on.seen == 1
    assert web.app_state.model3d.matted == []  # nothing was cut out
    assert web.app_state.model3d_store.working_inputs() == []  # no row is left working


def test_without_a_moderator_no_picture_is_taken_while_the_safeguards_are_on(web):
    Safeguards(web.app_state)
    web.app_state.caps = {}
    r = upload(web)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "moderation_unavailable"


def test_pictures_and_models_are_counted_and_the_daily_limits_stop_the_next(web, monkeypatch):
    on = Safeguards(
        web.app_state, quota={"models_per_user_per_day": 1, "pictures_per_user_per_day": 3}
    )
    on.counted(monkeypatch)
    pic = ready_picture(web)
    started = make(web, pic["id"])
    assert started.status_code == 202, started.text
    wait(web, f"/models/{started.json()['id']}", lambda r: r["status"] == "done")
    events = [(e.kind, e.quantity, e.unit) for e in web.app_state.usage.events]
    assert events == [("model3d.picture", 1, "pictures"), ("model3d.model", 1, "models")]
    on.used = {"model3d.model": 1, "model3d.picture": 3}
    again = make(web, pic["id"])
    assert again.status_code == 409 and again.json()["detail"]["code"] == "quota_exceeded"
    assert "limit of 1 3D models" in again.json()["detail"]["message"]
    assert upload(web).json()["detail"]["code"] == "quota_exceeded"


def test_with_the_safeguards_off_nothing_is_checked_but_usage_is_still_recorded(web):
    web.app_state.usage = InMemoryUsageRecorder()
    pic = ready_picture(web)
    assert pic["status"] == "ready"
    assert [e.kind for e in web.app_state.usage.events] == ["model3d.picture"]
