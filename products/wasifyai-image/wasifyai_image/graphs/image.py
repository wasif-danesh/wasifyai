# pyright: reportTypedDictNotRequiredAccess=false
# (Graph state is filled in node by node; a node only reads keys that earlier nodes have set.)
"""The image graph: a check of the request, one job, finish.

    check_request -> start_job -> await_job -> finalise
        |
        v
      refuse

Two modes: `text` (a description and a size) and `image` (an uploaded picture and an instruction).
Graph code names capabilities (`image.generate`, `image.edit`), never models or workflow node IDs.
The job is two nodes: one enqueues, one waits, because a paused node re-runs from its start on
resume.

The uploaded picture is deleted as soon as it is no longer needed: when the request is refused,
when the job fails, and when the image is saved.
"""

import asyncio
import io
import logging
import re
import secrets
from typing import Any, Literal, TypedDict, cast
from uuid import uuid4

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from PIL import Image
from wasifyai_platform_sdk import (
    Capabilities,
    InMemoryUploadStore,
    JobFailed,
    UploadRecord,
    UploadStore,
    await_job,
    require_context,
    upload_store,
)

from wasifyai_image.images import (
    IMAGE_CREATED,
    ImageRecord,
    ImageStore,
    InMemoryImageStore,
    image_store,
    thumbnail_of,
)
from wasifyai_image.index import index_text
from wasifyai_image.schemas import DEFAULT_SIZE, MAX_PROMPT_CHARS, MODES, SIZES

log = logging.getLogger(__name__)

Status = Literal["working", "done", "refused", "failed"]


class ImageState(TypedDict, total=False):
    # request
    mode: str
    prompt: str
    size: str
    image_key: str  # the picture to change, or the first reference
    image2_key: str  # the second reference (reference mode)
    mask_key: str  # the painted area, white on black (inpaint mode)
    seed: int  # optional in the request; always set once the request is checked
    loras: list[dict[str, Any]]  # [{name, weight}], checked: at most MAX_LORAS
    # on the desktop: [{id, strength}] of the person's styles (ADR-0091); turned into `loras`
    styles: list[dict[str, Any]]
    # Advanced (ADR-0091 decision 10): sampling steps, and a size of the person's own instead of a
    # named shape (text and reference); absent, the workflow's own steps and the named size
    steps: int
    width: int
    height: int
    lora_files: dict[
        str, str
    ]  # on the web: the storage key of each style, which is the person's own
    # the picture of the library the change starts from, when the person chose one there
    # (not a file they added)
    source_id: str
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


# The uploads each mode takes, as the state's key fields.
PICTURE_KEYS: dict[str, tuple[str, ...]] = {
    "text": (),
    "image": ("image_key",),
    "reference": ("image_key", "image2_key"),
    "inpaint": ("image_key", "mask_key"),
}
# What the model is told for an inpaint: there is no inpainting model for klein, so the painted area
# is filled white on the copy it sees and named in words (docs/spikes/image-ir0.md).
INPAINT_INSTRUCTION = "Fill the white area with: {prompt}. Keep everything else exactly the same."
MIN_PAINTED, MAX_PAINTED = 0.001, 0.98  # the share of the picture a mask may cover
MAX_SEED = 2**31 - 1
RECIPE_VERSION = 1
MAX_LORAS = 8  # ADR-0091 decision 7
LORA_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()/-]{0,200}\.safetensors$")
MIN_WEIGHT, MAX_WEIGHT = 0.05, 2.0
MIN_STEPS, MAX_STEPS = 1, 50
MIN_SIDE, MAX_SIDE = 256, 2048  # a size of one's own: multiples of 16 (FLUX.2's grid)


def check_loras(raw: object) -> tuple[list[dict[str, Any]], str]:
    """The LoRAs of a request as `[{name, weight}]`, or why they are refused. A name is a file name
    relative to a `loras` folder: no `..`, no absolute path, only `.safetensors`."""
    if raw in (None, []):
        return [], ""
    if not isinstance(raw, list):
        return [], "Please choose the styles from the list."
    if len(raw) > MAX_LORAS:
        return [], f"Please use at most {MAX_LORAS} styles."
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        name = item.get("name") if isinstance(item, dict) else None
        weight = item.get("weight", 1.0) if isinstance(item, dict) else None
        if not isinstance(name, str) or not LORA_NAME.match(name) or ".." in name:
            return [], "One of the styles has a name that cannot be used."
        if isinstance(weight, bool) or not isinstance(weight, int | float):
            return [], "A style's strength must be a number."
        if not MIN_WEIGHT <= float(weight) <= MAX_WEIGHT:
            return [], f"A style's strength must be between {MIN_WEIGHT} and {MAX_WEIGHT}."
        if name in seen:
            return [], "Each style can be used once."
        seen.add(name)
        out.append({"name": name, "weight": round(float(weight), 2)})
    return out, ""


