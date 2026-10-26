# pyright: reportTypedDictNotRequiredAccess=false
# (Graph state is filled in node by node; a node only reads keys that earlier nodes have set.)
"""The video graph: guardrail, one job, finish (ADR-0037).

    check_request -> start_job -> await_job -> finalise
        |
        v
      refuse

Three modes: `text` (a description, a shape and a length), `image` (an uploaded picture, a
description of the motion and a length) and `extend` (one of the person's clips and what should
keep happening: the last frames of the clip start a new clip and the two are joined, see
docs/spikes/video-extend-vx0.md). Graph code names capabilities (`text.moderate`,
`text.moderate_image`, `video.generate`, `video.animate`, `video.extend`), never models or workflow
node IDs.

The clip's row is created when the job starts, with status "working", so the site can show "being
made" on any page while the user explores it. The finished clip, a failure or a refusal ends it.
The uploaded picture is deleted as soon as it is no longer needed: when the request is refused,
when the job fails, and when the clip is saved. An extension works on a temporary copy of the source
clip in the user's uploads (the worker reads only from there); that is deleted the same way."""

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
    RunError,
    UploadRecord,
    UploadStore,
    await_job,
    require_context,
    upload_store,
)

from wasifyai_video import guardrail
from wasifyai_video.index import index_text
from wasifyai_video.schemas import (
    DEFAULT_SECONDS,
    DEFAULT_SHAPE,
    FPS,
    LENGTHS,
    MAX_PROMPT_CHARS,
    OVERLAP_FRAMES,
    SHAPES,
    check_looks,
)
from wasifyai_video.videos import (
    TAIL_FRAMES,
    VIDEO_CREATED,
    ClipError,
    InMemoryVideoStore,
    JoinError,
    PosterError,
    Quota,
    UsageQuota,
    VideoRecord,
    VideoStore,
    join_clips,
    last_frame,
    poster_of,
    tail_of,
    video_store,
)

log = logging.getLogger(__name__)

Status = Literal["working", "done", "refused", "failed"]
BUSY = "You already have a video being made. It will be in My creations when it's ready."
FAILED = "Your video couldn't be made. Please try again."
NOT_EXTENDABLE = "Please choose one of your finished videos to carry on."


