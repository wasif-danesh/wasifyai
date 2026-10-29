"""The trainer an engine offers the product, and the preview one (ADR-0073 decision 2, ADR-0076).

The product asks `state.training` to train a dataset and hands it a `TrainJob`: the pictures and
their captions as files, a folder for the samples, and the settings. The engine reports how far it
is and writes a sample picture now and then; it returns the adapter file. The real trainers (mflux
on the Mac, then Unsloth's component) are engines of their own that do the same; this package does
not change when they arrive.

`PreviewTrainer` does everything but learn: it runs the same steps, writes sample pictures that say
"Preview" and a small adapter file that is not a model. The screens say so while the engine is a
preview, so nobody mistakes it for a result."""

import asyncio
import json
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance

BASE = "flux2-klein-base-4b"  # what the first LoRA is taught on: the model Create image uses
BASE_TITLE = "FLUX.2 klein base 4B"
# measured on the owner's M5 Pro (ADR-0073, 2026-10-25): 9.2 to 11.6 s a step at 768 pixels, the
# model load and the sample pictures included, and 6.0 s a step at 512 pixels (518 steps in 51 min)
SECONDS_PER_STEP = {512: 6.0, 768: 10.0}
# the longest side of a training picture. A character is taught at 512, as the AI Toolkit run of
# the same 37 pictures was, and drew as well (Create, 2026-10-25); the others stay at 768 until
# they are measured at 512
SIDES = {"character": 512, "style": 768, "object": 768}
# steps. The least a kind needs: a character and an object bound their magic word in 150 to 200
# steps on 10 to 15 pictures; a style learnt the scenes it was shown by 250 steps
PRESETS = {"character": 200, "style": 250, "object": 150}
# a steps count is not a count of passes over the pictures: 200 steps is 18 passes over 11
# pictures and 5 over 37. The run takes about this many passes, never fewer steps than the preset
# and never more than the ceiling (a set of 37 took 518 steps, 14 passes: 51 minutes at 512)
PASSES = 14
MAX_STEPS = 500


@dataclass
class TrainJob:
    kind: str
    word: str
    steps: int
    pictures: list[Path]  # the training pictures, as PNG files
    captions: list[str]  # the same order, the magic word already first
    samples: Path  # a folder for the sample pictures
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass
class TrainResult:
    adapter: Path
    seconds: float
    engine: str
    note: str = ""
    peak_bytes: int = 0  # the most memory the run held, when the engine measures it


class Paused(Exception):
    """The run was paused: its last checkpoint is kept, and it can be picked up again."""

    def __init__(self, step: int = 0):
        super().__init__(f"paused at step {step}")
        self.step = step


class Stopped(Exception):
    """The run was stopped on request and nothing was kept (it had no checkpoint yet)."""


Report = Callable[[int, str], None]
SampleFn = Callable[[str], None]


def steps_for(kind: str, pictures: int) -> int:
    """How many steps to teach `pictures` pictures of this kind."""
    return min(MAX_STEPS, max(PRESETS[kind], PASSES * max(0, pictures)))


def side_for(kind: str) -> int:
    return SIDES.get(kind, 768)


def estimate_seconds(steps: int, kind: str = "character") -> int:
    return round(steps * SECONDS_PER_STEP[side_for(kind)])


def estimate_words(steps: int, kind: str = "character") -> str:
    minutes = max(1, round(estimate_seconds(steps, kind) / 60))
    return f"About {minutes} minutes"


def safetensors_stub() -> bytes:
    """A valid safetensors file with one tiny tensor: the shape of an adapter, not a trained one."""
    header = json.dumps(
        {
            "preview": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]},
            "__metadata__": {"format": "pt", "preview": "true"},
        }
    ).encode()
    return struct.pack("<Q", len(header)) + header + struct.pack("<f", 0.0)


class PreviewTrainer:
    preview = True
    engine = "preview"
    base = BASE
    slot: Any = None
    step_s = 0.02  # a preview run takes seconds, not the hour a real one does
    _pausing = False

    def ready(self) -> bool:
        return True

    def problem(self) -> str | None:
        return None

    def fit(self) -> dict[str, Any]:
        return {"verdict": "fits", "reason": "Preview: nothing is trained, so it fits anywhere."}

    def state(self) -> dict[str, Any]:
        return {"engine": self.engine, "preview": True, "base": self.base}

    async def stop(self) -> None:
        return None

    async def pause(self) -> None:
        self._pausing = True

    async def train(
        self, job: TrainJob, report: Report, sample: SampleFn, resume: bool = False
    ) -> TrainResult:
        started = time.monotonic()
        job.samples.mkdir(parents=True, exist_ok=True)
        every = max(1, job.steps // 4)
        marker = job.samples.parent / "preview-paused.json"
        first = 1
        if resume and marker.is_file():
            first = int(json.loads(marker.read_text())["step"]) + 1
        self._pausing = False
        for step in range(first, job.steps + 1):
            if self._pausing:
                marker.write_text(json.dumps({"step": step - 1}))
                raise Paused(step - 1)
            await asyncio.sleep(self.step_s)
            report(step, "Preview: not learning, only showing the steps")
            if step % every == 0 or step == job.steps:
                name = f"step-{step:04d}.png"
                await asyncio.to_thread(self._sample, job, step, job.samples / name)
                sample(name)
        adapter = job.samples.parent / "adapter.safetensors"
        await asyncio.to_thread(adapter.write_bytes, safetensors_stub())
        return TrainResult(
            adapter, time.monotonic() - started, self.engine,
            "A preview: this file is not a trained model.",
        )  # fmt: skip

    @staticmethod
    def _sample(job: TrainJob, step: int, path: Path) -> None:
        """One of the person's pictures, dimmed, labelled as a preview: a stand-in for what the
        model would draw with the magic word at this step."""
        source = job.pictures[step % len(job.pictures)] if job.pictures else None
        if source is not None:
            img = Image.open(source).convert("RGB")
            img.thumbnail((512, 512))
            img = ImageEnhance.Brightness(img).enhance(0.55)
        else:
            img = Image.new("RGB", (512, 512), (40, 40, 48))
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, img.width, 34), fill=(20, 20, 24))
        draw.text(
            (10, 10), f"PREVIEW  step {step} of {job.steps}  {job.word}", fill=(235, 235, 235)
        )
        img.save(path, "PNG")
