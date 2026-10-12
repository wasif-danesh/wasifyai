"""Fixtures for the music product: capabilities built from a scripted fake provider, so graph
tests need no GPU, network or database."""

import json
from pathlib import Path

import pytest
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
    reset_context,
    set_context,
)

CTX = RunContext(
    tenant_id="t1", product_id="wasifyai-music", user_id="u1", run_id="run-1", thread_id="th-1"
)

GOOD_LYRICS = (
    "[verse]\nRain on the window, the city is slow\nI hum a small tune that I used to know\n"
    "Streetlights are blinking in puddles below\nTomorrow is waiting, but I let it go\n\n"
    "[chorus]\nSing it out loud, sing it out loud\nLet the night carry us out of the crowd\n"
    "Sing it out loud, sing it out loud\nWe are the echo, we are the sound\n\n"
    "[verse]\nCoffee gets cold on the edge of the sill\nThe radio whispers and time stands still\n"
    "Footsteps are fading, the street is a hill\nI follow the music, I always will"
)


def draft(**kw) -> str:
    d = {
        "title": "Sing It Out Loud",
        "lyrics": GOOD_LYRICS,
        "style": "indie pop, mellow, female vocal, 100 bpm",
        "cover_prompt": "A rainy city window at night with glowing streetlights, teal and amber",
    }
    d.update(kw)
    return json.dumps(d)


def verdict(allowed=True, category="ok", reason="") -> str:
    return json.dumps({"allowed": allowed, "category": category, "reason": reason})


class Rig:
    def __init__(self, caps, sink, usage, raw):
        self.caps, self.sink, self.usage, self.raw = caps, sink, usage, raw

    @property
    def llm_calls(self):
        """Prompts the fake text provider received, per capability."""
        out = {}
        for (cap, _), prov in self.caps.text._bound.items() if False else []:
            out[cap] = prov.prompts
        return out


def make_rig(tmp_path: Path, moderate=None, lyrics=None, quotas=None, music="fake", image="fake"):
    """Capabilities for a throwaway `wasifyai-music` product with scripted replies."""
    d = tmp_path / "wasifyai-music"
    d.mkdir(exist_ok=True)
    (d / "product.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "wasifyai-music",
                "capabilities": {
                    "text.moderate": {
                        "provider": "fake",
                        "defaults": {"replies": moderate or [verdict()]},
                    },
                    "text.lyrics": {
                        "provider": "fake",
                        "defaults": {"replies": lyrics or [draft()]},
                    },
                    "music.generate": {"provider": music},
                    "image.generate": {"provider": image},
                },
                "quotas": quotas if quotas is not None else {"songs_per_user_per_day": 10},
            }
        )
    )
    usage, sink, raw = InMemoryUsageRecorder(), InMemoryJobSink(), memory_storage()
    deps = ProviderDeps(tmp_path, usage=usage, job_sink=sink, storage=ScopedStorage(raw))
    caps = build_capabilities(load_product_config(tmp_path, "wasifyai-music", environ={}), deps)
    return Rig(caps, sink, usage, raw)


@pytest.fixture
def ctx():
    token = set_context(CTX)
    yield CTX
    reset_context(token)
