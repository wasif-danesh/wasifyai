# ruff: noqa: E501  (the sentences shown to people, and made-up media in a test, are easier to read on one line)
"""A video adapter in ComfyUI's key names: one rename, nothing else, and every odd file refused in words."""

import struct
from pathlib import Path

import pytest
from wasifyai_training import comfy_lora, ltx_lora


def tensor(shape, fill=1.0):
    n = 1
    for d in shape:
        n *= d
    return {
        "dtype": "BF16",
        "shape": list(shape),
        "data": struct.pack("<H", 0x3F80) * n,
    }  # bf16 1.0


def adapter(prefix="transformer.", layers=2):
    out = {}
    for i in range(layers):
        for attn in ("attn1", "attn2"):
            for proj in ("to_q", "to_k", "to_v", "to_out.0"):
                base = f"{prefix}transformer_blocks.{i}.{attn}.{proj}"
                out[f"{base}.lora_A.weight"] = tensor((4, 8))
                out[f"{base}.lora_B.weight"] = tensor((8, 4))
    return out


def test_every_key_loses_its_prefix_and_nothing_else_changes():
    src = adapter()
    got = ltx_lora.convert_tensors(src)
    assert len(got) == len(src) == 32
    assert "transformer_blocks.0.attn1.to_q.lora_A.weight" in got
    assert "transformer_blocks.1.attn2.to_out.0.lora_B.weight" in got
    assert not any(k.startswith("transformer.") for k in got)
    assert all(
        got[k.removeprefix("transformer.")] is src[k] for k in src
    )  # the numbers are moved, not changed


def test_a_file_written_and_read_back_has_the_names_comfyui_wants(tmp_path: Path):
    src, dst = tmp_path / "a.safetensors", tmp_path / "b.safetensors"
    comfy_lora.write_tensors(src, adapter(), {"x": "y"})
    info = ltx_lora.convert(src, dst)
    assert info["tensors"] == 32 and info["ranks"] == [4] and info["bytes"] == dst.stat().st_size
    tensors, meta = comfy_lora.read_tensors(dst)
    assert all(k.startswith("transformer_blocks.") for k in tensors)
    assert meta["taught_on"] == "ltx-video-2b-0.9.5" and meta["converted_by"] == "wasifyai-training"
    assert not (tmp_path / "b.safetensors.part").exists()


def test_a_tensor_that_is_not_a_known_layer_is_refused_in_words():
    bad = adapter()
    bad["transformer.transformer_blocks.0.ff.net.0.proj.lora_A.weight"] = tensor((4, 8))
    with pytest.raises(ltx_lora.ConvertError, match="not a known LoRA weight"):
        ltx_lora.convert_tensors(bad)
    with pytest.raises(ltx_lora.ConvertError, match="not a known LoRA weight"):
        ltx_lora.convert_tensors({"model.layers.0.q.lora_A.weight": tensor((4, 8))})


def test_half_of_an_update_is_refused():
    half = adapter()
    del half["transformer.transformer_blocks.0.attn1.to_q.lora_B.weight"]
    with pytest.raises(ltx_lora.ConvertError, match="only half of its update"):
        ltx_lora.convert_tensors(half)


def test_an_adapter_already_in_comfyui_names_converts_to_itself():
    got = ltx_lora.convert_tensors(adapter(prefix=""))
    assert len(got) == 32 and "transformer_blocks.0.attn1.to_q.lora_A.weight" in got
