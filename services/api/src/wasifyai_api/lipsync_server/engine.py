"""EchoMimic v3 flash (Apache-2.0) as a function: a picture and a voice in, an MP4 out (ADR-0066).

The whole picture moves with the voice: head, eyes and mouth. This file wraps EchoMimic's modules
(`ECHOMIMIC_DIR`, the pinned source) with the settings measured on an Apple-silicon Mac
(`docs/spikes/lipsync-echomimic-v3-s1.md`): about 448 px, 8 steps, UniPC, TeaCache 0.2 after 2
steps, bf16. A voice is made in windows of 81 frames; each window starts from the last frame of
the one before, and every frame is matched to the picture's colour so the face does not drift
paler.

It differs from EchoMimic's `infer_flash.py` in these ways, all here and none in their code:
- the prompts are fixed and shipped already encoded (`echomimic_prompts.safetensors`,
  `make_prompts.py`), so the 11 GB text encoder is never loaded;
- the flash weights are loaded straight, without the base model's (they replace every weight);
- on MPS: the time embedding is made in float64 on the CPU (MPS has no float64), the rotary table
  is real cos and sin pairs in float32 (MPS has no complex128), and CUDA autocast becomes MPS
  autocast;
- the frames go to ffmpeg as each window is made, so a long voice is not held in memory.

The weights are laid out under `LIPSYNC_WEIGHTS` by the sidecar (see `lipsync_runtime.WEIGHTS`)."""

import contextlib
import math
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import cv2
import numpy as np
import torch

# the side of a square of the same area as the video
SIZE = int(os.environ.get("LIPSYNC_SIZE", "448"))
FRAMES = 81  # frames per window (3.24 s at 25 fps), as the model was trained
STEPS = 8
TEACACHE = 0.2
FORCED_STEPS = 2  # steps TeaCache always computes
FPS = 25  # the model's own rate
AUDIO_GUIDANCE = 3.0
SEED = 43
PROMPTS = Path(__file__).with_name("echomimic_prompts.safetensors")


class NoFace(Exception):
    """The picture could not be read (EchoMimic needs no face box: any readable picture works)."""


def _echomimic_dir() -> Path:
    if os.environ.get("ECHOMIMIC_DIR"):
        return Path(os.environ["ECHOMIMIC_DIR"]).resolve()
    return Path(__file__).resolve().parents[2] / ".lipsync" / "echomimic" / "src"


def _weights_dir() -> Path:
    return Path(os.environ.get("LIPSYNC_WEIGHTS") or _echomimic_dir().parent / "weights").resolve()


def _pick_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


# ---- fixes for Apple silicon (also correct elsewhere) --------------------------------------------


def _sinusoidal_embedding_1d(dim: int, position: torch.Tensor) -> torch.Tensor:
    """EchoMimic's time embedding, in float64 on the CPU, then back. Moving first matters: a
    float64 cast of an MPS tensor fails."""
    half = dim // 2
    pos = position.detach().cpu().double()
    sinusoid = torch.outer(pos, torch.pow(10000, -torch.arange(half).to(pos).div(half)))
    x = torch.cat([torch.cos(sinusoid), torch.sin(sinusoid)], dim=1)
    return x.to(position.device, torch.float32)


