"""An AI Toolkit adapter is in ComfyUI's names already: it is checked and passed on unchanged."""

import struct
from pathlib import Path

import pytest
from wasifyai_training import comfy_lora as cl


def tensor(rows: int, cols: int, seed: int) -> dict:
    values = [float((seed * 31 + i * 7) % 11 - 5) for i in range(rows * cols)]
    return {"dtype": "F32", "shape": [rows, cols], "data": struct.pack(f"<{rows * cols}f", *values)}


def adapter(rank: int = 2, dim: int = 4, mlp: int = 6) -> dict:
    """A tiny adapter as AI Toolkit writes one for FLUX.2 klein."""
    t = {}

    def add(module: str, out: int, inp: int, seed: int) -> None:
        t[f"diffusion_model.{module}.lora_A.weight"] = tensor(rank, inp, seed)
        t[f"diffusion_model.{module}.lora_B.weight"] = tensor(out, rank, seed + 1)

    add("double_blocks.0.img_attn.qkv", dim * 3, dim, 10)
    add("double_blocks.0.img_attn.proj", dim, dim, 40)
    add("double_blocks.0.img_mlp.0", mlp * 2, dim, 50)
    add("double_blocks.0.img_mlp.2", dim, mlp, 60)
    add("single_blocks.3.linear1", dim * 3 + mlp * 2, dim, 70)
    add("single_blocks.3.linear2", dim, dim + mlp, 80)
    return t


def test_a_file_goes_through_unchanged_with_a_note_of_what_it_was_taught_on(tmp_path: Path):
    src, dst = tmp_path / "a.safetensors", tmp_path / "b.safetensors"
    cl.write_tensors(src, adapter(), {"software": "ai-toolkit"})
    summary = cl.convert(src, dst)
    assert summary["ranks"] == [2] and summary["tensors"] == 12
    tensors, meta = cl.read_tensors(dst)
    assert meta["taught_on"] == "flux2-klein-4b" and meta["software"] == "ai-toolkit"
    assert tensors == dict(sorted(adapter().items()))
    assert not (tmp_path / "b.safetensors.part").exists()


def test_a_name_comfyui_would_not_read_is_an_error_not_a_silent_drop():
    src = adapter()
    src["transformer.transformer_blocks.0.attn.to_q.lora_A.weight"] = tensor(2, 4, 9)
    with pytest.raises(cl.ConvertError, match="would not read"):
        cl.check_tensors(src)
    half = adapter()
    del half["diffusion_model.double_blocks.0.img_attn.proj.lora_B.weight"]
    with pytest.raises(cl.ConvertError, match="half"):
        cl.check_tensors(half)
    with pytest.raises(cl.ConvertError, match="no layers"):
        cl.check_tensors({})


def test_a_model_with_no_recipe_is_not_passed_on(tmp_path: Path):
    src = tmp_path / "a.safetensors"
    cl.write_tensors(src, adapter(), {})
    with pytest.raises(cl.ConvertError, match="no way yet"):
        cl.convert(src, tmp_path / "b.safetensors", "some-other-model")
    assert not (tmp_path / "b.safetensors").exists()


def test_a_run_started_under_the_old_name_of_klein_is_still_passed_on(tmp_path: Path):
    src, dst = tmp_path / "a.safetensors", tmp_path / "b.safetensors"
    cl.write_tensors(src, adapter(), {})
    assert cl.convert(src, dst, "flux2-klein-base-4b")["tensors"] == 12
