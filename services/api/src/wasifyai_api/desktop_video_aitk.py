# ruff: noqa: E501  (the sentences in the docstrings read better on one line)
"""The newer video models taught with AI Toolkit on the desktop (ADR-0097, stage MV5).

LTX-Video 2B keeps its own trainer (`desktop_video_training.py`). LTX-2.5, Wan 2.2 14B and MiniMax-H3
are taught by AI Toolkit, the same tool and process as the pictures: `AitkVideoTrainer` writes the
config from the model's recipe (`wasifyai_training.video_bases`), runs it through the picture trainer
(its process, its slot, its progress bar and its fetch of a recipe's files) and keeps the adapter.
AI Toolkit reads Create's own files in ComfyUI's layout through MODELS_PATH, so only what Create
does not keep is fetched. `VideoTrainers` gives the video product the right trainer for a model."""

import asyncio
import contextlib
import json
import re
import shutil
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from wasifyai_training.video_bases import VIDEO_BASES, VideoBase

from wasifyai_api.desktop_fit import assess_fit, need_declared, read_machine
from wasifyai_api.desktop_training import (
    NAME,
    RANK,
    AiToolkitTrainer,
    device,
    where_taught,
)
from wasifyai_api.desktop_video_training import HEADROOM_GB, LtxTrainer
from wasifyai_api.training_setup import find_tool, picture_supported

ENGINE = "ai-toolkit"
Report = Callable[[int, str], None]


def video_config(
    recipe: VideoBase, steps: int, work: Path, out: Path, *, rank: int = RANK, lr: float = 1e-4
) -> dict[str, Any]:
    """AI Toolkit's config for a video recipe: a LoRA at rank 16, a checkpoint every 25 steps, no
    sample clips (a clip takes minutes to draw; the run is checked in Create)."""
    model: dict[str, Any] = {
        "name_or_path": recipe.name_or_path, "arch": recipe.arch, "low_vram": False,
    }  # fmt: skip
    if recipe.extras:
        model["extras_name_or_path"] = recipe.extras
    if recipe.quantize:
        model |= {"quantize": True, "qtype": recipe.quantize}
    if recipe.quantize_te:
        model |= {"quantize_te": True, "qtype_te": recipe.quantize_te}
    if recipe.model_kwargs:
        model["model_kwargs"] = dict(recipe.model_kwargs)
    model |= dict(recipe.model_fields)
    process = {
        "type": "sd_trainer",
        "training_folder": str(out),
        "device": device(),
        "network": {"type": "lora", "linear": rank, "linear_alpha": rank, **recipe.network_fields},
        "save": {"dtype": "float16", "save_every": 25, "max_step_saves_to_keep": 2},
        "datasets": [
            {
                "folder_path": str(work), "caption_ext": "txt", "caption_dropout_rate": 0.0,
                "cache_latents_to_disk": True, "resolution": [recipe.side],
                "num_frames": recipe.frames, **recipe.dataset_fields,
            }
        ],
        "train": {
            "batch_size": 1, "steps": steps, "train_unet": True, "train_text_encoder": False,
            "gradient_checkpointing": True, "noise_scheduler": "flowmatch", "optimizer": "adamw",
            "lr": lr, "dtype": "bf16", "disable_sampling": True, **recipe.train_fields,
        },
        "model": model,
        "sample": {
            "sampler": "flowmatch", "sample_every": steps + 1, "width": recipe.side,
            "height": recipe.side, "prompts": [], "seed": 42, "num_frames": recipe.frames,
            "fps": recipe.fps,
        },
    }  # fmt: skip
    return {
        "job": "extension",
        "config": {"name": NAME, "process": [process]},
        "meta": {"name": NAME},
    }


def video_data(media: list[Any], work: Path) -> int:
    """Each picture and clip with its description beside it, as AI Toolkit reads a folder."""
    work.mkdir(parents=True, exist_ok=True)
    for n, m in enumerate(media):
        dst = work / f"{n:04d}{Path(m.path).suffix.lower()}"
        shutil.copyfile(m.path, dst)
        dst.with_suffix(".txt").write_text(m.caption)
    return len(media)


