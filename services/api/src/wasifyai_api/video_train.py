# ruff: noqa: E501  (prose in the docstring and long calls are easier to read on one line)
# pyright: reportMissingImports=false, reportAttributeAccessIssue=false
"""Teach the video model (LTX-Video 2B) a look, a motion or a subject from pictures and short clips.

Run by the video trainer with the trainer's own Python (`python -I video_train.py -c <job.json>`),
never imported by the engine: it needs PyTorch, `diffusers` and `peft`, which only that environment
has. It prints one JSON object per line on stdout:

    {"event": "status", "message": ...}
    {"event": "progress", "step": n, "total": m, "loss": x, "seconds": s}
    {"event": "check", "step": n, "loss": x}            the steady loss on fixed noise
    {"event": "done", "seconds": s, "peak_bytes": b, "adapter": path, "loss_first": x, "loss_last": y}

What it does, in this order, each part freeing its memory before the next (docs/spikes/video-training-tv0.md):
the captions are encoded with the T5 text encoder, the pictures and clips with the video encoder (a
picture is one frame, a clip a few windows of 25 frames), then the transformer is taught a LoRA (rank 32,
every attention projection) by flow matching, with gradient checkpointing when the clips are large.
The adapter is written with the names `diffusers` uses (`transformer.transformer_blocks...`); the
engine renames them for ComfyUI. Stopping is killing the process: nothing is kept.

The job file is `{checkpoint, t5, small, ffmpeg, out, items: [{path, kind, caption, seconds}], width,
height, window_frames, steps, rank, lr, seed, checkpointing}`; `small` is the folder of the repository's
tokenizer and configuration files (under 1 MB). Offline: nothing is fetched."""

import json
import os
import random
import subprocess
import sys
import time

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def emit(**event: object) -> None:
    sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def cover(im, width: int, height: int):
    """The picture scaled to cover the size and cut in the middle."""
    from PIL import Image

    w, h = im.size
    scale = max(width / w, height / h)
    im = im.resize(
        (max(width, round(w * scale)), max(height, round(h * scale))), Image.Resampling.LANCZOS
    )
    left, top = (im.width - width) // 2, (im.height - height) // 2
    return im.crop((left, top, left + width, top + height))


def windows_of(seconds: float, frames: int, fps: int, most: int) -> list[float]:
    """Start times (seconds) of up to `most` windows of `frames` frames, spread over the clip."""
    room = seconds - frames / fps
    if room <= 0.05:
        return [0.0]
    n = min(most, 1 + int(room / (frames / fps)))
    return [round(room * i / max(1, n - 1), 3) for i in range(n)] if n > 1 else [round(room / 2, 3)]


