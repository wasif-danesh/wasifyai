"""Test helpers for the lip sync product: a rig of scripted fake models and an in-memory queue."""

import io
import json
import subprocess
import tempfile
import wave
from pathlib import Path

import yaml
from PIL import Image
from wasifyai_lipsync.lipsyncs import ffmpeg_path
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
    tenant_id="t1", product_id="wasifyai-lipsync", user_id="u1", run_id="run-1", thread_id="th-1"
)


def verdict(allowed=True, category="ok", reason="") -> str:
    return json.dumps({"allowed": allowed, "category": category, "reason": reason})


def png(size=(640, 480), colour=(30, 120, 200)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, "PNG")
    return out.getvalue()


def wav(seconds: float = 3.0, rate: int = 16000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return out.getvalue()


def mp4(size=(128, 96), frames=12) -> bytes:
    """A real tiny H.264 clip, made with the same ffmpeg the product uses for posters."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "clip.mp4"
        subprocess.run(
            [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
             f"testsrc=size={size[0]}x{size[1]}:rate=25", "-frames:v", str(frames),
             "-pix_fmt", "yuv420p", str(out)],
            check=True,
        )  # fmt: skip
        return out.read_bytes()


def transcript(text: str) -> bytes:
    return json.dumps({"text": text, "language": "en", "segments": []}).encode()


class Rig:
    def __init__(self, caps, sink, usage, raw, uploads):
        self.caps, self.sink, self.usage, self.raw, self.uploads = caps, sink, usage, raw, uploads

    def asked(self) -> list:
        return self.caps.text._bound["moderate"][1].prompts

    def word_checks(self) -> list:
        return [p for p in self.asked() if isinstance(p, str) and "<request>" in p]

    def picture_checks(self) -> list:
        return [p for p in self.asked() if not isinstance(p, str)]

    def switch(self, on: bool) -> None:
        """The safeguards switch (ADR-0047)."""

        async def state() -> bool:
            return on

        self.caps.safeguards = state


def make_rig(tmp_path: Path, moderate=None, moderate_image=None, quotas=None):
    """Capabilities for a throwaway `wasifyai-lipsync` product with scripted replies."""
    d = tmp_path / "wasifyai-lipsync"
    d.mkdir(parents=True, exist_ok=True)
    (d / "product.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "wasifyai-lipsync",
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
                    "speech.synthesize": {"provider": "fake"},
                    "speech.transcribe": {"provider": "fake"},
                    "video.lipsync": {"provider": "fake"},
                },
                "quotas": quotas if quotas is not None else {"lipsyncs_per_user_per_day": 3},
                "uploads": {"image": {}, "audio": {"max_seconds": 15}},
            }
        )
    )
    usage, sink, raw = InMemoryUsageRecorder(), InMemoryJobSink(), memory_storage()
    deps = ProviderDeps(tmp_path, usage=usage, job_sink=sink, storage=ScopedStorage(raw))
    caps = build_capabilities(load_product_config(tmp_path, "wasifyai-lipsync", environ={}), deps)
    return Rig(caps, sink, usage, raw, InMemoryUploadStore())


async def put_image(rig: Rig, user_id: str = "u1"):
    """A picture the user has uploaded: the file under their prefix and its record."""
    record = new_upload("t1", "wasifyai-lipsync", user_id, 10)
    await rig.caps.storage.put_for(record.owner, record.key, png(), "image/png")  # type: ignore[union-attr]
    await rig.uploads.add(record)
    return record


async def put_voice(rig: Rig, seconds: float = 3.0, user_id: str = "u1"):
    """A voice the user has uploaded or recorded."""
    record = new_upload("t1", "wasifyai-lipsync", user_id, 10, kind="audio", seconds=seconds)
    await rig.caps.storage.put_for(record.owner, record.key, wav(seconds), "audio/wav")  # type: ignore[union-attr]
    await rig.uploads.add(record)
    return record
