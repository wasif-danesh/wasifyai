import argparse, colorsys, json, time, numpy as np, torch
from PIL import Image
from diffusers import LTXPipeline, LTXVideoTransformer3DModel, AutoencoderKLLTXVideo, FlowMatchEulerDiscreteScheduler
ap = argparse.ArgumentParser(); ap.add_argument("--lora"); ap.add_argument("--tag", default="x"); ap.add_argument("--w", type=int, default=384); ap.add_argument("--h", type=int, default=256)
ap.add_argument("--frames", type=int, default=25); ap.add_argument("--steps", type=int, default=30); ap.add_argument("--scale", type=float, default=1.0); ap.add_argument("--seed", type=int, default=7); ap.add_argument("--cfg", type=float, default=3.0); ap.add_argument("--only", default=""); ap.add_argument("--data", default="data")
a = ap.parse_args()
dev = torch.device("mps")
CK = "/Users/wasifdanesh/ComfyUI-Shared/models/checkpoints/ltx-video-2b-v0.9.5.safetensors"
tr = LTXVideoTransformer3DModel.from_single_file(CK, torch_dtype=torch.bfloat16)
vae = AutoencoderKLLTXVideo.from_single_file(CK, torch_dtype=torch.bfloat16)
sch = FlowMatchEulerDiscreteScheduler.from_pretrained("hf_small/scheduler")
pipe = LTXPipeline(scheduler=sch, vae=vae, text_encoder=None, tokenizer=None, transformer=tr).to(dev)
if a.lora:
    pipe.load_lora_weights(a.lora, weight_name="pytorch_lora_weights.safetensors", adapter_name="x"); pipe.set_adapters(["x"], [a.scale])
vt = torch.load(f"{a.data}/val_text.pt"); nt = torch.load(f"{a.data}/neg_text.pt")
def hue_score(frames):
    # share of pixels that are teal (hue 150-200 deg) or magenta (hue 280-330 deg) with real colour, and mean brightness
    x = frames.reshape(-1, 3).astype(np.float32) / 255.0
    mx, mn = x.max(1), x.min(1); d = mx - mn
    sat = np.where(mx > 0, d / np.maximum(mx, 1e-6), 0)
    r, g, b = x[:, 0], x[:, 1], x[:, 2]
    h = np.zeros_like(mx)
    m = d > 1e-6
    h[m & (mx == r)] = (((g - b) / np.maximum(d, 1e-6)) % 6)[m & (mx == r)]
    h[m & (mx == g)] = (((b - r) / np.maximum(d, 1e-6)) + 2)[m & (mx == g)]
    h[m & (mx == b)] = (((r - g) / np.maximum(d, 1e-6)) + 4)[m & (mx == b)]
    h = h * 60
    colour = (sat > 0.35) & (mx > 0.25)
    tm = colour & (((h >= 150) & (h <= 200)) | ((h >= 280) & (h <= 330)))
    return float(tm.mean()), float(mx.mean())
res = {}
for i, name in enumerate(vt["names"]):
    if a.only and name != a.only: continue
    t0 = time.time()
    g = torch.Generator("cpu").manual_seed(a.seed)
    out = pipe(prompt_embeds=vt["embeds"][i:i+1].to(dev, torch.bfloat16), prompt_attention_mask=vt["mask"][i:i+1].to(dev),
               negative_prompt_embeds=nt["embeds"][None].to(dev, torch.bfloat16), negative_prompt_attention_mask=nt["mask"][None].to(dev),
               width=a.w, height=a.h, num_frames=a.frames, num_inference_steps=a.steps, guidance_scale=a.cfg, generator=g, output_type="np")
    v = (out.frames[0] * 255).clip(0, 255).astype(np.uint8)  # [F,H,W,3]
    idx = np.linspace(0, v.shape[0] - 1, 4).astype(int)
    Image.fromarray(np.concatenate([v[j] for j in idx], axis=1)).save(f"gen_{a.tag}_{name}.png")
    res[name] = {"seconds": round(time.time() - t0, 1), "teal_magenta_share": round(hue_score(v)[0], 3), "mean_brightness": round(hue_score(v)[1], 3)}
    print(name, res[name], flush=True)
json.dump(res, open(f"gen_{a.tag}.json", "w"), indent=1)