STYLE_ID = re.compile(r"^[a-f0-9]{6,32}$")


def check_styles(raw: object) -> tuple[list[dict[str, Any]], str]:
    """The styles of a request as `[{id, strength}]`, or why they are refused. An id names a record
    the engine keeps; the request never names a file."""
    if not isinstance(raw, list):
        return [], "Please choose the styles from the list."
    if len(raw) > MAX_LORAS:
        return [], f"Please use at most {MAX_LORAS} styles."
    out: list[dict[str, Any]] = []
    for item in raw:
        sid = item.get("id") if isinstance(item, dict) else None
        strength = item.get("strength", 1.0) if isinstance(item, dict) else None
        if not isinstance(sid, str) or not STYLE_ID.match(sid):
            return [], "Please choose the styles from the list."
        if isinstance(strength, bool) or not isinstance(strength, int | float):
            return [], "A style's strength must be a number."
        if not MIN_WEIGHT <= float(strength) <= MAX_WEIGHT:
            return [], f"A style's strength must be between {MIN_WEIGHT} and {MAX_WEIGHT}."
        if any(o["id"] == sid for o in out):
            return [], "Each style can be used once."
        out.append({"id": sid, "strength": round(float(strength), 2)})
    return out, ""


def check_advanced(state: dict[str, Any], sized: bool) -> tuple[dict[str, int], str]:
    """Steps and a size of one's own, or why they are refused."""
    out: dict[str, int] = {}
    steps = state.get("steps")
    if steps is not None:
        if (
            isinstance(steps, bool)
            or not isinstance(steps, int)
            or not (MIN_STEPS <= steps <= MAX_STEPS)
        ):
            return {}, f"Steps must be a whole number from {MIN_STEPS} to {MAX_STEPS}."
        out["steps"] = steps
    width, height = state.get("width"), state.get("height")
    if width is None and height is None:
        return out, ""
    if not sized:
        return {}, "This kind of change keeps the picture's own size."
    for side in (width, height):
        if isinstance(side, bool) or not isinstance(side, int):
            return {}, "Give the width and the height as whole numbers."
        if not MIN_SIDE <= side <= MAX_SIDE or side % 16:
            return {}, (
                f"Width and height must be between {MIN_SIDE} and {MAX_SIDE}, in steps of 16."
            )
    out["width"], out["height"] = int(width), int(height)  # type: ignore[arg-type]
    return out, ""


def size_of(state: ImageState) -> tuple[int, int]:
    """The picture's width and height: one's own, or the named shape's."""
    if state.get("width") and state.get("height"):
        return state["width"], state["height"]
    return SIZES[state["size"]]


def recipe_of(state: ImageState, width: int, height: int) -> dict[str, Any]:
    """What made the image, in the shape the window shows and "run again" reads. The model is not
    named: the graph asks for a capability, not a model (see docs/phase2-stage-b-plan.md)."""
    sized = state["mode"] in ("text", "reference")  # the others take their shape from the picture
    styles = {"styles": state["styles"]} if state.get("styles") else {}
    advanced: dict[str, Any] = {"steps": state["steps"]} if state.get("steps") else {}
    if sized and state.get("width"):  # a size of one's own, not the named shape
        advanced["own_size"] = True
    return {
        "v": RECIPE_VERSION,
        "mode": state["mode"],
        "prompt": state["prompt"],
        "size": state["size"] if sized else None,
        "width": width,
        "height": height,
        "seed": state["seed"],
        "loras": state.get("loras") or [],
        **styles,  # by id, strength, checksum and title: "Make it again" finds them (ADR-0091)
        **advanced,
    }


def _clean(value: object, limit: int) -> str:
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(value or ""))
    return re.sub(r"[ \t]+", " ", text).strip()[:limit]


