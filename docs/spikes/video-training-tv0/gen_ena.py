import argparse, json, subprocess, time, numpy as np, torch
from PIL import Image
from diffusers import LTXPipeline, LTXVideoTransformer3DModel, AutoencoderKLLTXVideo, FlowMatchEulerDiscreteScheduler
ap = argparse.ArgumentParser(); ap.add_argument("--lora"); ap.add_argument("--tag", required=True); ap.add_argument("--scale", type=float, default=1.0); ap.add_argument("--cfg", type=float, default=3.0)
ap.add_argument("--w", type=int, default=640); ap.add_argument("--h", type=int, default=576); ap.add_argument("--frames", type=int, default=49); ap.add_argument("--steps", type=int, default=30)
ap.add_argument("--seed", type=int, default=7); ap.add_argument("--only", default=""); ap.add_argument("--data", default="data_ena"); ap.add_argument("--out", default="ena_out")
a = ap.parse_args(); dev = torch.device("mps")
import os; os.makedirs(a.out, exist_ok=True)
CK = "/Users/wasifdanesh/ComfyUI-Shared/models/checkpoints/ltx-video-2b-v0.9.5.safetensors"
tr = LTXVideoTransformer3DModel.from_single_file(CK, torch_dtype=torch.bfloat16); vae = AutoencoderKLLTXVideo.from_single_file(CK, torch_dtype=torch.bfloat16)
pipe = LTXPipeline(scheduler=FlowMatchEulerDiscreteScheduler.from_pretrained("hf_small/scheduler"), vae=vae, text_encoder=None, tokenizer=None, transformer=tr).to(dev)
if a.lora: pipe.load_lora_weights(a.lora, weight_name="pytorch_lora_weights.safetensors", adapter_name="x"); pipe.set_adapters(["x"], [a.scale])
vt = torch.load(f"{a.data}/val_text.pt"); nt = torch.load(f"{a.data}/neg_text.pt")
for i, name in enumerate(vt["names"]):
    if a.only and name not in a.only.split(","): continue
    t0 = time.time(); g = torch.Generator("cpu").manual_seed(a.seed)
    out = pipe(prompt_embeds=vt["embeds"][i:i+1].to(dev, torch.bfloat16), prompt_attention_mask=vt["mask"][i:i+1].to(dev),
               negative_prompt_embeds=nt["embeds"][None].to(dev, torch.bfloat16), negative_prompt_attention_mask=nt["mask"][None].to(dev),
               width=a.w, height=a.h, num_frames=a.frames, num_inference_steps=a.steps, guidance_scale=a.cfg, generator=g, output_type="np")
    v = (out.frames[0] * 255).clip(0, 255).astype(np.uint8)
    stem = f"{a.out}/{a.tag}_{name}"
    p = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{a.w}x{a.h}", "-r", "24", "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", stem + ".mp4"], stdin=subprocess.PIPE)
    p.stdin.write(v.tobytes()); p.stdin.close(); p.wait()
    idx = np.linspace(0, len(v) - 1, 4).astype(int); Image.fromarray(np.concatenate([v[j] for j in idx], axis=1)).save(stem + ".png")
    print(name, f"{time.time()-t0:.0f}s", flush=True)
