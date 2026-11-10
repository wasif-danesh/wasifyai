"""S1: speed levers for EchoMimic v3 flash on MPS. Loads once, runs every variant in a JSON file.

    venv/bin/python bench.py variants.json [--fp16]

A variant: {"name", "image", "audio", "max_s", "size", "steps", "teacache", "skip_start", "cfg_skip",
            "frames", "fix_cond", "colour"}; missing keys take the S0 settings.
fix_cond: the pass without the voice is told it is that pass (their pipeline never says so, so TeaCache
reuses the voiced pass's result for it and the audio guidance fades out after the first steps).
colour: every frame is matched to the picture's colour (mean and spread in Lab), so drift cannot pile up.
"""

import json
import math
import resource
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch

import run_spike as rs  # the Mac fixes and the loading code of S0
from src.cache_utils import get_teacache_coefficients

from PIL import Image

S0 = {"max_s": 3.24, "size": 512, "steps": 8, "teacache": 0.1, "skip_start": 5, "cfg_skip": 0.0,
      "frames": 81, "fix_cond": False, "colour": False, "seed": 43}


def load(dtype):
    rs.DT = dtype
    rs._Freed.dtype = dtype
    base = rs.WEIGHTS / "Wan2.1-Fun-V1.1-1.3B-InP"
    cfg = rs.OmegaConf.load(rs.CODE / "config" / "config.yaml")
    w2v = rs.WEIGHTS / "chinese-wav2vec2-base"
    audio_encoder = rs.Wav2Vec2Model.from_pretrained(str(w2v), local_files_only=True).to("cpu")
    audio_encoder.feature_extractor._freeze_parameters()
    feat = rs.Wav2Vec2FeatureExtractor.from_pretrained(str(w2v), local_files_only=True)
    tr = rs.wt.WanTransformerAudioMask3DModel.from_pretrained(
        str(base / "./"), transformer_additional_kwargs=rs.OmegaConf.to_container(cfg["transformer_additional_kwargs"]),
        low_cpu_mem_usage=True, torch_dtype=dtype,
    )
    from safetensors.torch import load_file
    sd = load_file(str(rs.WEIGHTS / "flash" / "echomimicv3-flash-pro" / "diffusion_pytorch_model.safetensors"))
    tr.load_state_dict(sd, strict=False)
    del sd
    fr = tr.freqs.to(torch.complex64)
    tr.freqs = torch.stack([fr.real, fr.imag], dim=-1).float()
    vae = rs.AutoencoderKLWan.from_pretrained(
        str(base / cfg["vae_kwargs"]["vae_subpath"]), additional_kwargs=rs.OmegaConf.to_container(cfg["vae_kwargs"]),
    ).to(dtype)
    tok = rs.AutoTokenizer.from_pretrained(str(base / cfg["text_encoder_kwargs"]["tokenizer_subpath"]))
    te = rs.WanT5EncoderModel.from_pretrained(
        str(base / cfg["text_encoder_kwargs"]["text_encoder_subpath"]),
        additional_kwargs=rs.OmegaConf.to_container(cfg["text_encoder_kwargs"]), low_cpu_mem_usage=True,
        torch_dtype=dtype,
    ).eval()
    clip = rs.CLIPModel.from_pretrained(str(base / cfg["image_encoder_kwargs"]["image_encoder_subpath"])).to(dtype).eval()
    cfg["scheduler_kwargs"]["shift"] = 1
    sched = rs.FlowUniPCMultistepScheduler(
        **rs.filter_kwargs(rs.FlowUniPCMultistepScheduler, rs.OmegaConf.to_container(cfg["scheduler_kwargs"]))
    )
    pipe = rs.WanFunInpaintAudioPipeline(
        transformer=tr, vae=vae, tokenizer=tok, text_encoder=te, scheduler=sched, clip_image_encoder=clip,
    )
    pipe.to(device=rs.DEV)
    with torch.no_grad():
        pe, ne = pipe.encode_prompt("A person is speaking.", rs.NEG, True, device=rs.DEV, dtype=dtype)
    pipe.text_encoder = rs._Freed()
    del te
    import gc
    gc.collect()
    torch.mps.empty_cache()
    print(f"gpu after load and freeing the text encoder: {rs.gb(torch.mps.driver_allocated_memory())} GB", flush=True)
    return pipe, rs._Embeds(pe), rs._Embeds(ne), audio_encoder, feat, get_teacache_coefficients(str(base))


