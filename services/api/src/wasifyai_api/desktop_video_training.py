# ruff: noqa: E501  (prose in the docstring and the sentences shown to people are easier to read on one line)
"""The video training engine of the desktop profile (ADR-0073, video amendment; spike TV0).

On a Mac with Apple silicon it is PyTorch (the graphics chip) with `diffusers` and `peft`, run as a
separate process of its own: `video_train.py` reads a job (the pictures and clips with their
descriptions, the size, the steps) and teaches the video model, LTX-Video 2B 0.9.5, a LoRA. This module
builds the job, reads the events, keeps the adapter and **publishes** it: the adapter's tensors renamed
as ComfyUI's LTXV loader names them, in the `loras` folder of the models, which is where the video
engine reads a look (the names the trainer writes are silently ignored there: docs/spikes/video-training-tv0.md).
It holds the one big-model slot while it runs (ADR-0056) and kills the process group when the run is
stopped.

The video model and its text encoder (16 GB) are the files the Video screens already use, found where
the Models screen keeps them: they are never fetched here, and nothing is downloaded silently."""

import asyncio
import contextlib
import json
import os
import re
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from wasifyai_api.desktop_fit import assess_fit, need_declared, read_machine
from wasifyai_api.desktop_models import ModelEntry, free_disk_bytes
from wasifyai_api.desktop_training import (
    MIN_BATTERY_PERCENT,
    _kill_group,
    _no_slot,
    power_state,
    process_footprint,
)
from wasifyai_api.training_setup import apple_silicon
from wasifyai_api.video_setup import find_python, find_small

ENGINE = "diffusers"
SCRIPT = Path(__file__).with_name("video_train.py")
VIDEO_MODEL = (
    "ltx-video-2b"  # the id in the video product's catalogue (products/wasifyai-video/models.yaml)
)
RUN_DISK_BYTES = 3 * 1024**3  # the adapter is 60 to 120 MB; the clips are read in place
HEADROOM_GB = 2.0

Report = Callable[[int, str], None]


def to_job(
    job: Any, files: tuple[Path, Path], small: Path, ffmpeg: str, out: Path
) -> dict[str, Any]:
    """The job file `video_train.py` reads."""
    return {
        "checkpoint": str(files[0]), "t5": str(files[1]), "small": str(small), "ffmpeg": ffmpeg,
        "out": str(out), "width": job.width, "height": job.height, "window_frames": job.window_frames,
        "steps": job.steps, "rank": job.rank, "lr": job.lr, "seed": 3407,
        "checkpointing": job.checkpointing,
        "items": [
            {"path": str(m.path), "kind": m.kind, "caption": m.caption, "seconds": m.seconds}
            for m in job.media
        ],
    }  # fmt: skip


