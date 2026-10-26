"""A video-model adapter (LTX-Video 2B) in the key names ComfyUI reads (ADR-0073, video amendment).

`peft` and `diffusers` name a layer by its place in the model with a `transformer.` prefix
(`transformer.transformer_blocks.0.attn1.to_q.lora_A.weight`); ComfyUI's LTXV loader has no such
prefix in its key map (`transformer_blocks.0.attn1.to_q.lora_A.weight`), and a file that carries it
loads without a word and **does nothing** (spike TV0: every tensor "lora key not loaded"). So the
conversion is one rename of each key. Nothing is learnt again here: numbers are moved. A layer this
module does not know is an error, never dropped: a half-converted adapter would draw something else.
Like `comfy_lora` it needs no tensor library."""

import re
from pathlib import Path
from typing import Any

from wasifyai_training.comfy_lora import read_tensors, write_tensors

PREFIX = "transformer."
_LAYER = re.compile(
    r"^transformer_blocks\.(\d+)\.(attn1|attn2)\.(to_q|to_k|to_v|to_out\.0)\.lora_([AB])\.weight$"
)


class ConvertError(ValueError):
    """The adapter cannot be turned into a ComfyUI one, in words."""


def convert_tensors(tensors: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The tensors of a video adapter, under ComfyUI's names (every one of them a rename)."""
    out: dict[str, dict[str, Any]] = {}
    for name, t in tensors.items():
        key = name[len(PREFIX) :] if name.startswith(PREFIX) else name
        if not _LAYER.match(key):
            raise ConvertError(f"This adapter has a tensor that is not a known LoRA weight: {name}")
        out[key] = t
    layers: dict[str, set[str]] = {}
    for key in out:
        m = _LAYER.match(key)
        assert m is not None
        layers.setdefault(key[: key.rindex(".lora_")], set()).add(m.group(4))
    for layer, parts in layers.items():
        if parts != {"A", "B"}:
            raise ConvertError(f"The layer {layer} has only half of its update.")
    return dict(sorted(out.items()))


def convert(src: Path, dst: Path, base: str = "ltx-video-2b-0.9.5") -> dict[str, Any]:
    """Write `dst`, the ComfyUI version of the adapter `src`; what was written, in numbers."""
    tensors, meta = read_tensors(src)
    out = convert_tensors(tensors)
    meta = {**meta, "format": "pt", "converted_by": "wasifyai-training", "taught_on": base}
    tmp = dst.with_name(dst.name + ".part")
    write_tensors(tmp, out, meta)
    tmp.replace(dst)  # a half-written file is never seen by the video engine
    ranks = {t["shape"][0] for n, t in out.items() if n.endswith("lora_A.weight")}
    return {"tensors": len(out), "ranks": sorted(ranks), "bytes": dst.stat().st_size}
