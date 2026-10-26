import argparse, glob, json, math, os, random, time, torch
from pathlib import Path
from diffusers import LTXVideoTransformer3DModel
from peft import LoraConfig, get_peft_model
from peft.utils import get_peft_model_state_dict
from safetensors.torch import save_file

ap = argparse.ArgumentParser()
ap.add_argument("--data", default="data"); ap.add_argument("--steps", type=int, default=20); ap.add_argument("--rank", type=int, default=16)
ap.add_argument("--lr", type=float, default=1e-4); ap.add_argument("--batch", type=int, default=1); ap.add_argument("--ckpt", action="store_true")
ap.add_argument("--out", default="lora_out"); ap.add_argument("--fps", type=float, default=25.0); ap.add_argument("--seed", type=int, default=3407)
ap.add_argument("--log", type=int, default=10); ap.add_argument("--eval_every", type=int, default=0)
a = ap.parse_args()
dev = torch.device("mps"); random.seed(a.seed); torch.manual_seed(a.seed)
CK = "/Users/wasifdanesh/ComfyUI-Shared/models/checkpoints/ltx-video-2b-v0.9.5.safetensors"
def mem(): return torch.mps.driver_allocated_memory() / 1e9, torch.mps.current_allocated_memory() / 1e9

t0 = time.time()
tr = LTXVideoTransformer3DModel.from_single_file(CK, torch_dtype=torch.bfloat16)
tr.requires_grad_(False)
tr = get_peft_model(tr, LoraConfig(r=a.rank, lora_alpha=a.rank, init_lora_weights=True, target_modules=["to_k", "to_q", "to_v", "to_out.0"]))
tr.to(dev)
if a.ckpt: tr.base_model.model.enable_gradient_checkpointing()
tr.train()
params = [p for p in tr.parameters() if p.requires_grad]
print(f"loaded in {time.time()-t0:.1f}s; trainable {sum(p.numel() for p in params)/1e6:.1f} M, dtype {params[0].dtype}; mem driver/alloc {mem()}", flush=True)
opt = torch.optim.AdamW(params, lr=a.lr, weight_decay=0.0)

items = []
for lp in sorted(glob.glob(f"{a.data}/*_latent.pt")):
    t = torch.load(lp.replace("_latent", "_text")); items.append((torch.load(lp), t["embeds"], t["mask"]))
print(len(items), "clips; latent", tuple(items[0][0].shape), flush=True)
_, F, H, W = items[0][0].shape
rope = [1 / (a.fps / 8), 32, 32]
def pack(x): return x.reshape(x.shape[0], x.shape[1], F, 1, H, 1, W, 1).permute(0, 2, 4, 6, 1, 3, 5, 7).flatten(4, 7).flatten(1, 3)

def eval_loss():
    """A steady loss: four clips, four fixed sigmas, fixed noise (the training loss is noisy by design)."""
    g = torch.Generator("cpu").manual_seed(123); tot, n = 0.0, 0
    tr.eval()
    with torch.no_grad():
        for b in items[:4]:
            z = b[0][None].to(dev, torch.bfloat16); emb = b[1][None].to(dev, torch.bfloat16); mask = b[2][None].to(dev)
            for sg in (0.2, 0.4, 0.6, 0.8):
                noise = torch.randn(z.shape, generator=g).to(dev, torch.bfloat16)
                noisy = (1 - sg) * z + sg * noise
                pred = tr(hidden_states=pack(noisy), encoder_hidden_states=emb, timestep=torch.tensor([sg * 1000], device=dev, dtype=torch.bfloat16),
                          encoder_attention_mask=mask, num_frames=F, height=H, width=W, rope_interpolation_scale=rope, return_dict=False)[0]
                tot += torch.nn.functional.mse_loss(pred.float(), pack(noise - z).float()).item(); n += 1
    tr.train(); return tot / n
evals = {}
if a.eval_every: evals[0] = eval_loss(); print(f"eval at step 0: {evals[0]:.4f}", flush=True)
losses, times = [], []
for step in range(1, a.steps + 1):
    ts = time.time()
    batch = random.sample(items, a.batch) if a.batch <= len(items) else items
    z = torch.stack([b[0] for b in batch]).to(dev, torch.bfloat16)
    emb = torch.stack([b[1] for b in batch]).to(dev, torch.bfloat16); mask = torch.stack([b[2] for b in batch]).to(dev)
    sig = torch.sigmoid(torch.randn(z.shape[0], device=dev))  # logit-normal, as the trainers do
    noise = torch.randn_like(z)
    s5 = sig.view(-1, 1, 1, 1, 1).to(z.dtype)
    noisy = (1 - s5) * z + s5 * noise
    pred = tr(hidden_states=pack(noisy), encoder_hidden_states=emb, timestep=(sig * 1000).to(torch.bfloat16),
              encoder_attention_mask=mask, num_frames=F, height=H, width=W, rope_interpolation_scale=rope, return_dict=False)[0]
    loss = torch.nn.functional.mse_loss(pred.float(), pack(noise - z).float())
    opt.zero_grad(set_to_none=True); loss.backward()
    torch.nn.utils.clip_grad_norm_(params, 1.0); opt.step()
    torch.mps.synchronize(); dt = time.time() - ts
    losses.append(loss.item()); times.append(dt)
    if a.eval_every and step % a.eval_every == 0:
        evals[step] = eval_loss(); print(f"eval at step {step}: {evals[step]:.4f}", flush=True)
    if step % a.log == 0 or step <= 3:
        print(f"step {step} loss {loss.item():.4f} (avg10 {sum(losses[-10:])/len(losses[-10:]):.4f}) {dt:.2f}s mem driver/alloc {mem()}", flush=True)
warm = times[2:] or times
print(f"DONE steps {a.steps}; mean step {sum(warm)/len(warm):.2f}s (first 3 excluded); total {sum(times):.0f}s; peak driver {mem()[0]:.1f} GB")
sd = get_peft_model_state_dict(tr)
Path(a.out).mkdir(exist_ok=True)
save_file({"transformer." + k.replace("base_model.model.", "", 1): v.detach().float().cpu().contiguous() for k, v in sd.items()}, f"{a.out}/pytorch_lora_weights.safetensors")
json.dump({"losses": losses, "times": times, "evals": evals, "args": vars(a)}, open(f"{a.out}/log.json", "w"))
print("saved", f"{a.out}/pytorch_lora_weights.safetensors", os.path.getsize(f"{a.out}/pytorch_lora_weights.safetensors") / 1e6, "MB")