class VideoState(TypedDict, total=False):
    # request
    mode: str
    prompt: str
    shape: str
    seconds: int
    image_key: str
    source_id: str  # extend: the clip to carry on
    loras: list[dict[str, Any]]  # looks the person taught: [{name, weight}], checked
    # extend: what the check found about it, and the temporary copy the worker reads
    source_video_key: str
    source_mode: str
    source_frames: int
    keep_frames: int
    new_frames: int
    temp_key: str
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
    videos: VideoStore = video_store(caps.db) if caps.db is not None else InMemoryVideoStore()
    uploads: UploadStore = upload_store(caps.db) if caps.db is not None else InMemoryUploadStore()
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

    async def discard_temp(key: str | None) -> None:
        """Delete the temporary copy of a clip that is being carried on. Safe when it is gone."""
        if not key:
            return
        assert caps.storage is not None
        try:
            await caps.storage.delete(key)
        except FileNotFoundError:
            pass

    async def fail_clip(state: VideoState, message: str = FAILED) -> None:
        """The clip will not be made: tell the row, and do not keep the user's picture."""
        if video_id := state.get("video_id"):
            await videos.fail(require_context().tenant_id, video_id, message)
        await discard_upload(state.get("image_key"))
        await discard_temp(state.get("temp_key"))

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
        if mode not in ("text", "image", "extend"):
            return refuse_with("invalid_request", "Please choose what kind of video to make.")
        prompt = _clean(state.get("prompt"), MAX_PROMPT_CHARS + 1)
        if not prompt:
            what = {
                "text": "describe the video",
                "image": "say what should move",
                "extend": "say what should keep happening",
            }[mode]
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
            lengths = " or ".join(str(n) for n in LENGTHS)
            return refuse_with("invalid_request", f"Please choose a length of {lengths} seconds.")
        if mode == "image" and (not key or await find_upload(key) is None):
            return refuse_with("invalid_request", "Please upload your picture again.")
        loras, why = check_looks(state.get("loras"))
        if why:
            return refuse_with("invalid_request", why)
        out: VideoState = {
            "mode": mode,
            "prompt": prompt,
            "shape": str(state.get("shape") or DEFAULT_SHAPE),
            "seconds": seconds,
            "image_key": key if mode == "image" else "",
            "loras": loras,
            "status": "working",
        }
        if mode == "extend":
            ctx = require_context()
            source = await videos.get(ctx.tenant_id, ctx.user_id, str(state.get("source_id") or ""))
            if source is None or source.status != "done" or not source.video_key:
                return refuse_with("invalid_request", NOT_EXTENDABLE)
            if (
                source.mode not in ("text", "image", "extend", "import")
                or source.frames < OVERLAP_FRAMES
            ):
                return refuse_with("invalid_request", NOT_EXTENDABLE)
            keep = source.frames - OVERLAP_FRAMES
            out["source_id"] = source.id
            out["source_video_key"] = source.video_key
            out["source_mode"] = source.mode
            out["source_frames"] = source.frames
            out["keep_frames"] = keep
            out["new_frames"] = LENGTHS[seconds]  # the new part, which repeats the nine first
            out["seconds"] = round((keep + LENGTHS[seconds]) / FPS)  # the whole clip

        async def refused(code: str, message: str) -> VideoState:
            await discard_upload(key if mode == "image" else None)
            return refuse_with(code, message)

        if await busy():  # the GPU does one clip at a time
            return await refused("busy", BUSY)
        if await over_quota():  # before any LLM or GPU work
            return await refused("quota_exceeded", quota_message())

        if not await caps.safeguards_on():  # ADR-0047: no moderation while they are off
            return out
        kind = {
            "text": "video description",
            "image": "animation description",
            "extend": "description of how a video carries on",
        }[mode]
        verdict = await guardrail.judge_text(caps, kind, prompt)
        if not verdict.allowed:
            return await refused(verdict.category, guardrail.refusal_message(verdict.category))
        if mode == "image":
            assert caps.storage is not None
            picture = await caps.storage.get(key)
            verdict = await guardrail.judge_picture(caps, prompt, picture)
            if not verdict.allowed:
                return await refused(verdict.category, guardrail.refusal_message(verdict.category))
        if mode == "extend" and out.get("source_mode") == "import":
            # what the person added is looked at like any picture they bring: its last frame, which
            # is what the new part grows from
            assert caps.storage is not None
            try:
                frame = await last_frame(await caps.storage.get(out["source_video_key"]))
            except (ClipError, FileNotFoundError):
                return refuse_with("invalid_request", NOT_EXTENDABLE)
            verdict = await guardrail.judge_picture(caps, prompt, frame)
            if not verdict.allowed:
                return refuse_with(verdict.category, guardrail.refusal_message(verdict.category))
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
        extend = state["mode"] == "extend"
        frames = state["keep_frames"] + state["new_frames"] if extend else LENGTHS[seconds]
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
                frames=frames,
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
        looks: dict[str, Any] = {"loras": state["loras"]} if state.get("loras") else {}
        temp_key = ""
        try:
            if extend:
                # the worker reads a job's inputs only from the user's uploads: a copy of the clip
                temp_key = f"uploads/extend-{uuid4()}.mp4"
                assert caps.storage is not None
                clip = await caps.storage.get(state["source_video_key"])
                from_frame = state["keep_frames"]
                if state["source_frames"] > 3 * TAIL_FRAMES:
                    # only the end is needed, and the engine holds every frame it is given in memory
                    clip = await tail_of(clip, TAIL_FRAMES, state["source_frames"])
                    from_frame = TAIL_FRAMES - OVERLAP_FRAMES
                await caps.storage.put(temp_key, clip, "video/mp4")
                handle = await caps.video.extend(
                    prompt=state["prompt"],
                    video_key=temp_key,
                    from_frame=from_frame,
                    length=state["new_frames"],
                    seed=seed,
                    **looks,
                )
            elif edit:
                handle = await caps.video.animate(
                    prompt=state["prompt"],
                    image_key=state["image_key"],
                    length=LENGTHS[seconds],
                    seed=seed,
                    **looks,
                )
            else:
                width, height = SHAPES[state["shape"]]
                handle = await caps.video.generate(
                    prompt=state["prompt"],
                    width=width,
                    height=height,
                    length=LENGTHS[seconds],
                    seed=seed,
                    **looks,
                )
        except Exception:
            await fail_clip(
                {
                    "video_id": video_id,
                    "image_key": state.get("image_key", ""),
                    "temp_key": temp_key,
                }
            )
            raise
        return {"video_id": video_id, "job_id": handle.job_id, "temp_key": temp_key}

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
            if state["mode"] == "extend":
                # the old clip up to the frames the new one repeats, then the new clip, as one file
                joined = await join_clips(
                    await caps.storage.get(state["source_video_key"]),
                    await caps.storage.get(state["result_key"]),
                    state["keep_frames"],
                )
                video_key = f"{video_id}/video.mp4"
                await caps.storage.put(video_key, joined, "video/mp4")
                await caps.storage.delete(state["result_key"])
            else:
                video_key = await caps.storage.move(state["result_key"], f"{video_id}/video.mp4")
            width, height, poster = await poster_of(await caps.storage.get(video_key))
            poster_key = f"{video_id}/poster.jpg"
            await caps.storage.put(poster_key, poster, "image/jpeg")
            await videos.finish(ctx.tenant_id, video_id, width, height, video_key, poster_key)
        except (PosterError, JoinError):
            await fail_clip(state)
            raise RunError("video_failed", FAILED, retryable=True) from None
        await discard_upload(state.get("image_key"))  # the user's original is not kept
        await discard_temp(state.get("temp_key"))
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
