"""Sample graph for the media pipeline: queue an image job, wait for the worker, return a URL.

Two nodes because a paused node re-runs from its start on resume: `start` has the side effect
(enqueue), `wait` only pauses. This is the pattern products use for music and cover jobs.
"""

from typing import Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from wasifyai_platform_sdk import Capabilities, await_job


class MediaState(TypedDict, total=False):
    prompt: str
    seed: int
    job_id: str
    image_key: str
    image_url: str
    gpu_seconds: float


def build_media_demo(caps: Capabilities, checkpointer: Any):
    async def start(state: MediaState) -> MediaState:
        inputs: dict[str, Any] = {"prompt": state.get("prompt", "a lighthouse at dusk")}
        if "seed" in state:
            inputs["seed"] = state["seed"]
        handle = await caps.image.generate(**inputs)
        return {"job_id": handle.job_id}

    def wait(state: MediaState) -> MediaState:
        result = await_job(
            cast(str, state.get("job_id"))
        )  # raises JobFailed; the runtime reports it
        return {"image_key": result.outputs["image"].key, "gpu_seconds": result.gpu_seconds}

    async def finish(state: MediaState) -> MediaState:
        assert caps.storage is not None
        # The worker stored the file under this user's prefix; the URL goes to the client.
        return {"image_url": await caps.storage.url(cast(str, state.get("image_key")))}

    graph = StateGraph(MediaState)
    graph.add_node("start", start)
    graph.add_node("wait", wait)
    graph.add_node("finish", finish)
    graph.add_edge(START, "start")
    graph.add_edge("start", "wait")
    graph.add_edge("wait", "finish")
    graph.add_edge("finish", END)
    return graph.compile(checkpointer=checkpointer)
