"""What each cloud offer of a picture or clip model is sent (ADR-0100, stages CP4 and CP5).

A job is read once into an `Ask` (its words, size, seed, pictures, mask, clip and length). A
recipe turns an `Ask` into the provider's request for one offer: the endpoint (the offer's own for
the job's verb: make, edit, inpaint, animate, extend) and the body, with every input file sent the
way that provider takes it (`Send`: fal.ai's and WaveSpeed's file stores answer an address; Runware
takes the file inside the task). The field names are each provider's published schema, read in
`docs/spikes/fal-v1-fa0-inputs.md` and `docs/spikes/cloud-v1-cp0.md`.

    RECIPES[(provider, model)]   the recipe of the catalogue's model on that provider
    ask_of(job, files)            the `Ask` of a media worker job"""

import io
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from PIL import Image
from wasifyai_platform_sdk import JobRequest
from wasifyai_platform_sdk.fal import FalError, data_uri
from wasifyai_platform_sdk.offers import Offer

# a file to the provider, answered as what its request names: an address, or the file itself
Send = Callable[[bytes, str], Awaitable[str]]


@dataclass(frozen=True)
class Ask:
    capability: str
    prompt: str
    width: int | None = None
    height: int | None = None
    seed: int | None = None
    pictures: tuple[bytes, ...] = ()  # the picture to change, then any others to combine
    mask: bytes | None = None  # white where the change goes
    video: bytes | None = None  # the clip to extend
    seconds: float | None = None  # the clip's length
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def verb(self) -> str:
        """The offer's endpoint for this job: make, edit, inpaint, animate or extend."""
        return VERBS.get(self.capability, "make")


VERBS = {
    "image.edit": "edit",
    "image.reference": "edit",
    "image.inpaint": "inpaint",
    "video.animate": "animate",
    "video.extend": "extend",
}


def _bad(message: str) -> FalError:
    """A job this offer cannot take, found before anything is sent: the next offer may."""
    return FalError("invalid_input", message, before_running=True)


def ask_of(job: JobRequest, files: dict[str, bytes] | None) -> Ask:
    files = files or {}
    prompt = job.inputs.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise FalError("invalid_input", "The request has no description.")
    w, h, seed = job.inputs.get("width"), job.inputs.get("height"), job.inputs.get("seed")
    frames = job.inputs.get("length")
    # a look taught on a cloud model: its address there, which the model loads (stage CP10)
    urls = job.inputs.get("lora_urls") or {}
    loras = [
        {"path": urls[x["name"]]["url"], "scale": float(x.get("weight", 1.0))}
        for x in job.inputs.get("loras") or []
        if isinstance(x, dict) and isinstance(urls.get(x.get("name")), dict)
    ]
    return Ask(
        capability=job.capability, prompt=prompt.strip(),
        width=w if isinstance(w, int) else None, height=h if isinstance(h, int) else None,
        seed=seed if isinstance(seed, int) else None,
        pictures=tuple(files[n] for n in ("image", "image2") if n in files),
        mask=files.get("mask"), video=files.get("video"),
        seconds=frames / 24 if isinstance(frames, int) and frames > 0 else None,
        extra={"loras": loras} if loras else {},
    )  # fmt: skip


# ---- the shapes the providers take --------------------------------------------------------------


def aspect(ask: Ask, allowed: tuple[str, ...]) -> str:
    """The allowed ratio nearest the job's size ("1:1" when it gave none)."""
    if not (ask.width and ask.height):
        return "1:1" if "1:1" in allowed else allowed[0]

    def value(r: str) -> float:
        a, b = r.split(":")
        return float(a) / float(b)

    want = ask.width / ask.height
    return min(allowed, key=lambda r: abs(value(r) - want))


def fal_size(ask: Ask) -> dict[str, int] | None:
    """fal.ai's own size: width and height (a multiple of 16)."""
    if not (ask.width and ask.height):
        return None
    return {"width": round(ask.width / 16) * 16, "height": round(ask.height / 16) * 16}


def sixty_four(side: int | None, top: int = 2048) -> int:
    """Runware's sides: a multiple of 64 from 128 to `top`."""
    n = side if isinstance(side, int) else 1024
    return min(top, max(128, round(n / 64) * 64))


