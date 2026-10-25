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
import re
import shutil
import signal
import subprocess
import time
import zipfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from PIL import Image

from wasifyai_api.desktop_fit import assess_fit, need_declared, read_machine
from wasifyai_api.desktop_models import free_disk_bytes
from wasifyai_api.training_setup import TrainingSetup, apple_silicon, find_base, find_tool

BASE = "flux2-klein-base-4b"
# What a run holds at 768 px, 8-bit, with gradient checkpointing, as the system counts it.
# Measured on the owner's M5 Pro, 2026-10-25: 21.0 GB for a style and an object run, 35.0 GB for a
# character run; the worst case is used, so a computer that could not hold it is told so.
NEED_GB = 35.0
SIDE = 768  # the longest side of a training picture
RANK = 16
# per kind of thing taught. A style at 3e-4 did no better than at 1e-4 (measured, 2026-10-25), so
# all are 1e-4
LEARNING_RATE = {"character": 1e-4, "object": 1e-4, "style": 1e-4}
RUN_DISK_BYTES = 3 * 1024**3  # a run's pictures, checkpoints and samples; the model is already kept
MIN_BATTERY_PERCENT = 25  # below this on battery, a run is not started
CHECKPOINT_EVERY = 25  # steps: a pause loses at most this many
EXECUTABLE = "mflux-train"
TOKENIZE_SCRIPT = Path(__file__).with_name("training_tokenize.py")

# a sample shows what the model makes with the magic word: a scene it saw and one it did not
SAMPLE_PROMPTS = {
    "character": "{word}, standing in a sunny park",
    "style": "a lighthouse on a cliff at sunrise, {word}",
    "object": "{word} on a wooden table by a window",
}

# tqdm's bar: " 12%|███  | 12/100 [01:30<10:40,  7.3s/it]"
_BAR = re.compile(r"\|\s*(\d+)/(\d+)\s*\[")
_PREVIEW_FILE = re.compile(r"^(\d{7})_preview_image_(.+)\.png$")


def training_config(
    steps: int,
    pictures: int,
    work: Path,
    out: Path,
    *,
    sample_every: int,
    base: Path | None = None,
    kind: str = "character",
) -> dict[str, Any]:
    """The `mflux-train` config: epochs make up the steps (one picture is one step), the full
    timestep range (the klein finding), the layers of both kinds of block at rank 16."""
    epochs = max(1, math.ceil(steps / max(1, pictures)))
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
    config = {
        "model": BASE, "data": str(work), "seed": 42, "steps": 28, "guidance": 4.0,
        "quantize": 8, "max_resolution": SIDE, "low_ram": False, "gradient_checkpointing": True,
        "training_loop": {
            "num_epochs": epochs, "batch_size": 1,
            "timestep_low": 0, "timestep_high": 28, "timestep_type": "sigmoid",
        },
        "optimizer": {"name": "AdamW", "learning_rate": LEARNING_RATE.get(kind, 1e-4)},
        "checkpoint": {"save_frequency": CHECKPOINT_EVERY, "output_path": str(out)},
        "monitoring": {
            "preview_width": 512, "preview_height": 512, "plot_frequency": 1_000_000,
            "generate_image_frequency": max(1, sample_every),
        },
        "lora_layers": {"targets": targets},
    }  # fmt: skip
    if base is not None:
        config["model_path"] = str(base)  # the model's own folder: the trainer fetches nothing
    return config


def parse_progress(text: str) -> tuple[int, int] | None:
    """(done, total) from a progress bar line, or None."""
    found = _BAR.search(text)
    return (int(found.group(1)), int(found.group(2))) if found else None


def power_state() -> dict[str, Any]:
    """On battery or not, and how full it is: `pmset` on a Mac, unknown elsewhere."""
    try:
        out = subprocess.run(
            ["/usr/bin/pmset", "-g", "batt"], capture_output=True, text=True, timeout=5
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {"source": "unknown", "percent": None}
    percent = re.search(r"(\d+)%", out)
    source = "battery" if "Battery Power" in out else "mains" if "AC Power" in out else "unknown"
    return {"source": source, "percent": int(percent.group(1)) if percent else None}


_UNITS = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}


