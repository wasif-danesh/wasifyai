"""Run manager: executes graphs and writes their events to the shared event log.

Nothing here is tied to the replica that started a run. State lives in three shared places:
the LangGraph checkpoint (Postgres), the event log and the run store (Redis in production).
Any replica can therefore resume a run, and any replica can serve its SSE stream (ADR-0021).
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Coroutine
from typing import Any
from uuid import UUID, uuid4

from langgraph.types import Command
from wasifyai_contracts import (
    TERMINAL_EVENTS,
    DoneEvent,
    ErrorEvent,
    InterruptEvent,
    JobProgressEvent,
    NodeEvent,
    ReasoningEvent,
    TokenEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from wasifyai_platform_sdk import (
    EventLog,
    JobFailed,
    RunContext,
    RunError,
    RunRecord,
    RunStore,
    set_context,
)
from wasifyai_platform_sdk.context import current_context

from wasifyai_api.metrics import record_run

log = logging.getLogger(__name__)

# a stop that reached another replica is noticed at most this often (seconds) by the one running it
CANCEL_CHECK_S = 1.0
FINISHED = ("done", "error", "cancelled")


class RunIdTaken(Exception):
    """A client chose a run id that belongs to someone else (or to another product)."""


class RunManager:
    def __init__(self, event_log: EventLog, store: RunStore, graphs: dict[str, Any]):
        self.log = event_log
        self.store = store
        self.graphs = graphs
        self._tasks: set[asyncio.Task] = set()
        self._by_run: dict[str, asyncio.Task] = {}  # the runs executing in this process, by run id
        # the role of the person who started each run here (ADR-0088: an admin's jobs are not
        # limited); a run resumed on another replica runs as a user
        self._roles: dict[str, str] = {}
        # ADR-0088: the policy whose leases a media job holds; a stopped run gives its job's back
        self.job_policy: Any = None
        # stage J3: stop a media job a stopped run was waiting for (the sink's `cancel`)
        self.media_cancel: Any = None

    def _spawn(self, coro: Coroutine[Any, Any, None], run_id: str | None = None) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        if run_id:
            self._by_run[run_id] = task
            task.add_done_callback(
                lambda t: self._by_run.pop(run_id, None) if self._by_run.get(run_id) is t else None
            )

    async def aclose(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def start(
        self,
        product_id: str,
        tenant_id: str,
        user_id: str,
        thread_id: UUID | None,
        graph_input: dict[str, Any],
        run_id: UUID | None = None,
        role: str = "user",
    ) -> RunRecord:
        """Start a run. With `run_id` (chosen by the client) a second start under the same id by
        the same person is not a second run: it returns the first, whose events the caller
        replays."""
        rec = RunRecord(
            run_id=str(run_id or uuid4()),
            thread_id=str(thread_id or uuid4()),
            product_id=product_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if not await self.store.create(rec):
            existing = await self.store.get(tenant_id, rec.run_id)
            if existing is None or existing.user_id != user_id or existing.product_id != product_id:
                raise RunIdTaken(rec.run_id)
            return existing
        if role != "user":
            self._roles[rec.run_id] = role
        self._spawn(self._execute(rec, graph_input), rec.run_id)
        return rec

    async def cancel(self, rec: RunRecord) -> str:
        """Stop a run (the person pressed Stop). Returns the run's state now: the one it had if it
        was over already, else `cancelled`. The graph stops where it is (the assistant keeps the
        text it had written); its media jobs are not recalled. A closing `error` event with the
        code `cancelled` ends the stream for anyone still reading it."""
        current = await self.store.get(rec.tenant_id, rec.run_id)
        if current is None or current.status in FINISHED:
            return current.status if current else "cancelled"
        await self.store.set_state(rec.tenant_id, rec.run_id, "cancelled")
        task = self._by_run.get(rec.run_id)
        if task is not None:
            task.cancel()  # the run is here; on another replica its own loop notices the state
            await asyncio.gather(task, return_exceptions=True)  # let it save what it had
        if current.status == "waiting_job":
            if self.media_cancel is not None and current.waiting_job:
                try:
                    await self.media_cancel(current.waiting_job)
                except Exception:
                    log.warning("could not stop media job %s", current.waiting_job)
            if self.job_policy is not None and current.waiting_job:
                try:  # the place is free at once (ADR-0088); a lost one runs out on its own
                    await self.job_policy.release(rec.tenant_id, rec.user_id, current.waiting_job)
                except Exception:
                    log.warning("could not give back the place of job %s", current.waiting_job)
            await self._clean_up(rec)
        record_run(rec.product_id, "cancelled")
        await self._emit(rec, ErrorEvent, code="cancelled", message="Stopped.", retryable=False)
        return "cancelled"

    async def _clean_up(self, rec: RunRecord) -> None:
        """A run stopped while it waited for a media job never runs the node that would have
        handled the job's end: the graph's `on_cancel`, if it declares one, gets the run's last
        state to put things right (a clip's row, the person's uploads). Stage J3."""
        graph = self.graphs.get(rec.product_id)
        hook = getattr(graph, "on_cancel", None)
        if graph is None or hook is None:
            return

        async def run_hook() -> None:
            set_context(
                RunContext(
                    tenant_id=rec.tenant_id, product_id=rec.product_id, user_id=rec.user_id,
                    run_id=rec.run_id, thread_id=rec.thread_id,
                )
            )  # fmt: skip
            config = {"configurable": {"thread_id": rec.thread_id}}
            snapshot = await graph.aget_state(config)
            await hook(dict(snapshot.values or {}))

        try:
            await asyncio.create_task(run_hook())  # its own context, not the caller's
        except Exception:
            log.exception("the clean-up of stopped run %s failed", rec.run_id)

    def live(self, run_id: str) -> bool:
        """Whether this process is executing the run now."""
        task = self._by_run.get(run_id)
        return task is not None and not task.done()

    async def state_of(self, tenant_id: str, run_id: str) -> dict[str, Any]:
        """A run's status, and its last event once it has ended (`done`, `error`). An action job
        reads it after a restart (stage J3)."""
        rec = await self.store.get(tenant_id, run_id)
        if rec is None:
            return {"status": "unknown"}
        if rec.status not in FINISHED:
            return {"status": rec.status}
        end: dict[str, Any] | None = None
        after = 0
        while True:
            events = await self.log.read(tenant_id, run_id, after, 0)
            if not events:
                break
            for ev in events:
                after = max(after, int(ev.get("seq", after)))
                if ev.get("event") in TERMINAL_EVENTS:
                    end = ev
        return {"status": rec.status, "end": end}

    async def run_child(
        self,
        product_id: str,
        tenant_id: str,
        user_id: str,
        graph_input: dict[str, Any],
        timeout_s: float = 900.0,
    ) -> AsyncIterator[dict[str, Any]]:
        """Run another product's graph for this user as its own run, and yield its events until it
        ends. It runs in its own task, so the caller's run context is untouched. If it takes longer
        than `timeout_s` an `error` event ends the stream (the child run is left to finish)."""
        here = current_context()  # a child run is its parent's person, with the same role
        rec = await self.start(
            product_id, tenant_id, user_id, None, graph_input,
            role=here.role if here is not None else "user",
        )  # fmt: skip
        after = 0
        deadline = asyncio.get_running_loop().time() + timeout_s
        while True:
            if asyncio.get_running_loop().time() > deadline:
                yield {
                    "event": "error", "code": "timeout", "retryable": True,
                    "message": "That took too long.",
                }  # fmt: skip
                return
            for ev in await self.log.read(tenant_id, rec.run_id, after, 1000):
                after = max(after, int(ev.get("seq", after)))
                yield ev
                if ev.get("event") in TERMINAL_EVENTS:
                    return

    def resume(self, rec: RunRecord, value: Any) -> None:
        """Continue a run that was waiting for a user's answer."""
        self._spawn(self._execute(rec, Command(resume=value)), rec.run_id)

    def resume_with_job(self, rec: RunRecord, result: dict[str, Any]) -> None:
        """Continue a run that was waiting for a media job; `result` is a JobResult dump."""
        self._spawn(self._execute(rec, Command(resume=result)), rec.run_id)

    async def _emit(self, rec: RunRecord, cls: type, **kw: Any) -> None:
        event = cls(run_id=UUID(rec.run_id), thread_id=UUID(rec.thread_id), seq=0, **kw)
        await self.log.append(rec.tenant_id, rec.run_id, event.model_dump(mode="json"))

    async def _execute(self, rec: RunRecord, graph_input: Any) -> None:
        graph = self.graphs[rec.product_id]
        config = {
            "configurable": {
                "thread_id": rec.thread_id,
                "tenant_id": rec.tenant_id,
                "product_id": rec.product_id,
                "user_id": rec.user_id,
            }
        }
        # Capabilities read tenant/product/user/run from this context (usage events, job
        # payloads, storage keys). It is task-local, so concurrent runs cannot mix.
        set_context(
            RunContext(
                tenant_id=rec.tenant_id,
                product_id=rec.product_id,
                user_id=rec.user_id,
                run_id=rec.run_id,
                thread_id=rec.thread_id,
                role=self._roles.get(rec.run_id, "user"),
            )
        )
        checked = time.monotonic()
        try:
            async for mode, chunk in graph.astream(
                graph_input, config, stream_mode=["custom", "updates"]
            ):
                if (
                    time.monotonic() - checked > CANCEL_CHECK_S
                ):  # a stop may have come to another replica
                    checked = time.monotonic()
                    now = await self.store.get(rec.tenant_id, rec.run_id)
                    if now is not None and now.status == "cancelled":
                        raise asyncio.CancelledError
                if mode == "custom":
                    await self._emit_custom(rec, chunk)
                elif "__interrupt__" in chunk:
                    intr = chunk["__interrupt__"][0]
                    value = intr.value if isinstance(intr.value, dict) else {"value": intr.value}
                    if value.get("kind") == "job":
                        # Waiting for the media worker, not for the user: no client event.
                        await self.store.set_state(
                            rec.tenant_id, rec.run_id, "waiting_job", waiting_job=value["job_id"]
                        )
                        return
                    await self.store.set_state(
                        rec.tenant_id, rec.run_id, "waiting_input", awaiting=intr.id
                    )
                    await self._emit(
                        rec,
                        InterruptEvent,
                        interrupt_id=intr.id,
                        kind=value.get("kind", "interrupt"),
                        payload=value,
                    )
                    return
                else:
                    for node in chunk:
                        await self._emit(rec, NodeEvent, node=node, status="completed", label=node)
            state = await graph.aget_state(config)
            await self.store.set_state(rec.tenant_id, rec.run_id, "done")
            refusal = (
                (state.values.get("refusal") or {})
                if state.values.get("status") == "refused"
                else {}
            )
            if refusal:
                record_run(rec.product_id, "refused", refusal=str(refusal.get("code", "")))
            else:
                record_run(rec.product_id, "done")
            await self._emit(rec, DoneEvent, outputs=dict(state.values))
        except JobFailed as e:
            err = e.result.error
            record_run(rec.product_id, "error", code=err.code if err else "job_failed")
            await self.store.set_state(rec.tenant_id, rec.run_id, "error")
            await self._emit(
                rec,
                ErrorEvent,
                code=err.code if err else "job_failed",
                message=err.message if err else "The media job failed.",
                retryable=err.retryable if err else False,
                job_id=e.result.job_id,
            )
        except RunError as e:
            record_run(rec.product_id, "error", code=e.code)
            await self.store.set_state(rec.tenant_id, rec.run_id, "error")
            await self._emit(rec, ErrorEvent, code=e.code, message=e.message, retryable=e.retryable)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("run failed", extra={"run_id": rec.run_id})
            record_run(rec.product_id, "error", code="run_failed")
            await self.store.set_state(rec.tenant_id, rec.run_id, "error")
            await self._emit(
                rec, ErrorEvent, code="run_failed", message="The run failed.", retryable=True
            )

    async def _emit_custom(self, rec: RunRecord, chunk: dict[str, Any]) -> None:
        if chunk.get("type") == "token":
            await self._emit(rec, TokenEvent, node=chunk["node"], text=chunk["text"])
        elif chunk.get("type") == "reasoning":
            await self._emit(rec, ReasoningEvent, node=chunk["node"], text=chunk["text"])
        elif chunk.get("type") == "tool_call":
            await self._emit(
                rec, ToolCallEvent, id=chunk["id"], name=chunk["name"], arguments=chunk["arguments"]
            )
        elif chunk.get("type") == "tool_result":
            await self._emit(
                rec,
                ToolResultEvent,
                id=chunk["id"],
                name=chunk["name"],
                status=chunk["status"],
                output=chunk.get("output", {}),
            )
        elif chunk.get("type") == "job_progress":
            await self._emit(rec, JobProgressEvent, **chunk["data"])
        elif chunk.get("type") == "node":
            await self._emit(
                rec,
                NodeEvent,
                node=chunk["node"],
                status=chunk["status"],
                label=chunk.get("label", ""),
            )
