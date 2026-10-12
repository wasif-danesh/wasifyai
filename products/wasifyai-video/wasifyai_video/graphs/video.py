# pyright: reportTypedDictNotRequiredAccess=false
# (Graph state is filled in node by node; a node only reads keys that earlier nodes have set.)
"""The video graph: guardrail, one job, finish (ADR-0037).

    check_request -> start_job -> await_job -> finalise
        |
        v
      refuse

Two modes: `text` (a description, a shape and a length) and `image` (an uploaded picture, a
description of the motion and a length). Graph code names capabilities (`text.moderate`,
`text.moderate_image`, `video.generate`, `video.animate`), never models or workflow node IDs.

The clip's row is created when the job starts, with status "working", so the site can show "being
made" on any page while the user explores it. The finished clip, a failure or a refusal ends it.
The uploaded picture is deleted as soon as it is no longer needed: when the request is refused,
when the job fails, and when the clip is saved."""

import logging
import re
import secrets
from typing import Any, Literal, TypedDict, cast
from uuid import uuid4

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from wasifyai_platform_sdk import (
    Capabilities,
    InMemoryUploadStore,
    JobFailed,
    PostgresUploadStore,
    RunError,
    UploadRecord,
    UploadStore,
    await_job,
    require_context,
)

from wasifyai_video import guardrail
from wasifyai_video.index import index_text
from wasifyai_video.schemas import (
    DEFAULT_SECONDS,
    DEFAULT_SHAPE,
    FPS,
    LENGTHS,
    MAX_PROMPT_CHARS,
    SHAPES,
)
from wasifyai_video.videos import (
    VIDEO_CREATED,
    InMemoryVideoStore,
    PosterError,
    PostgresVideoStore,
    Quota,
    UsageQuota,
    VideoRecord,
    VideoStore,
    poster_of,
)

log = logging.getLogger(__name__)

Status = Literal["working", "done", "refused", "failed"]
BUSY = "You already have a video being made. It will be in My creations when it's ready."
FAILED = "Your video couldn't be made. Please try again."


class VideoState(TypedDict, total=False):
    # request
    mode: str
    prompt: str
    shape: str
    seconds: int
    image_key: str
    # job and result
    video_id: str
    job_id: str
    result_key: str
    video_key: str
    poster_key: str
    video_url: str
    poster_url: str
    width: int
    height: int
    # outcome
    status: Status
    refusal: dict[str, str]


def _clean(value: object, limit: int) -> str:
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(value or ""))
    return re.sub(r"[ \t]+", " ", text).strip()[:limit]


def build_video(caps: Capabilities, checkpointer: Any):
    """Registry entry point: wires the production stores from the capabilities."""
    videos: VideoStore = (
        PostgresVideoStore(caps.db) if caps.db is not None else InMemoryVideoStore()
    )
    uploads: UploadStore = (
        PostgresUploadStore(caps.db) if caps.db is not None else InMemoryUploadStore()
    )
    quota: Quota | None = UsageQuota(caps.db) if caps.db is not None else None
    return build_video_graph(caps, checkpointer, videos, uploads, quota)


