"""The one executor (ADR-0068 decision 2): the only way a surface other than the window does
anything.

    run_action(action_id, params, origin)
      -> find, surface   the action exists and is offered to this surface
      -> validate        params against the input model, then the product's own checks
      -> requires        ready, needs_setup (with the step) or unavailable (with the reason)
      -> approval        by the action's effect and flags and the caller's policy (policy.py)
      -> run             the child run of the product graph, or the direct function
      -> record          usage event, audit entry (no content), and the result

A long action may be run as a job with a handle (`wait_seconds`). Every call ends in exactly one
`ActionResult`, never an exception, so a surface only has to read a status."""

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from wasifyai_platform_sdk.actions.audit import (
    ApprovalRecord,
    ApprovalStore,
    AuditEntry,
    AuditStore,
    InMemoryApprovalStore,
    InMemoryAuditStore,
)
from wasifyai_platform_sdk.actions.host import ActionHost
from wasifyai_platform_sdk.actions.jobs import Job, JobBook
from wasifyai_platform_sdk.actions.library import LibraryKind
from wasifyai_platform_sdk.actions.model import (
    Action,
    ActionRefused,
    CallBinding,
    Outcome,
    Readiness,
    RunBinding,
    parse_origin,
    surface_of,
)
from wasifyai_platform_sdk.actions.policy import WINDOW_POLICY, ApprovalPolicy, decide
from wasifyai_platform_sdk.actions.registry import ActionRegistry
from wasifyai_platform_sdk.actions.result import ActionResult
from wasifyai_platform_sdk.context import (
    RunContext,
    current_context,
    require_context,
    reset_context,
    set_context,
)
from wasifyai_platform_sdk.errors import RunError
from wasifyai_platform_sdk.identity import Identity
from wasifyai_platform_sdk.tools import ToolUnavailable
from wasifyai_platform_sdk.usage import UsageEvent, UsageRecorder, record_safely

log = logging.getLogger(__name__)

ACTION_RUN = "action.run"  # the usage event of every call that ran an action
MAX_WAIT_SECONDS = 50.0  # below the 60 s tool limits of the agents' clients (ADR-0069 decision 7)
APPROVAL_POLL_S = 0.2
MAX_PROBLEMS = 5

Emit = Callable[[dict[str, Any]], None]


@dataclass
class ActionContext:
    """What a binding sees: who asked, from where, and the engine's side of the product."""

    actor: Identity
    origin: str
    action: Action
    host: ActionHost
    executor: "ActionExecutor"
    emit: Emit

    @property
    def deps(self) -> Any:
        return self.host.deps

    @property
    def registry(self) -> ActionRegistry:
        return self.executor.registry

    @property
    def jobs(self) -> JobBook:
        return self.executor.jobs

    @property
    def library(self) -> Mapping[str, LibraryKind]:
        return self.executor.library


def params_hash(action_id: str, actor: Identity, params: BaseModel) -> str:
    body = json.dumps(
        [action_id, actor.tenant_id, actor.user_id, params.model_dump(mode="json")],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode()).hexdigest()


def problems_in_words(error: ValidationError) -> str:
    """Why the parameters were not accepted, for the model to fix (ADR-0071 decision 3)."""
    lines = []
    for e in error.errors()[:MAX_PROBLEMS]:
        where = ".".join(str(p) for p in e["loc"]) or "the request"
        if e["type"] == "missing":
            lines.append(f"'{where}' is required.")
        elif e["type"] == "extra_forbidden":
            lines.append(f"'{where}' is not something this action takes.")
        else:
            lines.append(f"'{where}': {e['msg']}.".replace("..", "."))
    return " ".join(lines)


