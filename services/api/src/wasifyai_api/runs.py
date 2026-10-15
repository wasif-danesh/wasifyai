"""Run manager: executes graphs and writes their events to the shared event log.

Nothing here is tied to the replica that started a run. State lives in three shared places:
the LangGraph checkpoint (Postgres), the event log and the run store (Redis in production).
Any replica can therefore resume a run, and any replica can serve its SSE stream (ADR-0021).
"""

import asyncio
import logging
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

from wasifyai_api.metrics import record_run

log = logging.getLogger(__name__)


class RunManager:
    def __init__(self, event_log: EventLog, store: RunStore, graphs: dict[str, Any]):
        self.log = event_log
        self.store = store
        self.graphs = graphs
        self._tasks: set[asyncio.Task] = set()

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

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
    ) -> RunRecord:
        rec = RunRecord(
            run_id=str(uuid4()),
            thread_id=str(thread_id or uuid4()),
            product_id=product_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await self.store.create(rec)
        self._spawn(self._execute(rec, graph_input))
        return rec

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
        rec = await self.start(product_id, tenant_id, user_id, None, graph_input)
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
        self._spawn(self._execute(rec, Command(resume=value)))

    def resume_with_job(self, rec: RunRecord, result: dict[str, Any]) -> None:
        """Continue a run that was waiting for a media job; `result` is a JobResult dump."""
        self._spawn(self._execute(rec, Command(resume=result)))

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
            )
        )
        try:
            async for mode, chunk in graph.astream(
                graph_input, config, stream_mode=["custom", "updates"]
            ):
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