def main() -> None:
    job = json.load(open(sys.argv[sys.argv.index("-c") + 1], encoding="utf-8"))
    started = time.time()
    import numpy as np
    import torch
    from diffusers import AutoencoderKLLTXVideo, LTXVideoTransformer3DModel
    from peft import LoraConfig, get_peft_model
    from peft.utils import get_peft_model_state_dict
    from PIL import Image
    from safetensors.torch import load_file, save_file
    from transformers import T5Config, T5EncoderModel, T5Tokenizer

    dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    W, H, F = int(job["width"]), int(job["height"]), int(job["window_frames"])
    random.seed(job["seed"])
    torch.manual_seed(job["seed"])
    small = job["small"]

    # 1 the captions
    emit(event="status", message="Reading the descriptions")
    tok = T5Tokenizer.from_pretrained(os.path.join(small, "tokenizer"))
    cfg = T5Config.from_pretrained(os.path.join(small, "text_encoder"))
    with torch.device("meta"):
        te = T5EncoderModel(cfg)
    te.load_state_dict(load_file(job["t5"]), strict=False, assign=True)
    te = te.to(torch.bfloat16).to(dev).eval()
    texts = []
    for it in job["items"]:
        b = tok(
            [it["caption"]],
            padding="max_length",
            max_length=128,
            truncation=True,
            return_tensors="pt",
        )
        with torch.no_grad():
            e = te(b.input_ids.to(dev), attention_mask=b.attention_mask.to(dev))[0]
        texts.append((e[0].cpu(), b.attention_mask[0]))
    del te
    torch.mps.empty_cache() if dev.type == "mps" else None

    # 2 the pictures and clips
    emit(event="status", message="Looking at the pictures and clips")
    ck = job["checkpoint"]
    vae = AutoencoderKLLTXVideo.from_single_file(ck, torch_dtype=torch.bfloat16).to(dev).eval()
    mean = vae.latents_mean.view(1, -1, 1, 1, 1).float().cpu()
    std = vae.latents_std.view(1, -1, 1, 1, 1).float().cpu()
    sf = vae.config.scaling_factor
    samples = []  # (latent [C, F, h, w], embeds, mask)
    for it, (emb, mask) in zip(job["items"], texts, strict=True):
        clips = []
        if it["kind"] == "picture":
            im = cover(Image.open(it["path"]).convert("RGB"), W, H)
            clips.append(
                torch.from_numpy(np.asarray(im).copy()).permute(2, 0, 1).float()[None, :, None]
                / 127.5
                - 1.0
            )
        else:
            for start in windows_of(float(it["seconds"]), F, 24, 3):
                raw = subprocess.run(
                    [
                        job["ffmpeg"],
                        "-v",
                        "error",
                        "-ss",
                        str(start),
                        "-i",
                        it["path"],
                        "-vf",
                        f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}",
                        "-r",
                        "24",
                        "-frames:v",
                        str(F),
                        "-f",
                        "rawvideo",
                        "-pix_fmt",
                        "rgb24",
                        "-",
                    ],
                    capture_output=True,
                    check=True,
                ).stdout
                v = np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3)
                if len(v) < F:
                    continue
                clips.append(
                    torch.from_numpy(v[:F].copy()).permute(3, 0, 1, 2).float()[None] / 127.5 - 1.0
                )
        for x in clips:
            with torch.no_grad():
                z = vae.encode(x.to(dev, torch.bfloat16)).latent_dist.mode().float().cpu()
            samples.append((((z - mean) * sf / std)[0], emb, mask))
    del vae
    torch.mps.empty_cache() if dev.type == "mps" else None
    if not samples:
        raise SystemExit("No picture or clip could be read.")

    # 3 the teaching
    emit(event="status", message="Loading the video model")
    tr = LTXVideoTransformer3DModel.from_single_file(ck, torch_dtype=torch.bfloat16)
    tr.requires_grad_(False)
    tr = get_peft_model(
        tr,
        LoraConfig(
            r=int(job["rank"]),
            lora_alpha=int(job["rank"]),
            init_lora_weights=True,
            target_modules=["to_k", "to_q", "to_v", "to_out.0"],
        ),
    )
    tr.to(dev)
    if job.get("checkpointing"):
        tr.base_model.model.enable_gradient_checkpointing()
    tr.train()
    params = [p for p in tr.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=float(job["lr"]), weight_decay=0.0)
    rope = [1 / (25.0 / 8), 32, 32]

    def pack(x, f, h, w):
        return (
            x.reshape(x.shape[0], x.shape[1], f, 1, h, 1, w, 1)
            .permute(0, 2, 4, 6, 1, 3, 5, 7)
            .flatten(4, 7)
            .flatten(1, 3)
        )

    def predict(z, emb, mask, sig, noise):
        f, h, w = z.shape[2:]
        s5 = sig.view(-1, 1, 1, 1, 1).to(z.dtype)
        noisy = (1 - s5) * z + s5 * noise
        out = tr(
            hidden_states=pack(noisy, f, h, w),
            encoder_hidden_states=emb,
            timestep=(sig * 1000).to(torch.bfloat16),
            encoder_attention_mask=mask,
            num_frames=f,
            height=h,
            width=w,
            rope_interpolation_scale=rope,
            return_dict=False,
        )[0]
        return torch.nn.functional.mse_loss(out.float(), pack(noise - z, f, h, w).float())

    def check() -> float:
        """A steady loss: up to four samples, four noise levels, fixed noise (the training loss is noisy by design)."""
        g = torch.Generator("cpu").manual_seed(123)
        tot, n = 0.0, 0
        tr.eval()
        with torch.no_grad():
            for z, emb, mask in samples[:4]:
                zz = z[None].to(dev, torch.bfloat16)
                for sg in (0.2, 0.4, 0.6, 0.8):
                    noise = torch.randn(zz.shape, generator=g).to(dev, torch.bfloat16)
                    tot += predict(
                        zz,
                        emb[None].to(dev, torch.bfloat16),
                        mask[None].to(dev),
                        torch.tensor([sg], device=dev),
                        noise,
                    ).item()
                    n += 1
        tr.train()
        return tot / n

    steps = int(job["steps"])
    every = max(50, steps // 6)
    first = check()
    emit(event="check", step=0, loss=first)
    last = first
    emit(event="status", message="Learning")
    for step in range(1, steps + 1):
        t0 = time.time()
        z, emb, mask = random.choice(samples)
        zz = z[None].to(dev, torch.bfloat16)
        sig = torch.sigmoid(torch.randn(1, device=dev))
        loss = predict(
            zz, emb[None].to(dev, torch.bfloat16), mask[None].to(dev), sig, torch.randn_like(zz)
        )
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        opt.step()
        if dev.type == "mps":
            torch.mps.synchronize()
        emit(
            event="progress",
            step=step,
            total=steps,
            loss=round(loss.item(), 5),
            seconds=round(time.time() - t0, 3),
        )
        if step % every == 0 or step == steps:
            last = check()
            emit(event="check", step=step, loss=last)
    sd = get_peft_model_state_dict(tr)
    os.makedirs(job["out"], exist_ok=True)
    path = os.path.join(job["out"], "pytorch_lora_weights.safetensors")
    save_file(
        {
            "transformer." + k.replace("base_model.model.", "", 1): v.detach()
            .to(torch.bfloat16)
            .cpu()
            .contiguous()
            for k, v in sd.items()
        },
        path,
    )
    peak = torch.mps.driver_allocated_memory() if dev.type == "mps" else 0
    emit(
        event="done",
        seconds=round(time.time() - started, 1),
        peak_bytes=int(peak),
        adapter=path,
        loss_first=first,
        loss_last=last,
    )


if __name__ == "__main__":
    main()
