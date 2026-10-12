"""The Redis pieces of the media pipeline against a real Redis: event log, run store, queue,
worker delivery guarantees, GPU lock and the API's completion consumer."""

import asyncio
import json
from uuid import uuid4

import httpx
from wasifyai_api.jobs_consumer import JobCompletionConsumer
from wasifyai_media_worker.consumer import Worker
from wasifyai_media_worker.gpu import RedisGpuLock
from wasifyai_media_worker.processor import JobProcessor, StubRunner
from wasifyai_media_worker.settings import WorkerSettings
from wasifyai_media_worker.state import InMemoryJobState
from wasifyai_platform_sdk import (
    InMemoryUsageRecorder,
    JobRequest,
    RedisEventLog,
    RedisJobSink,
    RedisRunStore,
    RunRecord,
    memory_storage,
)
from wasifyai_platform_sdk.jobqueue import (
    DONE_GROUP,
    DONE_STREAM,
    JOBS_GROUP,
    JOBS_STREAM,
    ensure_groups,
)


def make_job(tenant: str = "t") -> JobRequest:
    return JobRequest(
        tenant_id=tenant,
        product_id="media-demo",
        user_id="u",
        run_id=str(uuid4()),
        thread_id=str(uuid4()),
        capability="image.generate",
        workflow="demo",
        prompt={"1": {"class_type": "SaveImage", "inputs": {}}},
        outputs={"image": {"node": "1", "type": "image"}},
    )


async def until(predicate, limit=10.0):
    """Poll an async condition: these tests wait on background tasks, not on a notification."""
    async with asyncio.timeout(limit):
        while not await predicate():  # noqa: ASYNC110
            await asyncio.sleep(0.05)


# ---- event log ------------------------------------------------------------------------------


async def test_event_log_orders_events_from_many_writers(redis_conn):
    api, worker = RedisEventLog(redis_conn), RedisEventLog(redis_conn)
    run = str(uuid4())
    seqs = await asyncio.gather(
        *(
            (api if i % 2 else worker).append("t", run, {"event": "token", "n": i})
            for i in range(50)
        )
    )
    assert sorted(seqs) == list(range(1, 51))  # no duplicates, no gaps, from either process
    assert [e["seq"] for e in await api.read("t", run, 0, 100)] == list(range(1, 51))
    assert [e["seq"] for e in await worker.read("t", run, 45, 100)] == [46, 47, 48, 49, 50]
    assert await api.last_seq("t", run) == 50


async def test_event_log_blocking_read_wakes_on_append_from_another_replica(redis_conn):
    a, b = RedisEventLog(redis_conn), RedisEventLog(redis_conn)
    run = str(uuid4())
    reader = asyncio.create_task(a.read("t", run, 0, 5000))
    await asyncio.sleep(0.2)
    await b.append("t", run, {"event": "done"})
    events = await asyncio.wait_for(reader, 3)
    assert [e["event"] for e in events] == ["done"] and events[0]["seq"] == 1
    assert await a.read("t", run, 1, 100) == []  # nothing new: times out empty


async def test_event_logs_are_separated_by_tenant(redis_conn):
    log = RedisEventLog(redis_conn)
    run = str(uuid4())
    await log.append("tenant-a", run, {"event": "node"})
    assert await log.read("tenant-b", run, 0, 50) == []


# ---- run store ------------------------------------------------------------------------------


def make_record(**kw) -> RunRecord:
    return RunRecord(
        run_id=str(uuid4()),
        thread_id=str(uuid4()),
        product_id="p",
        tenant_id="t",
        user_id="u",
        **kw,
    )


async def test_run_store_round_trip_and_tenant_scoping(redis_conn):
    store = RedisRunStore(redis_conn)
    rec = make_record()
    await store.create(rec)
    got = await store.get("t", rec.run_id)
    assert got is not None
    assert got == rec and got.awaiting is None and got.waiting_job is None
    assert await store.get("other-tenant", rec.run_id) is None


async def test_only_one_of_many_concurrent_resumes_wins(redis_conn):
    store = RedisRunStore(redis_conn)
    rec = make_record()
    await store.create(rec)
    await store.set_state("t", rec.run_id, "waiting_input", awaiting="intr-1")
    winners = await asyncio.gather(*(store.take_awaiting("t", rec.run_id) for _ in range(10)))
    assert [w for w in winners if w] == ["intr-1"]
    assert (await store.get("t", rec.run_id)).status == "running"  # type: ignore[union-attr]


