import sys, time, glob, os, numpy as np, torch
from pathlib import Path
from PIL import Image
from transformers import T5EncoderModel, T5Config, T5Tokenizer
from safetensors.torch import load_file
from diffusers import AutoencoderKLLTXVideo

W, H = int(sys.argv[1]), int(sys.argv[2]); out = Path(sys.argv[3]); out.mkdir(exist_ok=True)
SRC = Path("/Users/wasifdanesh/Projects/character-lora/data/characters/ena/training/flux")   # read only
dev = torch.device("mps")
CK = "/Users/wasifdanesh/ComfyUI-Shared/models/checkpoints/ltx-video-2b-v0.9.5.safetensors"
T5F = "/Users/wasifdanesh/ComfyUI-Shared/models/text_encoders/t5xxl_fp16.safetensors"
pics = sorted(SRC.glob("ena-*.png"))
caps = {p.stem: (p.with_suffix(".txt")).read_text().strip() for p in pics}
print(len(pics), "pictures; first caption:", list(caps.values())[0][:100], flush=True)
tok = T5Tokenizer.from_pretrained("hf_small/tokenizer"); cfg = T5Config.from_pretrained("hf_small/text_encoder")
with torch.device("meta"): te = T5EncoderModel(cfg)
sd = load_file(T5F); te.load_state_dict(sd, strict=False, assign=True); del sd
te = te.to(torch.bfloat16).to(dev).eval()
def encode(texts):
    b = tok(texts, padding="max_length", max_length=128, truncation=True, return_tensors="pt")
    with torch.no_grad(): e = te(b.input_ids.to(dev), attention_mask=b.attention_mask.to(dev))[0]
    return e.cpu(), b.attention_mask
long = [k for k, c in caps.items() if len(tok(c).input_ids) > 128]
print("captions over 128 tokens:", len(long), flush=True)
for k, c in caps.items():
    e, m = encode([c]); torch.save({"embeds": e[0], "mask": m[0]}, out / f"{k}_text.pt")
import json
val = json.load(open("val_prompts_ena.json")); ve, vm = encode(list(val.values()))
torch.save({"names": list(val), "embeds": ve, "mask": vm}, out / "val_text.pt")
ne, nm = encode([""]); torch.save({"embeds": ne[0], "mask": nm[0]}, out / "neg_text.pt")
del te; torch.mps.empty_cache()
vae = AutoencoderKLLTXVideo.from_single_file(CK, torch_dtype=torch.bfloat16).to(dev).eval()
mean, std = vae.latents_mean.view(1, -1, 1, 1, 1).float().cpu(), vae.latents_std.view(1, -1, 1, 1, 1).float().cpu(); sf = vae.config.scaling_factor
t0 = time.time()
for p in pics:
    im = Image.open(p).convert("RGB").resize((W, H), Image.LANCZOS)
    x = torch.from_numpy(np.asarray(im).copy()).permute(2, 0, 1).float()[None, :, None] / 127.5 - 1.0   # [1,3,1,H,W]
    with torch.no_grad(): z = vae.encode(x.to(dev, torch.bfloat16)).latent_dist.mode().float().cpu()
    z = (z - mean) * sf / std; torch.save(z[0], out / f"{p.stem}_latent.pt")
print("encoded", len(pics), "pictures in", round(time.time() - t0, 1), "s; latent", tuple(z.shape))
