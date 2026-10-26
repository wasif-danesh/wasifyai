import json, subprocess, sys, time, os, numpy as np, torch
from pathlib import Path
from transformers import T5EncoderModel, T5Config, T5Tokenizer
from safetensors.torch import load_file
from diffusers import AutoencoderKLLTXVideo

dev = torch.device("mps")
CK = "/Users/wasifdanesh/ComfyUI-Shared/models/checkpoints/ltx-video-2b-v0.9.5.safetensors"
T5F = "/Users/wasifdanesh/ComfyUI-Shared/models/text_encoders/t5xxl_fp16.safetensors"
out = Path("data"); out.mkdir(exist_ok=True)
caps = json.load(open("captions.json"))
val_prompts = json.load(open("val_prompts.json"))
def mem(tag): print(f"  [{tag}] mps allocated {torch.mps.current_allocated_memory()/1e9:.2f} GB, driver {torch.mps.driver_allocated_memory()/1e9:.2f} GB", flush=True)

t0 = time.time()
tok = T5Tokenizer.from_pretrained("hf_small/tokenizer")
cfg = T5Config.from_pretrained("hf_small/text_encoder")
with torch.device("meta"): te = T5EncoderModel(cfg)
sd = load_file(T5F)
te.load_state_dict(sd, strict=False, assign=True); del sd
te = te.to(torch.bfloat16).to(dev).eval()
print("t5 loaded", round(time.time() - t0, 1), "s"); mem("t5")
def encode(texts):
    b = tok(texts, padding="max_length", max_length=128, truncation=True, return_tensors="pt")
    with torch.no_grad():
        e = te(b.input_ids.to(dev), attention_mask=b.attention_mask.to(dev))[0]
    return e.cpu(), b.attention_mask
t0 = time.time()
for i, (f, c) in enumerate(caps.items()):
    e, m = encode([c]); torch.save({"embeds": e[0], "mask": m[0]}, out / f"{Path(f).stem}_text.pt")
ve, vm = encode(list(val_prompts.values()))
torch.save({"names": list(val_prompts), "embeds": ve, "mask": vm}, out / "val_text.pt")
ne, nm = encode([""]); torch.save({"embeds": ne[0], "mask": nm[0]}, out / "neg_text.pt")
print("text encoded", round(time.time() - t0, 1), "s for", len(caps) + len(val_prompts) + 1, "texts")
del te; torch.mps.empty_cache()

vae = AutoencoderKLLTXVideo.from_single_file(CK, torch_dtype=torch.bfloat16).to(dev).eval()
mean, std = vae.latents_mean.view(1, -1, 1, 1, 1).float().cpu(), vae.latents_std.view(1, -1, 1, 1, 1).float().cpu()
sf = vae.config.scaling_factor
t0 = time.time()
for f in caps:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", f, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    v = np.frombuffer(raw, np.uint8).reshape(-1, 256, 384, 3)[:25]
    x = torch.from_numpy(v.copy()).permute(3, 0, 1, 2).unsqueeze(0).float() / 127.5 - 1.0
    with torch.no_grad():
        z = vae.encode(x.to(dev, torch.bfloat16)).latent_dist.mode().float().cpu()
    z = (z - mean) * sf / std
    torch.save(z[0], out / f"{Path(f).stem}_latent.pt")
print("vae encoded", round(time.time() - t0, 1), "s for", len(caps), "clips; latent", tuple(z.shape)); mem("vae")
