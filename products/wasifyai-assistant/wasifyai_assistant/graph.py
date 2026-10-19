# pyright: reportTypedDictNotRequiredAccess=false
"""The assistant graph (ADR-0057): one turn of a conversation.

    check_request -> run_turn -> finalise
         |
         v
       refuse

`run_turn` is the tool-calling loop: stream the model's answer; if it asks for tools, run them
(events `tool_call` and `tool_result`, progress of any job), give the results back, and go again, a
few times at most. Everything is saved as messages of the conversation, so a reload shows what the
stream showed.
"""

import logging
import re
from typing import Any, Literal, TypedDict, cast

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from wasifyai_platform_sdk import Capabilities, RunError, ToolHost, require_context
from wasifyai_platform_sdk.search import search_text

from wasifyai_assistant.store import (
    PRODUCT_ID,
    ConversationStore,
    InMemoryConversationStore,
    Message,
    SqlConversationStore,
)
from wasifyai_assistant.tools import TOOL_DEFINITIONS, ToolOutcome, parse_arguments, run_tool

log = logging.getLogger(__name__)

MAX_TEXT_CHARS = 4000
MAX_ROUNDS = 4  # the model may use tools this many times in one turn
MAX_CALLS_PER_ROUND = 3
HISTORY_MESSAGES = 40  # what the model is shown of the conversation
TITLE_CHARS = 60

SYSTEM_PROMPT = (
    "You are Wasify AI, a helpful assistant inside a creative app that runs on the person's own "
    "computer. Answer in the language the person writes in, clearly and briefly. You can make "
    "pictures with the generate_image tool and find things the person made earlier with the "
    "search_creations tool. Use a tool only when the person asks for it. Never say you made "
    "something unless the tool reported that it did."
)

Status = Literal["working", "done", "refused"]


class AssistantState(TypedDict, total=False):
    text: str
    conversation_id: str
    status: Status
    refusal: dict[str, str]
    title: str
    message_id: str
    reply: str


def _clean(value: object) -> str:
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(value or ""))
    return text.strip()[: MAX_TEXT_CHARS + 1]


def title_from(text: str) -> str:
    line = " ".join(text.split())
    return line if len(line) <= TITLE_CHARS else line[: TITLE_CHARS - 1].rstrip() + "…"


