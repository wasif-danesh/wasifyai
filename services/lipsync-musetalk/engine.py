"""MuseTalk v1.5 (MIT) as a function: a picture and a voice in, an MP4 out (ADR-0044).

MuseTalk redraws the mouth area of a face to match the speech and leaves the rest of the picture
as it is. This file wraps its modules (`MUSETALK_DIR`, cloned by setup.sh) for a still image.
It differs from MuseTalk's own `scripts/inference.py` in two ways. The 68 face landmarks come from
the `face-alignment` package instead of mmpose/DWPose, which need CUDA-only packages that do not
install on a Mac. And the device is chosen at start: MPS on Apple silicon, CUDA elsewhere."""

import copy
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import cv2
import numpy as np
import torch


def _musetalk_dir() -> Path:
    """MUSETALK_DIR, or the repo's .lipsync/musetalk/src when run from a checkout."""
    if os.environ.get("MUSETALK_DIR"):
        return Path(os.environ["MUSETALK_DIR"]).resolve()
    return Path(__file__).resolve().parents[2] / ".lipsync" / "musetalk" / "src"


MUSETALK_DIR = _musetalk_dir()
MAX_SIDE = int(os.environ.get("LIPSYNC_MAX_SIDE", "768"))  # the picture is scaled down to this
MARGIN = 10  # extra pixels below the chin MuseTalk v1.5 asks for


class NoFace(Exception):
    """No face could be found in the picture."""


def _pick_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class Engine:
    def __init__(self) -> None:
        self.device = os.environ.get("LIPSYNC_DEVICE") or _pick_device()
        self._lock = threading.Lock()  # one clip at a time: the models are one set on one GPU
        self._ready = False

    def load(self) -> None:
        if self._ready:
            return
        sys.path.insert(0, str(MUSETALK_DIR))
        os.chdir(MUSETALK_DIR)  # MuseTalk reads ./models/... relative to its folder
        _load = torch.load  # its .pth files are old pickles from the project's own release
        torch.load = lambda *a, **k: _load(*a, **{**k, "weights_only": False})
        import face_alignment
        from musetalk.utils.audio_processor import AudioProcessor
        from musetalk.utils.blending import get_image
        from musetalk.utils.face_parsing import FaceParsing
        from musetalk.utils.utils import datagen, load_all_model
        from transformers import WhisperModel

        dev = torch.device(self.device)
        vae, unet, pe = load_all_model(
            "./models/musetalkV15/unet.pth", "sd-vae", "./models/musetalkV15/musetalk.json", dev
        )
        half = self.device == "cuda"  # fp16 on CUDA; MPS and CPU stay in fp32
        if half:
            pe, vae.vae, unet.model = pe.half(), vae.vae.half(), unet.model.half()
        self.pe, self.vae, self.unet = pe.to(dev), vae, unet
        self.vae.vae = self.vae.vae.to(dev)
        self.unet.model = self.unet.model.to(dev)
        self.dtype = self.unet.model.dtype
        self.audio = AudioProcessor(feature_extractor_path="./models/whisper")
        self.whisper = WhisperModel.from_pretrained("./models/whisper")
        self.whisper = self.whisper.to(device=dev, dtype=self.dtype).eval()
        self.parser = FaceParsing(left_cheek_width=90, right_cheek_width=90)
        # landmarks run on the CPU: one picture, a few seconds, and it avoids unsupported MPS ops
        self.aligner = face_alignment.FaceAlignment(
            face_alignment.LandmarksType.TWO_D, device="cuda" if half else "cpu"
        )
        self._get_image, self._datagen = get_image, datagen
        self._ready = True

    def _crop(self, frame: np.ndarray) -> tuple[int, int, int, int]:
        """MuseTalk's face crop from the 68 landmarks: from as far above the nose bridge as the chin
        is below it, down to the chin (what DWPose gave it in `preprocessing.py`)."""
        found = self.aligner.get_landmarks(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        if not found:
            raise NoFace
        lm = found[0].astype(np.int32)
        mid = lm[29]
        top = int(max(0, mid[1] - (np.max(lm[:, 1]) - mid[1])))
        x1, x2, y2 = int(np.min(lm[:, 0])), int(np.max(lm[:, 0])), int(np.max(lm[:, 1]))
        y2 = min(y2 + MARGIN, frame.shape[0])
        if x1 < 0 or x2 - x1 < 32 or y2 - top < 32:
            raise NoFace
        return x1, top, x2, y2

    def generate(self, picture: bytes, voice_path: str, fps: int = 25, batch: int = 8) -> bytes:
        with self._lock, torch.no_grad():
            self.load()
            frame = cv2.imdecode(np.frombuffer(picture, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                raise NoFace
            scale = MAX_SIDE / max(frame.shape[:2])
            if scale < 1:
                frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            h, w = frame.shape[:2]
            frame = frame[: h // 2 * 2, : w // 2 * 2]  # H.264 needs an even width and height
            x1, y1, x2, y2 = self._crop(frame)
            crop = cv2.resize(frame[y1:y2, x1:x2], (256, 256), interpolation=cv2.INTER_LANCZOS4)
            latent = self.vae.get_latents_for_unet(crop)

            dev = torch.device(self.device)
            feats, length = self.audio.get_audio_feature(voice_path)
            chunks = self.audio.get_whisper_chunk(
                feats, dev, self.dtype, self.whisper, length, fps=fps,
                audio_padding_length_left=2, audio_padding_length_right=2,
            )  # fmt: skip
            frames = []
            gen = self._datagen(
                whisper_chunks=chunks, vae_encode_latents=[latent], batch_size=batch,
                delay_frame=0, device=dev,
            )  # fmt: skip
            for whisper_batch, latent_batch in gen:
                pred = self.unet.model(
                    latent_batch.to(dtype=self.dtype), torch.tensor([0], device=dev),
                    encoder_hidden_states=self.pe(whisper_batch),
                ).sample  # fmt: skip
                frames.extend(self.vae.decode_latents(pred))

            with tempfile.TemporaryDirectory(prefix="wasifyai-lipsync-") as tmp:
                mp4 = Path(tmp) / "clip.mp4"
                h, w = frame.shape[:2]
                # the blended frames go straight to ffmpeg: a long song is thousands of frames
                enc = subprocess.Popen(
                    [_ffmpeg(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                     "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", "-i", voice_path,
                     "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-c:a", "aac",
                     "-shortest", str(mp4)],
                    stdin=subprocess.PIPE,
                )  # fmt: skip
                assert enc.stdin is not None
                try:
                    for res in frames:
                        mouth = cv2.resize(res.astype(np.uint8), (x2 - x1, y2 - y1))
                        out = self._get_image(
                            copy.deepcopy(frame),
                            mouth,
                            [x1, y1, x2, y2],
                            mode="jaw",
                            fp=self.parser,
                        )
                        enc.stdin.write(np.ascontiguousarray(out).tobytes())
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
