"""3D models for the web from an engine worker (ADR-0087, P3): the API's `RemoteModel3dEngine`
and the worker's handlers on one wire, with a fake queue that runs each job on the worker's own
code at once."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from wasifyai_api.engine_workers import WorkerDirectory
from wasifyai_api.remote_model3d import RemoteModel3dEngine
from wasifyai_engine_worker.handlers import run_job
from wasifyai_platform_sdk import (
    EngineJob,
    EngineWorkerInfo,
    RunContext,
    memory_storage,
    model3d_wire,
    reset_context,
    set_context,
)
from wasifyai_platform_sdk.storage import object_key


class Service:
    """The 3D component on the worker's machine, minimal."""

    def __init__(self) -> None:
        self.fail = False
        self.seen: list[str] = []

    async def matte(self, picture: Path, out_dir: Path, on_line=None):
        self.seen.append("matte:" + picture.read_bytes().decode())  # noqa: ASYNC240
        if self.fail:
            return SimpleNamespace(ok=False, reason="failed", message="No object found.",
                                   output=None, seconds=0.1, peak_gb=0.0)  # fmt: skip
        out = out_dir / "unused_cutout.png"
        out.write_bytes(b"CUT")  # noqa: ASYNC240
        return SimpleNamespace(
            ok=True, reason=None, message="", output=out, seconds=1.5, peak_gb=5.0
        )

    async def generate(self, cutout: Path, out_glb: Path, *, seed=42, detail="standard",
                       on_line=None, on_progress=None):  # fmt: skip
        self.seen.append(f"generate:{seed}:{detail}")
        if on_progress:
            on_progress(0.5, "Building the shape")
        out_glb.write_bytes(b"glTF" + cutout.read_bytes())  # noqa: ASYNC240
        return SimpleNamespace(ok=True, reason=None, message="", output=out_glb, seconds=600.0,
                               peak_gb=18.0)  # fmt: skip


class InlineQueue:
    def __init__(self, storage, service):
        self.storage, self.service = storage, service
        self.done: dict[str, object] = {}
        self.cancelled_ids: list[str] = []
        self.sent: dict[str, str] = {}  # job id -> "waiting": sent, no outcome yet
        self.reported: list[tuple[float, str]] = []

    async def submit(self, job):
        async def report(fraction, label):
            self.reported.append((fraction, label))

        self.done[job.id] = await run_job(
            {"model3d": self.service}, self.storage, job, "w1", report
        )

    async def wait(self, job_id, timeout_s, on_progress=None):
        for fraction, label in self.reported:
            if on_progress is not None:
                await on_progress(fraction, label)
        return self.done.pop(job_id)

    async def cancel(self, job_id):
        self.cancelled_ids.append(job_id)

    async def status(self, job_id):
        return "done" if job_id in self.done else self.sent.get(job_id, "lost")


def directory(*workers: EngineWorkerInfo) -> WorkerDirectory:
    d = WorkerDirectory(None)  # type: ignore[arg-type]
    d.workers = list(workers)
    return d


def worker(ready=True, problem=None) -> EngineWorkerInfo:
    comp = {
        "ready": ready,
        "problem": problem,
        "fit": {"verdict": "fits", "reason": "ok"},
        "state": {},
    }
    return EngineWorkerInfo(id="w1", kinds=model3d_wire.KINDS, models=[],
                            components={model3d_wire.COMPONENT: comp})  # fmt: skip


@pytest.fixture
def ctx():
    token = set_context(RunContext("t1", "wasifyai-model3d", "u1"))
    yield
    reset_context(token)


def make(workers):
    storage, service = memory_storage(), Service()
    queue = InlineQueue(storage, service)
    engine = RemoteModel3dEngine(queue, storage, directory(*workers))  # type: ignore[arg-type]
    return engine, queue, storage, service


def test_it_is_ready_only_when_a_live_worker_has_the_component_ready_and_says_why_not():
    assert make([worker()])[0].ready() is True
    assert make([worker()])[0].fit()["verdict"] == "fits"
    none = make([])[0]
    assert none.ready() is False and "not running" in str(none.problem())
    assert "not set up" in str(
        make([worker(False, "The 3D component is not set up yet.")])[0].problem()
    )
    no_3d = EngineWorkerInfo(id="w2", kinds=[], models=[])
    assert "No worker" in str(make([no_3d])[0].problem())