class ActionExecutor:
    def __init__(
        self,
        registry: ActionRegistry,
        host: ActionHost,
        *,
        audit: AuditStore | None = None,
        approvals: ApprovalStore | None = None,
        usage: UsageRecorder | None = None,
        library: Mapping[str, LibraryKind] | None = None,
        jobs: JobBook | None = None,
    ) -> None:
        self.registry = registry
        self.host = host
        self.audit = audit or InMemoryAuditStore()
        self.approvals = approvals or InMemoryApprovalStore()
        self.usage = usage
        self.library: Mapping[str, LibraryKind] = library or {}
        self.jobs = jobs or JobBook()

    # ---- readiness ----------------------------------------------------------------------

    async def readiness(self, action: Action) -> Readiness:
        """What `requires` resolves to: unavailable beats needs_setup, which beats ready."""
        found = [await self.host.readiness(need) for need in action.requires]
        for state in ("unavailable", "needs_setup"):
            for r in found:
                if r.state == state:
                    return r
        return Readiness.ready()

    # ---- the one entry point -----------------------------------------------------------

    async def run_action(
        self,
        action_id: str,
        params: Mapping[str, Any] | None,
        origin: str,
        *,
        actor: Identity | None = None,
        policy: ApprovalPolicy | None = None,
        wait_seconds: float | None = None,
        on_event: Emit | None = None,
        approval_id: str | None = None,
        approval_wait_s: float = 0.0,
        person_approved: bool = False,
    ) -> ActionResult:
        """Run one action for `actor` (the user of the current run when omitted).

        `wait_seconds` makes a `long` action a job: the call waits that long (at most 50 s), then
        answers `running` with a `job_id`. Without it the call waits for the end.
        `approval_id` is how a caller comes back with the person's yes (see `decide_approval`).
        `person_approved` is for the window only: its own click is the approval. Nothing that
        comes from an agent can set it."""
        started = time.monotonic()
        origin = parse_origin(origin)
        who = actor or _actor_of_current_run()
        emit = on_event or _ignore
        action = self.registry.get(action_id)
        if action is None:
            return await self._finish(
                None, who, origin, started,
                ActionResult(
                    status="error", action_id=action_id[:80], code="unknown_action",
                    text=f"There is no action called {action_id[:80]}.",
                ),
            )  # fmt: skip
        if person_approved and origin != "window":
            return await self._finish(
                action, who, origin, started,
                _refused(action, "approval_not_allowed", "Only the person can approve."),
            )  # fmt: skip
        surface = surface_of(origin)
        if surface is not None and surface not in action.surfaces:
            return await self._finish(
                action, who, origin, started,
                _refused(action, "not_offered", f"{action.title} is not available here."),
            )  # fmt: skip
        try:
            model = action.input.model_validate(dict(params or {}))
        except ValidationError as e:
            return await self._finish(
                action, who, origin, started,
                _refused(action, "invalid_input", problems_in_words(e)),
            )  # fmt: skip

        token = _ensure_context(who, action)
        try:
            ctx = ActionContext(who, origin, action, self.host, self, emit)
            ready = await self.readiness(action)
            if ready.state == "unavailable":
                why = ready.reason or f"{action.title} is unavailable."
                return await self._finish(
                    action, who, origin, started, _refused(action, "unavailable", why)
                )
            if ready.state == "needs_setup":
                return await self._finish(
                    action, who, origin, started,
                    ActionResult(
                        status="needs_setup", action_id=action.id, setup=ready,
                        text=f"{action.title} needs a step first: {ready.step}",
                        code="needs_setup",
                    ),
                )  # fmt: skip
            try:
                if action.bind.check is not None:
                    await action.bind.check(model, ctx)
            except ActionRefused as e:
                return await self._finish(
                    action, who, origin, started, _refused(action, e.code, e.message)
                )
            except ToolUnavailable as e:
                return await self._finish(
                    action, who, origin, started, _refused(action, "unavailable", e.message)
                )

            approver, waiting = await self._approval(
                action, model, ctx, policy, approval_id, approval_wait_s, person_approved
            )
            if waiting is not None:
                return await self._finish(action, who, origin, started, waiting)

            if action.long and wait_seconds is not None:
                return await self._as_job(
                    action, model, ctx, started, approver, min(wait_seconds, MAX_WAIT_SECONDS)
                )
            outcome = await self._execute(action, model, ctx)
            result = _result_of(action, outcome)
            return await self._finish(action, who, origin, started, result, approver, ran=True)
        finally:
            if token is not None:
                reset_context(token)

    # ---- approvals ----------------------------------------------------------------------

    async def _approval(
        self,
        action: Action,
        model: BaseModel,
        ctx: ActionContext,
        policy: ApprovalPolicy | None,
        approval_id: str | None,
        wait_s: float,
        person_approved: bool,
    ) -> tuple[str, ActionResult | None]:
        """How the go-ahead comes ("none", "auto" or "person"), or the result that ends the call
        because a person has to answer first."""
        chosen = policy or (WINDOW_POLICY if ctx.origin == "window" else ApprovalPolicy())
        if decide(action, chosen) == "run":
            return ("none" if action.effect == "read" else "auto"), None
        if person_approved:
            return "person", None
        who, digest = ctx.actor, params_hash(action.id, ctx.actor, model)
        if approval_id:
            rec = await self.approvals.get(who.tenant_id, who.user_id, approval_id)
            if rec is None or rec.action_id != action.id or rec.params_hash != digest:
                return "none", _refused(
                    action, "unknown_approval", "That approval is not for this request."
                )
            if rec.status == "denied":
                return "none", _refused(action, "denied", "The person said no.")
            if rec.status in ("approved", "pending"):
                rec = await self._wait_for(rec, wait_s)
                if rec.status == "approved" and await self.approvals.consume(
                    who.tenant_id, who.user_id, rec.id
                ):
                    return "person", None
                if rec.status == "denied":
                    return "none", _refused(action, "denied", "The person said no.")
                return "none", _waiting(action, rec)
            return "none", _refused(action, "used_approval", "That approval was already used.")
        rec = ApprovalRecord(
            tenant_id=who.tenant_id, product_id=action.product, user_id=who.user_id,
            action_id=action.id, origin=ctx.origin, params_hash=digest, summary=action.title,
            params=model.model_dump(mode="json"),
        )  # fmt: skip
        await self.approvals.create(rec)
        rec = await self._wait_for(rec, wait_s)
        if rec.status == "approved" and await self.approvals.consume(
            who.tenant_id, who.user_id, rec.id
        ):
            return "person", None
        if rec.status == "denied":
            return "none", _refused(action, "denied", "The person said no.")
        return "none", _waiting(action, rec)

    async def _wait_for(self, rec: ApprovalRecord, seconds: float) -> ApprovalRecord:
        end = time.monotonic() + max(0.0, seconds)
        while rec.status == "pending" and time.monotonic() < end:
            await asyncio.sleep(APPROVAL_POLL_S)
            rec = await self.approvals.get(rec.tenant_id, rec.user_id, rec.id) or rec
        return rec

    async def decide_approval(
        self, actor: Identity, approval_id: str, approved: bool, by: str = "window"
    ) -> bool:
        """The person's answer, given in the window. True when it was pending and is now decided.
        Only the window calls this: no action exposes it."""
        done = await self.approvals.decide(
            actor.tenant_id, actor.user_id, approval_id, approved, by
        )
        return done is not None

    # ---- running ------------------------------------------------------------------------

    async def _execute(self, action: Action, model: BaseModel, ctx: ActionContext) -> Outcome:
        bind = action.bind
        try:
            if isinstance(bind, CallBinding):
                done = await bind.call(model, ctx)
                if not isinstance(done, Outcome):  # a binding must answer with an outcome
                    log.error("action %s answered with no outcome", action.id)
                    return Outcome.error("That could not be done.", "failed")
                return done
            return await self._run_child(bind, model, ctx)
        except ActionRefused as e:
            return Outcome.refused(e.message, e.code)
        except ToolUnavailable as e:
            return Outcome.refused(e.message, "unavailable")
        except RunError as e:
            return Outcome.error(e.message, e.code)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("action %s failed", action.id)  # no params: they may hold content
            return Outcome.error("That could not be done.", "failed")

    async def _run_child(self, bind: RunBinding, model: BaseModel, ctx: ActionContext) -> Outcome:
        made = bind.build_input(model, ctx)
        graph_input = await made if asyncio.iscoroutine(made) else made
        assert isinstance(graph_input, dict)
        noun = bind.noun
        async for ev in self.host.run_product(bind.product_id, graph_input):
            kind = ev.get("event")
            if kind == "job_progress":
                ctx.emit(ev)
            elif kind == "error":
                return Outcome.error(
                    f"The {noun} could not be made: {ev.get('message', 'it failed')}.",
                    str(ev.get("code") or "failed"),
                )
            elif kind == "done":
                outputs = ev.get("outputs") or {}
                if outputs.get("status") == "refused":
                    refusal = outputs.get("refusal") or {}
                    reason = refusal.get("message", "it was not allowed")
                    return Outcome(
                        "refused", {"message": reason}, f"The {noun} was not made: {reason}",
                        str(refusal.get("code") or "refused"),
                    )  # fmt: skip
                built = bind.result(outputs, model)
                return built or Outcome.error(f"The {noun} could not be made.")
        return Outcome.error(f"The {noun} could not be made.")

    async def _as_job(
        self,
        action: Action,
        model: BaseModel,
        ctx: ActionContext,
        started: float,
        approver: str,
        seconds: float,
    ) -> ActionResult:
        job = self.jobs.start(
            action.id, ctx.actor.tenant_id, ctx.actor.user_id, ctx.origin,
            cancellable=isinstance(action.bind, CallBinding),
        )  # fmt: skip

        def note(ev: dict[str, Any]) -> None:
            job.progress = {k: v for k, v in ev.items() if k != "event"}
            ctx.emit(ev)

        job_ctx = ActionContext(ctx.actor, ctx.origin, action, self.host, self, note)

        async def work() -> None:
            try:
                outcome = await self._execute(action, model, job_ctx)
                result = _result_of(action, outcome).model_copy(update={"job_id": job.id})
                status = result.status if result.status in ("ok", "refused", "error") else "error"
            except asyncio.CancelledError:
                result = ActionResult(
                    status="error", action_id=action.id, code="cancelled", job_id=job.id,
                    text="It was stopped.",
                )  # fmt: skip
                status = "cancelled"
            await self._finish(action, ctx.actor, ctx.origin, started, result, approver, ran=True)
            self.jobs.finish(job, status, result)  # type: ignore[arg-type]

        job.task = asyncio.create_task(work())
        if await self.jobs.wait(job, seconds) and job.result is not None:
            return job.result
        running = ActionResult(
            status="running", action_id=action.id, job_id=job.id,
            text=f"{action.title} is running as job {job.id}. Ask for its status or wait for it.",
            output={"job_id": job.id, "status": "running"},
        )  # fmt: skip
        return await self._finish(action, ctx.actor, ctx.origin, started, running, approver)

    async def cancel_job(self, job: Job) -> bool:
        """Stop a job that can be stopped. A child run of a product graph cannot be: once started
        it finishes and is kept in the library."""
        if job.status != "running" or not job.cancellable or job.task is None:
            return False
        job.task.cancel()
        await asyncio.gather(job.task, return_exceptions=True)
        return True

    # ---- records ------------------------------------------------------------------------

    async def _finish(
        self,
        action: Action | None,
        who: Identity,
        origin: str,
        started: float,
        result: ActionResult,
        approver: str = "none",
        *,
        ran: bool = False,
    ) -> ActionResult:
        """Write the audit entry (and, when work ended, the usage event), and answer."""
        product = action.product if action else "platform"
        entry = AuditEntry(
            tenant_id=who.tenant_id, product_id=product, user_id=who.user_id,
            action_id=result.action_id, origin=origin, effect=action.effect if action else "",
            status=result.status, code=result.code, approval=approver,  # type: ignore[arg-type]
            job_id=result.job_id, duration_ms=int((time.monotonic() - started) * 1000),
        )  # fmt: skip
        try:
            await self.audit.record(entry)
        except Exception:
            log.exception("could not write the audit entry")  # never fail the person's request
        if ran and self.usage is not None:
            await record_safely(
                self.usage,
                UsageEvent(
                    tenant_id=who.tenant_id, product_id=product, user_id=who.user_id,
                    kind=ACTION_RUN, quantity=1, unit="actions",
                    meta={
                        "action": result.action_id, "origin": origin, "status": result.status,
                        "effect": action.effect if action else "",
                    },
                ),
            )  # fmt: skip
        return result


