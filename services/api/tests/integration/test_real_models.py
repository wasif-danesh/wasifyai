"""The product's real workflows on a real ComfyUI: ACE-Step 1.5 for the music, FLUX.2 [klein] 4B
for the cover. Opt-in and slow (`make test-comfyui`): it needs ComfyUI on :8188 with the models
installed, and uses the same worker code path as production (JobProcessor + ComfyRunner).

It checks what came out, not just that something did: audio length and codec with ffprobe, and
that the cover is a real 1024x1024 picture."""

import json
import os
import shutil
import struct
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from uuid import uuid4

import pytest
from wasifyai_media_worker.comfy import ComfyClient
from wasifyai_media_worker.gpu import LocalGpuLock
from wasifyai_media_worker.processor import ComfyRunner, JobProcessor
from wasifyai_media_worker.settings import WorkerSettings
from wasifyai_media_worker.state import InMemoryJobState
from wasifyai_platform_sdk import (
    InMemoryEventLog,
    InMemoryJobSink,
    InMemoryUsageRecorder,
    ProviderDeps,
    RunContext,
    build_capabilities,
    load_product_config,
    memory_storage,
    object_key,
    set_context,
)

from .conftest import PRODUCTS_DIR

COMFY = os.environ.get("COMFYUI_URL", "http://localhost:8188")
LYRICS = (
    "[verse]\nRain on the window, the city is slow\nI hum a small tune that I used to know\n"
    "Streetlights are blinking in puddles below\nTomorrow is waiting, but I let it go\n\n"
    "[chorus]\nSing it out loud, sing it out loud\nLet the night carry us out of the crowd\n"
    "Sing it out loud, sing it out loud\nWe are the echo, we are the sound"
)


def installed(node: str, field: str) -> list[str]:
    try:
        info = json.load(urllib.request.urlopen(f"{COMFY}/object_info/{node}", timeout=3))
        return info[node]["input"]["required"][field][0]
    except Exception:
        return []


INSTALLED = {
    "ace_step_1.5_turbo_aio.safetensors": installed("CheckpointLoaderSimple", "ckpt_name"),
    "flux-2-klein-4b.safetensors": installed("UNETLoader", "unet_name"),
    "flux2-vae.safetensors": installed("VAELoader", "vae_name"),
}


def needs(*models: str) -> pytest.MarkDecorator:
    """Skip unless this is an opt-in run and ComfyUI has these models installed."""
    missing = [m for m in models if m not in INSTALLED[m]]
    return pytest.mark.skipif(
        os.environ.get("COMFYUI_E2E") != "1" or bool(missing),
        reason=f"opt-in: `make test-comfyui` with ComfyUI and the models (missing: {missing})",
    )


need_ffprobe = pytest.mark.skipif(
    shutil.which("ffprobe") is None, reason="ffprobe inspects the audio"
)


def keep(name: str, data: bytes) -> None:
    """Set COMFYUI_SAVE_DIR to keep what the models made, for looking at and listening to."""
    if folder := os.environ.get("COMFYUI_SAVE_DIR"):
        Path(folder).mkdir(parents=True, exist_ok=True)
        (Path(folder) / name).write_bytes(data)


def probe(data: bytes, suffix: str) -> dict:
    with tempfile.NamedTemporaryFile(suffix=suffix) as f:
        f.write(data)
        f.flush()
        out = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries",
                "format=duration,format_name:stream=codec_name,sample_rate,channels",
                "-of", "json", f.name,
            ],
            capture_output=True, text=True, check=True,
        )  # fmt: skip
    return json.loads(out.stdout)


@pytest.fixture
async def worker():
    set_context(RunContext("real", "wasifyai-music", "u1", str(uuid4()), str(uuid4())))
    sink, storage = InMemoryJobSink(), memory_storage()
    config = load_product_config(PRODUCTS_DIR, "wasifyai-music", environ={})
    caps = build_capabilities(
        config, ProviderDeps(PRODUCTS_DIR, usage=InMemoryUsageRecorder(), job_sink=sink)
    )
    client = ComfyClient(COMFY)
    processor = JobProcessor(
        WorkerSettings(ollama_base_url="", job_timeout_s=900),
        InMemoryEventLog(), storage, InMemoryUsageRecorder(),
        ComfyRunner(client, 900), LocalGpuLock(), InMemoryJobState(),
    )  # fmt: skip
    yield caps, sink, storage, processor
    await client.aclose()


@needs("ace_step_1.5_turbo_aio.safetensors")
@need_ffprobe
async def test_ace_step_makes_a_song_of_the_requested_length(worker):
    caps, sink, storage, processor = worker
    await caps.music.generate(
        lyrics=LYRICS, style="indie pop, mellow, female vocal, 100 bpm", seed=7, duration_s=20
    )
    result = await processor.process(sink.submitted[-1])

    assert result.status == "completed", result.error
    out = result.outputs["audio"]
    assert out.content_type == "audio/mpeg" and out.key.endswith("/audio.mp3")
    audio = await storage.get(object_key("real", "wasifyai-music", "u1", out.key))
    keep("song.mp3", audio)
    info = probe(audio, ".mp3")
    assert info["streams"][0]["codec_name"] == "mp3"
    assert 18 <= float(info["format"]["duration"]) <= 23, info  # asked for 20 s
    assert len(audio) > 100_000  # not a stub
    assert result.gpu_seconds > 0


@needs("flux-2-klein-4b.safetensors", "flux2-vae.safetensors")
async def test_flux2_klein_paints_a_1024_cover(worker):
    caps, sink, storage, processor = worker
    await caps.image.generate(
        prompt="A rainy city window at night, glowing streetlights, teal and amber, no text",
        seed=3,
    )
    result = await processor.process(sink.submitted[-1])

    assert result.status == "completed", result.error
    out = result.outputs["image"]
    png = await storage.get(object_key("real", "wasifyai-music", "u1", out.key))
    keep("cover.png", png)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (1024, 1024)
    assert len(png) > 200_000  # a detailed picture, not a flat colour