class AitkVideoTrainer:
    """`VideoJob` in, `VideoResult` out, for the video recipes AI Toolkit teaches."""

    preview = False
    engine = ENGINE

    def __init__(self, pictures: AiToolkitTrainer, ltx: LtxTrainer) -> None:
        self.pictures = pictures  # its process, slot and fetch of a recipe's files
        self.ltx = ltx  # the loras folder, the disk and power checks are the same
        self.on_published: Callable[[], Awaitable[Any]] | None = None

    # ---- what the product asks -----------------------------------------------------------------

    def create_files_missing(self, recipe: VideoBase) -> bool:
        models = self.pictures.models
        entry = models.catalogue.get(recipe.model) if models is not None else None
        return entry is None or any(models.locate(f) is None for f in entry.files)

    def problem(self, base_id: str | None = None) -> str | None:
        recipe = VIDEO_BASES.get(base_id or "")
        if recipe is None:
            return "This video model cannot be taught yet."
        if not picture_supported():
            return (
                "Teaching a video model needs a Mac with Apple silicon, or a computer with an "
                "NVIDIA graphics card."
            )
        if why := where_taught(recipe):
            return why
        if find_tool(self.pictures.data_dir) is None:
            return "Training is not set up on this computer yet. Set it up first."
        if self.create_files_missing(recipe):
            return (
                f"{recipe.use_with} is not on this computer yet. Choose Select video model on a "
                "Video screen to get it."
            )
        if self.pictures.hub_missing(recipe.id):
            return (
                f"The training files of {recipe.title} are not on this computer yet "
                f"(about {recipe.hub_bytes / 1e9:.0f} GB). Get them first."
            )
        return None

    def ready(self, base_id: str | None = None) -> bool:
        return self.problem(base_id) is None

    def fit(self, need_gb: float) -> dict[str, Any]:
        return assess_fit(need_declared(need_gb + HEADROOM_GB), read_machine()).public()

    def state(self) -> dict[str, Any]:
        return {"engine": self.engine, "preview": False}

    @property
    def busy(self) -> bool:
        return self.pictures.busy

    async def stop(self) -> None:
        await self.pictures.stop()

    def preflight_blockers(self) -> list[str]:
        return self.ltx.preflight_blockers()

    def preflight(self, need_gb: float) -> dict[str, Any]:
        return self.ltx.preflight(need_gb)

    # ---- a run ---------------------------------------------------------------------------------

    async def train(self, job: Any, folder: Path, report: Report) -> Any:
        from wasifyai_training.video import VideoResult

        recipe = VIDEO_BASES.get(str(job.settings.get("base", "")))
        if recipe is None:
            raise RuntimeError("This video model cannot be taught yet.")
        if why := self.problem(recipe.id):
            raise RuntimeError(why)
        tool = find_tool(self.pictures.data_dir)
        assert tool is not None
        work, out = folder / "work", folder / "out"
        cfg = folder / "train.json"
        started = time.monotonic()
        try:
            await asyncio.to_thread(shutil.rmtree, work, True)
            await asyncio.to_thread(shutil.rmtree, out, True)
            await asyncio.to_thread(video_data, job.media, work)
            config = video_config(recipe, job.steps, work, out, rank=job.rank, lr=job.lr)
            await asyncio.to_thread(cfg.write_text, json.dumps(config, indent=2))
            shim = SimpleNamespace(steps=job.steps, samples=folder / "samples")
            await self.pictures._run(  # noqa: SLF001 - one AI Toolkit process for every kind
                tool[0], [str(cfg)], out / NAME, shim, report, lambda _name: None,
                self.pictures.hub_env(),
            )  # fmt: skip
            final = out / NAME / f"{NAME}.safetensors"
            if not final.is_file():
                raise RuntimeError("The training tool finished without an adapter.")
            adapter = folder / "adapter.safetensors"
            await asyncio.to_thread(shutil.copyfile, final, adapter)
            return VideoResult(
                adapter, time.monotonic() - started, self.engine,
                peak_bytes=self.pictures.peak_bytes,
            )  # fmt: skip
        finally:
            await asyncio.to_thread(shutil.rmtree, work, True)

    async def publish(self, adapter: Path, title: str, run_id: str) -> str | None:
        """AI Toolkit writes the key names ComfyUI reads: the adapter is copied as it is into the
        `loras` folder of the models."""
        folder = self.ltx._loras()  # noqa: SLF001 - the same folder for every video model
        if folder is None:
            return None
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "model"
        name = f"wasify-video-{slug}-{run_id[:8]}.safetensors"
        await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copyfile, adapter, folder / name)
        if self.on_published is not None:
            with contextlib.suppress(Exception):
                await self.on_published()
        return name

    async def unpublish(self, name: str) -> None:
        await self.ltx.unpublish(name)


class VideoTrainers:
    """The video product's engine on the desktop: LTX-Video 2B's own trainer, and AI Toolkit for the
    models in `video_bases`. Everything not about one model is LTX-Video's (the status, the setup)."""

    def __init__(self, ltx: LtxTrainer, aitk: AitkVideoTrainer) -> None:
        self.ltx, self.aitk = ltx, aitk

    def for_base(self, base_id: str) -> Any:
        return self.aitk if base_id in VIDEO_BASES else self.ltx

    def fetch_bytes(self, d: Any) -> int:
        if d.id not in VIDEO_BASES:
            return 0
        return sum(h.bytes for h in self.aitk.pictures.hub_missing(d.id))

    @property
    def busy(self) -> bool:
        return self.ltx.busy or self.aitk.busy

    async def stop(self) -> None:
        await self.ltx.stop()
        await self.aitk.stop()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.ltx, name)
