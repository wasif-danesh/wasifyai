"""mflux's klein adapter in ComfyUI's names: the fused attention keeps the three updates exactly."""

import struct
from pathlib import Path

import pytest
from wasifyai_training import comfy_lora as cl


def tensor(rows: int, cols: int, seed: int) -> dict:
    values = [float((seed * 31 + i * 7) % 11 - 5) for i in range(rows * cols)]
    return {"dtype": "F32", "shape": [rows, cols], "data": struct.pack(f"<{rows * cols}f", *values)}


def matrix(t: dict) -> list[list[float]]:
    rows, cols = t["shape"]
    flat = struct.unpack(f"<{rows * cols}f", t["data"])
    return [list(flat[r * cols : (r + 1) * cols]) for r in range(rows)]


def matmul(b: list[list[float]], a: list[list[float]]) -> list[list[float]]:
    return [
        [sum(b[i][k] * a[k][j] for k in range(len(a))) for j in range(len(a[0]))]
        for i in range(len(b))
    ]


def adapter(rank: int = 2, dim: int = 4, mlp: int = 6) -> dict:
    t = {}

    def add(module: str, out: int, inp: int, seed: int) -> None:
        t[f"transformer.{module}.lora_A.weight"] = tensor(rank, inp, seed)
        t[f"transformer.{module}.lora_B.weight"] = tensor(out, rank, seed + 1)

    for part, seed in (("q", 1), ("k", 2), ("v", 3)):
        add(f"transformer_blocks.0.attn.to_{part}", dim, dim, seed * 10)
    add("transformer_blocks.0.attn.to_out", dim, dim, 40)
    add("transformer_blocks.0.ff.linear_in", mlp * 2, dim, 50)
    add("transformer_blocks.0.ff.linear_out", dim, mlp, 60)
    add("single_transformer_blocks.3.attn.to_qkv_mlp_proj", dim * 3 + mlp * 2, dim, 70)
    add("single_transformer_blocks.3.attn.to_out", dim, dim + mlp, 80)
    return t


def test_the_layers_get_comfys_names():
    out = cl.convert_tensors(adapter())
    base = "diffusion_model."
    assert sorted({n.rsplit(".lora_", 1)[0] for n in out}) == sorted(
        base + m
        for m in (
            "double_blocks.0.img_attn.qkv",
            "double_blocks.0.img_attn.proj",
            "double_blocks.0.img_mlp.0",
            "double_blocks.0.img_mlp.2",
            "single_blocks.3.linear1",
            "single_blocks.3.linear2",
        )
    )


def test_the_fused_attention_is_the_three_updates_one_over_the_other():
    src = adapter()
    out = cl.convert_tensors(src)
    a = out["diffusion_model.double_blocks.0.img_attn.qkv.lora_A.weight"]
    b = out["diffusion_model.double_blocks.0.img_attn.qkv.lora_B.weight"]
    assert a["shape"] == [6, 4] and b["shape"] == [12, 6]  # 3r by in, and 3h by 3r
    fused = matmul(matrix(b), matrix(a))
    expected = []
    for part in ("q", "k", "v"):
        expected += matmul(
            matrix(src[f"transformer.transformer_blocks.0.attn.to_{part}.lora_B.weight"]),
            matrix(src[f"transformer.transformer_blocks.0.attn.to_{part}.lora_A.weight"]),
        )
    assert fused == expected


def test_a_part_that_was_not_trained_adds_nothing():
    src = adapter()
    for suffix in ("A", "B"):
        del src[f"transformer.transformer_blocks.0.attn.to_k.lora_{suffix}.weight"]
    out = cl.convert_tensors(src)
    fused = matmul(
        matrix(out["diffusion_model.double_blocks.0.img_attn.qkv.lora_B.weight"]),
        matrix(out["diffusion_model.double_blocks.0.img_attn.qkv.lora_A.weight"]),
    )
    assert all(v == 0 for row in fused[4:8] for v in row)  # the k rows
    assert any(v != 0 for row in fused[:4] for v in row)


def test_a_layer_it_does_not_know_is_an_error_not_a_silent_drop():
    src = adapter()
    src["transformer.transformer_blocks.0.attn.add_q_proj.lora_A.weight"] = tensor(2, 4, 9)
    src["transformer.transformer_blocks.0.attn.add_q_proj.lora_B.weight"] = tensor(4, 2, 9)
    with pytest.raises(cl.ConvertError, match="add_q_proj"):
        cl.convert_tensors(src)
    half = adapter()
    del half["transformer.transformer_blocks.0.attn.to_out.lora_B.weight"]
    with pytest.raises(cl.ConvertError, match="half"):
        cl.convert_tensors(half)
    with pytest.raises(cl.ConvertError, match="not a LoRA"):
        cl.convert_tensors({"something.else": tensor(1, 1, 1)})


def test_a_file_goes_through_and_comes_back_the_same(tmp_path: Path):
    src, dst = tmp_path / "a.safetensors", tmp_path / "b.safetensors"
    cl.write_tensors(src, adapter(), {"mflux_version": "0.22.0"})
    summary = cl.convert(src, dst)
    assert summary["ranks"] == [2, 6] and summary["tensors"] == 12
    tensors, meta = cl.read_tensors(dst)
    assert meta["taught_on"] == "flux2-klein-base-4b" and meta["mflux_version"] == "0.22.0"
    assert matrix(tensors["diffusion_model.double_blocks.0.img_attn.proj.lora_A.weight"]) == matrix(
        adapter()["transformer.transformer_blocks.0.attn.to_out.lora_A.weight"]
    )
    assert not (tmp_path / "b.safetensors.part").exists()