def process_footprint(pid: int) -> int:
    """What a process holds as the system counts it (Metal buffers included); 0 if unread."""
    try:
        out = subprocess.run(
            ["/usr/bin/footprint", "-p", str(pid)], capture_output=True, text=True, timeout=20
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return 0
    found = re.search(r"Footprint:\s*([\d.]+)\s*(B|KB|MB|GB)\b", out)
    return int(float(found.group(1)) * _UNITS[found.group(2)]) if found else 0


def latest_checkpoint(folder: Path) -> Path | None:
    zips = sorted(folder.glob("*_checkpoint.zip")) if folder.is_dir() else []
    return zips[-1] if zips else None


def checkpoint_step(path: Path | None) -> int | None:
    found = re.match(r"(\d+)_checkpoint", path.name) if path is not None else None
    return int(found.group(1)) if found else None


def prune_checkpoints(folder: Path, keep: int = 2, protect: Path | None = None) -> None:
    """Older checkpoints are large and no use: the newest two are kept (one may be half written).
    The one a resumed run started from stays: the trainer still reads it while it goes on."""
    zips = sorted(folder.glob("*_checkpoint.zip")) if folder.is_dir() else []
    for old in zips[:-keep]:
        if protect is not None and old == protect:
            continue
        with contextlib.suppress(OSError):
            old.unlink()


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

    def __init__(
        self,
        data_dir: Path | None = None,
        models_dir: Path | None = None,
        setup: TrainingSetup | None = None,
    ) -> None:
        self.data_dir = data_dir
        self.setup = setup  # what the person can be offered when the trainer is not there yet
        self.models_dir = models_dir  # the image engine reads styles from its `loras` folder
        self.on_published: Callable[[], Awaitable[None]] | None = None  # the engine looks again
        self.slot: Any = None  # the SlotManager: a run holds the one big-model slot
        self._proc: asyncio.subprocess.Process | None = None
        self._pausing = False
        self._resumed_from: Path | None = None  # the checkpoint a picked-up run started from
        self.peak_bytes = 0  # the most memory the last run held
        self._words: dict[tuple[str, str], dict[str, Any]] = {}  # how words were split

    # ---- what the product asks ---------------------------------------------------------------

    def problem(self) -> str | None:
        if not apple_silicon():
            return (
                "Teaching a picture model works on a Mac with Apple silicon for now. Windows and "
                "Linux (with an NVIDIA graphics card) come later."
            )
        if find_tool(self.data_dir) is None or find_base(self.data_dir) is None:
            return "Training is not set up on this computer yet. Set it up first."
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

    async def tokenize(self, words: list[str]) -> dict[str, dict[str, Any]] | None:
        """How the model's own tokenizer splits each word (`training_tokenize`), or None when it
        cannot be read. What was asked before is not asked again."""
        tool, base = find_tool(self.data_dir), find_base(self.data_dir)
        if tool is None or base is None:
            return None
        file = base[0] / "tokenizer" / "tokenizer.json"
        python = tool[0] / "bin" / "python"
        if not file.is_file() or not python.is_file():
            return None
        todo = [w for w in dict.fromkeys(words) if (str(file), w) not in self._words]
        if todo:
            proc = await asyncio.create_subprocess_exec(
                str(python), "-I", str(TOKENIZE_SCRIPT), str(file), json.dumps(todo),
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )  # fmt: skip
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), 30)
                got = json.loads(out)
            except (TimeoutError, ValueError, OSError):
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                return None
            for w, info in got.items():
                self._words[(str(file), w)] = info
        return {w: self._words[(str(file), w)] for w in words if (str(file), w) in self._words}

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

    # ---- before a run ------------------------------------------------------------------------

    def preflight(self) -> dict[str, Any]:
        """What a person should know before starting: whether anything stops it, what to look out
        for, and what waits while it runs. Every number is read from this computer now."""
        blockers: list[str] = []
        warnings: list[str] = []
        fit = self.fit()
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
            "facts": {
                "memory_need_bytes": fit["needed_bytes"],
                "memory_budget_bytes": fit["budget_bytes"],
                "disk_free_bytes": free_disk,
                "power": power["source"],
                "battery_percent": power["percent"],
            },
        }

    # ---- a run -------------------------------------------------------------------------------

    async def pause(self) -> None:
        """Stop the run now, keeping its last checkpoint so it can be picked up where it stopped."""
        self._pausing = True
        await self.stop()

    async def train(
        self,
        job: Any,
        report: Callable[[int, str], None],
        sample: Callable[[str], None],
        resume: bool = False,
    ) -> Any:
        from wasifyai_training.trainer import Paused, Stopped, TrainResult

        tool, base = find_tool(self.data_dir), find_base(self.data_dir)
        why = self.problem()
        if tool is None or base is None or why:
            raise RuntimeError(why or "Training is not set up.")
        home = tool[0]
        folder = job.samples.parent
        work, out = folder / "work", folder / "out"
        started = time.monotonic()
        self._pausing = False
        self._resumed_from = None
        keep = False  # a paused run keeps its pictures and checkpoints
        try:
            total = max(1, math.ceil(job.steps / max(1, len(job.pictures)))) * len(job.pictures)
            await asyncio.to_thread(job.samples.mkdir, parents=True, exist_ok=True)
            if resume:
                zip_ = latest_checkpoint(out / "checkpoints")
                if zip_ is None or not work.is_dir():
                    raise RuntimeError("What was kept of this run is gone. Start it again.")
                args = ["--resume", str(zip_)]
                self._resumed_from = zip_
            else:
                await asyncio.to_thread(shutil.rmtree, work, True)
                await asyncio.to_thread(shutil.rmtree, out, True)
                await asyncio.to_thread(prepare_data, job, work)
                config = training_config(
                    job.steps, len(job.pictures), work, out,
                    sample_every=max(1, total // 4), base=base[0], kind=job.kind,
                )  # fmt: skip
                cfg = folder / "train.json"
                await asyncio.to_thread(cfg.write_text, json.dumps(config, indent=2))
                args = ["--config", str(cfg)]
            try:
                await self._run(home, args, out, job, report, sample, total)
            except RuntimeError:
                if not self._pausing:
                    raise
                step = checkpoint_step(latest_checkpoint(out / "checkpoints"))
                if step is None:
                    raise Stopped(
                        "It was stopped before its first checkpoint, so nothing was kept."
                    ) from None
                keep = True
                raise Paused(step) from None
            adapter = folder / "adapter.safetensors"
            if not await asyncio.to_thread(take_adapter, out / "checkpoints", adapter):
                raise RuntimeError("The training tool finished without an adapter.")
            return TrainResult(
                adapter, time.monotonic() - started, self.engine,
                peak_bytes=self.peak_bytes,
            )  # fmt: skip
        finally:
            if not keep:
                await asyncio.to_thread(shutil.rmtree, work, True)
                await asyncio.to_thread(
                    shutil.rmtree, out, True
                )  # the checkpoints are large; the adapter is kept

    async def _run(
        self, home: Path, args: list[str], out: Path, job: Any,
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
        self.peak_bytes = 0
        holder = self.slot.hold("training") if self.slot is not None else _no_slot()
        async with holder:
            proc = await asyncio.create_subprocess_exec(
                str(home / "bin" / EXECUTABLE), *args,
                env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                stdin=asyncio.subprocess.DEVNULL, start_new_session=True,
            )  # fmt: skip
            self._proc = proc
            sampler = asyncio.create_task(self._sample_memory(proc))
            try:
                await self._watch(proc, out, job, report, sample, tail, seen, total)
                await proc.wait()
            except asyncio.CancelledError:
                _kill_group(proc.pid)
                await proc.wait()
                raise
            finally:
                sampler.cancel()
                self._proc = None
        if proc.returncode != 0:
            raise RuntimeError("The training tool stopped with an error: " + " | ".join(tail[-4:]))

    async def _sample_memory(self, proc: asyncio.subprocess.Process) -> None:
        """The most memory the run held, as the system counts it (Metal buffers included)."""
        while proc.returncode is None:
            held = await asyncio.to_thread(process_footprint, proc.pid)
            self.peak_bytes = max(self.peak_bytes, held)
            await asyncio.sleep(10)

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
            await asyncio.to_thread(prune_checkpoints, out / "checkpoints", 2, self._resumed_from)
        await asyncio.to_thread(self._copy_samples, out, job, sample, seen)

    @staticmethod
    def _copy_samples(out: Path, job: Any, sample: Callable[[str], None], seen: set[str]) -> None:
        """Each new preview picture of mflux becomes a sample of the run: `step-0000-1.png` is what
        the model drew before it learned anything, the later ones what it draws now. A run picked
        up again does not add the ones it already has."""
        for path in sorted((out / "preview").glob("*.png")) if (out / "preview").is_dir() else []:
            found = _PREVIEW_FILE.match(path.name)
            if found is None or path.name in seen:
                continue
            seen.add(path.name)
            kind = re.search(r"(\d+)$", found.group(2))
            name = f"step-{int(found.group(1)):04d}-{kind.group(1) if kind else '1'}.png"
            if (job.samples / name).is_file():
                continue
            shutil.copyfile(path, job.samples / name)
            sample(name)


@contextlib.asynccontextmanager
async def _no_slot():  # type: ignore[no-untyped-def]
    yield


def make_trainer(
    data_dir: Path | None, models_dir: Path | None = None, setup: TrainingSetup | None = None
) -> Any:
    """The trainer of this engine, or None when the training product is not part of this build."""
    try:
        import wasifyai_training  # noqa: F401
    except ImportError:
        return None
    return MfluxTrainer(data_dir, models_dir, setup)
