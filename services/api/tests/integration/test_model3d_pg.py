"""The 3D product's rows on real Postgres (ADR-0087, P3), and a worker cancelling a long job on
real Redis."""

import asyncio
from uuid import uuid4

import pytest
from wasifyai_engine_worker.worker import Worker
from wasifyai_model3d.store import Model3dStore, NotFound
from wasifyai_platform_sdk import EngineJob, EngineQueue, memory_storage, model3d_wire


@pytest.fixture
def store(engine):
    from wasifyai_api.config import get_settings

    schema = "m3d_t_" + uuid4().hex[:8]
    s = Model3dStore.on_postgres(get_settings().database_url, schema=schema)
    yield s
    s.drop_schema()
    s.close()


async def test_rows_are_kept_per_person_and_follow_a_model_from_start_to_done(store):
    pic = store.add_input("t1", "u1", "frog.png", 600, 400)
    store.set_input(
        pic["id"], status="ready", checks=[{"code": "ok", "level": "ok", "message": "x"}]
    )
    row = store.add_model("t1", "u1", title="Frog", prompt="a frog", input_id=pic["id"],
                          detail="standard", seed=7, recipe={"seed": 7})  # fmt: skip
    store.set_progress(row["id"], 0.4, "Building the shape")
    assert store.get_model("t1", "u1", row["id"])["progress"] == pytest.approx(0.4)
    store.finish_model(row["id"], "done", elapsed_s=611.0, peak_gb=18.7, glb_bytes=35_000_000)
    done = store.get_model("t1", "u1", row["id"])
    assert done["status"] == "done" and done["progress"] == 1 and done["glb_bytes"] == 35_000_000
    assert [m["id"] for m in store.list_models("t1", "u1")] == [row["id"]]
    with pytest.raises(NotFound):
        store.get_model("t1", "other", row["id"])
    assert store.list_models("t1", "other") == []


async def test_old_pictures_and_stuck_work_are_swept_but_a_used_picture_stays(store):
    used = store.add_input("t1", "u1", "a", 300, 200)
    spare = store.add_input("t1", "u1", "b", 300, 200)
    store.add_model("t1", "u1", title="x", prompt="", input_id=used["id"], detail="light",
                    seed=1, recipe={})  # fmt: skip
    assert store.purge_inputs("9999-01-01") == [("t1", "u1", spare["id"])]
    assert store.fail_stale("9999-01-01", "stopped") >= 1  # the working model


class Service:
    """A 3D component whose run takes as long as it is let to, and notes when it was stopped."""

    def __init__(self) -> None:
        self.stopped = False

    def ready(self):
        return True

    def problem(self):
        return None

    def fit(self):
        return {"verdict": "fits", "reason": ""}

    def state(self):
        return {}

    async def stop(self):
        self.stopped = True

    async def generate(self, cutout, out_glb, **kw):
        await asyncio.sleep(60)


async def test_a_worker_stops_a_long_3d_job_when_it_is_cancelled_and_says_so(redis_conn):
    q = EngineQueue(redis_conn, namespace=f"wasifyai:test:{uuid4().hex}")
    storage = memory_storage()
    prefix = "t1/wasifyai-model3d/u1/engine/j"
    await storage.put(f"{prefix}/in/cutout", b"CUT")
    service = Service()
    worker = Worker(q, {"speech": object(), "model3d": service}, storage, "w1", 30, 1)
    job = EngineJob(kind=model3d_wire.GENERATE, tenant_id="t1", product_id="wasifyai-model3d",
                    user_id="u1", prefix=prefix, params={"seed": 1, "detail": "light"},
                    files={"cutout": f"{prefix}/in/cutout"})  # fmt: skip
    await q.submit(job)
    running = asyncio.create_task(worker.run_once(block_ms=500))
    await asyncio.sleep(1.0)
    await q.cancel(job.id)
    assert await running is True
    out = await q.wait(job.id, 10, poll_s=1)
    assert not out.ok and out.error and out.error.code == "cancelled"
    assert service.stopped is True