def _rope_apply(x: torch.Tensor, grid_sizes: torch.Tensor, freqs: torch.Tensor) -> torch.Tensor:
    """EchoMimic's rotary embedding in real numbers: `freqs` is [S, C, 2] (cos, sin), float32."""
    n, c = x.size(2), x.size(3) // 2
    parts = freqs.split([c - 2 * (c // 3), c // 3, c // 3], dim=1)
    out = []
    for i, (f, h, w) in enumerate(grid_sizes.tolist()):
        seq = f * h * w
        xi = x[i, :seq].to(torch.float32).reshape(seq, n, -1, 2)
        fi = torch.cat(
            [
                parts[0][:f].view(f, 1, 1, -1, 2).expand(f, h, w, -1, 2),
                parts[1][:h].view(1, h, 1, -1, 2).expand(f, h, w, -1, 2),
                parts[2][:w].view(1, 1, w, -1, 2).expand(f, h, w, -1, 2),
            ],
            dim=3,
        ).reshape(seq, 1, -1, 2)
        a, b, cos, sin = xi[..., 0], xi[..., 1], fi[..., 0], fi[..., 1]
        yi = torch.stack([a * cos - b * sin, a * sin + b * cos], dim=-1).flatten(2)
        out.append(torch.cat([yi, x[i, seq:].to(torch.float32)]))
    return torch.stack(out).float()


def _mps_autocast(
    enabled: bool = True, dtype: torch.dtype = torch.float16, cache_enabled: bool = True
):
    """Their code asks for CUDA autocast, which is off on a Mac: MPS autocast instead. A float32
    request keeps what is around it (MPS autocast takes only half types)."""
    if not enabled:
        return torch.autocast("mps", enabled=False)
    if dtype == torch.float32:
        return contextlib.nullcontext()
    return torch.autocast("mps", dtype=dtype)


class _Embeds(list):
    """The pipeline reads `prompt_embeds.shape[0]` for the batch size of a list of tensors."""

    @property
    def shape(self) -> tuple[int]:
        return (len(self),)


class _NoTextEncoder:
    """Stands in for the text encoder, which is never loaded: the pipeline only reads its dtype."""

    def __init__(self, dtype: torch.dtype):
        self.dtype = dtype


# ---- colour --------------------------------------------------------------------------------------


def _lab_stats(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32).reshape(-1, 3)
    return lab.mean(0), lab.std(0) + 1e-6


def _match_colour(rgb: np.ndarray, target: tuple[np.ndarray, np.ndarray]) -> np.ndarray:
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    m, s = _lab_stats(rgb)
    lab = (lab - m) / s * target[1] + target[0]
    return cv2.cvtColor(lab.clip(0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)


def _video_size(width: int, height: int) -> tuple[int, int]:
    """The picture's shape at about SIZE x SIZE pixels (never larger), in multiples of 16."""
    r = max(1.0, math.sqrt(width * height / (SIZE * SIZE)))
    return max(16, int(width / r // 16 * 16)), max(16, int(height / r // 16 * 16))


# ---- the engine ----------------------------------------------------------------------------------


class Engine:
    def __init__(self) -> None:
        self.device = os.environ.get("LIPSYNC_DEVICE") or _pick_device()
        self._lock = threading.Lock()  # one clip at a time: one set of models on one GPU
        self._ready = False

    def load(self) -> None:
        if self._ready:
            return
        code, weights = _echomimic_dir(), _weights_dir()
        sys.path.insert(0, str(code))
        if self.device == "mps":
            # before their modules are imported: they decorate with it
            torch.cuda.amp.autocast = _mps_autocast
        from omegaconf import OmegaConf
        from safetensors.torch import load_file
        from src import wan_transformer3d_audio_2512 as wt
        from src.cache_utils import get_teacache_coefficients
        from src.fm_solvers_unipc import FlowUniPCMultistepScheduler
        from src.pipeline_wan_fun_inpaint_audio_2512 import WanFunInpaintAudioPipeline
        from src.utils import filter_kwargs, get_image_to_video_latent2
        from src.wan_image_encoder import CLIPModel
        from src.wan_vae import AutoencoderKLWan
        from src.wav2vec2 import Wav2Vec2Model
        from transformers import Wav2Vec2FeatureExtractor

        wt.sinusoidal_embedding_1d = _sinusoidal_embedding_1d
        wt.rope_apply = _rope_apply
        dev = torch.device(self.device)
        WanFunInpaintAudioPipeline._execution_device = property(lambda _self: dev)
        self.dtype = torch.float32 if self.device == "cpu" else torch.bfloat16

        cfg = OmegaConf.load(code / "config" / "config.yaml")
        w2v = weights / "wav2vec2"
        self.audio_encoder = (
            Wav2Vec2Model.from_pretrained(str(w2v), local_files_only=True).to("cpu").eval()
        )
        self.audio_encoder.feature_extractor._freeze_parameters()
        self.features = Wav2Vec2FeatureExtractor.from_pretrained(str(w2v), local_files_only=True)

        tr = wt.WanTransformerAudioMask3DModel.from_pretrained(
            str(weights / "transformer"),
            transformer_additional_kwargs=OmegaConf.to_container(cfg["transformer_additional_kwargs"]),
            low_cpu_mem_usage=True, torch_dtype=self.dtype,
        )  # fmt: skip
        f = tr.freqs.to(torch.complex64)
        tr.freqs = torch.stack([f.real, f.imag], dim=-1).float()  # [S, C, 2]: see _rope_apply
        vae = AutoencoderKLWan.from_pretrained(
            str(weights / "Wan2.1_VAE.pth"),
            additional_kwargs=OmegaConf.to_container(cfg["vae_kwargs"]),
        ).to(self.dtype)
        clip = CLIPModel.from_pretrained(str(weights / "clip.pth")).to(self.dtype).eval()
        sched_cfg = OmegaConf.to_container(cfg["scheduler_kwargs"])
        # as `infer_flash.py` does for UniPC; the run's own shift is passed per call
        sched_cfg["shift"] = 1
        sched = FlowUniPCMultistepScheduler(**filter_kwargs(FlowUniPCMultistepScheduler, sched_cfg))
        self.pipe = WanFunInpaintAudioPipeline(
            transformer=tr, vae=vae, tokenizer=None, text_encoder=None, scheduler=sched,
            clip_image_encoder=clip,
        )  # fmt: skip
        self.pipe.to(device=dev)
        self.pipe.text_encoder = _NoTextEncoder(self.dtype)
        coef = get_teacache_coefficients("wan2.1-fun-v1.1-1.3b")
        # as EchoMimic runs it: counted per step, so the pass without the voice reuses the voiced
        # one (S1)
        tr.enable_teacache(coef, STEPS, TEACACHE, num_skip_start_steps=FORCED_STEPS, offload=False)
        prompts = load_file(str(PROMPTS))
        self.prompt = _Embeds([prompts["prompt"].to(dev, self.dtype)])
        self.negative = _Embeds([prompts["negative"].to(dev, self.dtype)])
        self._latent = get_image_to_video_latent2
        self._ready = True

    def _audio(self, voice_path: str) -> tuple[torch.Tensor, int]:
        """wav2vec2 features of the whole voice at 25 fps, two frames each side: [F, 5, 12, 768]."""
        import librosa
        import pyloudnorm as pyln
        from einops import rearrange

        wav, sr = librosa.load(voice_path, sr=16000)
        loud = pyln.Meter(sr).integrated_loudness(wav)
        if abs(loud) <= 100:
            wav = pyln.normalize.loudness(wav, loud, -23)
        total = int(len(wav) / sr * FPS)
        values = np.squeeze(self.features(wav, sampling_rate=sr).input_values)
        emb = self.audio_encoder(
            torch.from_numpy(values).float().unsqueeze(0), seq_len=total, output_hidden_states=True
        )
        emb = rearrange(torch.stack(emb.hidden_states[1:], dim=1).squeeze(0), "b s d -> s b d")
        idx = torch.arange(total).unsqueeze(1) + (torch.arange(5) - 2).unsqueeze(0)
        return emb[idx.clamp(0, emb.shape[0] - 1)], total

    def generate(self, picture: bytes, voice_path: str, fps: int = FPS) -> bytes:
        if fps != FPS:
            raise ValueError(f"EchoMimic makes {FPS} frames a second")
        from PIL import Image

        with self._lock, torch.no_grad():
            self.load()
            bgr = cv2.imdecode(np.frombuffer(picture, np.uint8), cv2.IMREAD_COLOR)
            if bgr is None:
                raise NoFace
            ref = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            w, h = _video_size(*ref.size)
            target = _lab_stats(np.array(ref.resize((w, h), Image.LANCZOS)))
            emb, total = self._audio(voice_path)
            if total < 5:
                raise ValueError("the voice is too short")
            dev = torch.device(self.device)
            tr = self.pipe.transformer
            with tempfile.TemporaryDirectory(prefix="wasifyai-lipsync-") as tmp:
                mp4 = Path(tmp) / "clip.mp4"
                args = [
                    _ffmpeg(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                    "-s", f"{w}x{h}", "-r", str(FPS), "-i", "-", "-i", voice_path,
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-c:a", "aac",
                    "-shortest", str(mp4),
                ]  # fmt: skip
                enc = subprocess.Popen(args, stdin=subprocess.PIPE)
                assert enc.stdin is not None
                try:
                    start, image, written = 0, ref, 0
                    while start < total - 1:
                        need = min(FRAMES, total - start)
                        # rounded up to 4k+1 frames, as the VAE needs; the last voice frame
                        # pads the end and the extra frames are not written
                        n = max(5, (need + 2) // 4 * 4 + 1)
                        tr.teacache.reset()
                        video, mask, clip_image = self._latent(
                            image, None, video_length=n, sample_size=[h, w]
                        )
                        idx = torch.arange(start, start + n).clamp(max=total - 1)
                        audio = emb[idx].unsqueeze(0).to(dev, self.dtype)
                        out = self.pipe(
                            None, num_frames=n, audio_embeds=audio, audio_scale=1.0,
                            ip_mask=None, use_un_ip_mask=False, height=h, width=w,
                            generator=torch.Generator(device=dev).manual_seed(SEED),
                            neg_scale=1.0, neg_steps=0, guidance_scale=6.0,
                            audio_guidance_scale=AUDIO_GUIDANCE, num_inference_steps=STEPS,
                            video=video, mask_video=mask, clip_image=clip_image,
                            cfg_skip_ratio=0.0, shift=5.0,
                            prompt_embeds=self.prompt, negative_prompt_embeds=self.negative,
                        ).videos  # fmt: skip
                        frames = (
                            out[0, :, :n].permute(1, 2, 3, 0).float().cpu().numpy() * 255
                        ).clip(0, 255)
                        frames = [_match_colour(f, target) for f in frames[:need].astype(np.uint8)]
                        # a later window's first frame repeats the last one written
                        for f in frames[1:] if written else frames:
                            enc.stdin.write(np.ascontiguousarray(f).tobytes())
                            written += 1
                        image = Image.fromarray(frames[-1])
                        start += need - 1
                        if self.device == "mps":
                            torch.mps.empty_cache()
                finally:
                    enc.stdin.close()
                if enc.wait() != 0:
                    raise RuntimeError("ffmpeg could not encode the clip")
                data = mp4.read_bytes()
            if self.device == "mps":
                torch.mps.empty_cache()
            return data


def _ffmpeg() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"
