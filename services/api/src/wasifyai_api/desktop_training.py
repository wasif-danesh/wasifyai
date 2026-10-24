"""The training engine of the desktop profile (ADR-0073, ADR-0076).

On a Mac with Apple silicon it is mflux (MIT), run as a separate process of its own:
`mflux-train` is given a config and a folder of pictures with their descriptions, writes sample
pictures as it goes and a checkpoint that holds the adapter. This module builds the config, reads
the progress, keeps the samples and takes the adapter out. It holds the one big-model slot while
it runs (ADR-0056) and kills the process group when the run is stopped or the slot is wanted.
The first LoRA is taught on FLUX.2 klein base 4B, the model Create image uses, so what it learns
can be used there.

Anywhere else (Windows, Linux, an Intel Mac) it says so in words and trains nothing: the NVIDIA
trainers are a later stage (ADR-0073 decision 3). Nothing is downloaded silently: the base model
must already be on the computer."""

import asyncio
import contextlib
import json
import math
import os
import platform
import re
import shutil
import signal
import sys
import time
import zipfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from PIL import Image

from wasifyai_api.desktop_fit import assess_fit, need_declared, read_machine

BASE = "flux2-klein-base-4b"
BASE_REPO = "black-forest-labs/FLUX.2-klein-base-4B"
# the footprint of a run at 768 px, 8-bit, with gradient checkpointing (to be measured: ADR-0073)
NEED_GB = 28.0
SIDE = 768  # the longest side of a training picture
RANK = 16
EXECUTABLE = "mflux-train"
DEV_FALLBACK = (
    Path.home() / ".cache" / "wasifyai-art" / "mflux-env"
)  # where mflux was set up for the spikes

# a sample shows what the model makes with the magic word: a scene it saw and one it did not
SAMPLE_PROMPTS = {
    "character": "{word}, standing in a sunny park",
    "style": "a lighthouse on a cliff at sunrise, {word}",
    "object": "{word} on a wooden table by a window",
}

# tqdm's bar: " 12%|███  | 12/100 [01:30<10:40,  7.3s/it]"
_BAR = re.compile(r"\|\s*(\d+)/(\d+)\s*\[")
_PREVIEW_FILE = re.compile(r"^(\d{7})_preview_image_(.+)\.png$")


def find_mflux(data_dir: Path | None) -> Path | None:
    """The folder of an mflux environment (the one with `bin/mflux-train`): a setting, the app's own
    component folder, or where the spikes set it up."""
    candidates = [Path(p) for p in (os.environ.get("WASIFYAI_MFLUX_DIR"),) if p]
    if data_dir is not None:
        candidates.append(data_dir / "components" / "mflux")
    candidates.append(DEV_FALLBACK)
    return next((c for c in candidates if (c / "bin" / EXECUTABLE).is_file()), None)


def base_on_computer() -> bool:
    """Is the base model already in the Hugging Face cache? Training never fetches it by itself."""
    root = Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface") / "hub"
    folder = root / ("models--" + BASE_REPO.replace("/", "--")) / "snapshots"
    needed = (
        "transformer/diffusion_pytorch_model.safetensors",
        "text_encoder/model-00002-of-00002.safetensors",
        "vae/diffusion_pytorch_model.safetensors",
    )  # a download that is still going has the folders, not yet these files
    with contextlib.suppress(OSError):
        return any(all((s / name).is_file() for name in needed) for s in folder.iterdir())
    return False


def apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


