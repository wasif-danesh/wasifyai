# pyright: reportTypedDictNotRequiredAccess=false
# SPDX-License-Identifier: Apache-2.0
"""A question put to a notebook (ADR-0065 decision 10): one turn of a grounded conversation.

    check_request -> run_turn -> finalise
         |
         v
       refuse

`run_turn` searches the ticked sources first (shown as a `search_sources` step), puts the best
passages in front of the model with the question, streams the answer, and then checks the labels
the model wrote. Retrieval does not depend on the model calling a tool: a notebook has to answer
with whatever model the person has (E0, D6).

Events are the existing ones: `node`, `tool_call` / `tool_result` (the search, with its hits as a
small reference), `token`, and `done` whose outputs are the final state: `reply` with `[n]` labels
and `citations` carrying each cited passage as it was when the answer was written.
"""

import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from wasifyai_platform_sdk import Capabilities, RunError, require_context

from wasifyai_notebooks.components import Unavailable
from wasifyai_notebooks.grounding import (
    QUESTION_MAX_CHARS,
    Tier,
    build_context,
    check_labels,
    fit_history,
    history_budget,
    resolve_citations,
    tier_for,
    user_message,
)
from wasifyai_notebooks.output_job import OutputRequest, Progress, make_output
from wasifyai_notebooks.retrieval import retrieve
from wasifyai_notebooks.runtime import NotAvailable, Runtime, runtime_for
from wasifyai_notebooks.store import NotFound
from wasifyai_notebooks.studio.formats import (
    FORMATS,
    infographic_prompt,
)

log = logging.getLogger(__name__)

PRODUCT_ID = "wasifyai-notebooks"
TOP_K = 5
TITLE_CHARS = 60
SNIPPET_CHARS = 160
DEFAULT_CONTEXT = 8192
MADE_HERE = frozenset({"guide", "infographic"})  # outputs a worker is not asked to make

Status = Literal["working", "done", "refused"]


class ChatState(TypedDict, total=False):
    text: str
    notebook_id: str
    conversation_id: str
    document_ids: list[str]  # the ticked sources; absent means every source that is ready
    status: Status
    refusal: dict[str, str]
    title: str
    message_id: str
    reply: str
    citations: list[dict[str, Any]]
    labels_removed: int
    searched: int  # how many sources were searched
    # a Studio output instead of an answer: {"format": ..., "prompt": ...} (document_ids as above)
    studio: dict[str, Any]
    artifact_id: str
    format: str


def _clean(value: object) -> str:
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(value or ""))
    return text.strip()[: QUESTION_MAX_CHARS + 1]


def title_from(text: str) -> str:
    line = " ".join(text.split())
    return line if len(line) <= TITLE_CHARS else line[: TITLE_CHARS - 1].rstrip() + "…"


