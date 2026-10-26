"""An mlx-lm adapter as a GGUF LoRA: the layout llama.cpp reads, the numbers moved without change,
and what is refused. A small reader of the format stands in for llama.cpp here (the real file was
also compared with llama.cpp's own converter and served; see ADR-0074)."""

import json
import struct
from array import array
from pathlib import Path

import pytest
from wasifyai_training import gguf_lora
from wasifyai_training.comfy_lora import write_tensors


def f32(values: list[float] | list[int]) -> bytes:
    return array("f", values).tobytes()


def adapter(folder: Path, tensors: dict, rank: int = 2, scale: float = 1.0, kind: str = "lora"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "adapter_config.json").write_text(
        json.dumps({"fine_tune_type": kind, "lora_parameters": {"rank": rank, "scale": scale}})
    )
    write_tensors(folder / "adapters.safetensors", tensors, {})
    return folder


def tiny(layer: int = 0) -> dict:
    """q_proj of one layer: in 4, out 3, rank 2. a is (in, rank), b is (rank, out)."""
    a = [1, 2, 3, 4, 5, 6, 7, 8]  # (4, 2): rows 1 2 / 3 4 / 5 6 / 7 8
    b = [10, 20, 30, 40, 50, 60]  # (2, 3): rows 10 20 30 / 40 50 60
    return {
        f"model.layers.{layer}.self_attn.q_proj.lora_a": {
            "dtype": "F32", "shape": [4, 2], "data": f32(a),
        },
        f"model.layers.{layer}.self_attn.q_proj.lora_b": {
            "dtype": "F32", "shape": [2, 3], "data": f32(b),
        },
    }  # fmt: skip


def read(path: Path) -> tuple[dict, dict]:
    """(key values, {tensor name: (dims as ggml counts them, values)}) of a GGUF file."""
    raw = path.read_bytes()
    assert raw[:4] == b"GGUF"
    version, n_tensors, n_kv = struct.unpack_from("<IQQ", raw, 4)
    assert version == 3
    pos = 24

    def string() -> str:
        nonlocal pos
        (n,) = struct.unpack_from("<Q", raw, pos)
        text = raw[pos + 8 : pos + 8 + n].decode()
        pos += 8 + n
        return text

    kv = {}
    for _ in range(n_kv):
        key = string()
        (kind,) = struct.unpack_from("<I", raw, pos)
        pos += 4
        if kind == 8:
            kv[key] = string()
        else:
            (kv[key],) = struct.unpack_from("<f" if kind == 6 else "<I", raw, pos)
            pos += 4
    infos = []
    for _ in range(n_tensors):
        name = string()
        (n_dims,) = struct.unpack_from("<I", raw, pos)
        dims = list(struct.unpack_from(f"<{n_dims}Q", raw, pos + 4))
        pos += 4 + 8 * n_dims
        kind, offset = struct.unpack_from("<IQ", raw, pos)
        pos += 12
        assert kind == 0  # F32
        infos.append((name, dims, offset))
    start = pos + (-pos % 32)
    out = {}
    for name, dims, offset in infos:
        count = 1
        for d in dims:
            count *= d
        assert offset % 32 == 0
        out[name] = (dims, list(struct.unpack_from(f"<{count}f", raw, start + offset)))
    return kv, out


def test_the_file_names_the_adapter_and_scales_it_by_alpha_over_rank(tmp_path: Path):
    src = adapter(tmp_path / "a", tiny(), rank=2, scale=1.0)
    info = gguf_lora.convert(src, tmp_path / "out.gguf")
    kv, tensors = read(tmp_path / "out.gguf")
    assert kv["general.architecture"] == "qwen3" and kv["general.type"] == "adapter"
    assert kv["adapter.type"] == "lora" and kv["adapter.lora.alpha"] == 2.0  # scale 1.0 x rank 2
    assert info == {
        "tensors": 2,
        "rank": 2,
        "alpha": 2.0,
        "bytes": (tmp_path / "out.gguf").stat().st_size,
    }
    assert sorted(tensors) == ["blk.0.attn_q.weight.lora_a", "blk.0.attn_q.weight.lora_b"]


