import json
from pathlib import Path

import pytest
from wasifyai_platform_sdk import RunContext, reset_context, set_context

CTX = RunContext(tenant_id="t1", product_id="demo", user_id="u1", run_id="r1")


@pytest.fixture
def ctx():
    token = set_context(CTX)
    yield CTX
    reset_context(token)


@pytest.fixture
def products(tmp_path: Path) -> Path:
    """A throwaway products/ tree with one product, one ComfyUI workflow and its map."""
    d = tmp_path / "demo"
    (d / "workflows").mkdir(parents=True)
    (d / "product.yaml").write_text(
        """
id: demo
capabilities:
  text.chat:      { provider: fake, defaults: { reply: "hi there" } }
  text.embed:     { provider: fake }
  video.generate: { provider: comfyui, workflow: tiny, defaults: { duration_s: 60 } }
settings: { audio_format: mp3 }
"""
    )
    (d / "workflows" / "tiny.json").write_text(
        json.dumps(
            {
                "3": {"class_type": "KSampler", "inputs": {"seed": 0}},
                "14": {"class_type": "T", "inputs": {"lyrics": "", "seconds": 30}},
            }
        )
    )
    (d / "workflows" / "tiny.map.yaml").write_text(
        """
workflow: tiny.json
licence: test
inputs:
  lyrics:     { node: "14", field: lyrics }
  duration_s: { node: "14", field: seconds }
  seed:       { node: "3",  field: seed }
outputs:
  audio: { node: "14", type: audio }
"""
    )
    return tmp_path