def _snippet(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= SNIPPET_CHARS else flat[: SNIPPET_CHARS - 1].rstrip() + "…"


def model_facts(state: Any) -> tuple[int, Tier]:
    """The chosen model's window and which prompt it gets, from the engine's state when it has a
    chosen local model; a window of 8192 and the fuller prompt otherwise."""
    selected = getattr(getattr(state, "desktop_language", None), "selected", None)
    context = int(getattr(selected, "context", 0) or DEFAULT_CONTEXT)
    size: int | None = None
    if selected is not None and getattr(selected, "kind", "") == "file" and selected.path:
        try:
            size = Path(selected.path).stat().st_size
        except OSError:
            size = None
    return context, tier_for(size)


def build_notebook_chat(caps: Capabilities, checkpointer: Any):
    """Registry entry point: the library is the engine's, found through its app state."""

    def provider() -> Runtime:
        try:
            return runtime_for(caps.extras.get("app_state"))
        except NotAvailable:
            raise RunError("not_available", "Notebooks are not available here yet.") from None

    return build_notebook_chat_graph(
        caps, checkpointer, provider, lambda: model_facts(caps.extras.get("app_state"))
    )


def build_notebook_chat_graph(
    caps: Capabilities,
    checkpointer: Any,
    runtime: Callable[[], Runtime],
    facts: Callable[[], tuple[int, Tier]] = lambda: (DEFAULT_CONTEXT, "capable"),
):
    import asyncio

    def refuse_with(code: str, message: str) -> ChatState:
        return {"status": "refused", "refusal": {"code": code, "message": message}}

    async def check_request(state: ChatState) -> ChatState:
        ctx = require_context()
        if state.get("studio") is not None:
            return await check_studio(state, ctx)
        text = _clean(state.get("text"))
        if not text:
            return refuse_with("invalid_request", "Please type a question.")
        if len(text) > QUESTION_MAX_CHARS:
            return refuse_with(
                "invalid_request", f"Please keep it under {QUESTION_MAX_CHARS} characters."
            )
        nid = str(state.get("notebook_id") or "")
        rt = runtime()
        t, u = ctx.tenant_id, ctx.user_id
        try:
            counts = await asyncio.to_thread(rt.store.source_counts, t, u, nid)
        except NotFound:
            return refuse_with("not_found", "That notebook is not there any more.")
        if not counts:
            return refuse_with("no_sources", "Add a source to this notebook, then ask about it.")
        if not counts.get("ready"):
            return refuse_with(
                "sources_reading", "Your sources are still being read. Try again in a moment."
            )
        scope: list[str] | None = None
        if state.get("document_ids") is not None:
            ready = set(await asyncio.to_thread(rt.store.ready_document_ids, nid))
            scope = [d for d in dict.fromkeys(state["document_ids"]) if d in ready]
            if not scope:
                return refuse_with("no_scope", "None of the ticked sources can be searched yet.")
        cid = str(state.get("conversation_id") or "")
        try:
            if cid:
                conv = await asyncio.to_thread(rt.store.get_conversation, t, u, nid, cid)
            else:
                conv = await asyncio.to_thread(
                    rt.store.create_conversation, t, u, nid, title_from(text)
                )
        except NotFound:
            return refuse_with("not_found", "That conversation is not there any more.")
        await asyncio.to_thread(rt.store.add_message, t, u, nid, conv["id"], "user", text)
        out: ChatState = {
            "status": "working",
            "text": text,
            "notebook_id": nid,
            "conversation_id": conv["id"],
            "title": conv["title"],
        }
        if scope is not None:
            out["document_ids"] = scope
        return out

    async def check_studio(state: ChatState, ctx: Any) -> ChatState:
        """The same refusals as a question, then the output is recorded as being made."""
        spec = state.get("studio") or {}
        fmt = FORMATS.get(str(spec.get("format", "")))
        if fmt is None:
            return refuse_with("invalid_request", "That kind of output is not available.")
        nid = str(state.get("notebook_id") or "")
        rt = runtime()
        t, u = ctx.tenant_id, ctx.user_id
        try:
            counts = await asyncio.to_thread(rt.store.source_counts, t, u, nid)
        except NotFound:
            return refuse_with("not_found", "That notebook is not there any more.")
        if not counts:
            return refuse_with("no_sources", "Add a source to this notebook first.")
        if not counts.get("ready"):
            return refuse_with(
                "sources_reading", "Your sources are still being read. Try again in a moment."
            )
        ready = await asyncio.to_thread(rt.store.ready_document_ids, nid)
        scope = ready
        if state.get("document_ids") is not None:
            wanted = set(state["document_ids"])
            scope = [d for d in ready if d in wanted]
            if not scope:
                return refuse_with("no_scope", "None of the ticked sources can be used yet.")
        prompt = " ".join(str(spec.get("prompt", "")).split())[:1000]
        if fmt.key == "guide":  # kept with the notebook, not listed as an output
            return {
                "status": "working",
                "notebook_id": nid,
                "format": "guide",
                "document_ids": scope,
                "studio": {"format": "guide", "prompt": ""},
            }
        art = await asyncio.to_thread(
            rt.store.create_artifact, t, u, nid, fmt=fmt.key, prompt=prompt, source_ids=scope
        )
        return {
            "status": "working",
            "notebook_id": nid,
            "artifact_id": art["id"],
            "format": fmt.key,
            "document_ids": scope,
            "studio": {"format": fmt.key, "prompt": prompt},
        }

    def after_check(state: ChatState) -> str:
        if state.get("status") == "refused":
            return "refuse"
        return "studio_turn" if state.get("studio") is not None else "run_turn"

    async def refuse(state: ChatState) -> ChatState:
        return {}

    async def run_turn(state: ChatState) -> ChatState:
        ctx = require_context()
        write = get_stream_writer()
        rt = runtime()
        t, u = ctx.tenant_id, ctx.user_id
        nid, cid, question = state["notebook_id"], state["conversation_id"], state["text"]
        scope = state.get("document_ids")

        write({"type": "node", "node": "search", "status": "started", "label": "Searching sources"})
        try:
            embedder = rt.components.embedder()
        except Unavailable as e:
            raise RunError(e.code, e.message) from None
        vector = await asyncio.to_thread(rt.query_vector, embedder, t, u, question, "chat")

        def search() -> list[Any]:
            with rt.store.connect() as db:
                return retrieve(
                    db, nid, question, vector, weight=embedder.spec.semantic_weight,
                    top_k=TOP_K, document_ids=scope,
                )  # fmt: skip

        hits = await asyncio.to_thread(search)
        context, tier = facts()
        grounding = build_context(hits, tier)
        call_id = uuid.uuid4().hex
        searched = (
            len(scope)
            if scope is not None
            else (len(await asyncio.to_thread(rt.store.ready_document_ids, nid)))
        )
        write(
            {"type": "tool_call", "id": call_id, "name": "search_sources",
             "arguments": {"query": question, "sources": searched}}
        )  # fmt: skip
        write(
            {"type": "tool_result", "id": call_id, "name": "search_sources", "status": "ok",
             "output": {"hits": [
                 {"n": c.n, "document_id": c.document_id, "title": c.title,
                  "snippet": _snippet(c.text)}
                 for c in grounding.citations
             ]}}
        )  # fmt: skip

        history = await asyncio.to_thread(rt.store.messages, t, u, nid, cid)
        turns = [(m["role"], m["text"]) for m in history[:-1]]  # all but the question just saved
        kept = fit_history(turns, history_budget(context, question))
        messages: list[dict[str, Any]] = [{"role": "system", "content": grounding.instruction}]
        messages += [{"role": role, "content": text} for role, text in kept]
        messages.append({"role": "user", "content": user_message(grounding, question)})

        write(
            {"type": "node", "node": "answer", "status": "started", "label": "Writing the answer"}
        )
        text = ""
        try:
            async for chunk in caps.text.chat("chat", messages, None):
                if chunk.reasoning:  # shown collapsed; never stored, never part of the answer
                    write({"type": "reasoning", "node": "answer", "text": chunk.reasoning})
                if chunk.text:
                    text += chunk.text
                    write({"type": "token", "node": "answer", "text": chunk.text})
        except RunError:
            raise
        except Exception:
            log.exception("the language model failed")
            raise RunError(
                "language_failed",
                "The language model did not answer. Check it in the Model hub and try again.",
                retryable=True,
            ) from None

        checked = check_labels(text.strip(), grounding.citations)
        reply, used = resolve_citations(checked.text, grounding.citations)
        reply = reply.strip() or "I could not finish that. Please try again."
        public = [c.public() for c in used]
        msg = await asyncio.to_thread(
            rt.store.add_message, t, u, nid, cid, "assistant", reply, public
        )
        return {
            "reply": reply, "citations": public, "message_id": msg["id"],
            "labels_removed": checked.removed, "searched": searched,
        }  # fmt: skip

    async def paint(
        built: Any, progress: Progress, fail: Callable[[str], Awaitable[None]]
    ) -> dict[str, Any] | None:
        """Ask the image product for the infographic's picture, as a run of its own (the same tool
        the assistant draws with). Returns the picture's reference, or None after saying why not."""
        host = caps.extras.get("tool_host")
        if host is None:
            await fail("Making pictures is not available here.")
            return None
        progress("paint", "Drawing the picture")
        message = "The picture could not be made."
        async for ev in host.run_product(
            "wasifyai-image",
            {"mode": "text", "prompt": infographic_prompt(built.data), "size": "portrait"},
        ):
            kind = ev.get("event")
            if kind == "error":
                message = f"The picture could not be made: {ev.get('message', 'it failed')}"
                break
            if kind == "done":
                out = ev.get("outputs") or {}
                if out.get("status") == "refused":
                    reason = (out.get("refusal") or {}).get("message", "it was not allowed")
                    message = f"The picture was not made: {reason}"
                    break
                if out.get("status") == "done" and out.get("image_id"):
                    return {
                        "image_id": out["image_id"],
                        "width": int(out.get("width", 0)),
                        "height": int(out.get("height", 0)),
                    }
                break
        await fail(message)
        return None

    async def studio_turn(state: ChatState) -> ChatState:
        ctx = require_context()
        write = get_stream_writer()
        rt = runtime()
        t, u = ctx.tenant_id, ctx.user_id
        nid, aid = state["notebook_id"], state.get("artifact_id", "")
        fmt = FORMATS[state["format"]]
        spec = state.get("studio") or {}
        context, tier = facts()
        request = OutputRequest(
            fmt.key, str(spec.get("prompt", "")), state.get("document_ids") or [], context, tier
        )

        # Where a worker makes outputs (the web), an output that needs nothing of this program is
        # left for one and the run ends; the screen follows the output's row. A guide is kept with
        # the notebook and an infographic's picture is a run of the image product, which only
        # this program can start, so those are made here.
        if rt.outputs_by_worker and aid and fmt.key not in MADE_HERE:
            await asyncio.to_thread(rt.store.queue_artifact, t, u, nid, aid, request.to_json())
            return {"status": "done", "format": fmt.key, "artifact_id": aid, "title": ""}

        def progress(node: str, label: str) -> None:
            write({"type": "node", "node": node, "status": "started", "label": label})

        made = await make_output(
            rt, caps, tenant=t, user=u, nid=nid, aid=aid, request=request, progress=progress,
            paint=paint,
        )  # fmt: skip
        return cast(ChatState, made)

    async def finalise(state: ChatState) -> ChatState:
        await caps.record_usage(
            "notebooks.message", 1, "messages", notebook_id=state.get("notebook_id", "")
        )
        return {"status": "done"}

    g = StateGraph(ChatState)
    for name, fn in [
        ("check_request", check_request),
        ("refuse", refuse),
        ("run_turn", run_turn),
        ("studio_turn", studio_turn),
        ("finalise", finalise),
    ]:
        g.add_node(name, cast(Any, fn))
    g.add_edge(START, "check_request")
    g.add_conditional_edges(
        "check_request",
        after_check,
        {"refuse": "refuse", "run_turn": "run_turn", "studio_turn": "studio_turn"},
    )
    g.add_edge("refuse", END)
    g.add_edge("run_turn", "finalise")
    g.add_edge("studio_turn", END)
    g.add_edge("finalise", END)
    return g.compile(checkpointer=checkpointer)


__all__ = ["PRODUCT_ID", "build_notebook_chat", "build_notebook_chat_graph", "title_from"]