def test_the_numbers_are_moved_into_the_layout_llama_cpp_reads(tmp_path: Path):
    gguf_lora.convert(adapter(tmp_path / "a", tiny()), tmp_path / "out.gguf")
    _, t = read(tmp_path / "out.gguf")
    # PEFT lora_A is (rank 2, in 4): ggml counts the fastest dimension first, so [4, 2]; its
    # rows are the columns of mlx's (in, rank) matrix
    dims_a, a = t["blk.0.attn_q.weight.lora_a"]
    assert dims_a == [4, 2] and a == [1, 3, 5, 7, 2, 4, 6, 8]
    # PEFT lora_B is (out 3, rank 2): [2, 3]; its rows are the columns of mlx's (rank, out)
    dims_b, b = t["blk.0.attn_q.weight.lora_b"]
    assert dims_b == [2, 3] and b == [10, 40, 20, 50, 30, 60]
    # the product is the same: x @ A_mlx @ B_mlx equals B_peft @ A_peft @ x
    x = [1.0, 0.0, 2.0, -1.0]
    mlx_a = [[1, 2], [3, 4], [5, 6], [7, 8]]
    mlx_b = [[10, 20, 30], [40, 50, 60]]
    via_mlx = [
        sum(sum(x[i] * mlx_a[i][r] for i in range(4)) * mlx_b[r][o] for r in range(2))
        for o in range(3)
    ]
    h = [sum(a[r * 4 + i] * x[i] for i in range(4)) for r in range(2)]
    via_peft = [sum(b[o * 2 + r] * h[r] for r in range(2)) for o in range(3)]
    assert via_mlx == via_peft


def test_half_and_brain_floats_become_32_bit_without_changing_what_they_hold(tmp_path: Path):
    half = struct.pack("<8e", 1, 2, 3, 4, 5, 6, 7, 8)
    brain = array("H", [v >> 16 for v in struct.unpack("<8I", f32([1, 2, 3, 4, 5, 6, 7, 8]))])
    for dtype, data in (("F16", half), ("BF16", brain.tobytes())):
        tensors = tiny()
        tensors["model.layers.0.self_attn.q_proj.lora_a"] = {
            "dtype": dtype, "shape": [4, 2], "data": data,
        }  # fmt: skip
        out = tmp_path / f"{dtype}.gguf"
        gguf_lora.convert(adapter(tmp_path / dtype, tensors), out)
        assert read(out)[1]["blk.0.attn_q.weight.lora_a"][1] == [1, 3, 5, 7, 2, 4, 6, 8]


def test_every_projection_of_every_layer_gets_its_llama_cpp_name(tmp_path: Path):
    tensors = {}
    for layer in (0, 7):
        for proj in ("self_attn.k_proj", "self_attn.v_proj", "self_attn.o_proj", "mlp.gate_proj",
                     "mlp.up_proj", "mlp.down_proj"):  # fmt: skip
            tensors[f"model.layers.{layer}.{proj}.lora_a"] = {
                "dtype": "F32",
                "shape": [4, 2],
                "data": f32([0] * 8),
            }
            tensors[f"model.layers.{layer}.{proj}.lora_b"] = {
                "dtype": "F32",
                "shape": [2, 3],
                "data": f32([0] * 6),
            }
    gguf_lora.convert(adapter(tmp_path / "a", tensors), tmp_path / "out.gguf")
    names = set(read(tmp_path / "out.gguf")[1])
    for layer in (0, 7):
        for llama in ("attn_k", "attn_v", "attn_output", "ffn_gate", "ffn_up", "ffn_down"):
            assert f"blk.{layer}.{llama}.weight.lora_a" in names
            assert f"blk.{layer}.{llama}.weight.lora_b" in names


def test_what_cannot_be_converted_is_refused_in_words_and_leaves_no_file(tmp_path: Path):
    out = tmp_path / "out.gguf"
    with pytest.raises(gguf_lora.ConvertError, match="cannot be served yet"):
        gguf_lora.convert(adapter(tmp_path / "a", tiny()), out, "llama3")
    with pytest.raises(gguf_lora.ConvertError, match="small adapter"):
        gguf_lora.convert(adapter(tmp_path / "b", tiny(), kind="full"), out)
    half = {k: v for k, v in tiny().items() if k.endswith("lora_a")}
    with pytest.raises(gguf_lora.ConvertError, match="half of its update"):
        gguf_lora.convert(adapter(tmp_path / "c", half), out)
    odd = {"model.layers.0.self_attn.rope.lora_a": tiny()["model.layers.0.self_attn.q_proj.lora_a"]}
    with pytest.raises(gguf_lora.ConvertError, match="not known here"):
        gguf_lora.convert(adapter(tmp_path / "d", odd), out)
    with pytest.raises(gguf_lora.ConvertError, match="not a LoRA weight"):
        stray = {"embed.weight": tiny()["model.layers.0.self_attn.q_proj.lora_a"]}
        gguf_lora.convert(adapter(tmp_path / "e", stray), out)
    with pytest.raises(gguf_lora.ConvertError, match="rank"):
        gguf_lora.convert(adapter(tmp_path / "f", tiny(), rank=3), out)
    assert not out.exists() and not out.with_name(out.name + ".part").exists()
