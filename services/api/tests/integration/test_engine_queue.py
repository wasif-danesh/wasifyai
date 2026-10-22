"""The engine job queue and a worker on real Redis (ADR-0087). Each test uses a namespace of its
own, so a worker that is running on this machine never sees these jobs."""

import asyncio
from uuid import uuid4

import pytest
from wasifyai_engine_worker.worker import Worker
from wasifyai_platform_sdk import (
    EngineJob,
    EngineOutcome,
    EngineQueue,
    EngineUnavailable,
    EngineWorkerInfo,
    SpeechResult,
    memory_storage,
    speech_wire,
)

PREFIX = "t1/wasifyai-voice/u1/engine/x"


@pytest.fixture
async def queue(redis_conn):
    ns = f"wasifyai:test:{uuid4().hex}"
    yield EngineQueue(redis_conn, namespace=ns), ns
    async for key in redis_conn.scan_iter(match=f"{ns}:*"):
        await redis_conn.delete(key)


def job(kind: str = speech_wire.SPEAK) -> EngineJob:
    return EngineJob(
        kind=kind, tenant_id="t1", product_id="wasifyai-voice", user_id="u1", prefix=PREFIX,
        params={"model_id": "m", "text": "hi"},
    )  # fmt: skip


async def test_a_job_goes_to_one_worker_and_its_outcome_to_the_waiter(queue):
    q, _ = queue
    j = job()
    await q.submit(j)
    claimed = await q.claim("w1", block_ms=500)
    assert claimed is not None and claimed[1].id == j.id
    assert await q.claim("w2", block_ms=200) is None  # not delivered twice
    waiter = asyncio.create_task(q.wait(j.id, 10, poll_s=1))
    await q.finish(claimed[0], EngineOutcome(id=j.id, ok=True, meta={"n": 1}, worker="w1"))
    out = await waiter
    assert out.ok and out.meta == {"n": 1}


async def test_a_restarted_api_can_tell_whether_a_job_is_waiting_done_or_lost(queue):
    q, _ = queue
    j = job()
    assert await q.status(j.id) == "lost"  # never sent
    await q.submit(j)
    assert await q.status(j.id) == "waiting"
    claimed = await q.claim("w1", block_ms=500)
    assert claimed is not None
    await q.finish(claimed[0], EngineOutcome(id=j.id, ok=True, worker="w1"))
    assert await q.status(j.id) == "done"  # the outcome waits for whoever picks it up
    out = await q.wait(j.id, 5, poll_s=1)
    assert out.ok and await q.status(j.id) == "lost"  # taken: nothing is waiting for it any more


async def test_a_page_can_follow_a_job_it_does_not_wait_for(queue):
    q, _ = queue
    j = job()
    await q.submit(j)
    assert await q.peek(j.id) is None and await q.progress_of(j.id) is None
    claimed = await q.claim("w1", block_ms=500)
    assert claimed is not None
    await q.report(j.id, 0.25, "Downloading")
    assert await q.progress_of(j.id) == (0.25, "Downloading")
    await q.finish(claimed[0], EngineOutcome(id=j.id, ok=True, worker="w1"))
    first, second = await q.peek(j.id), await q.peek(j.id)  # looking does not take it
    assert first is not None and second is not None and first.ok


async def test_waiting_gives_up_and_progress_is_passed_on(queue):
    q, _ = queue
    j = job()
    await q.submit(j)
    seen: list[tuple[float, str]] = []

    async def on_progress(f: float, label: str) -> None:
        seen.append((f, label))

    waiter = asyncio.create_task(q.wait(j.id, 3, on_progress, poll_s=1))
    await asyncio.sleep(0.3)
    await q.report(j.id, 0.5, "half")
    with pytest.raises(EngineUnavailable):
        await waiter
    assert (0.5, "half") in seen


async def test_a_worker_is_listed_while_it_is_here_and_gone_when_it_leaves(queue):
    q, _ = queue
    await q.register(EngineWorkerInfo(id="w1", kinds=["speech.speak"], models=[{"id": "m"}]))
    assert [w.id for w in await q.workers()] == ["w1"]
    await q.leave("w1")
    assert await q.workers() == []


class Engine:
    def models(self, task=None):
        return [{"id": "kokoro-82m", "state": "ready"}]

    def resolve(self, task, model_id):
        return type("M", (), {"id": model_id})()

    async def speak(self, model, text, voice, options, *, beside=False):
        return SpeechResult(b"RIFF", 24000, 1.0, model.id, voice, 0.0, 0.1)


async def test_a_worker_takes_a_job_runs_it_and_answers(queue):
    q, _ = queue
    storage = memory_storage()
    worker = Worker(q, Engine(), storage, "w1", job_timeout_s=30, heartbeat_s=1)
    j = job()
    await q.submit(j)
    assert await worker.run_once(block_ms=500) is True
    out = await q.wait(j.id, 5, poll_s=1)
    assert out.ok and await storage.get(out.outputs["audio"]) == b"RIFF"
    assert await worker.run_once(block_ms=100) is False  # nothing left
    assert [m["id"] for m in worker.info().models] == ["kokoro-82m"]
