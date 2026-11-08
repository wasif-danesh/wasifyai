"""A picture adapter, checked and written where ComfyUI reads it (ADR-0059, ADR-0073).

AI Toolkit writes an adapter of FLUX.2 klein in the key names ComfyUI reads already
(`diffusion_model.double_blocks.0.img_attn.qkv.lora_A.weight`), so nothing is renamed: the file is
read, checked and written again with a note of what it was taught on. A tensor under another name,
or a layer with only half of its update, is an error, never passed on: ComfyUI would load part of
it and draw something else.

No tensor library is needed: a safetensors file is a JSON header and raw bytes."""

import json
import struct
from pathlib import Path
from typing import Any

OUT = "diffusion_model."
_HALVES = (".lora_A.weight", ".lora_B.weight")


class ConvertError(ValueError):
    """The adapter cannot be turned into a ComfyUI one, in words."""


def read_tensors(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """{name: {dtype, shape, data: bytes}} and the metadata of a safetensors file."""
    raw = path.read_bytes()
    (n,) = struct.unpack("<Q", raw[:8])
    head = json.loads(raw[8 : 8 + n])
    base = 8 + n
    meta = {str(k): str(v) for k, v in (head.pop("__metadata__", None) or {}).items()}
    out = {}
    for name, t in head.items():
        lo, hi = t["data_offsets"]
        out[name] = {
            "dtype": t["dtype"],
            "shape": list(t["shape"]),
            "data": raw[base + lo : base + hi],
        }
    return out, meta


def write_tensors(path: Path, tensors: dict[str, dict[str, Any]], meta: dict[str, str]) -> None:
    head: dict[str, Any] = {"__metadata__": meta}
    offset = 0
    for name, t in tensors.items():
        head[name] = {
            "dtype": t["dtype"],
            "shape": t["shape"],
            "data_offsets": [offset, offset + len(t["data"])],
        }
        offset += len(t["data"])
    blob = json.dumps(head, separators=(",", ":")).encode()
    blob += b" " * (-len(blob) % 8)  # the data starts on an 8-byte boundary
    with path.open("wb") as f:
        f.write(struct.pack("<Q", len(blob)) + blob)
        for t in tensors.values():
            f.write(t["data"])


def check_tensors(tensors: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The tensors of an adapter in ComfyUI's names, sorted; a `ConvertError` when one is not."""
    layers: dict[str, set[str]] = {}
    for name in tensors:
        if name.startswith(OUT) and name.endswith(".alpha"):
            continue
        if not name.startswith(OUT) or not name.endswith(_HALVES):
            raise ConvertError(f"This adapter has a tensor that ComfyUI would not read: {name}")
        module, _, half = name.rpartition(".lora_")
        layers.setdefault(module, set()).add(half[0])
    for module, halves in layers.items():
        if halves != {"A", "B"}:
            raise ConvertError(f"The layer {module} has only half of its update.")
    if not layers:
        raise ConvertError("This adapter has no layers.")
    return dict(sorted(tensors.items()))


def convert(src: Path, dst: Path, base: str = "flux2-klein-4b") -> dict[str, Any]:
    """Write `dst`, the adapter `src` taught on `base` as the image engine reads it; what was
    written, in numbers. A model with no recipe is an error: nothing says the names are right."""
    from wasifyai_training.picture_bases import picture_base

    try:
        picture_base(base)
    except KeyError:
        raise ConvertError(
            f"There is no way yet to make a style taught on {base} usable in Create."
        ) from None
    tensors, meta = read_tensors(src)
    out = check_tensors(tensors)
    meta = {**meta, "format": "pt", "converted_by": "wasifyai-training", "taught_on": base}
    tmp = dst.with_name(dst.name + ".part")
    write_tensors(tmp, out, meta)
    tmp.replace(dst)  # a half-written file is never seen by the image engine
    ranks = {t["shape"][0] for n, t in out.items() if n.endswith("lora_A.weight")}
    return {"tensors": len(out), "ranks": sorted(ranks), "bytes": dst.stat().st_size}