def mask_as_alpha(mask: bytes, picture: bytes | None) -> bytes:
    """OpenAI's mask is a picture whose clear pixels are the ones to change: ours is white where
    the change goes. Made at the picture's size."""
    m = Image.open(io.BytesIO(mask)).convert("L")
    if picture is not None:
        size = Image.open(io.BytesIO(picture)).size
        if m.size != size:
            m = m.resize(size)
    out = Image.new("RGBA", m.size, (0, 0, 0, 255))
    out.putalpha(m.point([0 if v >= 128 else 255 for v in range(256)]))
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()


async def _all(send: Send, pictures: tuple[bytes, ...], most: int) -> list[str]:
    if not pictures:
        raise _bad("The picture for this job is missing.")
    return [await send(p, f"picture{i}.png") for i, p in enumerate(pictures[:most])]


# ---- pictures ---------------------------------------------------------------------------------


Recipe = Callable[[Ask, Offer, Send], Awaitable[tuple[str, dict[str, Any]]]]


async def gpt_image_fal(ask: Ask, o: Offer, send: Send) -> tuple[str, dict[str, Any]]:
    body: dict[str, Any] = {"prompt": ask.prompt, "quality": "high", "output_format": "png"}
    size = fal_size(ask)
    if size:
        body["image_size"] = size
    if ask.verb == "make":
        return o.endpoint, body
    body["image_urls"] = await _all(send, ask.pictures, 16)
    if ask.verb == "inpaint":
        if ask.mask is None:
            raise _bad("The painted area for this job is missing.")
        body["mask_url"] = await send(mask_as_alpha(ask.mask, ask.pictures[0]), "mask.png")
    return o.endpoint_for("edit"), body


GPT_RATIOS = ("1:1", "3:2", "2:3", "16:9", "9:16", "4:3", "3:4")


async def gpt_image_wavespeed(ask: Ask, o: Offer, send: Send) -> tuple[str, dict[str, Any]]:
    body: dict[str, Any] = {
        "prompt": ask.prompt, "quality": "high", "resolution": "1k",
        "aspect_ratio": aspect(ask, GPT_RATIOS), "output_format": "png",
    }  # fmt: skip
    if ask.verb == "make":
        return o.endpoint, body
    body["images"] = await _all(send, ask.pictures, 16)
    if ask.verb == "inpaint":
        if ask.mask is None:
            raise _bad("The painted area for this job is missing.")
        body["mask_image"] = await send(mask_as_alpha(ask.mask, ask.pictures[0]), "mask.png")
    return o.endpoint_for("edit"), body


BANANA_RATIOS = ("1:1", "21:9", "16:9", "3:2", "4:3", "5:4", "4:5", "3:4", "2:3", "9:16")


async def nano_banana_wavespeed(ask: Ask, o: Offer, send: Send) -> tuple[str, dict[str, Any]]:
    body: dict[str, Any] = {
        "prompt": ask.prompt, "aspect_ratio": aspect(ask, BANANA_RATIOS), "resolution": "1k",
        "output_format": "png",
    }  # fmt: skip
    if ask.verb == "make":
        return o.endpoint, body
    body["images"] = await _all(send, ask.pictures, 14)
    return o.endpoint_for("edit"), body


async def grok_image_fal(ask: Ask, o: Offer, send: Send) -> tuple[str, dict[str, Any]]:
    ratios = ("1:1", "2:1", "16:9", "4:3", "3:2", "2:3", "3:4", "9:16", "1:2")
    body: dict[str, Any] = {
        "prompt": ask.prompt, "aspect_ratio": aspect(ask, ratios), "resolution": "1k",
        "quality": "medium", "output_format": "png",
    }  # fmt: skip
    if ask.verb == "make":
        return o.endpoint, body
    body["image_urls"] = await _all(send, ask.pictures, 5)
    return o.endpoint_for("edit"), body


async def klein_fal(ask: Ask, o: Offer, send: Send) -> tuple[str, dict[str, Any]]:
    body: dict[str, Any] = {"prompt": ask.prompt, "output_format": "png"}
    size = fal_size(ask)
    if size:
        body["image_size"] = size
    if ask.seed is not None:
        body["seed"] = ask.seed
    if ask.extra.get("loras"):  # a look trained on fal.ai (stage CP10): its own endpoint
        body["loras"] = ask.extra["loras"]
        return o.endpoint_for("lora"), body
    if ask.verb == "make":
        return o.endpoint, body
    body["image_urls"] = await _all(send, ask.pictures, 4)
    return o.endpoint_for("edit"), body


