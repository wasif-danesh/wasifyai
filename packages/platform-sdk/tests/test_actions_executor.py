"""The executor (ADR-0068 decision 2): validation, requires, approvals, jobs, audit, usage."""

import asyncio
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from wasifyai_platform_sdk import InMemoryUsageRecorder, RunContext, reset_context, set_context
from wasifyai_platform_sdk.actions import (
    Action,
    ActionExecutor,
    ActionRefused,
    ActionRegistry,
    ApprovalPolicy,
    CallBinding,
    InMemoryApprovalStore,
    InMemoryAuditStore,
    Outcome,
    Readiness,
    RunBinding,
    need_model,
)
from wasifyai_platform_sdk.actions.testing import FakeActionHost
from wasifyai_platform_sdk.errors import RunError
from wasifyai_platform_sdk.identity import Identity

ME = Identity("t1", "u1")
SECRET = "the secret words a person typed"


class In(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=50)
    count: int = Field(1, ge=1, le=3)


class Out(BaseModel):
    model_config = ConfigDict(extra="forbid")
    echoed: str


def _result(outputs: dict[str, Any], p: In) -> Outcome | None:
    if not outputs.get("thing_id"):
        return None
    return Outcome.ok({"echoed": outputs["thing_id"]}, f"Made {outputs['thing_id']}.")


async def _call(p: In, ctx) -> Outcome:
    return Outcome.ok({"echoed": p.text}, f"Echoed {p.text}.")


def act(id: str, **kw) -> Action:
    base: dict[str, Any] = dict(
        id=id, title=f"Title of {id}", summary="s", description="d", input=In, output=Out,
        effect="read", bind=CallBinding(_call), ui="chat", product="demo",
        examples=({"text": "hi"},),
    )  # fmt: skip
    return Action(**{**base, **kw})


def setup(*actions: Action, host: FakeActionHost | None = None):
    host = host or FakeActionHost()
    usage, audit, approvals = InMemoryUsageRecorder(), InMemoryAuditStore(), InMemoryApprovalStore()
    ex = ActionExecutor(
        ActionRegistry(actions), host, audit=audit, approvals=approvals, usage=usage
    )
    return ex, host, usage, audit, approvals


async def run(ex: ActionExecutor, action_id: str, params=None, origin="assistant", **kw):
    return await ex.run_action(
        action_id, {"text": "hi"} if params is None else params, origin, actor=ME, **kw
    )


# ---- the happy path, the records --------------------------------------------------------------


async def test_a_read_runs_and_leaves_an_audit_entry_and_a_usage_event():
    ex, _, usage, audit, _ = setup(act("demo.read"))
    r = await run(ex, "demo.read", {"text": SECRET})
    assert (r.status, r.output, r.text) == ("ok", {"echoed": SECRET}, f"Echoed {SECRET}.")
    [entry] = audit.entries
    assert (entry.action_id, entry.origin, entry.status, entry.effect) == (
        "demo.read", "assistant", "ok", "read",
    )  # fmt: skip
    assert (entry.tenant_id, entry.product_id, entry.user_id) == ("t1", "demo", "u1")
    assert entry.approval == "none"
    [event] = usage.events
    assert (event.kind, event.quantity, event.unit) == ("action.run", 1, "actions")
    assert (event.tenant_id, event.product_id, event.user_id) == ("t1", "demo", "u1")
    assert event.meta == {
        "action": "demo.read", "origin": "assistant", "status": "ok", "effect": "read",
    }  # fmt: skip


async def test_the_audit_log_holds_no_content():
    ex, _, usage, audit, _ = setup(
        act("demo.read"),
        act("demo.fail", bind=RunBinding("demo", "thing", lambda p, c: {"text": p.text}, _result)),
    )
    await run(ex, "demo.read", {"text": SECRET})
    await run(ex, "demo.fail", {"text": SECRET})
    await run(ex, "demo.read", {"text": ""})  # refused
    dumped = " ".join(e.model_dump_json() for e in audit.entries)
    dumped += " ".join(e.model_dump_json() for e in usage.events)
    assert SECRET not in dumped and "echoed" not in dumped


async def test_an_unknown_action_is_an_error_not_an_exception():
    ex, _, _, audit, _ = setup(act("demo.read"))
    r = await run(ex, "nope.nothing")
    assert (r.status, r.code) == ("error", "unknown_action")
    assert audit.entries[0].status == "error"


