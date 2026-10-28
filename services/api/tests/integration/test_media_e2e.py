"""A whole run through the real pieces: API runtime, Redis event log / run store / queue, the
completion consumer, and a media worker. Only ComfyUI differs: the stub runner for most tests,
and your real ComfyUI for the last one (skipped unless it is running with the models)."""

import asyncio
import json
import os
import urllib.request

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from wasifyai_api.assemble import Injected
from wasifyai_api.graphs.media_demo import build_media_demo
from wasifyai_api.main import create_app
from wasifyai_media_worker.comfy import ComfyClient
from wasifyai_media_worker.consumer import Worker
from wasifyai_media_worker.gpu import RedisGpuLock
from wasifyai_media_worker.processor import ComfyRunner, JobProcessor, StubRunner
from wasifyai_media_worker.settings import WorkerSettings
from wasifyai_media_worker.state import RedisJobState
from wasifyai_platform_sdk import (
    GraphRegistry,
    InMemoryUsageRecorder,
    RedisEventLog,
    RedisJobSink,
    RedisRunStore,
    ScopedStorage,
    memory_storage,
)

from .conftest import PRODUCTS_DIR


def parse(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = [ln for ln in block.split("\n") if not ln.startswith(":")]
        if lines:
            out.append(
                (lines[1].removeprefix("event: "), json.loads(lines[2].removeprefix("data: ")))
            )
    return out


class Pipeline:
    """API + worker sharing one Redis and one storage, as separate replicas would."""

    def __init__(self, redis_conn, runner=None, products_dir=PRODUCTS_DIR):
        self.raw = memory_storage()
        self.usage = InMemoryUsageRecorder()  # the worker's usage events
        log = RedisEventLog(redis_conn)
        registry = GraphRegistry()
        registry.register("media-demo", build_media_demo)
        self.app = create_app(
            Injected(
                registry=registry,
                products_dir=products_dir,
                checkpointer=InMemorySaver(),
                usage=InMemoryUsageRecorder(),
                storage=ScopedStorage(self.raw),
                heartbeat_s=0.1,
                event_log=log,
                run_store=RedisRunStore(redis_conn),
                job_sink=RedisJobSink(redis_conn, log),
                redis=redis_conn,
            )
        )
        settings = WorkerSettings(ollama_base_url="", job_timeout_s=60)
        processor = JobProcessor(
            settings, RedisEventLog(redis_conn), self.raw, self.usage, runner or StubRunner(),
            RedisGpuLock(redis_conn, "e2e"), RedisJobState(redis_conn),
        )  # fmt: skip
        self.worker = Worker(redis_conn, processor)

    async def run(self, body: dict, limit=120.0) -> list[tuple[str, dict]]:
        async with self.app.router.lifespan_context(self.app):
            worker = asyncio.create_task(self.worker.run_forever())
            try:
                transport = httpx.ASGITransport(app=self.app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://t", timeout=limit
                ) as c:
                    r = await c.post("/products/media-demo/runs", json={"input": body})
                    return parse(r.text)
            finally:
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)


async def test_run_queues_a_job_the_worker_runs_and_the_graph_finishes(redis_conn):
    p = Pipeline(redis_conn)
    events = await p.run({"prompt": "a cat on a windowsill"})

    names = [e for e, _ in events]
    assert names[-1] == "done" and "interrupt" not in names and "error" not in names
    jobs = [d for e, d in events if e == "job_progress"]
    # a fast worker can claim the job before the stream's first read: queued or already running
    assert [j["status"] for j in jobs][0] in ("queued", "running")
    if jobs[0]["status"] == "queued":
        assert jobs[0]["queue_position"] == 1
    assert [j["status"] for j in jobs][-1] == "completed" and jobs[-1]["progress"] == 1.0
    running = [j["progress"] for j in jobs if j["status"] == "running"]
    assert running[0] == 0.0 and running == sorted(running)
    assert [d["seq"] for _, d in events] == list(range(1, len(events) + 1))  # one ordered stream

    out = events[-1][1]["outputs"]
    assert out["image_key"].startswith("jobs/") and out["image_url"].endswith("/image.png")
    assert out["gpu_seconds"] > 0
    assert {e.kind for e in p.usage.events} == {"gpu.seconds", "job.completed"}


async def test_a_failing_job_ends_the_run_with_a_clean_error(redis_conn):
    class Failing:
        async def run(self, job, on_progress):
            from wasifyai_media_worker.comfy import ComfyError

            raise ComfyError("execution_failed", "The generation failed on the GPU worker.")

    events = await Pipeline(redis_conn, Failing()).run({"prompt": "x"})
    assert events[-1][0] == "error"
    err = events[-1][1]
    assert err["code"] == "execution_failed" and err["job_id"] and "GPU worker" in err["message"]
    assert [d["status"] for e, d in events if e == "job_progress"][-1] == "failed"


def comfyui_ready() -> bool:
    try:
        info = json.load(
            urllib.request.urlopen("http://localhost:8188/object_info/UNETLoader", timeout=2)
        )
        return (
            "z_image_turbo_bf16.safetensors"
            in info["UNETLoader"]["input"]["required"]["unet_name"][0]
        )
    except Exception:
        return False


@pytest.mark.skipif(
    os.environ.get("COMFYUI_E2E") != "1" or not comfyui_ready(),
    reason="opt-in: run `make test-comfyui` with ComfyUI (z_image_turbo) running on :8188",
)
async def test_real_comfyui_generates_an_image_end_to_end(redis_conn):
    """Slow (loads a 12 GB model on first use). Proves the real protocol, not just the fake one."""
    runner = ComfyRunner(ComfyClient("http://localhost:8188"), timeout_s=600)
    p = Pipeline(redis_conn, runner)
    events = await p.run(
        {"prompt": "a small red lighthouse on a cliff, flat illustration", "seed": 7}, 700
    )

    assert events[-1][0] == "done", events[-1]
    key = events[-1][1]["outputs"]["image_key"]
    from wasifyai_platform_sdk import object_key

    png = await p.raw.get(object_key("dev-tenant", "media-demo", "dev-user", key))
    assert png.startswith(b"\x89PNG\r\n\x1a\n") and len(png) > 10_000  # a real picture, not a stub
    progress = [
        d["progress"] for e, d in events if e == "job_progress" and d["status"] == "running"
    ]
    assert len(progress) >= 3 and progress[-1] > 0  # saw the sampler's live progress
