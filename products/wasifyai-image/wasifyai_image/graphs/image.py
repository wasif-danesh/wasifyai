# pyright: reportTypedDictNotRequiredAccess=false
# (Graph state is filled in node by node; a node only reads keys that earlier nodes have set.)
"""The image graph: guardrail, one job, finish.

    check_request -> start_job -> await_job -> finalise
        |
        v
      refuse

Two modes: `text` (a description and a size) and `image` (an uploaded picture and an instruction).
Graph code names capabilities (`text.moderate`, `text.moderate_image`, `image.generate`,
`image.edit`), never models or workflow node IDs. The job is two nodes: one enqueues, one waits,
because a paused node re-runs from its start on resume.

The uploaded picture is deleted as soon as it is no longer needed: when the request is refused,
when the job fails, and when the image is saved.
"""

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

from wasifyai_image import guardrail
from wasifyai_image.images import (
    IMAGE_CREATED,
    ImageRecord,
    ImageStore,
    InMemoryImageStore,
    Quota,
    UsageQuota,
    image_store,
    thumbnail_of,
)
from wasifyai_image.index import index_text
from wasifyai_image.schemas import DEFAULT_SIZE, MAX_PROMPT_CHARS, SIZES

log = logging.getLogger(__name__)

Status = Literal["working", "done", "refused", "failed"]


class ImageState(TypedDict, total=False):
    # request
    mode: str
    prompt: str
    size: str
    image_key: str
    # job and result
    job_id: str
    result_key: str
    image_id: str
    image_key_final: str
    image_url: str
    thumb_url: str
    width: int
    height: int
    # outcome
    status: Status
    refusal: dict[str, str]


def _clean(value: object, limit: int) -> str:
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(value or ""))
    return re.sub(r"[ \t]+", " ", text).strip()[:limit]


def build_image(caps: Capabilities, checkpointer: Any):
    """Registry entry point: wires the production stores from the capabilities."""
    images: ImageStore = image_store(caps.db) if caps.db is not None else InMemoryImageStore()
    uploads: UploadStore = upload_store(caps.db) if caps.db is not None else InMemoryUploadStore()
    quota: Quota | None = UsageQuota(caps.db) if caps.db is not None else None
    return build_image_graph(caps, checkpointer, images, uploads, quota)


def build_image_graph(
    caps: Capabilities,
    checkpointer: Any,
    images: ImageStore,
    uploads: UploadStore,
    quota: Quota | None,
):
    limit = (caps.config.quotas.get("images_per_user_per_day") if caps.config else None) or None

    async def over_quota() -> bool:
        if not await caps.safeguards_on():  # ADR-0047: quotas apply only with safeguards
            return False
        return bool(limit and quota and await quota.used_today(require_context()) >= limit)

    def quota_message() -> str:
        return f"You've reached today's limit of {limit} images. Please try again tomorrow."

    def refuse_with(code: str, message: str) -> ImageState:
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

    # ---- guardrail ----------------------------------------------------------------------

    async def check_request(state: ImageState) -> ImageState:
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
            return refuse_with("invalid_request", "Please choose text to image or image to image.")
        prompt = _clean(state.get("prompt"), MAX_PROMPT_CHARS + 1)
        if not prompt:
            what = "describe the image" if mode == "text" else "say what to change"
            return refuse_with("invalid_request", f"Please {what} you would like.")
        if len(prompt) > MAX_PROMPT_CHARS:
            return refuse_with(
                "invalid_request", f"Please keep it under {MAX_PROMPT_CHARS} characters."
            )
        key = str(state.get("image_key") or "")
        if mode == "text" and (state.get("size") or DEFAULT_SIZE) not in SIZES:
            return refuse_with("invalid_request", "Please choose one of the image sizes.")
        if mode == "image" and (not key or await find_upload(key) is None):
            return refuse_with("invalid_request", "Please upload your picture again.")
        out: ImageState = {
            "mode": mode,
            "prompt": prompt,
            "size": str(state.get("size") or DEFAULT_SIZE),
            "image_key": key if mode == "image" else "",
            "status": "working",
        }

        async def refused(code: str, message: str) -> ImageState:
            await discard_upload(key if mode == "image" else None)
            return refuse_with(code, message)

        if await over_quota():  # before any LLM or GPU work
            return await refused("quota_exceeded", quota_message())

        if not await caps.safeguards_on():  # ADR-0047: no moderation while they are off
            return out
        kind = "image description" if mode == "text" else "edit instruction"
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

    def after_check(state: ImageState) -> str:
        return "refuse" if state.get("status") == "refused" else "start_job"

    async def refuse(state: ImageState) -> ImageState:
        return {}

    # ---- the job ------------------------------------------------------------------------

    async def start_job(state: ImageState) -> ImageState:
        if await over_quota():  # again, right before the GPU is used
            await discard_upload(state.get("image_key"))
            raise RunError("quota_exceeded", quota_message())
        write = get_stream_writer()
        edit = state["mode"] == "image"
        write(
            {
                "type": "node",
                "node": "generate_image",
                "status": "started",
                "label": "Changing your picture" if edit else "Painting your image",
            }
        )
        seed = secrets.randbelow(2**31)
        if edit:
            handle = await caps.image.edit(
                prompt=state["prompt"], image_key=state["image_key"], seed=seed
            )
        else:
            width, height = SIZES[state["size"]]
            handle = await caps.image.generate(
                prompt=state["prompt"], width=width, height=height, seed=seed
            )
        return {"job_id": handle.job_id}

    async def await_job_node(state: ImageState) -> ImageState:
        try:
            result = await_job(state["job_id"])
        except JobFailed:
            # Nothing was made: do not keep the user's picture around.
            await discard_upload(state.get("image_key"))
            raise
        return {"result_key": result.outputs["image"].key}

    # ---- finish -------------------------------------------------------------------------

    async def finalise(state: ImageState) -> ImageState:
        assert caps.storage is not None, "object storage is required"
        ctx = require_context()
        image_id = str(uuid4())
        # Final layout {tenant}/wasifyai-image/{user}/{image_id}/image.*; the worker's jobs/ paths
        # are
        # temporary.
        ext = state["result_key"].rsplit(".", 1)[-1]
        image_key = await caps.storage.move(state["result_key"], f"{image_id}/image.{ext}")
        width, height, thumb = await thumbnail_of(await caps.storage.get(image_key))
        thumb_key = f"{image_id}/thumb.jpg"
        await caps.storage.put(thumb_key, thumb, "image/jpeg")
        await images.add(
            ImageRecord(
                id=image_id,
                tenant_id=ctx.tenant_id,
                product_id=ctx.product_id,
                user_id=ctx.user_id,
                thread_id=ctx.thread_id,
                run_id=ctx.run_id,
                mode=state["mode"],
                prompt=state["prompt"],
                width=width,
                height=height,
                image_key=image_key,
                thumb_key=thumb_key,
            )
        )
        await discard_upload(state.get("image_key"))  # the user's original is not kept
        await caps.index_creation("image", image_id, index_text(state["prompt"]))  # ADR-0041
        await caps.record_usage(IMAGE_CREATED, 1, "images", image_id=image_id, mode=state["mode"])
        return {
            "image_id": image_id,
            "image_key_final": image_key,
            "image_url": await caps.storage.url(image_key),
            "thumb_url": await caps.storage.url(thumb_key),
            "width": width,
            "height": height,
            "status": "done",
        }

    g = StateGraph(ImageState)
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
