"""Multimodal prompt parts. A prompt is a string, or a list mixing strings, `Image` and `Audio`.

    prompt = ["What is in this picture, and what is said?", Image.from_bytes(png, "image/png"),
              Audio.from_bytes(wav, "wav")]
    text = await caps.text.complete("multimodal", system, prompt)

Files belong in object storage, never in graph state (rules 7, 10): graphs keep a storage key,
load the bytes with `caps.storage.get(key)` and build the part at call time.
"""

import base64
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_AUDIO_BYTES = 25 * 1024 * 1024
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")
AUDIO_FORMATS = ("wav", "mp3")

Modality = Literal["text", "image", "audio"]


class InvalidInput(ValueError):
    """A part is too large, or of a type we do not accept."""


class UnsupportedInput(ValueError):
    """The capability's model is not configured to accept this modality."""


@dataclass(frozen=True)
class Image:
    media_type: str
    data: bytes | None = None
    url: str | None = None  # http(s) or data: URL, passed through to the gateway

    @classmethod
    def from_bytes(cls, data: bytes, media_type: str) -> "Image":
        if media_type not in IMAGE_TYPES:
            raise InvalidInput(f"image type {media_type!r} not accepted; use one of {IMAGE_TYPES}")
        if len(data) > MAX_IMAGE_BYTES:
            raise InvalidInput(f"image is {len(data)} bytes; the limit is {MAX_IMAGE_BYTES}")
        return cls(media_type=media_type, data=data)

    @classmethod
    def from_url(cls, url: str, media_type: str = "image/png") -> "Image":
        if not url.startswith(("http://", "https://", "data:")):
            raise InvalidInput("image url must be http(s) or a data: URL")
        return cls(media_type=media_type, url=url)


@dataclass(frozen=True)
class Audio:
    format: str  # "wav" or "mp3"
    data: bytes

    @classmethod
    def from_bytes(cls, data: bytes, format: str) -> "Audio":  # noqa: A002
        if format not in AUDIO_FORMATS:
            raise InvalidInput(f"audio format {format!r} not accepted; use one of {AUDIO_FORMATS}")
        if len(data) > MAX_AUDIO_BYTES:
            raise InvalidInput(f"audio is {len(data)} bytes; the limit is {MAX_AUDIO_BYTES}")
        return cls(format=format, data=data)


Part = str | Image | Audio
Prompt = str | Sequence[Part]

_EXTENSIONS: dict[str, tuple[str, str]] = {
    "png": ("image", "image/png"),
    "jpg": ("image", "image/jpeg"),
    "jpeg": ("image", "image/jpeg"),
    "webp": ("image", "image/webp"),
    "gif": ("image", "image/gif"),
    "wav": ("audio", "wav"),
    "mp3": ("audio", "mp3"),
}


def part_from_file(name: str, data: bytes) -> Image | Audio:
    """Build a part from a stored file, using its extension to pick the type."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in _EXTENSIONS:
        raise InvalidInput(
            f"cannot tell the media type of {name!r}; supported: {sorted(_EXTENSIONS)}"
        )
    kind, detail = _EXTENSIONS[ext]
    return Image.from_bytes(data, detail) if kind == "image" else Audio.from_bytes(data, detail)


def as_parts(prompt: Prompt) -> list[Part]:
    return [prompt] if isinstance(prompt, str) else list(prompt)


def modalities(prompt: Prompt) -> set[Modality]:
    found: set[Modality] = {"text"}
    for p in as_parts(prompt):
        if isinstance(p, Image):
            found.add("image")
        elif isinstance(p, Audio):
            found.add("audio")
    return found


def counts(prompt: Prompt) -> dict[str, int]:
    parts = as_parts(prompt)
    return {
        "images": sum(isinstance(p, Image) for p in parts),
        "audio": sum(isinstance(p, Audio) for p in parts),
    }


def to_openai_content(prompt: Prompt) -> str | list[dict[str, Any]]:
    """OpenAI-style message content. Plain strings stay plain for maximum compatibility."""
    if isinstance(prompt, str):
        return prompt
    out: list[dict[str, Any]] = []
    for p in prompt:
        if isinstance(p, str):
            out.append({"type": "text", "text": p})
        elif isinstance(p, Image):
            url = p.url or f"data:{p.media_type};base64,{base64.b64encode(p.data or b'').decode()}"
            out.append({"type": "image_url", "image_url": {"url": url}})
        else:
            out.append(
                {
                    "type": "input_audio",
                    "input_audio": {"data": base64.b64encode(p.data).decode(), "format": p.format},
                }
            )
    return out
