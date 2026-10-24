"""An mflux adapter of FLUX.2 klein, in the key names ComfyUI reads (ADR-0059, ADR-0073).

mflux names a layer by its place in the diffusers model
(`transformer.transformer_blocks.0.attn.to_q`) and trains the three projections of attention
apart. ComfyUI's klein has the original layout: one fused `qkv` per double block, one fused
`linear1` and `linear2` per single block, named `diffusion_model.double_blocks.0.img_attn.qkv`.
Nothing is learnt again here: numbers are moved.

    to_q, to_k, to_v -> img_attn.qkv   A: the three A stacked (3r by in); B: the three B on a
                                       diagonal (3h by 3r), so B_fused A_fused is the three updates
                                       one over the other
    attn.to_out      -> img_attn.proj
    ff.linear_in     -> img_mlp.0
    ff.linear_out    -> img_mlp.2
    single attn.to_qkv_mlp_proj -> linear1,  single attn.to_out -> linear2

The text stream (`txt_*`) is not trained by mflux's recipe, so nothing is written for it. A layer
this module does not know is an error, never dropped: a half-converted adapter would draw
something else.
No tensor library is needed: a safetensors file is a JSON header and raw bytes, and every step here
is a rename, a concatenation or a zero fill, so the dtype does not matter."""

import json
import re
import struct
from pathlib import Path
from typing import Any

SIZE = {"F32": 4, "F16": 2, "BF16": 2, "F64": 8}
PREFIX = "transformer."
OUT = "diffusion_model."

_DOUBLE = re.compile(
    r"^transformer_blocks\.(\d+)\.(attn\.to_[qkv]|attn\.to_out|ff\.linear_in|ff\.linear_out)$"
)
_SINGLE = re.compile(r"^single_transformer_blocks\.(\d+)\.attn\.(to_qkv_mlp_proj|to_out)$")
_RENAME = {
    "attn.to_out": "img_attn.proj",
    "ff.linear_in": "img_mlp.0",
    "ff.linear_out": "img_mlp.2",
}
_SINGLE_RENAME = {"to_qkv_mlp_proj": "linear1", "to_out": "linear2"}


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


def _fuse_qkv(parts: dict[str, dict[str, dict[str, Any]]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The fused A and B of one block from its q, k and v (each {"A": tensor, "B": tensor})."""
    present = [p for p in ("q", "k", "v") if p in parts]
    first = parts[present[0]]
    rank, inp = first["A"]["shape"]
    out_dim = first["B"]["shape"][0]
    dtype = first["A"]["dtype"]
    item = SIZE[dtype]
    a_rows = bytearray()
    for p in ("q", "k", "v"):
        if p in parts:
            a, b = parts[p]["A"], parts[p]["B"]
            if a["shape"] != [rank, inp] or b["shape"] != [out_dim, rank] or a["dtype"] != dtype:
                raise ConvertError("The three parts of an attention layer do not agree in shape.")
            a_rows += a["data"]
        else:
            a_rows += bytes(rank * inp * item)  # a part that was not trained: no update
    b_rows = bytearray()
    for index, p in enumerate(("q", "k", "v")):
        for row in range(out_dim):
            line = bytearray(3 * rank * item)
            if p in parts:
                data = parts[p]["B"]["data"]
                start = row * rank * item
                line[index * rank * item : (index + 1) * rank * item] = data[
                    start : start + rank * item
                ]
            b_rows += line
    return (
        {"dtype": dtype, "shape": [3 * rank, inp], "data": bytes(a_rows)},
        {"dtype": dtype, "shape": [3 * out_dim, 3 * rank], "data": bytes(b_rows)},
    )


def convert_tensors(tensors: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The tensors of an mflux klein adapter, under ComfyUI's names."""
    layers: dict[str, dict[str, dict[str, Any]]] = {}
    for name, t in tensors.items():
        if not name.startswith(PREFIX) or not name.endswith((".lora_A.weight", ".lora_B.weight")):
            raise ConvertError(f"This adapter has a tensor that is not a LoRA weight: {name}")
        module, _, tail = name[len(PREFIX) :].rpartition(".lora_")
        layers.setdefault(module, {})[tail[0]] = t  # "A" or "B"
    out: dict[str, dict[str, Any]] = {}
    qkv: dict[int, dict[str, dict[str, dict[str, Any]]]] = {}
    for module, ab in layers.items():
        if set(ab) != {"A", "B"}:
            raise ConvertError(f"The layer {module} has only half of its update.")
        double, single = _DOUBLE.match(module), _SINGLE.match(module)
        if double:
            block, what = int(double.group(1)), double.group(2)
            if what.startswith("attn.to_") and what != "attn.to_out":
                qkv.setdefault(block, {})[what[-1]] = ab
                continue
            key = f"{OUT}double_blocks.{block}.{_RENAME[what]}"
        elif single:
            key = f"{OUT}single_blocks.{single.group(1)}.{_SINGLE_RENAME[single.group(2)]}"
        else:
            raise ConvertError(f"This adapter has a layer that is not known here: {module}")
        out[f"{key}.lora_A.weight"], out[f"{key}.lora_B.weight"] = ab["A"], ab["B"]
    for block, parts in qkv.items():
        a, b = _fuse_qkv(parts)
        key = f"{OUT}double_blocks.{block}.img_attn.qkv"
        out[f"{key}.lora_A.weight"], out[f"{key}.lora_B.weight"] = a, b
    return dict(sorted(out.items()))


def convert(src: Path, dst: Path, base: str = "flux2-klein-base-4b") -> dict[str, Any]:
    """Write `dst`, the ComfyUI version of the adapter `src`; what was written, in numbers."""
    tensors, meta = read_tensors(src)
    out = convert_tensors(tensors)
    meta = {**meta, "format": "pt", "converted_by": "wasifyai-training", "taught_on": base}
    tmp = dst.with_name(dst.name + ".part")
    write_tensors(tmp, out, meta)
    tmp.replace(dst)  # a half-written file is never seen by the image engine
    ranks = {t["shape"][0] for n, t in out.items() if n.endswith("lora_A.weight")}
    return {"tensors": len(out), "ranks": sorted(ranks), "bytes": dst.stat().st_size}