async def test_job_wait_is_taken_only_for_the_exact_job(redis_conn):
    store = RedisRunStore(redis_conn)
    rec = make_record()
    await store.create(rec)
    await store.set_state("t", rec.run_id, "waiting_job", waiting_job="job-1")
    assert not await store.take_waiting_job("t", rec.run_id, "job-2")
    assert await store.take_waiting_job("t", rec.run_id, "job-1")
    assert not await store.take_waiting_job("t", rec.run_id, "job-1")  # redelivery


# ---- queue and worker -----------------------------------------------------------------------


def make_worker(redis_conn, runner=None, **settings):
    s = WorkerSettings(ollama_base_url="", job_timeout_s=1, **settings)
    log, storage = RedisEventLog(redis_conn), memory_storage()
    from wasifyai_media_worker.gpu import LocalGpuLock

    proc = JobProcessor(
        s,
        log,
        storage,
        InMemoryUsageRecorder(),
        runner or StubRunner(),
        LocalGpuLock(),
        InMemoryJobState(),
    )
    return Worker(redis_conn, proc, retry_backoff=lambda attempt: 0), proc, storage


async def queued_positions(log, job) -> list[int]:
    events = await log.read(job.tenant_id, job.run_id, 0, 50)
    return [e["queue_position"] for e in events if e["status"] == "queued"]


async def test_queue_positions_are_reported_and_updated_as_jobs_run(redis_conn):
    log = RedisEventLog(redis_conn)
    sink = RedisJobSink(redis_conn, log)
    jobs = [make_job() for _ in range(3)]
    for j in jobs:
        await sink.submit(j)
    assert [(await queued_positions(log, j))[-1] for j in jobs] == [1, 2, 3]

    worker, _, _ = make_worker(redis_conn)
    assert await worker.run_once()  # job 1 runs; 2 and 3 are told their new place
    assert (await queued_positions(log, jobs[1]))[-1] == 2 and (
        await queued_positions(log, jobs[2])
    )[-1] == 3
    assert await worker.run_once()  # job 2 runs; job 3 moves up
    assert (await queued_positions(log, jobs[2]))[-1] == 2


async def test_results_are_published_then_the_job_is_acknowledged(redis_conn):
    log = RedisEventLog(redis_conn)
    job = make_job()
    await RedisJobSink(redis_conn, log).submit(job)
    worker, _, storage = make_worker(redis_conn)
    await worker.run_once()

    (entry,) = await redis_conn.xrange(DONE_STREAM)
    msg = json.loads(entry[1]["d"])
    assert (msg["tenant_id"], msg["run_id"], msg["job_id"]) == (
        job.tenant_id,
        job.run_id,
        job.job_id,
    )
    assert msg["result"]["status"] == "completed" and "image" in msg["result"]["outputs"]
    assert (await redis_conn.xpending(JOBS_STREAM, JOBS_GROUP))["pending"] == 0


async def test_a_job_abandoned_by_a_dead_worker_is_reclaimed_and_finished_once(redis_conn):
    log = RedisEventLog(redis_conn)
    job = make_job()
    await RedisJobSink(redis_conn, log).submit(job)
    # a worker takes the job and dies without acknowledging it
    await redis_conn.xreadgroup(JOBS_GROUP, "dead-worker", {JOBS_STREAM: ">"}, count=1)
    assert (await redis_conn.xpending(JOBS_STREAM, JOBS_GROUP))["pending"] == 1

    survivor, _, _ = make_worker(redis_conn)
    survivor._stale_ms = 10
    await asyncio.sleep(0.05)
    await survivor._reclaim_stale()

    assert len(await redis_conn.xrange(DONE_STREAM)) == 1
    assert (await redis_conn.xpending(JOBS_STREAM, JOBS_GROUP))["pending"] == 0


async def test_transient_failures_requeue_the_job_at_the_back(redis_conn):
    log = RedisEventLog(redis_conn)
    job = make_job()
    await RedisJobSink(redis_conn, log).submit(job)

    class Flaky:
        calls = 0

        async def run(self, job, on_progress):
            Flaky.calls += 1
            if Flaky.calls == 1:
                raise httpx.ConnectError("connection refused")  # the backend is down for now
            return {"image": (b"x", "image/png", "png")}

    worker, _, _ = make_worker(redis_conn, runner=Flaky())
    await worker.run_once()  # the processor raises RetryJob -> requeued, original acknowledged
    assert len(await redis_conn.xrange(DONE_STREAM)) == 0
    assert (await redis_conn.xpending(JOBS_STREAM, JOBS_GROUP))["pending"] == 0
    await worker.run_once()  # second delivery succeeds
    (entry,) = await redis_conn.xrange(DONE_STREAM)
    assert json.loads(entry[1]["d"])["result"]["status"] == "completed"


