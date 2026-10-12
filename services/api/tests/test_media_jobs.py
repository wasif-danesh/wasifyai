"""The job round trip without Redis or a GPU: the graph enqueues and pauses, a simulated worker
reports a result, the runtime resumes the graph and the client's stream finishes."""

import asyncio
import json

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from wasifyai_api.graphs.media_demo import build_media_demo
from wasifyai_api.jobs_consumer import handle_completion
from wasifyai_api.main import create_app
from wasifyai_platform_sdk import (
    GraphRegistry,
    InMemoryEventLog,
    InMemoryJobSink,
    InMemoryRunStore,
    InMemoryUsageRecorder,
    JobError,
    JobOutput,
    JobResult,
    ScopedStorage,
    memory_storage,
    object_key,
)


@pytest.fixture
def rig(tmp_path):
    d = tmp_path / "media-demo"
    d.mkdir()
    (d / "product.yaml").write_text(
        "id: media-demo\ncapabilities:\n  image.generate: { provider: fake }\n"
    )
    registry = GraphRegistry()
    registry.register("media-demo", build_media_demo)
    raw = memory_storage()
    sink, store = InMemoryJobSink(), InMemoryRunStore()
    app = create_app(
        registry,
        tmp_path,
        InMemorySaver(),
        InMemoryUsageRecorder(),
        ScopedStorage(raw),
        heartbeat_s=0.05,
        event_log=InMemoryEventLog(),
        run_store=store,
        job_sink=sink,
    )
    return app, raw, sink, store


def parse(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = [ln for ln in block.split("\n") if not ln.startswith(":")]
        if lines:
            out.append(
                (lines[1].removeprefix("event: "), json.loads(lines[2].removeprefix("data: ")))
            )
    return out


async def deliver(app, store, msg: dict) -> None:
    """What the API's completion consumer does: retry until the graph has reached its wait."""
    for _ in range(500):
        if await handle_completion(app.state.runs, store, msg):
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the completion was never accepted")


def completion(job, result: JobResult) -> dict:
    return {
        "tenant_id": job.tenant_id,
        "run_id": job.run_id,
        "job_id": job.job_id,
        "result": result.model_dump(),
    }


async def run_to_end(app, sink, worker):
    """Start a run, let `worker(job)` act once the job is queued, return the SSE events."""
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as c:

            async def client():
                r = await c.post("/products/media-demo/runs", json={"input": {"prompt": "a cat"}})
                return parse(r.text)

            task = asyncio.create_task(client())
            for _ in range(200):
                if sink.submitted:
                    break
                await asyncio.sleep(0.01)
            assert sink.submitted, "the graph never enqueued a job"
            await worker(app, sink.submitted[0])
            return await asyncio.wait_for(task, timeout=10)


async def test_job_round_trip_resumes_the_graph(rig):
    app, raw, sink, store = rig

    async def worker(app, job):
        # what the real worker does: write the output under the user's prefix, then report it
        key = object_key(
            job.tenant_id, job.product_id, job.user_id, "jobs", job.job_id, "image.png"
        )
        await raw.put(key, b"PNG", "image/png")
        result = JobResult(
            job_id=job.job_id,
            status="completed",
            outputs={
                "image": JobOutput(
                    key=f"jobs/{job.job_id}/image.png", content_type="image/png", size=3
                )
            },
            gpu_seconds=1.5,
        )
        await deliver(app, store, completion(job, result))

    events = await run_to_end(app, sink, worker)

    names = [e for e, _ in events]
    assert names[-1] == "done" and "interrupt" not in names  # a job wait is not a user prompt
    outputs = events[-1][1]["outputs"]
    assert outputs["gpu_seconds"] == 1.5
    assert outputs["image_url"].endswith(f"jobs/{sink.submitted[0].job_id}/image.png")
    assert [d["seq"] for _, d in events] == list(range(1, len(events) + 1))


async def test_failed_job_becomes_a_clean_error_event(rig):
    app, _, sink, store = rig

    async def worker(app, job):
        result = JobResult(
            job_id=job.job_id,
            status="failed",
            error=JobError(
                code="job_failed", message="The image could not be generated.", retryable=True
            ),
        )
        await deliver(app, store, completion(job, result))

    events = await run_to_end(app, sink, worker)

    assert events[-1][0] == "error"
    err = events[-1][1]
    assert (err["code"], err["retryable"]) == ("job_failed", True)
    assert err["message"] == "The image could not be generated." and err["job_id"]


async def test_redelivered_completion_does_not_resume_twice(rig):
    app, raw, sink, store = rig

    async def worker(app, job):
        result = JobResult(
            job_id=job.job_id,
            status="completed",
            outputs={"image": JobOutput(key="jobs/x/image.png", content_type="image/png", size=1)},
        )
        await raw.put(
            object_key(job.tenant_id, job.product_id, job.user_id, "jobs/x/image.png"), b"1"
        )
        msg = completion(job, result)
        await deliver(app, store, msg)
        # Redis redelivers the same entry: the wait was already taken, so nothing resumes again
        await handle_completion(app.state.runs, store, msg)

    events = await run_to_end(app, sink, worker)

    assert [e for e, _ in events].count("done") == 1  # not resumed (and finished) twice


async def test_completion_for_unknown_or_finished_runs_is_dropped(rig):
    app, _, _, store = rig
    async with app.router.lifespan_context(app):
        ghost = {"tenant_id": "t", "run_id": "no-such-run", "job_id": "j", "result": {}}
        assert await handle_completion(app.state.runs, store, ghost) is True
        assert await handle_completion(app.state.runs, store, {**ghost, "run_id": None}) is True
