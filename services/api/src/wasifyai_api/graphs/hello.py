"""One-node walking-skeleton graph: streams a reply to the user's message.

Optional `image_key` / `audio_key` name files already in the user's object storage (relative
paths, e.g. "uploads/cat.png"). Graph state only ever holds the key, never file bytes (rule 10);
the bytes are loaded here and sent to the multimodal capability.
"""

from typing import Any, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from wasifyai_platform_sdk import Capabilities, Part, Prompt, part_from_file

SYSTEM = "You are a friendly assistant. Answer in one or two short sentences."


class HelloState(TypedDict, total=False):
    message: str
    image_key: str
    audio_key: str
    reply: str


def build_hello(caps: Capabilities, checkpointer: Any):
    async def hello(state: HelloState) -> HelloState:
        write = get_stream_writer()
        write({"type": "node", "node": "hello", "status": "started", "label": "Thinking"})

        message = state.get("message", "")
        parts: list[Part] = [message]
        keys = [k for k in (state.get("image_key"), state.get("audio_key")) if k]
        for key in keys:
            if caps.storage is None:
                raise RuntimeError("object storage is not configured")
            parts.append(part_from_file(key, await caps.storage.get(key)))
        capability = "multimodal" if keys else "chat"

        reply: list[str] = []
        prompt: Prompt = parts if keys else message
        async for delta in caps.text.stream(capability, SYSTEM, prompt):
            reply.append(delta)
            write({"type": "token", "node": "hello", "text": delta})
        return {"reply": "".join(reply).strip()}

    graph = StateGraph(HelloState)
    graph.add_node("hello", hello)
    graph.add_edge(START, "hello")
    graph.add_edge("hello", END)
    return graph.compile(checkpointer=checkpointer)