# ---- GPU lock -------------------------------------------------------------------------------


async def test_gpu_lock_serialises_holders_and_survives_a_crashed_holder(redis_conn):
    inside = peak = 0

    async def work(lock):
        nonlocal inside, peak
        async with lock.hold():
            inside += 1
            peak = max(peak, inside)
            await asyncio.sleep(0.1)
            inside -= 1

    await asyncio.gather(*(work(RedisGpuLock(redis_conn, "g1", poll_s=0.02)) for _ in range(3)))
    assert peak == 1

    await redis_conn.set(
        "wasifyai:gpu:g2", "crashed-worker", px=300
    )  # holder died without releasing
    async with asyncio.timeout(3):
        async with RedisGpuLock(redis_conn, "g2", poll_s=0.05).hold():
            pass  # acquired after the stale lock expired
    assert await redis_conn.get("wasifyai:gpu:g2") is None  # released again


# ---- API completion consumer ----------------------------------------------------------------


class FakeRuns:
    def __init__(self):
        self.resumed: list[tuple[str, dict]] = []

    def resume_with_job(self, rec, result):
        self.resumed.append((rec.run_id, result))


def completion_entry(rec: RunRecord, job_id: str) -> dict:
    return {
        "d": json.dumps(
            {
                "tenant_id": rec.tenant_id,
                "run_id": rec.run_id,
                "job_id": job_id,
                "result": {"job_id": job_id, "status": "completed"},
            }
        )
    }


async def test_consumer_resumes_a_waiting_run_exactly_once(redis_conn):
    store, runs = RedisRunStore(redis_conn), FakeRuns()
    rec = make_record()
    await store.create(rec)
    await store.set_state("t", rec.run_id, "waiting_job", waiting_job="job-1")
    consumer = JobCompletionConsumer(redis_conn, runs, store)  # type: ignore[arg-type]
    await consumer.start()
    try:
        await redis_conn.xadd(DONE_STREAM, completion_entry(rec, "job-1"))
        await until(lambda: _len(runs.resumed, 1))
        await store.set_state("t", rec.run_id, "done")  # the resumed graph finished
        await redis_conn.xadd(DONE_STREAM, completion_entry(rec, "job-1"))  # redelivered duplicate
        await until(lambda: _pending_zero(redis_conn))
        assert len(runs.resumed) == 1 and runs.resumed[0][1]["status"] == "completed"
    finally:
        await consumer.stop()


async def test_consumer_waits_for_a_graph_that_has_not_reached_its_wait_yet(redis_conn):
    store, runs = RedisRunStore(redis_conn), FakeRuns()
    rec = make_record()
    await store.create(rec)  # status running, not yet waiting on the job
    consumer = JobCompletionConsumer(redis_conn, runs, store)  # type: ignore[arg-type]
    await consumer.start()
    try:
        await redis_conn.xadd(DONE_STREAM, completion_entry(rec, "job-9"))  # worker was fast
        await asyncio.sleep(1.5)
        assert runs.resumed == []  # not lost, not resumed too early
        await store.set_state("t", rec.run_id, "waiting_job", waiting_job="job-9")
        await until(lambda: _len(runs.resumed, 1))
    finally:
        await consumer.stop()


async def test_consumer_drops_results_for_unknown_runs(redis_conn):
    store, runs = RedisRunStore(redis_conn), FakeRuns()
    consumer = JobCompletionConsumer(redis_conn, runs, store)  # type: ignore[arg-type]
    await consumer.start()
    try:
        await redis_conn.xadd(DONE_STREAM, completion_entry(make_record(), "job-x"))
        await until(lambda: _pending_zero(redis_conn))
        assert runs.resumed == []
    finally:
        await consumer.stop()


async def _len(items, n):
    return len(items) >= n


async def _pending_zero(conn):
    await ensure_groups(conn)
    p = await conn.xpending(DONE_STREAM, DONE_GROUP)
    return p["pending"] == 0 and await conn.xlen(DONE_STREAM) > 0