async def test_the_actor_defaults_to_the_user_of_the_current_run():
    ex, _, _, audit, _ = setup(act("demo.read"))
    token = set_context(RunContext("tenantX", "wasifyai-assistant", "userY", run_id="r"))
    try:
        r = await ex.run_action("demo.read", {"text": "hi"}, "assistant")
    finally:
        reset_context(token)
    assert r.ok and (audit.entries[0].tenant_id, audit.entries[0].user_id) == ("tenantX", "userY")


async def test_a_surface_with_no_run_gets_a_context_for_the_call():
    seen: list[Any] = []

    async def peek(p, ctx):
        from wasifyai_platform_sdk import require_context

        seen.append(require_context())
        return Outcome.ok({"echoed": "x"}, "ok")

    ex, *_ = setup(act("demo.read", bind=CallBinding(peek)))
    assert (await run(ex, "demo.read", origin="mcp:Codex")).ok
    assert (seen[0].tenant_id, seen[0].user_id, seen[0].product_id) == ("t1", "u1", "demo")
    from wasifyai_platform_sdk.context import current_context

    assert current_context() is None  # and it is gone afterwards


# ---- validation -------------------------------------------------------------------------------


async def test_invalid_parameters_come_back_in_words_for_the_model_to_fix():
    ex, *_ = setup(act("demo.read"))
    r = await run(ex, "demo.read", {"count": 9, "extra": 1})
    assert (r.status, r.code) == ("refused", "invalid_input")
    assert "'text' is required." in r.text
    assert "'count'" in r.text and "'extra' is not something this action takes." in r.text


async def test_a_surface_only_gets_what_the_action_allows():
    ex, *_ = setup(act("demo.read", surfaces=("assistant",)))
    assert (await run(ex, "demo.read", origin="assistant")).ok
    r = await run(ex, "demo.read", origin="mcp:Codex")
    assert (r.status, r.code) == ("refused", "not_offered")
    assert (await run(ex, "demo.read", origin="window")).ok  # the window is the person


async def test_the_products_own_check_runs_before_anything_else_and_refuses_in_words():
    async def check(p, ctx):
        if len(p.text) > 3:
            raise ActionRefused("too_long", "Please keep it under 3 characters.")

    ex, host, *_ = setup(
        act(
            "demo.make",
            effect="make",
            bind=RunBinding("demo", "thing", lambda p, c: {}, _result, check=check),
        )
    )
    r = await run(ex, "demo.make", {"text": "long text"}, policy=ApprovalPolicy(make="auto"))
    assert (r.status, r.code, r.text) == (
        "refused",
        "too_long",
        "Please keep it under 3 characters.",
    )
    assert host.runs == []


# ---- requires ---------------------------------------------------------------------------------


async def test_requires_resolve_to_needs_setup_with_the_step_that_fixes_it():
    host = FakeActionHost()
    host.not_ready(need_model("speak"), Readiness.needs_setup("Get a speech model.", ui="models"))
    ex, _, _, audit, _ = setup(act("demo.read", requires=(need_model("speak"),)), host=host)
    r = await run(ex, "demo.read")
    assert r.status == "needs_setup" and r.setup is not None
    assert (r.setup.step, r.setup.ui) == ("Get a speech model.", "models")
    assert "Get a speech model." in r.text
    assert audit.entries[0].status == "needs_setup"


async def test_unavailable_beats_needs_setup_and_says_why():
    host = FakeActionHost()
    host.not_ready(need_model("speak"), Readiness.needs_setup("Get a speech model."))
    host.not_ready(need_model("music"), Readiness.unavailable("Music is not served here."))
    ex, *_ = setup(act("demo.read", requires=(need_model("speak"), need_model("music"))), host=host)
    r = await run(ex, "demo.read")
    assert (r.status, r.code, r.text) == ("refused", "unavailable", "Music is not served here.")


# ---- approvals --------------------------------------------------------------------------------


async def test_a_make_asks_by_default_and_runs_after_the_person_says_yes():
    ex, host, usage, audit, approvals = setup(act("demo.make", effect="make"))
    first = await run(ex, "demo.make")
    assert first.status == "needs_approval" and first.approval_id
    assert usage.events == []  # nothing ran
    [pending] = await approvals.pending("t1", "u1")
    assert pending.params == {"text": "hi", "count": 1}  # the card can show what will be done

    assert await ex.decide_approval(ME, first.approval_id, True)
    second = await run(ex, "demo.make", approval_id=first.approval_id)
    assert second.ok and audit.entries[-1].approval == "person"
    assert (await approvals.get("t1", "u1", first.approval_id)).status == "used"  # type: ignore[union-attr]
    assert (await approvals.get("t1", "u1", first.approval_id)).params is None  # type: ignore[union-attr]

    again = await run(ex, "demo.make", approval_id=first.approval_id)  # an approval works once
    assert (again.status, again.code) == ("refused", "used_approval")


