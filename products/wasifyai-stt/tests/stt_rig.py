"""Test helpers for the speech to text product: fake capabilities, a queue and uploads."""

import io
import wave
from pathlib import Path

import yaml
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
    tenant_id="t1", product_id="wasifyai-stt", user_id="u1", run_id="run-1", thread_id="th-1"
)


def wav(seconds: float = 2.0, rate: int = 16000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(rate * seconds))
    return out.getvalue()


class Rig:
    def __init__(self, caps, sink, usage, raw, uploads):
        self.caps, self.sink, self.usage, self.raw, self.uploads = caps, sink, usage, raw, uploads

    async def add_recording(self, seconds: float = 120.0, kind: str = "audio") -> str:
        """Put a cleaned recording where the upload endpoint would, and return its key."""
        record = new_upload("t1", "wasifyai-stt", "u1", 1000, kind, seconds)
        await ScopedStorage(self.raw).put_for(record.owner, record.key, wav(1.0), "audio/wav")
        await self.uploads.add(record)
        return record.key


def make_rig(tmp_path: Path, quotas=None):
    """Capabilities for a throwaway `wasifyai-stt` product."""
    d = tmp_path / "wasifyai-stt"
    d.mkdir(parents=True, exist_ok=True)
    (d / "product.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "wasifyai-stt",
                "capabilities": {"speech.transcribe": {"provider": "fake"}},
                "quotas": quotas if quotas is not None else {"minutes_per_user_per_day": 120},
            }
        )
    )
    usage, sink, raw = InMemoryUsageRecorder(), InMemoryJobSink(), memory_storage()
    deps = ProviderDeps(tmp_path, usage=usage, job_sink=sink, storage=ScopedStorage(raw))
    caps = build_capabilities(load_product_config(tmp_path, "wasifyai-stt", environ={}), deps)
    return Rig(caps, sink, usage, raw, InMemoryUploadStore())