async def z_image_fal(ask: Ask, o: Offer, send: Send) -> tuple[str, dict[str, Any]]:
    body: dict[str, Any] = {"prompt": ask.prompt, "output_format": "png"}
    size = fal_size(ask)
    if size:
        body["image_size"] = size
    if ask.seed is not None:
        body["seed"] = ask.seed
    if ask.extra.get("loras"):  # a look trained on a cloud model (stage CP10): its own endpoint
        if ask.verb != "make":
            raise _bad("A look is used on Z-Image Turbo only to make a picture.")
        body["loras"] = ask.extra["loras"]
        return o.endpoint_for("lora"), body
    if ask.verb == "make":
        return o.endpoint, body
    if ask.verb != "inpaint" or ask.mask is None or not ask.pictures:
        raise _bad("Z-Image Turbo on fal.ai paints over part of a picture; it does not change one.")
    body["image_url"] = await send(ask.pictures[0], "picture.png")
    body["mask_image_url"] = await send(ask.mask, "mask.png")
    return o.endpoint_for("inpaint"), body


def runware_image(refs: int, quality: str | None = None) -> Recipe:
    """A Runware `imageInference` task: references for change and combine (up to `refs`), the
    picture and mask for Inpaint (`inputs.seedImage`, `inputs.maskImage`)."""

    async def recipe(ask: Ask, o: Offer, send: Send) -> tuple[str, dict[str, Any]]:
        task: dict[str, Any] = {
            "taskType": "imageInference", "positivePrompt": ask.prompt, "numberResults": 1,
            "outputFormat": "PNG", "width": sixty_four(ask.width), "height": sixty_four(ask.height),
            "includeCost": True,
        }  # fmt: skip
        if ask.seed is not None:
            task["seed"] = ask.seed
        if quality:
            task["settings"] = {"quality": quality}
        if ask.verb == "edit":
            if not refs:
                raise _bad("This model does not change pictures on Runware.")
            task["inputs"] = {"referenceImages": await _all(send, ask.pictures, refs)}
        elif ask.verb == "inpaint":
            if ask.mask is None or not ask.pictures:
                raise _bad("The picture or the painted area for this job is missing.")
            task["inputs"] = {
                "seedImage": await send(ask.pictures[0], "picture.png"),
                "maskImage": await send(ask.mask, "mask.png"),
            }
        return o.endpoint_for(ask.verb), task

    return recipe


async def runware_send(data: bytes, name: str) -> str:
    """Runware takes a picture inside the task, as a data URI: nothing goes up first (a clip or a
    voice goes up first: `RunwareTasks.upload`)."""
    return data_uri(data)


# ---- clips ------------------------------------------------------------------------------------
#
# A clip is made at 720p (768p for MiniMax H3) without sound, at the length nearest what was asked
# that the model takes. Extend sends the clip and asks for it back with the new part after it (the
# whole of what was sent, then the new seconds): the video product keeps its own clip up to what it
# sent and joins the rest (`extend_whole`).


def seconds_in(ask: Ask, lowest: int, highest: int, default: int) -> int:
    want = round(ask.seconds) if ask.seconds else default
    return max(lowest, min(highest, want))


WIDE = ("16:9", "9:16")
SEVEN = ("16:9", "4:3", "1:1", "3:4", "9:16", "21:9")


async def _clip(send: Send, ask: Ask) -> str:
    if ask.video is None:
        raise _bad("The clip to extend is missing.")
    return await send(ask.video, "clip.mp4")


async def _first(send: Send, ask: Ask) -> str:
    if not ask.pictures:
        raise _bad("The picture for this job is missing.")
    return await send(ask.pictures[0], "picture.png")


def runware_video(lowest: int, highest: int, size: str, extend: str | None = None) -> Recipe:
    """A Runware `videoInference` task: the first frame for animate (`inputs.frameImages`), the
    clip for extend (`inputs.video`, with `settings.operation` where the model asks for it)."""

    async def recipe(ask: Ask, o: Offer, send: Send) -> tuple[str, dict[str, Any]]:
        task: dict[str, Any] = {
            "taskType": "videoInference", "positivePrompt": ask.prompt,
            "duration": seconds_in(ask, lowest, highest, 5), "resolution": size,
            "outputFormat": "MP4", "includeCost": True, "settings": {"audio": False},
        }  # fmt: skip
        if ask.seed is not None:
            task["seed"] = ask.seed
        if ask.verb == "animate":
            task["inputs"] = {"frameImages": [{"image": await _first(send, ask), "frame": "first"}]}
        elif ask.verb == "extend":
            if extend is None:
                raise _bad("This model does not extend a clip on Runware.")
            task["inputs"] = {"video": await _clip(send, ask)}
            if extend:
                task["settings"]["operation"] = extend
        return o.endpoint_for(ask.verb), task

    return recipe


