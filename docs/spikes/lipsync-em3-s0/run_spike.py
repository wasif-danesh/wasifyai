"""EchoMimic v3 flash on Apple silicon (MPS): one spike run, measured.

A picture and a voice give an MP4. Voices longer than one window are made window by window: each window
starts from the last frame of the one before (the audio features are made once for the whole voice and
sliced). Mac fixes are applied here, not in their code: the rotary table and the time embedding avoid
float64 and complex numbers on the GPU. The text encoder is used once for the prompts and then freed.

    venv/bin/python run_spike.py --image p.png --audio v.wav --size 512 --out out.mp4 [--frames 81] [--max-s 10]
"""

import argparse
import gc
import json
import math
import resource
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
CODE = HERE / "code"
WEIGHTS = Path("/Volumes/AI-1TB/wasify-models/echomimic-v3")
sys.path.insert(0, str(CODE))

import contextlib  # noqa: E402


def _autocast(enabled=True, dtype=torch.float16, cache_enabled=True):
    """Their code asks for CUDA autocast, which is off on a Mac: give MPS autocast instead. A float32
    request keeps whatever is around it (MPS autocast takes only half types)."""
    if not enabled:
        return torch.autocast("mps", enabled=False)
    if dtype == torch.float32:
        return contextlib.nullcontext()
    return torch.autocast("mps", dtype=dtype)


torch.cuda.amp.autocast = _autocast

import librosa  # noqa: E402
import pyloudnorm as pyln  # noqa: E402
from einops import rearrange  # noqa: E402
from omegaconf import OmegaConf  # noqa: E402
from PIL import Image  # noqa: E402
from transformers import AutoTokenizer, Wav2Vec2FeatureExtractor  # noqa: E402

import src.wan_transformer3d_audio_2512 as wt  # noqa: E402
from src.fm_solvers_unipc import FlowUniPCMultistepScheduler  # noqa: E402
from src.pipeline_wan_fun_inpaint_audio_2512 import WanFunInpaintAudioPipeline  # noqa: E402
from src.utils import filter_kwargs, get_image_to_video_latent2  # noqa: E402
from src.wan_image_encoder import CLIPModel  # noqa: E402
from src.wan_text_encoder import WanT5EncoderModel  # noqa: E402
from src.wan_vae import AutoencoderKLWan  # noqa: E402
from src.wav2vec2 import Wav2Vec2Model  # noqa: E402
from diffusers import FlowMatchEulerDiscreteScheduler  # noqa: E402

NEG = ("Gesture is bad. Gesture is unclear. Strange and twisted hands. Bad hands. Bad fingers. "
       "Unclear and blurry hands. Unclear gestures, broken hands, fused fingers. 手指融合，")
DEV = torch.device("mps")
DT = torch.bfloat16


# ---- Mac fixes ----------------------------------------------------------------------------------
def sinusoidal_embedding_1d(dim, position):
    """As theirs, in float64 on the CPU (MPS has no float64), then back to the caller's device."""
    half = dim // 2
    pos = position.detach().cpu().double()  # move first: casting on MPS fails
    sinusoid = torch.outer(pos, torch.pow(10000, -torch.arange(half).to(pos).div(half)))
    x = torch.cat([torch.cos(sinusoid), torch.sin(sinusoid)], dim=1)
    return x.to(position.device, torch.float32)


