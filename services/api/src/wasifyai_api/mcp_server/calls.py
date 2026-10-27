"""A tool call (ADR-0069 decisions 7 and 8): the executor runs the action for the connection's
principal under its approval setting; a long action becomes a job after `WAIT_SECONDS`; progress
goes to the client at least every `HEARTBEAT_S` (what keeps Claude Code's idle limit and
OpenCode's 60 s at bay); an action that needs the person's yes waits a bounded time for the card
in the window and otherwise answers `needs_approval` with the id to follow."""

import asyncio
import json
import logging
from typing import Any

from mcp.server.mcpserver import Context
from mcp_types import CallToolResult, TextContent
from wasifyai_platform_sdk.actions import Action, ActionExecutor, ActionResult

from wasifyai_api.mcp_server.approvals import ApprovalDesk, Pending
from wasifyai_api.mcp_server.connections import Connection

log = logging.getLogger(__name__)

WAIT_SECONDS = 25.0  # below the clients' limits (spike S1): then a job handle
HEARTBEAT_S = 5.0
APPROVAL_WAIT_S = 25.0
MAX_RESULT_CHARS = 10_000  # Codex cuts the middle above about 12,000 (spike S1)
ASKED = (
    "This needs the person's approval. A card was shown in the Wasify AI window; it was not "
    "answered yet. Call approval_status with this approval_id to follow it, and tell the person "
    "to look at the app."
)


def result_of(result: ActionResult, connection: Connection) -> CallToolResult:
    """The executor's result as the client gets it: a sentence in the text, the structured part
    with the status and the output, never a file (ADR-0069 decision 6)."""
    structured: dict[str, Any] = {
        "status": result.status,
        "action": result.action_id,
        **({"code": result.code} if result.code else {}),
        **({"job_id": result.job_id} if result.job_id else {}),
        **({"approval_id": result.approval_id} if result.approval_id else {}),
        **(
            {"setup": result.setup.step, "setup_screen": result.setup.ui}
            if result.setup is not None and result.status == "needs_setup"
            else {}
        ),
        "output": result.output,
    }
    text = result.text or f"{result.action_id}: {result.status}."
    if len(json.dumps(structured)) > MAX_RESULT_CHARS:
        structured["output"] = {"truncated": True, "note": "The output was too large to send."}
    return CallToolResult(
        content=[TextContent(text=text[:MAX_RESULT_CHARS])],
        structured_content=structured,
        is_error=result.status == "error",
    )


async def _heartbeat(ctx: Context, started: float, stop: asyncio.Event, last: dict) -> None:
    """A progress notification every HEARTBEAT_S while a call runs, with the latest job event's
    numbers when there was one."""
    n = 0
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), HEARTBEAT_S)
            return
        except TimeoutError:
            n += 1
        try:
            progress = last.get("progress")
            await ctx.report_progress(
                float(progress) if isinstance(progress, int | float) else float(n),
                1.0 if isinstance(progress, int | float) else None,
                str(last.get("status") or "working"),
            )
        except Exception:  # a client without a progress token: nothing to send
            log.debug("could not send progress", exc_info=True)


async def run_call(
    executor: ActionExecutor,
    desk: ApprovalDesk,
    events: Any,
    connection: Connection,
    action: Action,
    arguments: dict[str, Any],
    ctx: Context,
) -> CallToolResult:
    principal = connection.principal()
    last: dict[str, Any] = {}

    def on_event(ev: dict[str, Any]) -> None:
        if ev.get("event") == "job_progress":
            last.update({k: ev[k] for k in ("progress", "status") if k in ev})

    stop = asyncio.Event()
    beat = asyncio.create_task(_heartbeat(ctx, 0.0, stop, last))
    try:
        result = await executor.run_action(
            action.id, arguments, principal.origin, actor=principal,
            policy=connection.approval, wait_seconds=WAIT_SECONDS, on_event=on_event,
        )  # fmt: skip
        if result.status == "needs_approval" and result.approval_id:
            pending = desk.ask(
                Pending(
                    approval_id=result.approval_id,
                    action_id=action.id,
                    params=dict(arguments),
                    principal=principal,
                    policy=connection.approval,
                    connection_id=connection.id,
                    connection_name=connection.name,
                    title=action.title,
                    summary=result.text,
                )  # fmt: skip
            )
            if events is not None:
                events.publish(
                    "approval", approval_id=pending.approval_id, connection=connection.name,
                    action_id=action.id, title=action.title, summary=result.text,
                )  # fmt: skip
            waited = await desk.wait(pending.approval_id, APPROVAL_WAIT_S)
            if waited is not None and waited.status == "approved" and waited.result is not None:
                return result_of(waited.result, connection)
            if waited is not None and waited.status == "denied":
                return result_of(
                    ActionResult(
                        status="refused",
                        action_id=action.id,
                        code="denied",
                        text="The person said no in the Wasify AI window.",
                    ),  # fmt: skip
                    connection,
                )
            return result_of(
                ActionResult(
                    status="needs_approval",
                    action_id=action.id,
                    approval_id=result.approval_id,
                    text=ASKED,
                ),  # fmt: skip
                connection,
            )
        return result_of(result, connection)
    finally:
        stop.set()
        beat.cancel()
        await asyncio.gather(beat, return_exceptions=True)