async def test_an_approval_is_for_exactly_what_was_asked():
    ex, *_ = setup(act("demo.make", effect="make"))
    first = await run(ex, "demo.make", {"text": "a"})
    assert first.approval_id
    await ex.decide_approval(ME, first.approval_id, True)
    other = await run(ex, "demo.make", {"text": "b"}, approval_id=first.approval_id)
    assert (other.status, other.code) == ("refused", "unknown_approval")


async def test_an_approval_of_another_person_is_no_approval():
    ex, *_ = setup(act("demo.make", effect="make"))
    first = await run(ex, "demo.make")
    assert first.approval_id
    await ex.decide_approval(ME, first.approval_id, True)
    r = await ex.run_action(
        "demo.make", {"text": "hi"}, "assistant", actor=Identity("t1", "someone-else"),
        approval_id=first.approval_id,
    )  # fmt: skip
    assert r.code == "unknown_approval"
    assert not await ex.decide_approval(Identity("t1", "someone-else"), first.approval_id, False)


async def test_a_no_ends_it():
    ex, host, *_ = setup(act("demo.make", effect="make"))
    first = await run(ex, "demo.make")
    assert first.approval_id
    await ex.decide_approval(ME, first.approval_id, False)
    r = await run(ex, "demo.make", approval_id=first.approval_id)
    assert (r.status, r.code, r.text) == ("refused", "denied", "The person said no.")


async def test_the_call_can_wait_a_little_for_the_person():
    ex, *_ = setup(act("demo.make", effect="make"))

    async def answer_soon():
        await asyncio.sleep(0.05)
        [p] = await ex.approvals.pending("t1", "u1")
        await ex.decide_approval(ME, p.id, True)

    task = asyncio.create_task(answer_soon())
    r = await run(ex, "demo.make", approval_wait_s=3)
    await task
    assert r.ok  # it waited, got the yes and ran

    slow = await run(ex, "demo.make", {"text": "other"}, approval_wait_s=0.3)
    assert slow.status == "needs_approval"  # no answer in time: tell the person where to look


async def test_destroy_and_consent_ask_whatever_the_policy_says():
    destroy = act("demo.destroy", effect="destroy")
    consent = act("demo.consent", effect="make", flags=("needs_consent",), consent="I agree.")
    ex, *_ = setup(destroy, consent)
    open_policy = ApprovalPolicy(make="auto", change="auto")
    for action_id in ("demo.destroy", "demo.consent"):
        r = await run(ex, action_id, policy=open_policy)
        assert r.status == "needs_approval", action_id
    r = await run(ex, "demo.consent", {"text": "hi", "count": 2}, policy=open_policy)
    assert "I agree." in r.text  # the statement the person will be shown


async def test_an_agent_cannot_approve_for_itself():
    ex, *_ = setup(act("demo.destroy", effect="destroy"))
    for origin in ("assistant", "mcp:Codex"):
        r = await run(ex, "demo.destroy", origin=origin, person_approved=True)
        assert (r.status, r.code) == ("refused", "approval_not_allowed")


async def test_the_window_runs_a_make_at_once_but_a_delete_needs_its_own_yes():
    ex, _, _, audit, _ = setup(
        act("demo.make", effect="make"), act("demo.destroy", effect="destroy")
    )
    assert (await run(ex, "demo.make", origin="window")).ok
    asked = await run(ex, "demo.destroy", origin="window")
    assert asked.status == "needs_approval"
    done = await run(ex, "demo.destroy", origin="window", person_approved=True)
    assert done.ok and audit.entries[-1].approval == "person"


async def test_the_assistants_current_behaviour_is_a_setting_not_a_default():
    ex, *_ = setup(act("demo.make", effect="make"))
    assert (await run(ex, "demo.make")).status == "needs_approval"
    assert (await run(ex, "demo.make", policy=ApprovalPolicy(make="auto"))).ok


# ---- child runs -------------------------------------------------------------------------------


def child(check=None):
    return RunBinding("wasifyai-demo", "thing", lambda p, c: {"text": p.text}, _result, check=check)


