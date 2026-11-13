"""The Indian-language speech models as functions (docs/voice-languages-plan.md, stages L5 and L6).

    Speaker   Indic Parler-TTS (AI4Bharat): text and a named speaker in, a WAV out. Bengali, Hindi,
              Marathi, Telugu, Tamil and Gujarati are what the app offers of its languages.
    Writer    IndicConformer 600M (AI4Bharat): a recording and its language in, the words out, with
              rough times. ONNX on the CPU; it must be told the language (finding it by itself
              mistakes Bengali for Hindi, docs/spikes/voice-languages-l0.md).

Each is loaded from a folder the engine laid out (links to the files Models downloaded), on the
first request, and stays loaded. Nothing here reaches the network (HF_HUB_OFFLINE is set)."""

import importlib.util
import io
import re
import sys
import threading
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

# a sentence ends at a full stop of the language (Bengali and Hindi use the danda) or ? and !
_SENTENCE = re.compile(r"(?<=[।॥.!?])\s+")
MAX_CHUNK_CHARS = 220  # Parler keeps its voice steady up to about this much text at a time
PAUSE_S = 0.25  # between sentences
CONFORMER_RATE = 16000
WINDOW_S = 20  # a long recording is written down in parts this long


def pick_device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    return "cuda" if torch.cuda.is_available() else "cpu"


def chunks(text: str) -> list[str]:
    """Sentences, joined while they fit in one chunk; a long sentence is cut at commas or spaces."""
    out: list[str] = []
    for sentence in (s.strip() for s in _SENTENCE.split(text.strip())):
        if not sentence:
            continue
        while len(sentence) > MAX_CHUNK_CHARS:
            cut = max(
                sentence.rfind(",", 0, MAX_CHUNK_CHARS), sentence.rfind(" ", 0, MAX_CHUNK_CHARS)
            )
            cut = cut if cut > 40 else MAX_CHUNK_CHARS
            out.append(sentence[: cut + 1].strip())
            sentence = sentence[cut + 1 :].strip()
        if out and len(out[-1]) + 1 + len(sentence) <= MAX_CHUNK_CHARS:
            out[-1] = f"{out[-1]} {sentence}"
        elif sentence:
            out.append(sentence)
    return out


def describe(speaker: str) -> str:
    """The voice description Parler is conditioned on: the named speaker, clear and natural."""
    return (
        f"{speaker} speaks at a moderate pace with a clear, natural voice. The recording is of "
        "very high quality, with very clear audio and no background noise."
    )


class Speaker:
    def __init__(self, device: str):
        self.device = device
        self._loaded: tuple[str, object, object, object] | None = None
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._loaded is not None

    def _load(self, folder: str) -> tuple[object, object, object]:
        if self._loaded is not None and self._loaded[0] == folder:
            return self._loaded[1], self._loaded[2], self._loaded[3]
        from parler_tts import ParlerTTSForConditionalGeneration
        from transformers import AutoTokenizer

        root = Path(folder)
        dtype = torch.float32 if self.device == "cpu" else torch.float16  # measured in L0
        model = ParlerTTSForConditionalGeneration.from_pretrained(
            str(root / "indic-parler-tts"), torch_dtype=dtype
        ).to(self.device)
        tok = AutoTokenizer.from_pretrained(str(root / "indic-parler-tts"))
        desc = AutoTokenizer.from_pretrained(str(root / "flan-t5-large"))
        self._loaded = (folder, model, tok, desc)
        return model, tok, desc

    def speak(self, folder: str, text: str, speaker: str, seed: int | None = None) -> bytes:
        with self._lock:
            model, tok, desc_tok = self._load(folder)
            rate = model.config.sampling_rate  # type: ignore[attr-defined]
            d = desc_tok(describe(speaker), return_tensors="pt").to(self.device)  # type: ignore[operator]
            pause = np.zeros(int(rate * PAUSE_S), dtype=np.float32)
            parts: list[np.ndarray] = []
            for piece in chunks(text):
                p = tok(piece, return_tensors="pt").to(self.device)  # type: ignore[operator]
                if seed is not None:
                    torch.manual_seed(seed)
                with torch.inference_mode():
                    audio = model.generate(  # type: ignore[attr-defined]
                        input_ids=d.input_ids, attention_mask=d.attention_mask,
                        prompt_input_ids=p.input_ids, prompt_attention_mask=p.attention_mask,
                    )  # fmt: skip
                parts += [audio.to(torch.float32).cpu().numpy().squeeze(), pause]
            if not parts:
                raise ValueError("no text to speak")
            buf = io.BytesIO()
            sf.write(buf, np.concatenate(parts[:-1]), rate, format="WAV", subtype="PCM_16")
            return buf.getvalue()


class Writer:
    def __init__(self) -> None:
        self._loaded: tuple[str, object] | None = None
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._loaded is not None

    def _load(self, folder: str) -> object:
        if self._loaded is not None and self._loaded[0] == folder:
            return self._loaded[1]
        root = Path(folder) / "indic-conformer-600m"
        # the model's own code (pinned with its weights), imported from the laid-out folder
        spec = importlib.util.spec_from_file_location("indic_conformer", root / "model_onnx.py")
        if spec is None or spec.loader is None:
            raise RuntimeError("the IndicConformer code is missing")
        module = importlib.util.module_from_spec(spec)
        sys.modules["indic_conformer"] = module
        spec.loader.exec_module(module)
        model = module.IndicASRModel(
            module.IndicASRConfig(ts_folder=str(root), FRAME_DURATION_MS=0.08)
        )
        self._loaded = (folder, model)
        return model

    def write(self, folder: str, audio: bytes, language: str) -> dict:
        data, rate = sf.read(io.BytesIO(audio), dtype="float32", always_2d=True)
        mono = torch.from_numpy(data.mean(axis=1).copy()).unsqueeze(0)
        if rate != CONFORMER_RATE:
            import torchaudio

            mono = torchaudio.functional.resample(mono, rate, CONFORMER_RATE)
        seconds = mono.shape[-1] / CONFORMER_RATE
        step = WINDOW_S * CONFORMER_RATE
        segments = []
        with self._lock:
            model = self._load(folder)
            for start in range(0, mono.shape[-1], step):
                part = mono[:, start : start + step]
                if part.shape[-1] < CONFORMER_RATE // 4:
                    continue
                with torch.inference_mode():
                    text = model(part, language, "ctc")  # type: ignore[operator]
                text = str(text).strip()
                if text:
                    t0 = start / CONFORMER_RATE
                    segments.append(
                        {"text": text, "start": round(t0, 2),
                         "end": round(min(seconds, t0 + part.shape[-1] / CONFORMER_RATE), 2)}
                    )  # fmt: skip
        return {
            "text": " ".join(s["text"] for s in segments),
            "segments": segments,
            "seconds": round(seconds, 2),
        }