class Timer:
    """Counts and times the transformer's passes and the VAE decode."""

    def __init__(self, pipe, fix_cond):
        self.passes = self.skipped = 0
        self.denoise_s = self.decode_s = 0.0
        tr, self.pipe = pipe.transformer, pipe
        self._fwd, self._dec = tr.forward, pipe.decode_latents
        timer = self

        def fwd(*args, **kw):
            if fix_cond:
                kw["cond_flag"] = not bool((kw["context"][1] == 0).all())
            t = time.monotonic()
            out = timer._fwd(*args, **kw)
            torch.mps.synchronize()
            timer.denoise_s += time.monotonic() - t
            timer.passes += 1
            if tr.teacache is not None and not tr.teacache.should_calc:
                timer.skipped += 1
            return out

        def dec(*args, **kw):
            t = time.monotonic()
            out = timer._dec(*args, **kw)
            timer.decode_s += time.monotonic() - t
            return out

        tr.forward, pipe.decode_latents = fwd, dec

    def close(self):
        self.pipe.transformer.forward, self.pipe.decode_latents = self._fwd, self._dec


def lab_stats(img):
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB).astype(np.float32)
    return lab.reshape(-1, 3).mean(0), lab.reshape(-1, 3).std(0) + 1e-6


def match(img, target):
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB).astype(np.float32)
    m, s = lab.reshape(-1, 3).mean(0), lab.reshape(-1, 3).std(0) + 1e-6
    lab = (lab - m) / s * target[1] + target[0]
    return cv2.cvtColor(lab.clip(0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)


def audio_embeds(path, max_s, audio_encoder, feat):
    wav, sr = rs.librosa.load(path, sr=16000)
    wav = wav[: int(max_s * sr)]
    loud = rs.pyln.Meter(sr).integrated_loudness(wav)
    if abs(loud) <= 100:
        wav = rs.pyln.normalize.loudness(wav, loud, -23)
    total = int(len(wav) / sr * 25)
    with torch.no_grad():
        iv = torch.from_numpy(np.squeeze(feat(wav, sampling_rate=sr).input_values)).float().unsqueeze(0)
        e = audio_encoder(iv, seq_len=total, output_hidden_states=True)
    e = rs.rearrange(torch.stack(e.hidden_states[1:], dim=1).squeeze(0), "b s d -> s b d")
    idx = torch.arange(total).unsqueeze(1) + (torch.arange(5) - 2).unsqueeze(0)
    return e[idx.clamp(0, e.shape[0] - 1)], total


def run(v, pipe, pe, ne, audio_encoder, feat, coef, outdir, dtype):
    v = {**S0, **v}
    tr = pipe.transformer
    if v["teacache"] > 0:
        # S0 behaviour: the count runs per call but is set per step. With fix_cond both are per call.
        k = 2 if v["fix_cond"] else 1
        calls = v["steps"] * k
        tr.enable_teacache(coef, calls, v["teacache"], num_skip_start_steps=min(v["skip_start"] * k, calls), offload=False)
    else:
        tr.disable_teacache()
    emb, total = audio_embeds(v["audio"], v["max_s"], audio_encoder, feat)
    ref = Image.open(v["image"]).convert("RGB")
    w0, h0 = ref.size
    r = math.sqrt(w0 * h0 / (v["size"] ** 2))
    W, H = int(w0 / r // 16 * 16), int(h0 / r // 16 * 16)
    target = lab_stats(np.array(ref.resize((W, H), Image.LANCZOS)))
    timer = Timer(pipe, v["fix_cond"])
    t0 = time.monotonic()
    frames, start, img, wins = [], 0, ref, []
    while start < total - 1 or not frames:
        n = (min(v["frames"], total - start) - 1) // 4 * 4 + 1
        if n < 5:
            break
        if tr.teacache is not None:
            tr.teacache.reset()
        tw = time.monotonic()
        ae = emb[start : start + n].unsqueeze(0).to(rs.DEV, dtype)
        video, mask, clip_img = rs.get_image_to_video_latent2(img, None, video_length=n, sample_size=[H, W])
        gen = torch.Generator(device=rs.DEV).manual_seed(v["seed"])
        with torch.no_grad():
            out = pipe(
                None, num_frames=n, audio_embeds=ae, audio_scale=1.0, ip_mask=None, use_un_ip_mask=False,
                height=H, width=W, generator=gen, neg_scale=1.0, neg_steps=0, guidance_scale=6.0,
                audio_guidance_scale=3.0, num_inference_steps=v["steps"], video=video, mask_video=mask,
                clip_image=clip_img, cfg_skip_ratio=v["cfg_skip"], shift=5.0, prompt_embeds=pe,
                negative_prompt_embeds=ne,
            ).videos
        torch.mps.synchronize()
        clipf = (out[0, :, :n].permute(1, 2, 3, 0).float().cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
        if v["colour"]:
            clipf = np.stack([match(f, target) for f in clipf])
        frames.extend(list(clipf if not frames else clipf[1:]))
        wins.append(round(time.monotonic() - tw, 1))
        img = Image.fromarray(clipf[-1])
        start += n - 1
        torch.mps.empty_cache()
    work = time.monotonic() - t0
    timer.close()
    secs = len(frames) / 25
    mp4 = outdir / f"{v['name']}.mp4"
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", "25", "-i", "-",
         "-t", f"{secs:.3f}", "-i", v["audio"], "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-c:a", "aac",
         "-shortest", str(mp4)], stdin=subprocess.PIPE,
    )  # fmt: skip
    for f in frames:
        enc.stdin.write(np.ascontiguousarray(f).tobytes())
    enc.stdin.close()
    enc.wait()
    res = {**{k: v[k] for k in v if k not in ("image", "audio")}, "image": Path(v["image"]).name,
           "audio": Path(v["audio"]).name, "dtype": str(dtype).split(".")[-1], "px": [W, H],
           "video_s": round(secs, 2), "work_s": round(work, 1), "per_video_s": round(work / secs, 1),
           "denoise_s": round(timer.denoise_s, 1), "decode_s": round(timer.decode_s, 1),
           "passes": timer.passes, "cached_passes": timer.skipped, "windows_s": wins,
           "max_rss_gb": rs.gb(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)}
    print(json.dumps(res), flush=True)
    with (outdir / "s1-results.jsonl").open("a") as fh:
        fh.write(json.dumps(res) + "\n")


def main():
    variants = json.loads(Path(sys.argv[1]).read_text())
    dtype = torch.float16 if "--fp16" in sys.argv else torch.bfloat16
    outdir = rs.HERE / "out" / "s1"
    outdir.mkdir(parents=True, exist_ok=True)
    t = time.monotonic()
    pipe, pe, ne, ae, feat, coef = load(dtype)
    print(f"loaded in {time.monotonic() - t:.1f}s", flush=True)
    for v in variants:
        try:
            run(v, pipe, pe, ne, ae, feat, coef, outdir, dtype)
        except Exception as e:  # keep going: one bad variant should not stop the rest
            print(json.dumps({"name": v["name"], "error": repr(e)[:300]}), flush=True)


if __name__ == "__main__":
    main()