async def omni_wavespeed(ask: Ask, o: Offer, send: Send) -> tuple[str, dict[str, Any]]:
    body: dict[str, Any] = {
        "prompt": ask.prompt, "duration": seconds_in(ask, 3, 15, 8),
        "aspect_ratio": aspect(ask, WIDE), "resolution": "720p",
    }  # fmt: skip
    if ask.verb == "animate":
        body["image"] = await _first(send, ask)
    elif ask.verb == "extend":
        raise _bad("Gemini Omni does not extend a clip on WaveSpeed.")
    return o.endpoint_for(ask.verb), body


async def seedance_wavespeed(ask: Ask, o: Offer, send: Send) -> tuple[str, dict[str, Any]]:
    body: dict[str, Any] = {
        "prompt": ask.prompt, "duration": seconds_in(ask, 4, 30, 5), "resolution": "720p",
        "generate_audio": False,
    }  # fmt: skip
    if ask.verb == "animate":
        body["image"] = await _first(send, ask)
    elif ask.verb == "extend":
        body["video"] = await _clip(send, ask)
    else:
        body["aspect_ratio"] = aspect(ask, SEVEN)
    return o.endpoint_for(ask.verb), body


async def h3_fal(ask: Ask, o: Offer, send: Send) -> tuple[str, dict[str, Any]]:
    body: dict[str, Any] = {
        "prompt": ask.prompt, "duration": seconds_in(ask, 5, 10, 5), "resolution": "768P",
    }  # fmt: skip
    if ask.seed is not None:
        body["seed"] = ask.seed
    if ask.verb == "extend":
        body |= {"video_url": await _clip(send, ask), "output": "extended"}
        return o.endpoint_for("extend"), body
    body["prompt_expansion_mode"] = "balanced"
    if ask.verb == "animate":
        body["image_url"] = await _first(send, ask)
    else:
        body["aspect_ratio"] = aspect(ask, SEVEN)
    return o.endpoint_for(ask.verb), body


async def grok_video_fal(ask: Ask, o: Offer, send: Send) -> tuple[str, dict[str, Any]]:
    body: dict[str, Any] = {
        "prompt": ask.prompt, "duration": seconds_in(ask, 1, 15, 6), "resolution": "720p",
    }  # fmt: skip
    if ask.verb == "animate":
        body["image_url"] = await _first(send, ask)
    elif ask.verb == "extend":
        raise _bad("Grok Imagine Video does not extend a clip.")
    else:
        body["aspect_ratio"] = aspect(ask, ("16:9", "4:3", "3:2", "1:1", "2:3", "3:4", "9:16"))
    return o.endpoint_for(ask.verb), body


RECIPES: dict[tuple[str, str], Recipe] = {
    ("wavespeed", "gpt-image-2.5"): gpt_image_wavespeed,
    ("fal", "gpt-image-2.5"): gpt_image_fal,
    ("runware", "nano-banana-2.1"): runware_image(14),
    ("wavespeed", "nano-banana-2.1"): nano_banana_wavespeed,
    ("runware", "grok-imagine-image-2.0"): runware_image(5, "medium"),
    ("fal", "grok-imagine-image-2.0"): grok_image_fal,
    ("runware", "flux-3-klein"): runware_image(4),
    ("fal", "flux-3-klein"): klein_fal,
    ("runware", "z-image-turbo"): runware_image(0),
    ("fal", "z-image-turbo"): z_image_fal,
    ("runware", "gemini-omni-flash-1.2"): runware_video(3, 15, "720p", ""),
    ("wavespeed", "gemini-omni-flash-1.2"): omni_wavespeed,
    ("runware", "seedance-2.5"): runware_video(4, 30, "720p", "extend"),
    ("wavespeed", "seedance-2.5"): seedance_wavespeed,
    ("runware", "minimax-h3-max"): runware_video(5, 15, "768p"),
    ("fal", "minimax-h3-max"): h3_fal,
    ("runware", "minimax-h3-max-turbo"): runware_video(5, 15, "768p"),
    ("fal", "minimax-h3-max-turbo"): h3_fal,
    ("runware", "grok-imagine-video-1.5-lite"): runware_video(1, 15, "720p"),
    ("fal", "grok-imagine-video-1.5-lite"): grok_video_fal,
}
