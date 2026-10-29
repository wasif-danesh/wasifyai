"""Test helpers for the video product: a rig of scripted fake models and an in-memory queue."""

import io
import re
import subprocess
import tempfile
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
from wasifyai_video.videos import ffmpeg_path

CTX = RunContext(
    tenant_id="t1", product_id="wasifyai-video", user_id="u1", run_id="run-1", thread_id="th-1"
)


def png(size=(640, 480), colour=(30, 120, 200)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, "PNG")
    return out.getvalue()


def mp4(size=(128, 96), frames=12) -> bytes:
    """A real tiny H.264 clip, made with the same ffmpeg the product uses for posters."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "clip.mp4"
        subprocess.run(
            [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
             f"testsrc=size={size[0]}x{size[1]}:rate=24", "-frames:v", str(frames),
             "-pix_fmt", "yuv420p", str(out)],
            check=True,
        )  # fmt: skip
        return out.read_bytes()


def frame_count(clip: bytes) -> int:
    """How many frames a clip has, as ffmpeg decodes them."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "clip.mp4"
        src.write_bytes(clip)
        report = subprocess.run(
            [ffmpeg_path(), "-hide_banner", "-i", str(src), "-f", "null", "-"],
            capture_output=True, text=True, check=True,
        ).stderr  # fmt: skip
    return int(re.findall(r"frame=\s*(\d+)", report)[-1])


class Rig:
    def __init__(self, caps, sink, usage, raw, uploads):
        self.caps, self.sink, self.usage, self.raw, self.uploads = caps, sink, usage, raw, uploads

    def asked(self) -> list:
        """Everything the text models were asked, in order (one fake provider serves them all)."""
        return self.caps.text._bound["enhance"][1].prompts

    def pictures(self) -> list:
        """What the models were shown with a picture: the instruction and the picture."""
        return [p for p in self.asked() if not isinstance(p, str)]


def make_rig(tmp_path: Path, enhance=None, describe=None):
    """Capabilities for a throwaway `wasifyai-video` product with scripted replies."""
    d = tmp_path / "wasifyai-video"
    d.mkdir(parents=True, exist_ok=True)
    (d / "product.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "wasifyai-video",
                "capabilities": {
                    "text.enhance": {
                        "provider": "fake",
                        "defaults": {"replies": enhance or ["A tidy prompt."]},
                    },
                    "text.describe_image": {
                        "provider": "fake",
                        "defaults": {"replies": describe or ["A blue square."]},
                        "inputs": ["text", "image"],
                    },
                    "video.generate": {"provider": "fake"},
                    "video.animate": {"provider": "fake"},
                    "video.extend": {"provider": "fake"},
                },
                "uploads": {"image": {}},
                "enhance": {
                    "text_to_video": {"prompt": "enhance_text_to_video", "max_chars": 500},
                    "image_to_video": {
                        "prompt": "enhance_image_to_video",
                        "max_chars": 500,
                        "needs_picture": True,
                    },
                },
            }
        )
    )
    usage, sink, raw = InMemoryUsageRecorder(), InMemoryJobSink(), memory_storage()
    deps = ProviderDeps(tmp_path, usage=usage, job_sink=sink, storage=ScopedStorage(raw))
    caps = build_capabilities(load_product_config(tmp_path, "wasifyai-video", environ={}), deps)
    return Rig(caps, sink, usage, raw, InMemoryUploadStore())


async def put_upload(rig: Rig, user_id: str = "u1", data: bytes | None = None):
    """A picture the user has uploaded: the file under their prefix and its record."""
    record = new_upload("t1", "wasifyai-video", user_id, 10)
    await rig.caps.storage.put_for(record.owner, record.key, data or png(), "image/png")  # type: ignore[union-attr]
    await rig.uploads.add(record)
    return record