def build_video_graph(
    caps: Capabilities,
    checkpointer: Any,
    videos: VideoStore,
    uploads: UploadStore,
    quota: Quota | None,
):
    limit = (caps.config.quotas.get("videos_per_user_per_day") if caps.config else None) or None

    async def over_quota() -> bool:
        if not await caps.safeguards_on():  # ADR-0047: quotas apply only with safeguards
            return False
        return bool(limit and quota and await quota.used_today(require_context()) >= limit)

    def quota_message() -> str:
        return f"You've reached today's limit of {limit} videos. Please try again tomorrow."

    async def busy() -> bool:
        ctx = require_context()
        return await videos.working_count(ctx.tenant_id, ctx.user_id) >= 1

    def refuse_with(code: str, message: str) -> VideoState:
        return {"status": "refused", "refusal": {"code": code, "message": message}}

    async def find_upload(key: str) -> UploadRecord | None:
        ctx = require_context()
        return await uploads.find(ctx.tenant_id, ctx.product_id, ctx.user_id, key)

    async def discard_upload(key: str | None) -> None:
        """Delete the user's picture (file and record). Safe to call when it is already gone."""
        if not key:
            return
        assert caps.storage is not None
        record = await find_upload(key)
        if record is None:
            return
        try:
            await caps.storage.delete(record.key)
        except FileNotFoundError:
            pass
        await uploads.consume(record)

    async def fail_clip(state: VideoState, message: str = FAILED) -> None:
        """The clip will not be made: tell the row, and do not keep the user's picture."""
        if video_id := state.get("video_id"):
            await videos.fail(require_context().tenant_id, video_id, message)
        await discard_upload(state.get("image_key"))

    # ---- guardrail ----------------------------------------------------------------------

    async def check_request(state: VideoState) -> VideoState:
        write = get_stream_writer()
        write(
            {
                "type": "node",
                "node": "check_request",
                "status": "started",
                "label": "Checking your request",
            }
        )
        mode = state.get("mode")
        if mode not in ("text", "image"):
            return refuse_with("invalid_request", "Please choose text to video or image to video.")
        prompt = _clean(state.get("prompt"), MAX_PROMPT_CHARS + 1)
        if not prompt:
            what = "describe the video" if mode == "text" else "say what should move"
            return refuse_with("invalid_request", f"Please {what} you would like.")
        if len(prompt) > MAX_PROMPT_CHARS:
            return refuse_with(
                "invalid_request", f"Please keep it under {MAX_PROMPT_CHARS} characters."
            )
        key = str(state.get("image_key") or "")
        if mode == "text" and (state.get("shape") or DEFAULT_SHAPE) not in SHAPES:
            return refuse_with("invalid_request", "Please choose one of the video shapes.")
        seconds = state.get("seconds", DEFAULT_SECONDS)
        if seconds not in LENGTHS:
            return refuse_with("invalid_request", "Please choose a length of 2 or 5 seconds.")
        if mode == "image" and (not key or await find_upload(key) is None):
            return refuse_with("invalid_request", "Please upload your picture again.")
        out: VideoState = {
            "mode": mode,
            "prompt": prompt,
            "shape": str(state.get("shape") or DEFAULT_SHAPE),
            "seconds": seconds,
            "image_key": key if mode == "image" else "",
            "status": "working",
        }

        async def refused(code: str, message: str) -> VideoState:
            await discard_upload(key if mode == "image" else None)
            return refuse_with(code, message)

        if await busy():  # the GPU does one clip at a time
            return await refused("busy", BUSY)
        if await over_quota():  # before any LLM or GPU work
            return await refused("quota_exceeded", quota_message())

        if not await caps.safeguards_on():  # ADR-0047: no moderation while they are off
            return out
        kind = "video description" if mode == "text" else "animation description"
        verdict = await guardrail.judge_text(caps, kind, prompt)
        if not verdict.allowed:
            return await refused(verdict.category, guardrail.refusal_message(verdict.category))
        if mode == "image":
            assert caps.storage is not None
            picture = await caps.storage.get(key)
            verdict = await guardrail.judge_picture(caps, prompt, picture)
            if not verdict.allowed:
                return await refused(verdict.category, guardrail.refusal_message(verdict.category))
        return out

    def after_check(state: VideoState) -> str:
        return "refuse" if state.get("status") == "refused" else "start_job"

    async def refuse(state: VideoState) -> VideoState:
        return {}

    # ---- the job ------------------------------------------------------------------------

    async def start_job(state: VideoState) -> VideoState:
        if await over_quota():  # again, right before the GPU is used
            await discard_upload(state.get("image_key"))
            raise RunError("quota_exceeded", quota_message())
        if await busy():  # a second run that started while this one was being checked
            await discard_upload(state.get("image_key"))
            raise RunError("busy", BUSY)
        ctx = require_context()
        seconds, edit = state["seconds"], state["mode"] == "image"
        video_id = str(uuid4())
        await videos.add(
            VideoRecord(
                id=video_id,
                tenant_id=ctx.tenant_id,
                product_id=ctx.product_id,
                user_id=ctx.user_id,
                thread_id=ctx.thread_id,
                run_id=ctx.run_id,
                mode=state["mode"],
                status="working",
                prompt=state["prompt"],
                seconds=seconds,
                frames=LENGTHS[seconds],
                fps=FPS,
            )
        )
        write = get_stream_writer()
        write(
            {
                "type": "node",
                "node": "generate_video",
                "status": "started",
                "label": "Making your video",
            }
        )
        seed = secrets.randbelow(2**31)
        try:
            if edit:
                handle = await caps.video.animate(
                    prompt=state["prompt"],
                    image_key=state["image_key"],
                    length=LENGTHS[seconds],
                    seed=seed,
                )
            else:
                width, height = SHAPES[state["shape"]]
                handle = await caps.video.generate(
                    prompt=state["prompt"],
                    width=width,
                    height=height,
                    length=LENGTHS[seconds],
                    seed=seed,
                )
        except Exception:
            await fail_clip({"video_id": video_id, "image_key": state.get("image_key", "")})
            raise
        return {"video_id": video_id, "job_id": handle.job_id}

    async def await_job_node(state: VideoState) -> VideoState:
        try:
            result = await_job(state["job_id"])
        except JobFailed as exc:
            message = exc.result.error.message if exc.result.error else FAILED
            await fail_clip(state, message)
            raise
        return {"result_key": result.outputs["video"].key}

    # ---- finish -------------------------------------------------------------------------

    async def finalise(state: VideoState) -> VideoState:
        assert caps.storage is not None, "object storage is required"
        ctx = require_context()
        video_id = state["video_id"]
        try:
            # Final layout {tenant}/wasifyai-video/{user}/{video_id}/video.mp4; the worker's jobs/
            # paths are temporary.
            video_key = await caps.storage.move(state["result_key"], f"{video_id}/video.mp4")
            width, height, poster = await poster_of(await caps.storage.get(video_key))
            poster_key = f"{video_id}/poster.jpg"
            await caps.storage.put(poster_key, poster, "image/jpeg")
            await videos.finish(ctx.tenant_id, video_id, width, height, video_key, poster_key)
        except PosterError:
            await fail_clip(state)
            raise RunError("video_failed", FAILED, retryable=True) from None
        await discard_upload(state.get("image_key"))  # the user's original is not kept
        await caps.index_creation("video", video_id, index_text(state["prompt"]))  # ADR-0041
        await caps.record_usage(
            VIDEO_CREATED,
            1,
            "videos",
            video_id=video_id,
            mode=state["mode"],
            seconds=state["seconds"],
        )
        return {
            "video_key": video_key,
            "poster_key": poster_key,
            "video_url": await caps.storage.url(video_key),
            "poster_url": await caps.storage.url(poster_key),
            "width": width,
            "height": height,
            "status": "done",
        }

    g = StateGraph(VideoState)
    for name, fn in [
        ("check_request", check_request),
        ("refuse", refuse),
        ("start_job", start_job),
        ("await_job", await_job_node),
        ("finalise", finalise),
    ]:
        g.add_node(name, cast(Any, fn))
    g.add_edge(START, "check_request")
    g.add_conditional_edges(
        "check_request", after_check, {"refuse": "refuse", "start_job": "start_job"}
    )
    g.add_edge("refuse", END)
    g.add_edge("start_job", "await_job")
    g.add_edge("await_job", "finalise")
    g.add_edge("finalise", END)
    return g.compile(checkpointer=checkpointer)
