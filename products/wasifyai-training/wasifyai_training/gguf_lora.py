"""An `mlx-lm` adapter as a GGUF LoRA, the file `llama-server --lora` loads (ADR-0074 decision 6).

The writing trainer leaves `adapters.safetensors`: for every projection of every layer a
`lora_a` (in by rank) and a `lora_b` (rank by out). llama.cpp wants the PEFT layout, `lora_A`
(rank by in) and `lora_B` (out by rank), under its own tensor names, with the scale as
`adapter.lora.alpha` (`alpha / rank`; mlx-lm's `scale` times the rank). Nothing is learnt here:
numbers are moved, so the file is written by hand (a GGUF file is a header, a list of key values,
a list of tensor infos and the aligned data) and no tensor library is needed. The result was
checked against llama.cpp's own converter on the spike's adapter (the same tensors, to
half-precision rounding) and by serving it.

Only the architectures listed are converted (Qwen3: the layout is the same as Hugging Face's, with
no permutation of the query and key weights). Any other architecture is an error, never a guess: a
half-converted adapter would answer as something else."""

import json
import struct
from array import array
from pathlib import Path
from typing import Any

from wasifyai_training.comfy_lora import read_tensors

GGUF_VERSION = 3
ALIGN = 32
T_F32 = 0
KV_UINT32, KV_FLOAT32, KV_STRING = 4, 6, 8

# the architectures llama.cpp names and the tensors of one layer, by the projection mlx-lm trained
QWEN3 = {
    "self_attn.q_proj": "attn_q",
    "self_attn.k_proj": "attn_k",
    "self_attn.v_proj": "attn_v",
    "self_attn.o_proj": "attn_output",
    "mlp.gate_proj": "ffn_gate",
    "mlp.up_proj": "ffn_up",
    "mlp.down_proj": "ffn_down",
}
ARCHITECTURES = {"qwen3": QWEN3}


class ConvertError(ValueError):
    """The adapter cannot be turned into a GGUF LoRA, in words."""


def _as_f32(data: bytes, dtype: str) -> array:
    out = array("f")
    if dtype == "F32":
        out.frombytes(data)
    elif dtype == "F16":
        out.extend(struct.unpack(f"<{len(data) // 2}e", data))
    elif dtype == "BF16":
        wide = array("I", (v << 16 for v in array("H", data)))
        out.frombytes(wide.tobytes())
    else:
        raise ConvertError(f"This adapter holds numbers of a kind that is not handled: {dtype}.")
    return out


def _transposed(values: array, rows: int, cols: int) -> array:
    """`values` as a rows by cols matrix, row by row, made cols by rows (a step slice a column)."""
    out = array("f")
    for column in range(cols):
        out.extend(values[column::cols])
    return out


def _string(text: str) -> bytes:
    raw = text.encode()
    return struct.pack("<Q", len(raw)) + raw


def _kv(key: str, kind: int, value: Any) -> bytes:
    head = _string(key) + struct.pack("<I", kind)
    if kind == KV_STRING:
        return head + _string(value)
    return head + struct.pack("<f" if kind == KV_FLOAT32 else "<I", value)


def _pad(size: int) -> int:
    return -size % ALIGN


def layout(names: list[str], table: dict[str, str]) -> dict[str, tuple[str, str, int]]:
    """The mlx-lm tensor names, mapped: `{mlx name: (gguf name, "a" or "b", layer)}`."""
    out = {}
    for name in names:
        parts = name.split(".")
        if (
            len(parts) < 5
            or parts[0] != "model"
            or parts[1] != "layers"
            or parts[-1]
            not in (
                "lora_a",
                "lora_b",
            )
        ):
            raise ConvertError(f"This adapter has a tensor that is not a LoRA weight: {name}")
        layer, projection = int(parts[2]), ".".join(parts[3:-1])
        if projection not in table:
            raise ConvertError(f"This adapter has a layer that is not known here: {projection}")
        which = parts[-1][-1]
        out[name] = (f"blk.{layer}.{table[projection]}.weight.lora_{which}", which, layer)
    return out


def convert(adapter: Path, dst: Path, architecture: str = "qwen3") -> dict[str, Any]:
    """Write `dst`, the GGUF LoRA of the mlx-lm adapter in `adapter`; what was written."""
    table = ARCHITECTURES.get(architecture)
    if table is None:
        raise ConvertError(f"Adapters for {architecture} models cannot be served yet.")
    config = json.loads((adapter / "adapter_config.json").read_text())
    params = config.get("lora_parameters", {})
    rank, scale = int(params["rank"]), float(params.get("scale", 1.0))
    if config.get("fine_tune_type", "lora") != "lora":
        raise ConvertError("Only adapters taught as a small adapter (LoRA) can be served.")
    tensors, _ = read_tensors(adapter / "adapters.safetensors")
    names = layout(list(tensors), table)
    pairs: dict[str, dict[str, tuple[list[int], array]]] = {}
    for name, (target, which, _layer) in names.items():
        t = tensors[name]
        values = _as_f32(t["data"], t["dtype"])
        d0, d1 = t["shape"]
        if which == "a":  # (in, rank) -> PEFT lora_A (rank, in)
            if d1 != rank:
                raise ConvertError("The adapter's rank does not match its own settings.")
            pairs.setdefault(target[: -len(".lora_a")], {})["a"] = (
                [rank, d0], _transposed(values, d0, d1),
            )  # fmt: skip
        else:  # (rank, out) -> PEFT lora_B (out, rank)
            if d0 != rank:
                raise ConvertError("The adapter's rank does not match its own settings.")
            pairs.setdefault(target[: -len(".lora_b")], {})["b"] = (
                [d1, rank], _transposed(values, d0, d1),
            )  # fmt: skip
    body: list[tuple[str, list[int], array]] = []
    for base in sorted(pairs):
        if set(pairs[base]) != {"a", "b"}:
            raise ConvertError(f"The layer {base} has only half of its update.")
        for which in ("a", "b"):
            shape, values = pairs[base][which]
            body.append((f"{base}.lora_{which}", shape, values))
    kvs = [
        _kv("general.architecture", KV_STRING, architecture),
        _kv("general.type", KV_STRING, "adapter"),
        _kv("adapter.type", KV_STRING, "lora"),
        _kv("general.name", KV_STRING, "wasifyai writing style"),
        _kv("adapter.lora.alpha", KV_FLOAT32, scale * rank),
    ]
    head = b"GGUF" + struct.pack("<IQQ", GGUF_VERSION, len(body), len(kvs)) + b"".join(kvs)
    infos, offset = b"", 0
    for name, shape, values in body:
        dims = shape[::-1]  # ggml counts the fastest dimension first
        infos += _string(name) + struct.pack("<I", len(dims)) + struct.pack(f"<{len(dims)}Q", *dims)
        infos += struct.pack("<IQ", T_F32, offset)
        size = len(values) * 4
        offset += size + _pad(size)
    prologue = head + infos
    tmp = dst.with_name(dst.name + ".part")
    with tmp.open("wb") as out:
        out.write(prologue + bytes(_pad(len(prologue))))
        for _name, _shape, values in body:
            out.write(values.tobytes())
            out.write(bytes(_pad(len(values) * 4)))
    tmp.replace(dst)  # a half-written file is never seen by the language server
    return {"tensors": len(body), "rank": rank, "alpha": scale * rank, "bytes": dst.stat().st_size}
