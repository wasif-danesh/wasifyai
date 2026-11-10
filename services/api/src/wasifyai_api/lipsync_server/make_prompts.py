"""Makes `echomimic_prompts.safetensors`: EchoMimic v3's two fixed prompts, encoded once by its
umt5-xxl text encoder.

Lip sync takes no prompt from the person, so the text is always the same and its encoding is shipped
instead of the 11 GB encoder (the server then never loads it). Run it again only if the prompts
change, from the lip sync environment, with EchoMimic's code and the Wan2.1-Fun-V1.1-1.3B-InP folder
(`models_t5_umt5-xxl-enc-bf16.pth`, `google/umt5-xxl/`):

    ECHOMIMIC_DIR=<code> <venv>/bin/python make_prompts.py <Wan2.1-Fun-V1.1-1.3B-InP folder>
"""

import os
import sys
from pathlib import Path

import torch
from safetensors.torch import save_file

PROMPT = "A person is speaking."
# EchoMimic's own negative prompt (`infer_flash.py`); the lip sync passes do not read it, but the
# pipeline asks for it
NEGATIVE = (
    "Gesture is bad. Gesture is unclear. Strange and twisted hands. Bad hands. Bad fingers. "
    "Unclear and blurry hands. Unclear gestures, broken hands, fused fingers. 手指融合，"
)
OUT = Path(__file__).with_name("echomimic_prompts.safetensors")


def main() -> None:
    base = Path(sys.argv[1])
    sys.path.insert(0, os.environ["ECHOMIMIC_DIR"])
    from omegaconf import OmegaConf
    from src.wan_text_encoder import WanT5EncoderModel
    from transformers import AutoTokenizer

    cfg = OmegaConf.load(Path(os.environ["ECHOMIMIC_DIR"]) / "config" / "config.yaml")[
        "text_encoder_kwargs"
    ]
    tok = AutoTokenizer.from_pretrained(str(base / cfg["tokenizer_subpath"]))
    enc = WanT5EncoderModel.from_pretrained(
        str(base / cfg["text_encoder_subpath"]), additional_kwargs=OmegaConf.to_container(cfg),
        low_cpu_mem_usage=True, torch_dtype=torch.bfloat16,
    ).eval()  # fmt: skip
    out = {}
    with torch.no_grad():
        for name, text in (("prompt", PROMPT), ("negative", NEGATIVE)):
            t = tok(
                [text], padding="max_length", max_length=512, truncation=True, return_tensors="pt"
            )
            n = int(t.attention_mask.sum())
            emb = enc(t.input_ids, attention_mask=t.attention_mask)[0][0, :n]
            out[name] = emb.to(torch.bfloat16).contiguous()
    save_file(
        out,
        str(OUT),
        metadata={"prompt": PROMPT, "negative": NEGATIVE, "encoder": "umt5-xxl-enc-bf16"},
    )
    print({k: tuple(v.shape) for k, v in out.items()}, OUT)


if __name__ == "__main__":
    main()