def model_messages(history: list[Message]) -> list[dict[str, Any]]:
    """The conversation as OpenAI-style messages (assistant text and tool calls, tool results)."""
    out: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    recent = history[-HISTORY_MESSAGES:]
    while recent and recent[0].role != "user":  # never start in the middle of a tool exchange
        recent = recent[1:]
    for m in recent:
        if m.role == "user":
            out.append({"role": "user", "content": m.text()})
        elif m.role == "assistant":
            calls = [
                {
                    "id": p["id"],
                    "type": "function",
                    "function": {"name": p["name"], "arguments": _dumps(p.get("arguments", {}))},
                }
                for p in m.parts
                if p.get("type") == "tool_call"
            ]
            msg: dict[str, Any] = {"role": "assistant", "content": m.text() or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
        elif m.role == "tool":
            for p in m.parts:
                if p.get("type") == "tool_result":
                    out.append(
                        {"role": "tool", "tool_call_id": p["id"], "content": str(p.get("text", ""))}
                    )
    return out


def _dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def conversation_text(title: str, history: list[Message]) -> str:
    """What a conversation is found by: its title and what the person wrote."""
    return search_text(title, *[m.text() for m in history if m.role == "user"])


def build_assistant(caps: Capabilities, checkpointer: Any):
    """Registry entry point: the store is chosen from the database the engine speaks to."""
    store: ConversationStore = (
        SqlConversationStore(caps.db) if caps.db is not None else InMemoryConversationStore()
    )
    return build_assistant_graph(caps, checkpointer, store)


def offered_tools(h: ToolHost | None) -> list[dict[str, Any]] | None:
    """The tool definitions the model is told about: those the host can run here (all of them for a
    host that does not say), or none without a host."""
    if h is None:
        return None
    available = getattr(h, "available_tools", None)
    names = available() if callable(available) else None
    if names is None:
        return TOOL_DEFINITIONS
    chosen = [t for t in TOOL_DEFINITIONS if t["function"]["name"] in names]
    return chosen or None


def build_assistant_graph(caps: Capabilities, checkpointer: Any, store: ConversationStore):
    def host() -> ToolHost | None:
        return caps.extras.get("tool_host")

    def refuse_with(code: str, message: str) -> AssistantState:
        return {"status": "refused", "refusal": {"code": code, "message": message}}

    async def check_request(state: AssistantState) -> AssistantState:
        ctx = require_context()
        text = _clean(state.get("text"))
        if not text:
            return refuse_with("invalid_request", "Please type a message.")
        if len(text) > MAX_TEXT_CHARS:
            return refuse_with(
                "invalid_request", f"Please keep it under {MAX_TEXT_CHARS} characters."
            )
        conv_id = str(state.get("conversation_id") or "")
        if conv_id:
            conv = await store.get(ctx.tenant_id, ctx.user_id, conv_id)
            if conv is None:  # also what another person's conversation looks like
                return refuse_with("not_found", "That conversation is not there any more.")
        else:
            conv = await store.create(ctx.tenant_id, ctx.user_id)
        await store.add_message(
            ctx.tenant_id, ctx.user_id, conv.id, "user", [{"type": "text", "text": text}]
        )
        return {"status": "working", "conversation_id": conv.id, "text": text, "title": conv.title}

    def after_check(state: AssistantState) -> str:
        return "refuse" if state.get("status") == "refused" else "run_turn"

    async def refuse(state: AssistantState) -> AssistantState:
        return {}

    async def run_turn(state: AssistantState) -> AssistantState:
        ctx = require_context()
        write = get_stream_writer()
        conv_id = state["conversation_id"]
        tools = offered_tools(host())
        reply = ""
        for round_no in range(MAX_ROUNDS + 1):
            history = await store.messages(ctx.tenant_id, ctx.user_id, conv_id)
            allow_tools = tools if round_no < MAX_ROUNDS else None
            text = ""
            calls: list[Any] = []
            write({"type": "node", "node": "agent", "status": "started", "label": "Thinking"})
            try:
                async for chunk in caps.text.chat("chat", model_messages(history), allow_tools):
                    if chunk.text:
                        text += chunk.text
                        write({"type": "token", "node": "agent", "text": chunk.text})
                    if chunk.tool_calls:
                        calls = chunk.tool_calls[:MAX_CALLS_PER_ROUND]
            except RunError:
                raise
            except Exception:
                log.exception("the language model failed")
                raise RunError(
                    "language_failed",
                    "The language model did not answer. Check it in Models and try again.",
                    retryable=True,
                ) from None
            if allow_tools is None:
                calls = []  # the last round offered no tools: whatever came back is the answer
            if not calls:
                reply = text.strip()
                break
            parts: list[dict[str, Any]] = [{"type": "text", "text": text}] if text.strip() else []
            for c in calls:
                parts.append(
                    {
                        "type": "tool_call", "id": c.id, "name": c.name,
                        "arguments": parse_arguments(c.arguments),
                    }
                )  # fmt: skip
            await store.add_message(ctx.tenant_id, ctx.user_id, conv_id, "assistant", parts)
            results: list[dict[str, Any]] = []
            for c in calls:
                args = parse_arguments(c.arguments)
                write({"type": "tool_call", "id": c.id, "name": c.name, "arguments": args})
                executor = caps.extras.get("actions")
                if host() is None or executor is None:
                    outcome = ToolOutcome("error", text="Tools are not available here.")
                else:
                    outcome = await run_tool(c.name, args, executor, write)
                write(
                    {
                        "type": "tool_result", "id": c.id, "name": c.name,
                        "status": outcome.status, "output": outcome.output,
                    }
                )  # fmt: skip
                results.append(
                    {
                        "type": "tool_result", "id": c.id, "name": c.name,
                        "status": outcome.status, "output": outcome.output, "text": outcome.text,
                    }
                )  # fmt: skip
            await store.add_message(ctx.tenant_id, ctx.user_id, conv_id, "tool", results)
        if not reply:
            reply = "I could not finish that. Please try again."
        msg = await store.add_message(
            ctx.tenant_id, ctx.user_id, conv_id, "assistant", [{"type": "text", "text": reply}]
        )
        return {"reply": reply, "message_id": msg.id}

    async def finalise(state: AssistantState) -> AssistantState:
        ctx = require_context()
        conv_id = state["conversation_id"]
        conv = await store.get(ctx.tenant_id, ctx.user_id, conv_id)
        title = conv.title if conv else ""
        if conv and not title:
            title = title_from(state["text"])
            await store.rename(ctx.tenant_id, ctx.user_id, conv_id, title)
        history = await store.messages(ctx.tenant_id, ctx.user_id, conv_id)
        await caps.index_creation("conversation", conv_id, conversation_text(title, history))
        await caps.record_usage("assistant.message", 1, "messages", conversation_id=conv_id)
        return {"status": "done", "title": title}

    g = StateGraph(AssistantState)
    for name, fn in [
        ("check_request", check_request),
        ("refuse", refuse),
        ("run_turn", run_turn),
        ("finalise", finalise),
    ]:
        g.add_node(name, cast(Any, fn))
    g.add_edge(START, "check_request")
    g.add_conditional_edges(
        "check_request", after_check, {"refuse": "refuse", "run_turn": "run_turn"}
    )
    g.add_edge("refuse", END)
    g.add_edge("run_turn", "finalise")
    g.add_edge("finalise", END)
    return g.compile(checkpointer=checkpointer)


__all__ = ["PRODUCT_ID", "build_assistant", "build_assistant_graph"]