def rope_apply(x, grid_sizes, freqs):
    """As theirs with real numbers: `freqs` is [S, C, 2] (cos, sin) in float32."""
    n, c = x.size(2), x.size(3) // 2
    parts = freqs.split([c - 2 * (c // 3), c // 3, c // 3], dim=1)
    out = []
    for i, (f, h, w) in enumerate(grid_sizes.tolist()):
        seq = f * h * w
        xi = x[i, :seq].to(torch.float32).reshape(seq, n, -1, 2)
        fi = torch.cat([
            parts[0][:f].view(f, 1, 1, -1, 2).expand(f, h, w, -1, 2),
            parts[1][:h].view(1, h, 1, -1, 2).expand(f, h, w, -1, 2),
            parts[2][:w].view(1, 1, w, -1, 2).expand(f, h, w, -1, 2),
        ], dim=3).reshape(seq, 1, -1, 2)
        a, b = xi[..., 0], xi[..., 1]
        cos, sin = fi[..., 0], fi[..., 1]
        yi = torch.stack([a * cos - b * sin, a * sin + b * cos], dim=-1).flatten(2)
        out.append(torch.cat([yi, x[i, seq:].to(torch.float32)]))
    return torch.stack(out).float()


wt.sinusoidal_embedding_1d = sinusoidal_embedding_1d
wt.rope_apply = rope_apply
WanFunInpaintAudioPipeline._execution_device = property(lambda self: DEV)


class _Freed:
    """Stands in for the text encoder once the prompts are encoded (the pipeline reads its dtype)."""
    dtype = DT


class _Embeds(list):
    @property
    def shape(self):
        return (len(self),)


# ---- memory ---------------------------------------------------------------------------------------
class Peak:
    def __init__(self):
        self.gpu = 0
        self._stop = False
        self._t = threading.Thread(target=self._poll, daemon=True)
        self._t.start()

    def _poll(self):
        while not self._stop:
            self.gpu = max(self.gpu, torch.mps.driver_allocated_memory())
            time.sleep(0.25)

    def stop(self):
        self._stop = True
        self._t.join()


def gb(n):
    return round(n / 1e9, 2)


# ---- the run --------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--frames", type=int, default=81, help="frames per window")
    ap.add_argument("--max-s", type=float, default=3.24, help="longest voice to use, in seconds")
    ap.add_argument("--steps", type=int, default=8)
    ap.add_argument("--sampler", default="unipc", choices=["unipc", "euler"])
    ap.add_argument("--teacache", type=float, default=0.1)
    ap.add_argument("--prompt", default="A person is speaking.")
    ap.add_argument("--seed", type=int, default=43)
    ap.add_argument("--clip-original", action="store_true", help="every window's identity image is the picture")
    a = ap.parse_args()

    peak = Peak()
    t0 = time.monotonic()
    base = WEIGHTS / "Wan2.1-Fun-V1.1-1.3B-InP"
    cfg = OmegaConf.load(CODE / "config" / "config.yaml")

    w2v_dir = WEIGHTS / "chinese-wav2vec2-base"
    audio_encoder = Wav2Vec2Model.from_pretrained(str(w2v_dir), local_files_only=True).to("cpu")
    audio_encoder.feature_extractor._freeze_parameters()
    feat = Wav2Vec2FeatureExtractor.from_pretrained(str(w2v_dir), local_files_only=True)

    transformer = wt.WanTransformerAudioMask3DModel.from_pretrained(
        str(base / cfg["transformer_additional_kwargs"].get("transformer_subpath", "transformer")),
        transformer_additional_kwargs=OmegaConf.to_container(cfg["transformer_additional_kwargs"]),
        low_cpu_mem_usage=True, torch_dtype=DT,
    )
    from safetensors.torch import load_file
    sd = load_file(str(WEIGHTS / "flash" / "echomimicv3-flash-pro" / "diffusion_pytorch_model.safetensors"))
    m, u = transformer.load_state_dict(sd, strict=False)
    del sd
    print(f"flash weights: missing {len(m)}, unexpected {len(u)}", flush=True)
    fr = transformer.freqs.to(torch.complex64)
    transformer.freqs = torch.stack([fr.real, fr.imag], dim=-1).float()  # [S, C, 2]

    vae = AutoencoderKLWan.from_pretrained(
        str(base / cfg["vae_kwargs"].get("vae_subpath", "vae")),
        additional_kwargs=OmegaConf.to_container(cfg["vae_kwargs"]),
    ).to(DT)
    tok = AutoTokenizer.from_pretrained(str(base / cfg["text_encoder_kwargs"].get("tokenizer_subpath")))
    text_encoder = WanT5EncoderModel.from_pretrained(
        str(base / cfg["text_encoder_kwargs"].get("text_encoder_subpath")),
        additional_kwargs=OmegaConf.to_container(cfg["text_encoder_kwargs"]),
        low_cpu_mem_usage=True, torch_dtype=DT,
    ).eval()
    clip = CLIPModel.from_pretrained(
        str(base / cfg["image_encoder_kwargs"].get("image_encoder_subpath"))
    ).to(DT).eval()

    if a.sampler == "unipc":
        cfg["scheduler_kwargs"]["shift"] = 1
        Sched = FlowUniPCMultistepScheduler
    else:
        Sched = FlowMatchEulerDiscreteScheduler
    sched = Sched(**filter_kwargs(Sched, OmegaConf.to_container(cfg["scheduler_kwargs"])))
    pipe = WanFunInpaintAudioPipeline(
        transformer=transformer, vae=vae, tokenizer=tok, text_encoder=text_encoder,
        scheduler=sched, clip_image_encoder=clip,
    )
    pipe.to(device=DEV)
    if a.teacache > 0:
        from src.cache_utils import get_teacache_coefficients
        coef = get_teacache_coefficients(str(base))
        if coef is not None:
            pipe.transformer.enable_teacache(coef, a.steps, a.teacache, num_skip_start_steps=5, offload=False)

    with torch.no_grad():
        pe, ne = pipe.encode_prompt(a.prompt, NEG, True, device=DEV, dtype=DT)
    pe, ne = _Embeds(pe), _Embeds(ne)  # the pipeline reads .shape[0] for the batch size
    pipe.text_encoder = _Freed()
    del text_encoder
    gc.collect()
    torch.mps.empty_cache()
    load_s = time.monotonic() - t0
    print(f"loaded in {load_s:.1f}s, gpu now {gb(torch.mps.driver_allocated_memory())} GB", flush=True)

    # ---- audio: features for the whole voice, once ----
    fps = 25
    wav, sr = librosa.load(a.audio, sr=16000)
    wav = wav[: int(a.max_s * sr)]
    meter = pyln.Meter(sr)
    loud = meter.integrated_loudness(wav)
    if abs(loud) <= 100:
        wav = pyln.normalize.loudness(wav, loud, -23)
    total = int(len(wav) / sr * fps)
    with torch.no_grad():
        iv = torch.from_numpy(np.squeeze(feat(wav, sampling_rate=sr).input_values)).float().unsqueeze(0)
        emb = audio_encoder(iv, seq_len=total, output_hidden_states=True)
    emb = rearrange(torch.stack(emb.hidden_states[1:], dim=1).squeeze(0), "b s d -> s b d")  # [F, 12, 768]
    idx = torch.arange(total).unsqueeze(1) + (torch.arange(5) - 2).unsqueeze(0)
    emb = emb[idx.clamp(0, emb.shape[0] - 1)]  # [F, 5, 12, 768]

    # ---- windows ----
    ref = Image.open(a.image).convert("RGB")
    w0, h0 = ref.size
    r = math.sqrt(w0 * h0 / (a.size * a.size))
    W, H = int(w0 / r // 16 * 16), int(h0 / r // 16 * 16)
    frames: list[np.ndarray] = []
    windows = []
    start, img = 0, ref
    while start < total - 1 or not frames:
        n = min(a.frames, total - start)
        n = (n - 1) // 4 * 4 + 1
        if n < 5:
            break
        tw = time.monotonic()
        ae = emb[start : start + n].unsqueeze(0).to(DEV, DT)
        video, mask, clip_img = get_image_to_video_latent2(img, None, video_length=n, sample_size=[H, W])
        if a.clip_original and img is not ref:
            clip_img = get_image_to_video_latent2(ref, None, video_length=n, sample_size=[H, W])[2]
        gen = torch.Generator(device=DEV).manual_seed(a.seed)
        with torch.no_grad():
            out = pipe(
                None, num_frames=n, audio_embeds=ae, audio_scale=1.0, ip_mask=None, use_un_ip_mask=False,
                height=H, width=W, generator=gen, neg_scale=1.0, neg_steps=0,
                guidance_scale=6.0, audio_guidance_scale=3.0, num_inference_steps=a.steps,
                video=video, mask_video=mask, clip_image=clip_img, cfg_skip_ratio=0.0, shift=5.0,
                prompt_embeds=pe, negative_prompt_embeds=ne,
            ).videos  # [1, 3, F, H, W] in 0..1
        torch.mps.synchronize()
        clipf = (out[0, :, :n].permute(1, 2, 3, 0).float().cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
        keep = clipf if not frames else clipf[1:]  # the first frame repeats the last one
        frames.extend(list(keep))
        ws = time.monotonic() - tw
        windows.append({"start": start, "frames": n, "work_s": round(ws, 1)})
        print(f"window at {start}: {n} frames in {ws:.1f}s", flush=True)
        img = Image.fromarray(clipf[-1])
        start += n - 1
        torch.mps.empty_cache()

    # ---- write ----
    seconds = len(frames) / fps
    out = Path(a.out)
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps),
         "-i", "-", "-ss", "0", "-t", f"{seconds:.3f}", "-i", a.audio, "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-crf", "18", "-c:a", "aac", "-shortest", str(out)],
        stdin=subprocess.PIPE,
    )
    for f in frames:
        enc.stdin.write(np.ascontiguousarray(f).tobytes())
    enc.stdin.close()
    enc.wait()
    peak.stop()
    work = sum(w["work_s"] for w in windows)
    res = {
        "image": Path(a.image).name, "audio": Path(a.audio).name, "size": [W, H], "sampler": a.sampler,
        "steps": a.steps, "teacache": a.teacache, "video_s": round(seconds, 2), "load_s": round(load_s, 1),
        "work_s": round(work, 1), "work_per_video_s": round(work / seconds, 1) if seconds else None,
        "peak_gpu_gb": gb(peak.gpu), "max_rss_gb": gb(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
        "windows": windows, "clip_original": a.clip_original, "torch": torch.__version__,
    }
    print(json.dumps(res), flush=True)
    out.with_suffix(".json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