def build_image(caps: Capabilities, checkpointer: Any):
    """Registry entry point: wires the production stores from the capabilities."""
    images: ImageStore = image_store(caps.db) if caps.db is not None else InMemoryImageStore()
    uploads: UploadStore = upload_store(caps.db) if caps.db is not None else InMemoryUploadStore()
    return build_image_graph(caps, checkpointer, images, uploads)


def build_image_graph(
    caps: Capabilities,
    checkpointer: Any,
    images: ImageStore,
    uploads: UploadStore,
):
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

    async def discard_all(state: ImageState) -> None:
        """Delete every picture of the request (the second reference and the mask too)."""
        for field in PICTURE_KEYS.get(state.get("mode", ""), ("image_key",)):
            await discard_upload(state.get(field))  # type: ignore[misc]

    async def check_mask(source_key: str, mask_key: str) -> str:
        """Why a painted area cannot be used, or an empty string: it covers something, not nearly
        all of the picture, and has the picture's shape."""
        assert caps.storage is not None
        source, mask = await caps.storage.get(source_key), await caps.storage.get(mask_key)

        def look() -> str:
            try:
                with Image.open(io.BytesIO(source)) as s, Image.open(io.BytesIO(mask)) as m:
                    (sw, sh), (mw, mh) = s.size, m.size
                    painted = sum(m.convert("L").histogram()[128:]) / (mw * mh)
            except (OSError, ValueError):
                return "That painted area could not be read. Please paint it again."
            if abs(sw / sh - mw / mh) > 0.02 * (sw / sh):
                return "The painted area does not fit the picture. Please paint it again."
            if painted < MIN_PAINTED:
                return "Paint the part of the picture you want to change."
            if painted > MAX_PAINTED:
                return "Leave part of the picture unpainted, or use Change a picture instead."
            return ""

        return await asyncio.to_thread(look)

    # ---- the request ----------------------------------------------------------------------

    async def source_of(state: ImageState, mode: str) -> str:
        """The picture of the person's library this one starts from: kept only when it is theirs
        and the mode changes a picture (a file they added has none)."""
        wanted = str(state.get("source_id") or "")
        if mode == "text" or not wanted:
            return ""
        ctx = require_context()
        found = await images.get(ctx.tenant_id, ctx.user_id, wanted)
        return found.id if found is not None else ""

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
        if mode not in MODES:
            return refuse_with("invalid_request", "Please choose what kind of picture to make.")
        prompt = _clean(state.get("prompt"), MAX_PROMPT_CHARS + 1)
        if not prompt:
            what = {
                "text": "describe the image",
                "image": "say what to change",
                "reference": "describe the new picture",
                "inpaint": "say what to put in the painted area",
            }[mode]
            return refuse_with("invalid_request", f"Please {what} you would like.")
        if len(prompt) > MAX_PROMPT_CHARS:
            return refuse_with(
                "invalid_request", f"Please keep it under {MAX_PROMPT_CHARS} characters."
            )
        # the uploads this mode takes: every one is deleted on every way out
        keys = {field: str(state.get(field) or "") for field in PICTURE_KEYS[mode]}
        picked: ImageState = {"mode": mode, **keys}  # type: ignore[typeddict-item]

        async def refused(code: str, message: str) -> ImageState:
            await discard_all(picked)
            return refuse_with(code, message)

        sized = mode in ("text", "reference")
        if sized and (state.get("size") or DEFAULT_SIZE) not in SIZES:
            return await refused("invalid_request", "Please choose one of the image sizes.")
        advanced, why = check_advanced(dict(state), sized)
        if why:
            return await refused("invalid_request", why)
        for key in keys.values():
            if not key or await find_upload(key) is None:
                again = "picture" if len(keys) == 1 else "pictures"
                return await refused("invalid_request", f"Please upload your {again} again.")
        if mode == "inpaint" and (why_mask := await check_mask(*keys.values())):
            return await refused("invalid_mask", why_mask)
        seed = state.get("seed")
        if seed is None:  # a new picture each time, unless the person asked for this one again
            seed = secrets.randbelow(MAX_SEED + 1)
        elif isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= MAX_SEED:
            return await refused("invalid_request", "That seed is not valid.")
        wanted = state.get("styles")
        styles: list[dict[str, Any]] = []
        raw_loras = state.get("loras")
        if wanted:
            to_files = caps.extras.get("styles")  # the desktop: style ids to the files it keeps
            styles, why = check_styles(wanted)
            if to_files is None:
                why = why or "Styles cannot be used here."
            if why or to_files is None:
                return await refused("invalid_request", why)
            raw_loras, why = await to_files(styles)
            if why:
                return await refused("invalid_request", why)
            # what each style was, kept with the picture: "Make it again" can say which is missing
            styles = [
                {**s, **{k: r[k] for k in ("sha256", "title") if k in r}}
                for s, r in zip(styles, raw_loras, strict=False)
            ]
        loras, why = check_loras(raw_loras)
        if why:
            return await refused("invalid_request", why)
        # the web: a style an admin added is fetched by its storage key (the resolver says it)
        lora_files: dict[str, str] = {
            str(r["name"]): str(r["key"])
            for r in (raw_loras if isinstance(raw_loras, list) else [])
            if isinstance(r, dict) and r.get("key")
        }
        resolve_looks = caps.extras.get(
            "person_looks"
        )  # the web keeps each person's styles in storage
        own = [x["name"] for x in loras if x["name"] not in lora_files]
        if own and resolve_looks is not None:
            ctx = require_context()
            found = await resolve_looks(ctx.tenant_id, ctx.user_id, own)
            if found is None:
                return await refused(
                    "invalid_request", "One of those styles is not yours any more."
                )
            lora_files = {**lora_files, **found}
        out: ImageState = {
            "mode": mode,
            "prompt": prompt,
            "size": str(state.get("size") or DEFAULT_SIZE),
            "image_key": keys.get("image_key", ""),
            "image2_key": keys.get("image2_key", ""),
            "mask_key": keys.get("mask_key", ""),
            "seed": seed,
            "loras": loras,
            "styles": styles,
            "lora_files": lora_files,
            "source_id": await source_of(state, mode),
            "status": "working",
        }
        if "steps" in advanced:
            out["steps"] = advanced["steps"]
        if "width" in advanced:
            out["width"], out["height"] = advanced["width"], advanced["height"]
        return out

    def after_check(state: ImageState) -> str:
        return "refuse" if state.get("status") == "refused" else "start_job"

    async def refuse(state: ImageState) -> ImageState:
        return {}

    # ---- the job ------------------------------------------------------------------------

    async def start_job(state: ImageState) -> ImageState:
        write = get_stream_writer()
        mode = state["mode"]
        write(
            {
                "type": "node",
                "node": "generate_image",
                "status": "started",
                "label": {
                    "image": "Changing your picture",
                    "reference": "Combining your pictures",
                    "inpaint": "Changing the painted area",
                }.get(mode, "Painting your image"),
            }
        )
        seed = state["seed"]
        extra: dict[str, Any] = {"loras": state["loras"]} if state.get("loras") else {}
        if state.get("steps"):
            extra["steps"] = state["steps"]
        if state.get("lora_files"):
            extra["lora_files"] = state["lora_files"]
        prompt = state["prompt"]
        if mode == "image":
            handle = await caps.image.edit(
                prompt=prompt, image_key=state["image_key"], seed=seed, **extra
            )
        elif mode == "reference":
            width, height = size_of(state)
            handle = await caps.image.reference(
                prompt=prompt, image_key=state["image_key"], image2_key=state["image2_key"],
                width=width, height=height, seed=seed, **extra,
            )  # fmt: skip
        elif mode == "inpaint":
            handle = await caps.image.inpaint(
                prompt=INPAINT_INSTRUCTION.format(prompt=prompt), image_key=state["image_key"],
                mask_key=state["mask_key"], seed=seed, **extra,
            )  # fmt: skip
        else:
            width, height = size_of(state)
            handle = await caps.image.generate(
                prompt=prompt, width=width, height=height, seed=seed, **extra
            )
        return {"job_id": handle.job_id}

    async def await_job_node(state: ImageState) -> ImageState:
        try:
            result = await_job(state["job_id"])
        except JobFailed:
            # Nothing was made: do not keep the user's pictures around.
            await discard_all(state)
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
                recipe=recipe_of(state, width, height),
                source_id=state.get("source_id") or None,
            )
        )
        await discard_all(state)  # the user's originals are not kept
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
