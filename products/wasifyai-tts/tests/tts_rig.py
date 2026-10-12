"""Test helpers for the text to speech product: scripted fake models and an in-memory queue."""

import io
import json
import wave
from pathlib import Path

import yaml
from wasifyai_platform_sdk import (
    InMemoryJobSink,
    InMemoryUsageRecorder,
    ProviderDeps,
    RunContext,
    ScopedStorage,
    build_capabilities,
    load_product_config,
    memory_storage,
)

CTX = RunContext(
    tenant_id="t1", product_id="wasifyai-tts", user_id="u1", run_id="run-1", thread_id="th-1"
)


def verdict(allowed=True, category="ok", reason="") -> str:
    return json.dumps({"allowed": allowed, "category": category, "reason": reason})


def wav(seconds: float = 1.0, rate: int = 24000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(rate * seconds))
    return out.getvalue()


class Rig:
    def __init__(self, caps, sink, usage, raw):
        self.caps, self.sink, self.usage, self.raw = caps, sink, usage, raw

    def moderator_calls(self) -> list:
        return self.caps.text._bound["moderate"][1].prompts


def make_rig(tmp_path: Path, moderate=None, quotas=None):
    """Capabilities for a throwaway `wasifyai-tts` product with scripted replies."""
    d = tmp_path / "wasifyai-tts"
    d.mkdir(parents=True, exist_ok=True)
    (d / "product.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "wasifyai-tts",
                "capabilities": {
                    "text.moderate": {
                        "provider": "fake",
                        "defaults": {"replies": moderate or [verdict()]},
                    },
                    "speech.synthesize": {"provider": "fake"},
                },
                "quotas": quotas if quotas is not None else {"speeches_per_user_per_day": 30},
            }
        )
    )
    usage, sink, raw = InMemoryUsageRecorder(), InMemoryJobSink(), memory_storage()
    deps = ProviderDeps(tmp_path, usage=usage, job_sink=sink, storage=ScopedStorage(raw))
    caps = build_capabilities(load_product_config(tmp_path, "wasifyai-tts", environ={}), deps)
    return Rig(caps, sink, usage, raw)