def training_config(
    steps: int, pictures: int, work: Path, out: Path, *, sample_every: int
) -> dict[str, Any]:
    """The `mflux-train` config: epochs make up the steps (one picture is one step), the full
    timestep range (the klein finding), the layers of both kinds of block at rank 16."""
    epochs = max(1, math.ceil(steps / max(1, pictures)))
    total = epochs * pictures
    blocks_double, blocks_single = {"start": 0, "end": 5}, {"start": 0, "end": 20}
    targets = [
        {"module_path": f"transformer_blocks.{{block}}.{m}", "blocks": blocks_double, "rank": RANK}
        for m in (
            "attn.to_q",
            "attn.to_k",
            "attn.to_v",
            "attn.to_out",
            "ff.linear_in",
            "ff.linear_out",
        )
    ] + [
        {
            "module_path": f"single_transformer_blocks.{{block}}.{m}",
            "blocks": blocks_single,
            "rank": RANK,
        }
        for m in ("attn.to_qkv_mlp_proj", "attn.to_out")
    ]
    return {
        "model": BASE, "data": str(work), "seed": 42, "steps": 28, "guidance": 4.0,
        "quantize": 8, "max_resolution": SIDE, "low_ram": False, "gradient_checkpointing": True,
        "training_loop": {
            "num_epochs": epochs, "batch_size": 1,
            "timestep_low": 0, "timestep_high": 28, "timestep_type": "sigmoid",
        },
        "optimizer": {"name": "AdamW", "learning_rate": 1e-4},
        "checkpoint": {"save_frequency": max(25, total // 4), "output_path": str(out)},
        "monitoring": {
            "preview_width": 512, "preview_height": 512, "plot_frequency": 1_000_000,
            "generate_image_frequency": max(1, sample_every),
        },
        "lora_layers": {"targets": targets},
    }  # fmt: skip


def parse_progress(text: str) -> tuple[int, int] | None:
    """(done, total) from a progress bar line, or None."""
    found = _BAR.search(text)
    return (int(found.group(1)), int(found.group(2))) if found else None


def _kill_group(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, signal.SIGTERM)


def prepare_data(job: Any, work: Path) -> None:
    """The folder `mflux-train` reads: `pic-NN.png` with `pic-NN.txt`, and the sample prompts."""
    work.mkdir(parents=True, exist_ok=True)
    for n, (path, caption) in enumerate(zip(job.pictures, job.captions, strict=True), start=1):
        with Image.open(path) as im:
            im.convert("RGB").save(work / f"pic-{n:03d}.png", "PNG")
        (work / f"pic-{n:03d}.txt").write_text(caption, encoding="utf-8")
    first = job.captions[0] if job.captions else job.word
    new = SAMPLE_PROMPTS.get(job.kind, SAMPLE_PROMPTS["character"]).format(word=job.word)
    (work / "preview-1.txt").write_text(first, encoding="utf-8")
    (work / "preview-2.txt").write_text(new, encoding="utf-8")


def take_adapter(checkpoints: Path, target: Path) -> bool:
    """The adapter of the newest checkpoint, written to `target`."""
    zips = sorted(checkpoints.glob("*_checkpoint.zip"))
    if not zips:
        return False
    with zipfile.ZipFile(zips[-1]) as z:
        name = next((n for n in z.namelist() if n.endswith("_adapter.safetensors")), None)
        if name is None:
            return False
        with z.open(name) as src, target.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    return True


class MfluxTrainer:
    """The `TrainJob` in, the `TrainResult` out, behind the product's interface (`trainer.py`)."""

    preview = False
    engine = "mflux"
    base = BASE

    def __init__(self, data_dir: Path | None = None, models_dir: Path | None = None) -> None:
        self.data_dir = data_dir
        self.models_dir = models_dir  # the image engine reads styles from its `loras` folder
        self.on_published: Callable[[], Awaitable[None]] | None = None  # the engine looks again
        self.slot: Any = None  # the SlotManager: a run holds the one big-model slot
        self._proc: asyncio.subprocess.Process | None = None

    # ---- what the product asks ---------------------------------------------------------------

    def problem(self) -> str | None:
        if not apple_silicon():
            return (
                "Teaching a picture model works on a Mac with Apple silicon for now. Windows and "
                "Linux (with an NVIDIA graphics card) come later."
            )
        if find_mflux(self.data_dir) is None:
            return "The training tool is not set up on this computer yet."
        if not base_on_computer():
            return (
                "The picture model it learns on (FLUX.2 klein base 4B, about 12 GB) is not on "
                "this computer yet. Get it first."
            )
        return None

    def ready(self) -> bool:
        return self.problem() is None

    def fit(self) -> dict[str, Any]:
        return assess_fit(need_declared(NEED_GB), read_machine()).public()

    def state(self) -> dict[str, Any]:
        return {"engine": self.engine, "preview": False, "base": BASE, "setup": self.problem()}

    @property
    def busy(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def stop(self) -> None:
        """Let go of memory for another model: a run in progress is stopped."""
        if self.busy and self._proc is not None:
            _kill_group(self._proc.pid)

    # ---- the image engine (ComfyUI) reads what was taught --------------------------------------

    async def publish(self, adapter: Path, title: str, run_id: str) -> str | None:
        """The adapter in ComfyUI's key names, in the `loras` folder of the models: the name an
        image workflow gives it, or None when there is no folder to put it in."""
        if self.models_dir is None:
            return None
        from wasifyai_training import comfy_lora

        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "model"
        name = f"wasify-{slug}-{run_id[:8]}.safetensors"
        target = self.models_dir / "loras" / name
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(comfy_lora.convert, adapter, target, BASE)
        if self.on_published is not None:
            with contextlib.suppress(Exception):
                await self.on_published()
        return name

    async def unpublish(self, name: str) -> None:
        if self.models_dir is None or "/" in name or ".." in name:
            return
        with contextlib.suppress(OSError):
            (self.models_dir / "loras" / name).unlink()
        if self.on_published is not None:
            with contextlib.suppress(Exception):
                await self.on_published()

    # ---- a run -------------------------------------------------------------------------------

    async def train(
        self, job: Any, report: Callable[[int, str], None], sample: Callable[[str], None]
    ) -> Any:
        from wasifyai_training.trainer import TrainResult

        home = find_mflux(self.data_dir)
        if home is None or (why := self.problem()):
            raise RuntimeError(why or "The training tool is not set up.")
        folder = job.samples.parent
        work, out = folder / "work", folder / "out"
        started = time.monotonic()
        try:
            await asyncio.to_thread(shutil.rmtree, work, True)
            await asyncio.to_thread(shutil.rmtree, out, True)
            await asyncio.to_thread(prepare_data, job, work)
            await asyncio.to_thread(job.samples.mkdir, parents=True, exist_ok=True)
            total = max(1, math.ceil(job.steps / max(1, len(job.pictures)))) * len(job.pictures)
            config = training_config(
                job.steps, len(job.pictures), work, out, sample_every=max(1, total // 4)
            )
            cfg = folder / "train.json"
            await asyncio.to_thread(cfg.write_text, json.dumps(config, indent=2))
            await self._run(home, cfg, out, job, report, sample, total)
            adapter = folder / "adapter.safetensors"
            if not await asyncio.to_thread(take_adapter, out / "checkpoints", adapter):
                raise RuntimeError("The training tool finished without an adapter.")
            return TrainResult(adapter, time.monotonic() - started, self.engine)
        finally:
            await asyncio.to_thread(shutil.rmtree, work, True)
            await asyncio.to_thread(
                shutil.rmtree, out, True
            )  # the checkpoints are large; the adapter is kept

    async def _run(
        self, home: Path, cfg: Path, out: Path, job: Any,
        report: Callable[[int, str], None], sample: Callable[[str], None], total: int,
    ) -> None:  # fmt: skip
        env = {
            **os.environ,
            "PYTHONUNBUFFERED": "1",
            "HF_HUB_OFFLINE": "1",  # the base model is on the computer or the run does not start
            "PATH": f"{home / 'bin'}:{os.environ.get('PATH', '')}",
        }
        report(0, "Loading the model")
        tail: list[str] = []
        seen: set[str] = set()
        holder = self.slot.hold("training") if self.slot is not None else _no_slot()
        async with holder:
            proc = await asyncio.create_subprocess_exec(
                str(home / "bin" / EXECUTABLE), "--config", str(cfg),
                env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                stdin=asyncio.subprocess.DEVNULL, start_new_session=True,
            )  # fmt: skip
            self._proc = proc
            try:
                await self._watch(proc, out, job, report, sample, tail, seen, total)
                await proc.wait()
            except asyncio.CancelledError:
                _kill_group(proc.pid)
                await proc.wait()
                raise
            finally:
                self._proc = None
        if proc.returncode != 0:
            raise RuntimeError("The training tool stopped with an error: " + " | ".join(tail[-4:]))

    async def _watch(
        self, proc: asyncio.subprocess.Process, out: Path, job: Any,
        report: Callable[[int, str], None], sample: Callable[[str], None],
        tail: list[str], seen: set[str], total: int,
    ) -> None:  # fmt: skip
        assert proc.stdout is not None
        buffer = ""
        reported = -1

        def progress(text: str) -> None:
            """The bar is redrawn in place: a step is known as soon as it is written, not when the
            next one starts."""
            nonlocal reported
            bar = parse_progress(text)
            # the tool draws other bars (loading, quantising): only the training one counts
            if bar is not None and bar[1] == total and bar[0] != reported:
                reported = step = min(bar[0], job.steps)
                report(step, f"Learning, step {step} of {job.steps}")

        while chunk := await proc.stdout.read(4096):
            buffer += chunk.decode(errors="replace")
            *lines, buffer = re.split(r"[\r\n]", buffer)
            for line in lines:
                if not line.strip():
                    continue
                tail.append(line.strip()[:200])
                del tail[:-20]
                progress(line)
            progress(buffer)
            await asyncio.to_thread(self._copy_samples, out, job, sample, seen)
        await asyncio.to_thread(self._copy_samples, out, job, sample, seen)

    @staticmethod
    def _copy_samples(out: Path, job: Any, sample: Callable[[str], None], seen: set[str]) -> None:
        """Each new preview picture of mflux becomes a sample of the run: `step-0000-1.png` is what
        the model drew before it learned anything, the later ones what it draws now."""
        for path in sorted((out / "preview").glob("*.png")) if (out / "preview").is_dir() else []:
            found = _PREVIEW_FILE.match(path.name)
            if found is None or path.name in seen:
                continue
            seen.add(path.name)
            kind = re.search(r"(\d+)$", found.group(2))
            name = f"step-{int(found.group(1)):04d}-{kind.group(1) if kind else '1'}.png"
            shutil.copyfile(path, job.samples / name)
            sample(name)


@contextlib.asynccontextmanager
async def _no_slot():  # type: ignore[no-untyped-def]
    yield


def make_trainer(data_dir: Path | None, models_dir: Path | None = None) -> Any:
    """The trainer of this engine, or None when the training product is not part of this build."""
    try:
        import wasifyai_training  # noqa: F401
    except ImportError:
        return None
    return MfluxTrainer(data_dir, models_dir)