async def test_a_child_run_becomes_the_documented_result_and_progress_is_passed_on():
    host = FakeActionHost()
    host.script(
        "wasifyai-demo",
        [
            {"event": "job_progress", "job_id": "j1", "progress": 0.5},
            {"event": "done", "outputs": {"status": "done", "thing_id": "th-1"}},
        ],
    )
    ex, *_ = setup(act("demo.make", effect="make", bind=child()), host=host)
    seen: list[dict] = []
    r = await run(ex, "demo.make", policy=ApprovalPolicy(make="auto"), on_event=seen.append)
    assert (r.status, r.output, r.text) == ("ok", {"echoed": "th-1"}, "Made th-1.")
    assert host.runs == [("wasifyai-demo", {"text": "hi"})]
    assert seen == [{"event": "job_progress", "job_id": "j1", "progress": 0.5}]


async def test_a_refused_child_run_says_why():
    host = FakeActionHost()
    host.script(
        "wasifyai-demo",
        [
            {
                "event": "done",
                "outputs": {
                    "status": "refused",
                    "refusal": {"code": "moderation", "message": "Not allowed."},
                },
            }
        ],
    )
    ex, *_ = setup(act("demo.make", effect="make", bind=child()), host=host)
    r = await run(ex, "demo.make", policy=ApprovalPolicy(make="auto"))
    assert (r.status, r.code, r.text) == (
        "refused",
        "moderation",
        "The thing was not made: Not allowed.",
    )


async def test_a_failed_child_run_is_an_error_with_the_products_sentence():
    host = FakeActionHost()
    host.script(
        "wasifyai-demo", [{"event": "error", "code": "engine_stopped", "message": "It stopped"}]
    )
    ex, *_ = setup(act("demo.make", effect="make", bind=child()), host=host)
    r = await run(ex, "demo.make", policy=ApprovalPolicy(make="auto"))
    assert (r.status, r.code) == ("error", "engine_stopped")
    assert r.text == "The thing could not be made: It stopped."


async def test_an_output_the_action_does_not_document_is_an_error():
    host = FakeActionHost()
    host.script("wasifyai-demo", [{"event": "done", "outputs": {"status": "done", "thing_id": 7}}])
    bad = RunBinding(
        "wasifyai-demo", "thing", lambda p, c: {}, lambda o, p: Outcome.ok({"unexpected": 1}, "x")
    )
    ex, *_ = setup(act("demo.make", effect="make", bind=bad), host=host)
    r = await run(ex, "demo.make", policy=ApprovalPolicy(make="auto"))
    assert (r.status, r.code) == ("error", "bad_output")


async def test_an_unexpected_failure_never_leaks():
    async def boom(p, ctx):
        raise RuntimeError(f"stack trace with {SECRET}")

    ex, *_ = setup(act("demo.read", bind=CallBinding(boom)))
    r = await run(ex, "demo.read")
    assert (r.status, r.code, r.text) == ("error", "failed", "That could not be done.")
    assert SECRET not in r.model_dump_json()


async def test_a_runerror_ends_in_its_own_sentence():
    async def stop(p, ctx):
        raise RunError("busy", "The speech engine is busy.", retryable=True)

    ex, *_ = setup(act("demo.read", bind=CallBinding(stop)))
    r = await run(ex, "demo.read")
    assert (r.status, r.code, r.text) == ("error", "busy", "The speech engine is busy.")


# ---- jobs -------------------------------------------------------------------------------------


async def test_a_long_action_answers_running_with_a_handle_and_finishes_in_the_background():
    gate = asyncio.Event()

    async def slow(p, ctx):
        ctx.emit({"event": "job_progress", "progress": 0.25})
        await gate.wait()
        return Outcome.ok({"echoed": p.text}, "Finished.")

    ex, _, usage, audit, _ = setup(
        act("demo.slow", effect="read", long=True, bind=CallBinding(slow))
    )
    r = await run(ex, "demo.slow", wait_seconds=0.05)
    assert r.status == "running" and r.job_id and r.output["job_id"] == r.job_id
    assert audit.entries[-1].status == "running" and audit.entries[-1].job_id == r.job_id
    assert usage.events == []  # the work has not ended

    job = ex.jobs.get("t1", "u1", r.job_id)
    assert job and job.status == "running" and job.progress == {"progress": 0.25}
    gate.set()
    assert await ex.jobs.wait(job, 2)
    assert job.result and job.result.status == "ok" and job.result.job_id == r.job_id
    assert [e.status for e in audit.entries if e.job_id == r.job_id] == ["running", "ok"]
    assert [e.meta["status"] for e in usage.events] == ["ok"]


