"""One job per person (ADR-0088, stage J4): the policy, its leases and the media sink in front of
the line. The Redis leases are checked on a real Redis in services/api/tests/integration."""

import pytest
from wasifyai_platform_sdk import (
    InMemoryJobSink,
    JobRequest,
    RunContext,
    reset_context,
    set_context,
)
from wasifyai_platform_sdk.jobpolicy import (
    LEASE_MARGIN_S,
    AdmittedSink,
    InMemoryLeases,
    JobLimitReached,
    JobPolicy,
    no_limit,
    words_for,
)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def policy(limit: int = 1, clock: Clock | None = None) -> JobPolicy:
    clock = clock or Clock()
    return JobPolicy(InMemoryLeases(clock), lambda: limit, clock)


async def test_a_second_job_is_refused_in_words_that_name_the_first():
    p = policy()
    await p.admit("t1", "u1", "j1", "video.generate", 600)
    with pytest.raises(JobLimitReached) as e:
        await p.admit("t1", "u1", "j2", "image.generate", 600)
    assert e.value.code == "busy" and e.value.retryable
    assert e.value.message == (
        "You already have something being made (a video). Wait for it to finish, or stop it, "
        "then try again."
    )
    assert e.value.blocking.job_id == "j1"


async def test_the_place_is_free_once_the_job_is_given_back():
    p = policy()
    await p.admit("t1", "u1", "j1", "speech.speak", 600)
    await p.release("t1", "u1", "j1")
    await p.admit("t1", "u1", "j2", "speech.speak", 600)
    assert [lease.job_id for lease in await p.leases.held("t1", "u1")] == ["j2"]


async def test_the_same_job_asking_again_is_not_refused_by_itself():
    p = policy()
    await p.admit("t1", "u1", "j1", "model3d.generate", 600)
    await p.admit("t1", "u1", "j1", "model3d.generate", 600)  # a retry of the same submit


async def test_people_and_tenants_do_not_share_a_place():
    p = policy()
    await p.admit("t1", "u1", "j1", "image.generate", 600)
    await p.admit("t1", "u2", "j2", "image.generate", 600)
    await p.admit("t2", "u1", "j3", "image.generate", 600)


async def test_a_lease_runs_out_after_its_time_out_and_margin_so_a_crash_locks_nobody_out():
    clock = Clock()
    p = policy(clock=clock)
    await p.admit("t1", "u1", "j1", "image.generate", 600)
    clock.now += 600 + LEASE_MARGIN_S - 1
    with pytest.raises(JobLimitReached):
        await p.admit("t1", "u1", "j2", "image.generate", 600)
    clock.now += 2
    await p.admit("t1", "u1", "j2", "image.generate", 600)


async def test_no_limit_admins_admin_jobs_and_the_system_are_never_refused():
    free = no_limit()
    for i in range(3):
        await free.admit("t1", "u1", f"j{i}", "image.generate", 600)
    p = policy()
    await p.admit("t1", "u1", "j1", "image.generate", 600)
    await p.admit("t1", "u1", "a1", "admin.fetch_model", 600)
    await p.admit("t1", "u1", "a2", "image.generate", 600, role="admin")
    await p.admit("t1", "system", "s1", "train.words", 600)
    await p.admit("t1", "system", "s2", "train.words", 600)


async def test_the_role_is_read_from_the_run_when_it_is_not_given():
    p = policy()
    token = set_context(RunContext("t1", "p1", "u1", role="admin"))
    try:
        await p.admit("t1", "u1", "j1", "image.generate", 600)
        await p.admit("t1", "u1", "j2", "image.generate", 600)
    finally:
        reset_context(token)


async def test_the_limit_is_read_when_a_job_asks_not_when_the_policy_is_made():
    limit = [1]
    clock = Clock()
    p = JobPolicy(InMemoryLeases(clock), lambda: limit[0], clock)
    await p.admit("t1", "u1", "j1", "image.generate", 600)
    limit[0] = 2
    await p.admit("t1", "u1", "j2", "image.generate", 600)
    with pytest.raises(JobLimitReached):
        await p.admit("t1", "u1", "j3", "image.generate", 600)


def test_every_kind_has_words_and_the_longest_match_wins():
    assert words_for("speech.music") == "a song"
    assert words_for("speech.convert") == "a voice job"
    assert words_for("builder.render") == "a motion graphics video"
    assert words_for("something.new") == "a job"


def request(job_id: str) -> JobRequest:
    return JobRequest(
        job_id=job_id, tenant_id="t1", product_id="p1", user_id="u1", capability="image.generate",
        workflow="demo", prompt={}, outputs={},
    )  # fmt: skip


async def test_the_media_sink_queues_only_what_the_policy_lets_in():
    inner = InMemoryJobSink()
    sink = AdmittedSink(inner, policy())
    await sink.submit(request("j1"))
    with pytest.raises(JobLimitReached):
        await sink.submit(request("j2"))
    assert [r.job_id for r in inner.submitted] == ["j1"]


async def test_a_job_the_sink_could_not_queue_gives_its_place_back():
    class Broken:
        async def submit(self, request):
            raise ConnectionError("redis is down")

    p = policy()
    sink = AdmittedSink(Broken(), p)  # type: ignore[arg-type]
    with pytest.raises(ConnectionError):
        await sink.submit(request("j1"))
    assert await p.leases.held("t1", "u1") == []


async def test_the_sinks_own_calls_go_through():
    class Desktop(InMemoryJobSink):
        def cancel(self, job_id: str) -> str:
            return f"stopped {job_id}"

    sink = AdmittedSink(Desktop(), no_limit())
    assert sink.cancel("j1") == "stopped j1"  # type: ignore[attr-defined]
