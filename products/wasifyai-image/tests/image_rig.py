"""Test helpers for the image product: a rig of scripted fake models and an in-memory queue."""

import io
import json
from pathlib import Path

import yaml
from PIL import Image
from wasifyai_platform_sdk import (
    InMemoryJobSink,
    InMemoryUploadStore,
    InMemoryUsageRecorder,
    ProviderDeps,
    RunContext,
    ScopedStorage,
    build_capabilities,
    load_product_config,
    memory_storage,
    new_upload,
)

CTX = RunContext(
    tenant_id="t1", product_id="wasifyai-image", user_id="u1", run_id="run-1", thread_id="th-1"
)


def verdict(allowed=True, category="ok", reason="") -> str:
    return json.dumps({"allowed": allowed, "category": category, "reason": reason})


def png(size=(640, 480), colour=(30, 120, 200)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, "PNG")
    return out.getvalue()


def mask_png(size=(640, 480), box=(100, 100, 300, 250)) -> bytes:
    """A painted area: white inside `box` (None: nothing painted), black elsewhere."""
    out = io.BytesIO()
    mask = Image.new("L", size, 0)
    if box:
        mask.paste(255, box)
    mask.save(out, "PNG")
    return out.getvalue()


class Rig:
    def __init__(self, caps, sink, usage, raw, uploads):
        self.caps, self.sink, self.usage, self.raw, self.uploads = caps, sink, usage, raw, uploads

    def asked(self) -> list:
        """Everything the text models were asked, in order. (One fake text provider serves every
        text capability, so this is the words check and the picture check together.)"""
        return self.caps.text._bound["moderate"][1].prompts

    def word_checks(self) -> list:
        """The requests the text moderator saw: plain strings with a <request>."""
        return [p for p in self.asked() if isinstance(p, str) and "<request>" in p]

    def picture_checks(self) -> list:
        """The requests the picture model saw: a list with the instruction and the picture."""
        return [p for p in self.asked() if not isinstance(p, str)]


def make_rig(
    tmp_path: Path, moderate=None, moderate_image=None, quotas=None, enhance=None, describe=None
):
    """Capabilities for a throwaway `wasifyai-image` product with scripted replies."""
    d = tmp_path / "wasifyai-image"
    d.mkdir(parents=True, exist_ok=True)
    (d / "product.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "wasifyai-image",
                "capabilities": {
                    "text.moderate": {
                        "provider": "fake",
                        "defaults": {"replies": moderate or [verdict()]},
                    },
                    "text.moderate_image": {
                        "provider": "fake",
                        "defaults": {"replies": moderate_image or [verdict()]},
                        "inputs": ["text", "image"],
                    },
                    "text.enhance": {
                        "provider": "fake",
                        "defaults": {"replies": enhance or ["A tidy prompt."]},
                    },
                    "text.describe_image": {
                        "provider": "fake",
                        "defaults": {"replies": describe or ["A blue square."]},
                        "inputs": ["text", "image"],
                    },
                    "image.generate": {"provider": "fake"},
                    "image.edit": {"provider": "fake"},
                    "image.reference": {"provider": "fake"},
                    "image.inpaint": {"provider": "fake"},
                },
                "quotas": quotas if quotas is not None else {"images_per_user_per_day": 20},
                "uploads": {"image": {}},
                "enhance": {
                    "text_to_image": {"prompt": "enhance_text_to_image", "max_chars": 500},
                    "edit_image": {
                        "prompt": "enhance_edit_image",
                        "max_chars": 500,
                        "needs_picture": True,
                    },
                },
            }
        )
    )
    usage, sink, raw = InMemoryUsageRecorder(), InMemoryJobSink(), memory_storage()
    deps = ProviderDeps(tmp_path, usage=usage, job_sink=sink, storage=ScopedStorage(raw))
    caps = build_capabilities(load_product_config(tmp_path, "wasifyai-image", environ={}), deps)
    return Rig(caps, sink, usage, raw, InMemoryUploadStore())


async def put_upload(rig: Rig, user_id: str = "u1", data: bytes | None = None):
    """A picture the user has uploaded: the file under their prefix and its record."""
    record = new_upload("t1", "wasifyai-image", user_id, 10)
    await rig.caps.storage.put_for(record.owner, record.key, data or png(), "image/png")  # type: ignore[union-attr]
    await rig.uploads.add(record)
    return record