class LtxTrainer:
    """`VideoJob` in, `VideoResult` out; `publish` puts the result where the video engine reads it."""

    preview = False
    engine = ENGINE

    def __init__(self, data_dir: Path | None = None, models: Any = None) -> None:
        self.data_dir = data_dir
        self.models = models  # the ModelsService: where the video model's files are
        self.slot: Any = None  # the SlotManager: a run holds the one big-model slot
        self.on_published: Callable[[], Awaitable[Any]] | None = None
        self._proc: asyncio.subprocess.Process | None = None
        self._stopping = False
        self.peak_bytes = 0

    # ---- where the model is --------------------------------------------------------------------

    def model_files(self) -> tuple[Path, Path] | None:
        """(the video model, its text encoder) where the Models screen keeps them, or None."""
        env = os.environ.get(
            "WASIFYAI_VIDEO_MODEL_DIR"
        )  # development: a folder with `checkpoints/` and `text_encoders/`
        if self.models is None:
            return None
        entry: ModelEntry | None = self.models.catalogue.get(VIDEO_MODEL)
        if entry is None:
            return None
        found = [self.models.locate(f) for f in entry.files]
        if env:
            root = Path(env).expanduser()
            found = [
                p or (root / f.folder / f.name if (root / f.folder / f.name).is_file() else None)
                for p, f in zip(found, entry.files, strict=True)
            ]
        if any(p is None for p in found):
            return None
        by_name = {f.name: p for f, p in zip(entry.files, found, strict=True) if p is not None}
        ck = next((p for n, p in by_name.items() if "ltx-video" in n), None)
        t5 = next((p for n, p in by_name.items() if "t5xxl" in n), None)
        return (ck, t5) if ck is not None and t5 is not None else None

    # ---- what the product asks -----------------------------------------------------------------

    def problem(self, base_id: str | None = None) -> str | None:
        if not apple_silicon():
            return (
                "Teaching the video model works on a Mac with Apple silicon for now. Windows and "
                "Linux (with an NVIDIA graphics card) come later."
            )
        if find_python(self.data_dir) is None or find_small(self.data_dir) is None:
            return "Training is not set up on this computer yet. Set it up first."
        if self.model_files() is None:
            return "The video model is not on this computer yet. Choose Select video model on a Video screen to get it."
        return None

    def ready(self, base_id: str | None = None) -> bool:
        return self.problem(base_id) is None

    def fit(self, need_gb: float) -> dict[str, Any]:
        return assess_fit(need_declared(need_gb + HEADROOM_GB), read_machine()).public()

    def state(self) -> dict[str, Any]:
        return {"engine": self.engine, "preview": False, "setup": self.problem()}

    @property
    def busy(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def stop(self) -> None:
        """Let go of memory for another model: a run in progress is stopped."""
        self._stopping = True
        if self.busy and self._proc is not None:
            _kill_group(self._proc.pid)

    def preflight_blockers(self) -> list[str]:
        if free_disk_bytes(self.data_dir or Path.home()) < RUN_DISK_BYTES:
            return ["There is not enough free disk space for a run. Free up 3 GB first."]
        return []

    def preflight(self, need_gb: float) -> dict[str, Any]:
        """What a person should know before starting: whether anything stops it, what to look out
        for, and what waits while it runs. Every number is read from this computer now."""
        blockers: list[str] = []
        warnings: list[str] = []
        fit = self.fit(need_gb)
        free_disk = free_disk_bytes(self.data_dir or Path.home())
        power = power_state()
        if fit["verdict"] == "too_big":
            blockers.append(fit["reason"])
        elif fit["verdict"] == "tight":
            warnings.append(fit["reason"] + " Close other apps first.")
        if free_disk < RUN_DISK_BYTES:
            blockers.append(
                f"There is not enough free disk space: about {RUN_DISK_BYTES / 1e9:.0f} GB is "
                f"needed for the run and {free_disk / 1e9:.1f} GB is free."
            )
        if power["source"] == "battery":
            pct = power["percent"]
            where = f" ({pct}%)" if pct is not None else ""
            if pct is not None and pct < MIN_BATTERY_PERCENT:
                blockers.append(f"The battery is low{where}. Plug in before you start.")
            else:
                warnings.append(f"You are on battery power{where}. Plug in: a run takes a while.")
        return {
            "ok": not blockers,
            "blockers": blockers,
            "warnings": warnings,
            "pauses": "Chat, images, video and 3D wait while it runs.",
        }

    # ---- a run ---------------------------------------------------------------------------------

    async def train(self, job: Any, folder: Path, report: Report) -> Any:
        """Teach the video model and keep the adapter in `folder / "out"`. Raises `Stopped` when
        stopped and `RuntimeError` with a sentence when the tool fails."""
        from wasifyai_training.clips import ffmpeg_path
        from wasifyai_training.video import VideoResult

        python, small, files = (
            find_python(self.data_dir),
            find_small(self.data_dir),
            self.model_files(),
        )
        if python is None or small is None or files is None:
            raise RuntimeError(self.problem() or "Training is not set up.")
        started = time.monotonic()
        out = folder / "out"
        await asyncio.to_thread(out.mkdir, parents=True, exist_ok=True)
        cfg = folder / "job.json"
        await asyncio.to_thread(
            cfg.write_text, json.dumps(to_job(job, files, small, ffmpeg_path(), out))
        )
        self._stopping = False
        got: dict[str, Any] = {}
        try:
            await self._run(python, cfg, job, report, got)
        finally:
            await asyncio.to_thread(cfg.unlink, True)
        adapter = out / "pytorch_lora_weights.safetensors"
        if not adapter.is_file() or "done" not in got:
            raise RuntimeError("The training tool finished without a model.")
        done = got["done"]
        return VideoResult(
            adapter, time.monotonic() - started, self.engine, peak_bytes=max(self.peak_bytes, int(done.get("peak_bytes", 0))),
            loss_first=done.get("loss_first"), loss_last=done.get("loss_last"),
        )  # fmt: skip

    async def _run(
        self, python: Path, cfg: Path, job: Any, report: Report, got: dict[str, Any]
    ) -> None:
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "HF_HUB_OFFLINE": "1"}
        report(0, "Starting")
        tail: list[str] = []
        self.peak_bytes = 0
        holder = self.slot.hold("training") if self.slot is not None else _no_slot()
        async with holder:
            proc = await asyncio.create_subprocess_exec(
                str(python), "-I", str(SCRIPT), "-c", str(cfg),
                env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                stdin=asyncio.subprocess.DEVNULL, start_new_session=True,
            )  # fmt: skip
            self._proc = proc
            sampler = asyncio.create_task(self._sample_memory(proc))
            step = 0
            try:
                assert proc.stdout is not None
                async for raw in proc.stdout:
                    line = raw.decode(errors="replace").strip()
                    if not line:
                        continue
                    tail.append(line[:200])
                    del tail[:-20]
                    if not line.startswith("{"):
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    match event.get("event"):
                        case "status":
                            report(step, str(event.get("message", "")))
                        case "progress":
                            step = min(int(event["step"]), job.steps)
                            report(step, f"Learning, step {step} of {job.steps}")
                        case "done":
                            got["done"] = event
                await proc.wait()
            except asyncio.CancelledError:
                _kill_group(proc.pid)
                await proc.wait()
                raise
            finally:
                sampler.cancel()
                self._proc = None
        if self._stopping:
            from wasifyai_training.trainer import Stopped

            raise Stopped("It was stopped, so nothing was kept.")
        if proc.returncode != 0:
            raise RuntimeError("The training tool stopped with an error: " + " | ".join(tail[-4:]))

    async def _sample_memory(self, proc: asyncio.subprocess.Process) -> None:
        while proc.returncode is None:
            held = await asyncio.to_thread(process_footprint, proc.pid)
            self.peak_bytes = max(self.peak_bytes, held)
            await asyncio.sleep(5)

    # ---- the video engine reads what was taught --------------------------------------------------

    def _loras(self) -> Path | None:
        models_dir = getattr(self.models, "models_dir", None)
        return Path(models_dir) / "loras" if models_dir is not None else None

    async def publish(self, adapter: Path, title: str, run_id: str) -> str | None:
        """The adapter in ComfyUI's key names, in the `loras` folder of the models: the name a video
        workflow gives it, or None when there is no folder to put it in."""
        folder = self._loras()
        if folder is None:
            return None
        from wasifyai_training import ltx_lora

        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "model"
        name = f"wasify-video-{slug}-{run_id[:8]}.safetensors"
        await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(ltx_lora.convert, adapter, folder / name)
        if self.on_published is not None:
            with contextlib.suppress(Exception):
                await self.on_published()
        return name

    async def unpublish(self, name: str) -> None:
        folder = self._loras()
        if folder is None or "/" in name or ".." in name:
            return
        with contextlib.suppress(OSError):
            (folder / name).unlink()
        if self.on_published is not None:
            with contextlib.suppress(Exception):
                await self.on_published()


def make_video_trainer(data_dir: Path | None, models: Any = None) -> LtxTrainer | None:
    """The video trainer of this engine, or None when the training product is absent."""
    try:
        import wasifyai_training  # noqa: F401
    except ImportError:
        return None
    return LtxTrainer(data_dir, models)