@pytest.mark.asyncio
async def test_a_picture_is_cut_out_and_a_model_made_through_the_worker(ctx, tmp_path):
    engine, queue, storage, service = make([worker()])
    pic = tmp_path / "picture.png"
    pic.write_bytes(b"PIC")
    cut = await engine.matte(pic, tmp_path)
    assert cut.ok and cut.output is not None and cut.output.read_bytes() == b"CUT"
    assert cut.seconds == 1.5 and cut.peak_gb == 5.0
    told: list[tuple[float, str]] = []
    glb = tmp_path / "model.glb"
    made = await engine.generate(
        cut.output, glb, seed=7, detail="light", on_progress=lambda f, w: told.append((f, w))
    )
    assert made.ok and glb.read_bytes() == b"glTFCUT" and made.seconds == 600.0
    assert service.seen == ["matte:PIC", "generate:7:light"]
    assert told == [(0.5, "Building the shape")]
    assert await storage.list("t1/wasifyai-model3d/u1") == []  # nothing is left in storage


@pytest.mark.asyncio
async def test_a_component_that_says_no_gives_the_product_its_words(ctx, tmp_path):
    engine, _, _, service = make([worker()])
    service.fail = True
    pic = tmp_path / "p.png"
    pic.write_bytes(b"PIC")
    res = await engine.matte(pic, tmp_path)
    assert not res.ok and res.reason == "failed" and res.message == "No object found."


@pytest.mark.asyncio
async def test_pressing_stop_tells_the_worker_to_cancel_the_job(ctx, tmp_path):
    engine, queue, _, _ = make([worker()])

    async def never(job_id, timeout_s, on_progress=None):
        await asyncio.sleep(60)

    queue.wait = never  # type: ignore[method-assign]
    cutout = tmp_path / "c.png"
    cutout.write_bytes(b"CUT")
    task = asyncio.create_task(engine.generate(cutout, tmp_path / "m.glb"))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(queue.cancelled_ids) == 1


@pytest.mark.asyncio
async def test_a_model_the_worker_finished_while_the_api_was_down_is_picked_up_without_a_resend(
    ctx, tmp_path
):
    engine, queue, storage, service = make([worker()])
    prefix = object_key("t1", "wasifyai-model3d", "u1", "engine", "row-1")
    await storage.put(f"{prefix}/in/cutout", b"CUT", "application/octet-stream")
    # before the restart: the job went out under the row's id and the worker finished it
    await queue.submit(
        EngineJob(
            id="row-1",
            kind=model3d_wire.GENERATE,
            tenant_id="t1",
            product_id="wasifyai-model3d",
            user_id="u1",
            prefix=prefix,
            params={"seed": 7, "detail": "light"},
            files={"cutout": f"{prefix}/in/cutout"},
        )  # fmt: skip
    )
    # after the restart: the same row id, resumed
    out = tmp_path / "m.glb"
    res = await engine.generate(tmp_path / "unused.png", out, job_key="row-1", resume=True)
    assert res.ok and out.read_bytes() == b"glTFCUT"
    assert service.seen == ["generate:7:light"]  # run once, not sent again
    assert await storage.list("t1/wasifyai-model3d/u1") == []  # and nothing is left behind


@pytest.mark.asyncio
async def test_a_job_the_queue_has_lost_is_failed_in_words_not_waited_for(ctx, tmp_path):
    engine, queue, _, service = make([worker()])
    cutout = tmp_path / "c.png"
    cutout.write_bytes(b"CUT")
    res = await engine.generate(cutout, tmp_path / "m.glb", job_key="gone", resume=True)
    assert not res.ok and res.reason == "lost" and "stopped" in res.message
    assert service.seen == []


@pytest.mark.asyncio
async def test_a_stopping_service_does_not_tell_the_worker_to_stop(ctx, tmp_path):
    engine, queue, _, _ = make([worker()])

    async def never(job_id, timeout_s, on_progress=None):
        await asyncio.sleep(60)

    queue.wait = never  # type: ignore[method-assign]
    cutout = tmp_path / "c.png"
    cutout.write_bytes(b"CUT")
    task = asyncio.create_task(engine.generate(cutout, tmp_path / "m.glb", job_key="row-2"))
    await asyncio.sleep(0.05)
    engine.closing = True  # the API is going down: the job is for the next start
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert queue.cancelled_ids == []
