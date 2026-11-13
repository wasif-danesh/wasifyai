"""Rules every audit store and approval store must follow (ADR-0068); run against memory, SQLite
(the desktop) and Postgres (the web)."""

from datetime import UTC, datetime, timedelta

from wasifyai_platform_sdk.actions import ActionResult, ApprovalRecord, AuditEntry, Job


def audit(tenant: str, user: str, **kw) -> AuditEntry:
    base = dict(
        tenant_id=tenant, product_id="wasifyai-voice", user_id=user, action_id="speech.speak",
        origin="assistant", effect="make", status="ok", duration_ms=12,
    )  # fmt: skip
    return AuditEntry(**{**base, **kw})  # type: ignore[arg-type]


async def check_audit(store, tenant: str) -> None:
    t0 = datetime.now(UTC) - timedelta(minutes=5)
    await store.record(audit(tenant, "u1", created_at=t0))
    await store.record(
        audit(tenant, "u1", status="running", job_id="job-1", created_at=t0 + timedelta(seconds=1))
    )
    await store.record(
        audit(tenant, "u1", status="ok", job_id="job-1", created_at=t0 + timedelta(seconds=2))
    )
    await store.record(audit(tenant, "u2", action_id="library.delete", origin="mcp:Codex"))

    mine = await store.recent(tenant, "u1")
    assert [(e.status, e.job_id) for e in mine] == [
        ("ok", "job-1"),
        ("running", "job-1"),
        ("ok", None),
    ]
    assert mine[0].created_at > mine[-1].created_at and mine[0].created_at.tzinfo is not None
    assert (mine[0].tenant_id, mine[0].product_id, mine[0].origin) == (
        tenant, "wasifyai-voice", "assistant",
    )  # fmt: skip
    assert len(await store.recent(tenant, "u1", 2)) == 2
    assert [e.origin for e in await store.recent(tenant, "u2")] == ["mcp:Codex"]
    assert await store.recent("another-tenant", "u1") == []

    last = await store.last_for_job(tenant, "u1", "job-1")
    assert last is not None and last.status == "ok"
    assert await store.last_for_job(tenant, "u2", "job-1") is None  # another person's job
    assert await store.last_for_job("another-tenant", "u1", "job-1") is None
    assert await store.last_for_job(tenant, "u1", "nope") is None


def approval(tenant: str, user: str, **kw) -> ApprovalRecord:
    base = dict(
        tenant_id=tenant, product_id="wasifyai-voice", user_id=user, action_id="library.delete",
        origin="mcp:Codex", params_hash="h" * 64, summary="Delete a creation",
        params={"kind": "image", "id": "i1"},
    )  # fmt: skip
    return ApprovalRecord(**{**base, **kw})  # type: ignore[arg-type]


async def check_approvals(store, tenant: str) -> None:
    a, b = approval(tenant, "u1"), approval(tenant, "u2")
    await store.create(a)
    await store.create(b)

    got = await store.get(tenant, "u1", a.id)
    assert got is not None and got.status == "pending" and got.params == a.params
    assert got.params_hash == "h" * 64 and got.decided_at is None
    assert await store.get(tenant, "u2", a.id) is None  # not another person's
    assert await store.get("another-tenant", "u1", a.id) is None
    assert [r.id for r in await store.pending(tenant, "u1")] == [a.id]

    assert await store.consume(tenant, "u1", a.id) is False  # not approved yet
    assert await store.decide(tenant, "u2", a.id, True, "window") is None  # not theirs
    done = await store.decide(tenant, "u1", a.id, True, "window")
    assert done is not None and done.status == "approved" and done.decided_by == "window"
    assert done.params is None and done.decided_at is not None  # the parameters are dropped
    assert await store.decide(tenant, "u1", a.id, False, "window") is None  # decided once
    assert await store.pending(tenant, "u1") == []

    assert await store.consume(tenant, "u2", a.id) is False
    assert await store.consume(tenant, "u1", a.id) is True
    assert await store.consume(tenant, "u1", a.id) is False  # works once
    after = await store.get(tenant, "u1", a.id)
    assert after is not None and after.status == "used"

    denied = await store.decide(tenant, "u2", b.id, False, "window")
    assert denied is not None and denied.status == "denied"
    assert await store.consume(tenant, "u2", b.id) is False


async def check_jobs(store, tenant: str) -> None:
    """A long job is kept, changes as it runs, and only its person sees it (stage J3)."""
    job = Job(
        "j" + tenant[-8:], "speech.speak", tenant, "u1", "mcp:Codex", True, product_id="voice"
    )
    job.params = {"text": "hello"}
    await store.save(job)
    kept = await store.get(tenant, "u1", job.id)
    assert kept is not None and kept.status == "running" and not kept.live
    assert (kept.action_id, kept.origin, kept.product_id) == ("speech.speak", "mcp:Codex", "voice")
    assert kept.params == {"text": "hello"} and kept.cancellable and kept.run_id is None
    assert await store.get(tenant, "someone-else", job.id) is None
    assert await store.get("another-tenant", "u1", job.id) is None

    job.run_id, job.progress = "run-1", {"progress": 0.5}
    await store.save(job)
    kept = await store.get(tenant, "u1", job.id)
    assert kept is not None and kept.run_id == "run-1" and kept.progress == {"progress": 0.5}

    job.status, job.ended_at = "ok", job.started_at + 12.5
    job.result = ActionResult(status="ok", action_id="speech.speak", job_id=job.id, text="Done.")
    await store.save(job)
    kept = await store.get(tenant, "u1", job.id)
    assert kept is not None and kept.status == "ok" and kept.finished.is_set()
    assert kept.result is not None and kept.result.text == "Done." and kept.seconds == 12.5