def _ignore(_: dict[str, Any]) -> None:
    return None


def _actor_of_current_run() -> Identity:
    ctx = require_context()
    return Identity(ctx.tenant_id, ctx.user_id)


def _ensure_context(who: Identity, action: Action):
    """Product code and the host read the user from the run context. Inside a run it is already
    there; for a surface with no run (MCP) it is set for the length of the call."""
    ctx = current_context()
    if ctx is not None and (ctx.tenant_id, ctx.user_id) == (who.tenant_id, who.user_id):
        return None
    return set_context(RunContext(who.tenant_id, action.product, who.user_id))


def _refused(action: Action, code: str, text: str) -> ActionResult:
    return ActionResult(status="refused", action_id=action.id, code=code, text=text)


def _waiting(action: Action, rec: ApprovalRecord) -> ActionResult:
    statement = f" {action.consent}" if action.consent else ""
    return ActionResult(
        status="needs_approval", action_id=action.id, approval_id=rec.id, code="needs_approval",
        text=f"{action.title} needs the person's approval, which is asked for in the Wasify AI "
        f"window.{statement} Tell them to open the window, then try again.",
        output={"approval_id": rec.id},
    )  # fmt: skip


def _result_of(action: Action, outcome: Outcome) -> ActionResult:
    """The outcome as a result; a good outcome must match the output the action documents."""
    if outcome.status != "ok":
        return ActionResult(
            status=outcome.status, action_id=action.id, text=outcome.text,
            output=outcome.output, code=outcome.code,
        )  # fmt: skip
    try:
        output = action.output.model_validate(outcome.output).model_dump(
            mode="json", exclude_none=True
        )
    except ValidationError:
        log.error("action %s answered with an output it does not document", action.id)
        return ActionResult(
            status="error", action_id=action.id, code="bad_output",
            text="That finished, but the result could not be read.",
        )  # fmt: skip
    return ActionResult(status="ok", action_id=action.id, text=outcome.text, output=output)
