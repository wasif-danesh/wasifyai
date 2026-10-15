"""Rules every event log, run store and job queue must follow (ADR-0021, ADR-0056).

The web profile serves them from Redis, the desktop profile from SQLite, tests from memory; the
same checks run against each so a run behaves the same everywhere."""

import asyncio
import time
from uuid import uuid4

from wasifyai_platform_sdk import JobRequest
from wasifyai_platform_sdk.runstore import RunRecord


def _event(n: int, node: str = "n") -> dict:
    return {"event": "node", "node": node, "status": "started", "label": f"step {n}"}


async def check_event_log(log, tenant: str) -> None:
    run = str(uuid4())

    # seq is allocated per run, from 1, in order
    assert [await log.append(tenant, run, _event(i)) for i in range(1, 4)] == [1, 2, 3]
    assert await log.append(tenant, str(uuid4()), _event(1)) == 1
    assert await log.last_seq(tenant, run) == 3
    assert await log.last_seq(tenant, str(uuid4())) == 0

    # a read returns everything after `after`, with seq set and the payload intact
    got = await log.read(tenant, run, 0, 50)
    assert [e["seq"] for e in got] == [1, 2, 3]
    assert got[1]["label"] == "step 2" and got[1]["event"] == "node"
    assert [e["seq"] for e in await log.read(tenant, run, 2, 50)] == [3]
    assert await log.read(tenant, run, 3, 50) == []  # nothing new: empty, after the wait

    # tenants do not see each other's runs
    assert await log.read(tenant + "-b", run, 0, 50) == []

    # a reader that is waiting wakes when an event arrives, well before its timeout
    waiter = asyncio.create_task(log.read(tenant, run, 3, 5000))
    await asyncio.sleep(0.05)
    started = time.monotonic()
    await log.append(tenant, run, _event(4))
    woke = await asyncio.wait_for(waiter, timeout=3)
    assert [e["seq"] for e in woke] == [4]
    assert time.monotonic() - started < 2

    # writers racing for the next seq each get their own
    seqs = await asyncio.gather(*(log.append(tenant, run, _event(i)) for i in range(20)))
    assert sorted(seqs) == list(range(5, 25))


def _record(tenant: str, run: str) -> RunRecord:
    return RunRecord(
        run_id=run, thread_id=str(uuid4()), product_id="p", tenant_id=tenant, user_id="u1"
    )


async def check_run_store(store, tenant: str) -> None:
    run = str(uuid4())
    assert await store.get(tenant, run) is None

    rec = _record(tenant, run)
    await store.create(rec)
    got = await store.get(tenant, run)
    assert got is not None
    assert (got.run_id, got.thread_id, got.user_id, got.status) == (
        run, rec.thread_id, "u1", "running"
    )  # fmt: skip
    assert got.awaiting is None and got.waiting_job is None
    assert await store.get(tenant + "-b", run) is None  # runs belong to their tenant

    # an interrupt is answered once: the first taker gets it, the second gets nothing
    await store.set_state(tenant, run, "waiting_input", awaiting="int-1")
    assert (await store.get(tenant, run)).awaiting == "int-1"  # type: ignore[union-attr]
    assert await store.take_awaiting(tenant, run) == "int-1"
    assert await store.take_awaiting(tenant, run) is None
    after = await store.get(tenant, run)
    assert after is not None and after.status == "running" and after.awaiting is None

    # the run resumes from a job only when it is waiting on exactly that job, and only once
    await store.set_state(tenant, run, "waiting_job", waiting_job="job-1")
    assert await store.take_waiting_job(tenant, run, "job-other") is False
    assert (await store.get(tenant, run)).status == "waiting_job"  # type: ignore[union-attr]
    assert await store.take_waiting_job(tenant, run, "job-1") is True
    assert await store.take_waiting_job(tenant, run, "job-1") is False
    assert (await store.get(tenant, run)).status == "running"  # type: ignore[union-attr]

    # two takers at once: one winner
    await store.set_state(tenant, run, "waiting_job", waiting_job="job-2")
    wins = await asyncio.gather(*(store.take_waiting_job(tenant, run, "job-2") for _ in range(6)))
    assert wins.count(True) == 1


def job(tenant: str, run: str | None = None, thread: str | None = None) -> JobRequest:
    return JobRequest(
        tenant_id=tenant,
        product_id="p",
        user_id="u1",
        run_id=run or str(uuid4()),
        thread_id=thread or str(uuid4()),
        capability="image.generate",
        workflow="w",
        prompt={},
        outputs={"image": {"node": "9", "type": "image"}},
    )


async def check_job_queue(queue, log, tenant: str) -> None:
    """`queue` has submit, claim, waiting, complete, requeue, recover, position, take_done and
    ack_done; `log` is the event log its submit writes the `queued` events to."""
    a, b = job(tenant), job(tenant)
    await queue.submit(a)
    await queue.submit(b)

    # the run is told where its job stands: 1 = next, 2 = behind one
    queued = [(await log.read(tenant, j.run_id, 0, 50))[0] for j in (a, b)]
    assert [(e["event"], e["status"], e["queue_position"]) for e in queued] == [
        ("job_progress", "queued", 1),
        ("job_progress", "queued", 2),
    ]

    # jobs are taken in the order they came
    waiting = await queue.waiting()
    assert [w.request.job_id for w in waiting] == [a.job_id, b.job_id]
    first = await queue.claim()
    assert first is not None and first.request.job_id == a.job_id
    assert [w.request.job_id for w in await queue.waiting()] == [b.job_id]
    assert await queue.position(waiting[1].entry_id) == 2  # one running ahead of it

    # a result is delivered, and delivered again only if nobody finishes with it
    await queue.complete(first.entry_id, {"job_id": a.job_id, "run_id": a.run_id})
    await queue.complete(first.entry_id, {"job_id": a.job_id, "run_id": a.run_id})  # harmless
    done = await queue.take_done(retry_after_s=0.2)
    assert [d.message["job_id"] for d in done] == [a.job_id] and done[0].attempts == 1
    assert await queue.take_done(retry_after_s=0.2) == []
    await asyncio.sleep(0.25)
    again = await queue.take_done(retry_after_s=0.2)
    assert [d.attempts for d in again] == [2]
    await queue.ack_done(again[0].entry_id)
    await asyncio.sleep(0.25)
    assert await queue.take_done(retry_after_s=0.2) == []

    # a transient failure sends the job to the back
    c = job(tenant)
    await queue.submit(c)
    second = await queue.claim()
    assert second is not None and second.request.job_id == b.job_id
    await queue.requeue(second.entry_id)
    assert [w.request.job_id for w in await queue.waiting()] == [c.job_id, b.job_id]

    # a job held by a worker that is gone comes back
    held = await queue.claim()
    assert held is not None and held.request.job_id == c.job_id
    assert await queue.recover() == 1
    assert [w.request.job_id for w in await queue.waiting()] == [c.job_id, b.job_id]
    assert await queue.claim() is not None and await queue.claim() is not None
    assert await queue.claim() is None
