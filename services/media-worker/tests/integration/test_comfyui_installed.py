"""The ComfyUI component the desktop app installs really starts and sees the machine's accelerator.

Skipped unless `WASIFYAI_COMFYUI_DATA_DIR` names an app data folder in which the component was
installed (the shell's "Set up image generation", or the `comfyui` CI job). No model is needed."""

import os
import sys
from pathlib import Path

import httpx
import pytest
from wasifyai_media_worker.sidecar import ComfySidecar, SidecarConfig

DATA = os.environ.get("WASIFYAI_COMFYUI_DATA_DIR", "")

pytestmark = pytest.mark.skipif(
    not DATA or sys.platform == "win32", reason="needs an installed ComfyUI component"
)


async def test_the_installed_sidecar_starts_answers_and_stops(tmp_path):
    data = Path(DATA)
    s = ComfySidecar(SidecarConfig(data, tmp_path / "models", startup_timeout_s=180))
    assert s.installed
    try:
        url = await s.ensure_running()
        async with httpx.AsyncClient(timeout=10) as http:
            stats = (await http.get(f"{url}/system_stats")).json()
        assert stats["system"]["comfyui_version"]
        devices = [d["type"] for d in stats["devices"]]
        assert devices, "ComfyUI reports no device"
        print("ComfyUI", stats["system"]["comfyui_version"], "devices:", devices)
        # no model files anywhere: the sidecar's own check says so rather than ComfyUI failing late
        assert s.missing_models({"1": {"inputs": {"unet_name": "nothing.safetensors"}}}) == [
            "nothing.safetensors"
        ]
    finally:
        await s.stop()
    assert not s.running