async def test_a_long_action_that_ends_within_the_wait_just_answers():
    ex, *_ = setup(act("demo.slow", long=True))
    r = await run(ex, "demo.slow", wait_seconds=5)
    assert r.status == "ok" and r.job_id  # it was a job, and it is over


async def test_without_wait_seconds_a_long_action_is_awaited_inline():
    ex, *_ = setup(act("demo.slow", long=True))
    r = await run(ex, "demo.slow")
    assert r.status == "ok" and r.job_id is None


async def test_waiting_is_bounded_below_the_clients_timeouts():
    ex, *_ = setup(act("demo.slow", long=True))
    r = await run(ex, "demo.slow", wait_seconds=10_000)
    assert r.ok  # (the bound is 50 s; a finished job does not wait at all)


async def test_a_job_of_another_person_does_not_exist():
    ex, *_ = setup(act("demo.slow", long=True))
    gate = asyncio.Event()

    async def hold(p, ctx):
        await gate.wait()
        return Outcome.ok({"echoed": "x"}, "x")

    ex.registry.add(act("demo.hold", long=True, bind=CallBinding(hold)))
    r = await run(ex, "demo.hold", wait_seconds=0.01)
    assert r.job_id
    assert ex.jobs.get("t1", "u1", r.job_id) is not None
    assert ex.jobs.get("t1", "someone-else", r.job_id) is None
    assert ex.jobs.get("t2", "u1", r.job_id) is None
    gate.set()


async def test_a_direct_call_can_be_stopped_and_a_child_run_cannot():
    gate = asyncio.Event()

    async def hold(p, ctx):
        await gate.wait()
        return Outcome.ok({"echoed": "x"}, "x")

    host = FakeActionHost()

    async def endless(p, ev):  # a child run that never ends
        return {}

    ex, *_ = setup(
        act("demo.hold", long=True, bind=CallBinding(hold)),
        act(
            "demo.child",
            effect="make",
            long=True,
            bind=RunBinding("wasifyai-demo", "thing", lambda p, c: {}, _result),
        ),  # fmt: skip
        host=host,
    )

    class Never:
        async def __aiter__(self):
            await asyncio.Event().wait()
            yield {}

    host.run_product = lambda pid, gi: Never()  # type: ignore[method-assign]
    held = await run(ex, "demo.hold", wait_seconds=0.01)
    child_job = await run(ex, "demo.child", wait_seconds=0.01, policy=ApprovalPolicy(make="auto"))
    assert held.job_id and child_job.job_id
    job, run_job = ex.jobs.get("t1", "u1", held.job_id), ex.jobs.get("t1", "u1", child_job.job_id)
    assert job and run_job and job.cancellable and not run_job.cancellable
    assert await ex.cancel_job(job) and job.status == "cancelled"
    assert not await ex.cancel_job(run_job) and run_job.status == "running"
    assert run_job.task is not None
    run_job.task.cancel()
    await asyncio.gather(run_job.task, return_exceptions=True)


# ---- principals and scopes (stage F3; ADR-0092) -----------------------------------------------


async def test_a_principal_is_held_to_its_scopes_and_the_audit_names_its_origin():
    from wasifyai_platform_sdk import Principal

    ex, _, _, audit, _ = setup(act("demo.read"), act("library.list"))
    key = Principal("api_key", "t1", "u1", scopes=frozenset({"read"}), origin="api:k1")
    ok = await ex.run_action("demo.read", {"text": "hi"}, key.origin, actor=key)
    assert ok.ok and ok.output == {"echoed": "hi"}
    no = await ex.run_action("library.list", {"text": "hi"}, key.origin, actor=key)
    assert no.status == "refused" and no.code == "not_offered"
    assert no.text == "This key may not list, open and delete creations (the library scope)."
    assert [(e.action_id, e.origin, e.status) for e in audit.entries] == [
        ("demo.read", "api:k1", "ok"),
        ("library.list", "api:k1", "refused"),
    ]
    assert audit.entries[0].user_id == "u1"  # the key acts as the person who made it


async def test_a_person_principal_changes_nothing_for_the_window():
    from wasifyai_platform_sdk import Principal

    ex, _, _, _, _ = setup(act("library.list"))
    me = Principal.person("t1", "u1")
    r = await ex.run_action("library.list", {"text": "hi"}, "window", actor=me)
    assert r.ok
