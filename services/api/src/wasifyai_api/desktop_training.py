"""The picture trainer of the desktop profile (ADR-0073, ADR-0076; amendment 2026-11-07).

It is AI Toolkit (Ostris), run as a separate process of its own: `run.py` is given a config and a
folder of pictures with their descriptions, writes sample pictures and checkpoints as it goes, and
an adapter in the key names ComfyUI reads. This module builds the config, reads the progress,
keeps the samples and takes the adapter out. It holds the one big-model slot while it runs
(ADR-0056) and stops the process tree when the run is stopped or the slot is wanted.

The same code runs on a Mac with Apple silicon (PyTorch on the graphics chip) and on Windows or
Linux with an NVIDIA graphics card (CUDA): the owner's aim is that teaching works everywhere.
A model is taught from the image model's own files, the ones Create uses, found where the Models
screen keeps them; nothing is downloaded during a run."""

import asyncio
import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from PIL import Image
from wasifyai_training.picture_bases import (
    KLEIN_4B,
    MAC,
    NVIDIA,
    PICTURE_BASES,
    HubFiles,
    PictureBase,
    picture_base,
)
from wasifyai_training.video_bases import VIDEO_BASES, VideoBase

from wasifyai_api.desktop_fit import assess_fit, need_declared, read_machine
from wasifyai_api.desktop_models import free_disk_bytes
from wasifyai_api.training_setup import (
    TrainingSetup,
    find_base,
    find_tool,
    picture_supported,
    venv_python,
)

# starts `run.py` with klein reading the text encoder folder the config names (AI Toolkit ignores
# it); run with -P so this folder's modules (`logging.py`) do not shadow the standard library's
LAUNCHER = Path(__file__).with_name("training_aitk_run.py")

# the model taught when a run names none; every number that depends on the model (its files,
# its architecture, the memory, the learning rate) is in its recipe in
# `wasifyai_training.picture_bases`
BASE = KLEIN_4B.id
NEED_GB = KLEIN_4B.need_gb
SIDE = 512  # the longest side of a training picture, when a run does not say
RANK = 16
RUN_DISK_BYTES = 3 * 1024**3  # a run's pictures, checkpoints and samples; the model is already kept
MIN_BATTERY_PERCENT = 25  # below this on battery, a run is not started
CHECKPOINT_EVERY = 25  # steps: a pause loses at most this many
NAME = "wasify"  # the run's name inside AI Toolkit: its files are `wasify_000000025.safetensors`
TOKENIZE_SCRIPT = Path(__file__).with_name("training_tokenize.py")
# development: a folder with the image models in ComfyUI's layout (`diffusion_models/`, ...)
MODEL_DIR_ENV = "WASIFYAI_PICTURE_MODEL_DIR"

# a sample shows what the model makes with the magic word: a scene it saw and one it did not
SAMPLE_PROMPTS = {
    "character": "{word}, standing in a sunny park",
    "style": "{word}, a lighthouse on a cliff at sunrise",
    "object": "{word} on a wooden table by a window",
}

# tqdm's bar: "wasify:  12%|███  | 12/100 [01:30<10:40,  7.3s/it, lr: 1.0e-04 loss: 3.2e-01]"
_BAR = re.compile(r"\|\s*(\d+)/(\d+)\s*\[")
_SAMPLE_FILE = re.compile(r"__(\d{9})_(\d+)\.(?:jpg|jpeg|png|webp)$")
_SAVE_FILE = re.compile(rf"^{NAME}_(\d{{9}})\.safetensors$")


def device() -> str:
    """Where AI Toolkit runs: the graphics chip of a Mac, else the first NVIDIA card."""
    return "mps" if sys.platform == "darwin" else "cuda:0"


# fetches a recipe's Hugging Face files in AI Toolkit's own environment, into HF_HOME; the token,
# when there is one, is in the child's environment only and is sent only to huggingface.co
HUB_FETCH = (
    "import json, sys\n"
    "from huggingface_hub import snapshot_download\n"
    "repo, revision, into = sys.argv[1], sys.argv[2], sys.argv[4]\n"
    "patterns = json.loads(sys.argv[3])\n"
    "snapshot_download(repo, revision=revision, allow_patterns=patterns, local_dir=into or None)\n"
    # AI Toolkit loads a repo by name, which offline means the cache's "main": point it at the pin
    "if not into:\n"
    "    from pathlib import Path\n"
    "    from huggingface_hub.constants import HF_HUB_CACHE\n"
    "    refs = Path(HF_HUB_CACHE) / ('models--' + repo.replace('/', '--')) / 'refs'\n"
    "    refs.mkdir(parents=True, exist_ok=True)\n"
    "    (refs / 'main').write_text(revision)\n"
)


def recipe_of(base: str) -> PictureBase | VideoBase:
    """The picture or video recipe AI Toolkit teaches `base` with; a `KeyError` when none."""
    if base in VIDEO_BASES:
        return VIDEO_BASES[base]
    return picture_base(base)


def hub_marker(home: Path, files: HubFiles) -> Path:
    """Written once every file of `files` is in the cache: a half-fetched repo is not used."""
    return home / ".wasify" / f"{files.repo.replace('/', '--')}@{files.revision}.done"


def folder_bytes(folder: Path) -> int:
    total = 0
    for root, _, names in os.walk(folder):
        for n in names:
            with contextlib.suppress(OSError):
                total += (Path(root) / n).stat().st_size
    return total


MODELS_MARK = "{models}/"


def in_models_folder(config: dict[str, Any], root: Path) -> dict[str, Any]:
    """A recipe names a path in the models folder as `{models}/...`; the run gets the real one."""
    for process in config["config"]["process"]:
        model = process["model"]
        for key, value in model.items():
            if isinstance(value, str) and value.startswith(MODELS_MARK):
                model[key] = str(root / value.removeprefix(MODELS_MARK))
    return config


def link_models(root: Path, links: tuple[tuple[str, str], ...]) -> None:
    """Each (AI Toolkit's name, the file) under `root`: AI Toolkit's name made a link to the file
    when the file is there and the name is free."""
    for alias, target in links:
        src, dst = root / target, root / alias
        if src.is_file() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.unlink(missing_ok=True)  # a link left pointing at a removed file
            dst.symlink_to(src)


def where_taught(recipe: PictureBase | VideoBase) -> str | None:
    """Why `recipe` cannot be taught on this kind of computer, or None when it can."""
    here = MAC if sys.platform == "darwin" else NVIDIA
    if here in recipe.devices:
        return None
    if recipe.devices == (NVIDIA,):
        return (
            f"{recipe.title} can be taught only on a computer with an NVIDIA graphics card: "
            "its weights do not load on a Mac."
        )
    return f"{recipe.title} cannot be taught on this computer."


def training_config(
    steps: int,
    work: Path,
    out: Path,
    files: dict[str, Path],
    *,
    sample_every: int,
    prompts: list[str],
    kind: str = "character",
    side: int = SIDE,
    recipe: PictureBase = KLEIN_4B,
) -> dict[str, Any]:
    """AI Toolkit's config for the model `recipe` describes, taught from the image model's own
    `files` (transformer, text encoder folder, vae): a LoRA at rank 16, a checkpoint every 25 steps
    (the newest two kept, so a paused run picks up where it stopped) and sample pictures."""
    model: dict[str, Any]
    if recipe.name_or_path:  # loaded from its Hugging Face repos, read offline from the cache
        model = {"name_or_path": recipe.name_or_path, "arch": recipe.arch, "low_vram": False}
        if recipe.extras:
            model["extras_name_or_path"] = recipe.extras
    else:  # taught from the image model's own files
        model = {
            "name_or_path": str(files["transformer"]),
            "arch": recipe.arch,
            "te_name_or_path": str(files["text_encoder"]),
            "vae_path": str(files["vae"]),
            "low_vram": False,
        }
    if recipe.model_kwargs:
        model["model_kwargs"] = dict(recipe.model_kwargs)
    model |= dict(recipe.model_fields)
    if recipe.quantize:
        model |= {"quantize": True, "qtype": recipe.quantize}
        if recipe.quantize_te:
            model |= {"quantize_te": True, "qtype_te": recipe.quantize}
    process = {
        "type": "sd_trainer",
        "training_folder": str(out),
        "device": device(),
        "network": {"type": "lora", "linear": RANK, "linear_alpha": RANK, **recipe.network_fields},
        "save": {
            "dtype": "float16", "save_every": CHECKPOINT_EVERY, "max_step_saves_to_keep": 2,
        },
        "datasets": [
            {
                "folder_path": str(work), "caption_ext": "txt", "caption_dropout_rate": 0.0,
                "shuffle_tokens": False, "cache_latents_to_disk": True, "resolution": [side],
            }
        ],
        "train": {
            "batch_size": 1, "steps": steps, "train_unet": True, "train_text_encoder": False,
            "gradient_checkpointing": recipe.gradient_checkpointing,
            "noise_scheduler": "flowmatch", "optimizer": "adamw",
            "lr": recipe.learning_rate.get(kind, 1e-4), "dtype": "bf16",
            "disable_sampling": False, **recipe.train_fields,
        },
        "model": model,
        "sample": {
            "sampler": "flowmatch", "sample_every": max(1, sample_every),
            "width": 512, "height": 512, "prompts": prompts, "seed": 42,
            "guidance_scale": recipe.guidance, "sample_steps": recipe.sample_steps,
            # no negative prompt; AI Toolkit's own default is False, which FLUX.3 cannot encode
            "neg": "",
        },
    }  # fmt: skip
    return {
        "job": "extension",
        "config": {"name": NAME, "process": [process]},
        "meta": {"name": NAME},
    }


def text_encoder_dir(small: Path, weights: Path, target: Path) -> Path:
    """The text encoder as one folder, the way AI Toolkit loads it: its settings and tokenizer
    files (the setup's small files) beside the weights the image model uses. Links, not copies;
    a copy only where a link cannot be made (a small file, never the weights)."""
    target.mkdir(parents=True, exist_ok=True)
    wanted = [(weights, "model.safetensors")]
    for sub in ("text_encoder", "tokenizer"):
        # settings and tokenizer only: another copy's weights or shard index (a Hugging Face cache
        # holds both) would be loaded instead of `weights`
        wanted += [
            (f, f.name)
            for f in sorted((small / sub).glob("*"))
            if f.is_file() and f.suffix != ".safetensors" and not f.name.endswith(".index.json")
        ]
    for src, name in wanted:
        dst = target / name
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        try:
            dst.symlink_to(src)
        except OSError:
            try:
                os.link(src, dst)
            except OSError:
                if src == weights:
                    raise RuntimeError(
                        "The text encoder could not be linked into the run's folder."
                    ) from None
                shutil.copyfile(src, dst)
    return target


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
    """The newest checkpoint AI Toolkit kept of the run (`wasify_000000025.safetensors`)."""
    saves = sorted(p for p in folder.glob(f"{NAME}_*.safetensors") if _SAVE_FILE.match(p.name))
    return saves[-1] if saves else None


def checkpoint_step(path: Path | None) -> int | None:
    found = _SAVE_FILE.match(path.name) if path is not None else None
    return int(found.group(1)) if found else None


def _kill_group(pid: int) -> None:
    """The trainer and every process it started."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, check=False)
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, signal.SIGTERM)


def prepare_data(job: Any, work: Path) -> list[str]:
    """The folder AI Toolkit reads: `pic-NNN.png` with `pic-NNN.txt`; the two sample prompts."""
    work.mkdir(parents=True, exist_ok=True)
    for n, (path, caption) in enumerate(zip(job.pictures, job.captions, strict=True), start=1):
        with Image.open(path) as im:
            im.convert("RGB").save(work / f"pic-{n:03d}.png", "PNG")
        (work / f"pic-{n:03d}.txt").write_text(caption, encoding="utf-8")
    first = job.captions[0] if job.captions else job.word
    new = SAMPLE_PROMPTS.get(job.kind, SAMPLE_PROMPTS["character"]).format(word=job.word)
    return [first, new]


class AiToolkitTrainer:
    """The `TrainJob` in, the `TrainResult` out, behind the product's interface (`trainer.py`)."""

    preview = False
    engine = "ai-toolkit"
    base = BASE

    def __init__(
        self,
        data_dir: Path | None = None,
        models_dir: Path | None = None,
        setup: TrainingSetup | None = None,
        models: Any = None,
    ) -> None:
        self.data_dir = data_dir
        self.setup = setup  # what the person can be offered when the trainer is not there yet
        self.models_dir = models_dir  # the image engine reads styles from its `loras` folder
        self.models = models  # the Models screen's catalogue and folders: the image model's files
        self.on_published: Callable[[], Awaitable[None]] | None = None  # the engine looks again
        self.slot: Any = None  # the SlotManager: a run holds the one big-model slot
        self._proc: asyncio.subprocess.Process | None = None
        self._pausing = False
        self.peak_bytes = 0  # the most memory the last run held
        self._words: dict[tuple[str, str], dict[str, Any]] = {}  # how words were split
        self.hub_token: Callable[[], str | None] | None = None  # the person's Hugging Face token
        self._hub: dict[str, Any] = {"state": "idle"}
        self._hub_task: asyncio.Task[None] | None = None

    # ---- what the product asks ---------------------------------------------------------------

    def problem(self, base: str | None = None) -> str | None:
        """What stops `base` (the default model when None) being taught here, or None."""
        if not picture_supported():
            return (
                "Teaching a picture model needs a Mac with Apple silicon, or a computer with an "
                "NVIDIA graphics card."
            )
        if find_tool(self.data_dir) is None or find_base(self.data_dir) is None:
            return "Training is not set up on this computer yet. Set it up first."
        try:
            recipe = picture_base(base or self.base)
        except KeyError:
            return "This picture model cannot be taught yet."
        if why := where_taught(recipe):
            return why
        if recipe.hub:
            if self.hub_missing(recipe.id):
                return (
                    f"The training files of {recipe.title} are not on this computer yet "
                    f"(about {recipe.hub_bytes / 1e9:.0f} GB). Get them first."
                )
            return None
        if self.model_files(recipe.id) is None:
            return (
                f"{recipe.use_with} is not on this computer yet. Choose Select image model on "
                "an Images screen to get it."
            )
        return None

    # ---- a recipe's Hugging Face files ---------------------------------------------------------

    def hub_home(self) -> Path:
        """The Hugging Face cache AI Toolkit reads a recipe's repos from: beside the models."""
        return self.models_root() / "huggingface"

    def models_root(self) -> Path:
        """The models folder in ComfyUI's layout: AI Toolkit reads it as MODELS_PATH."""
        return self.models_dir or (self.data_dir or Path.home()) / "models"

    def hub_missing(self, base: str) -> list[HubFiles]:
        recipe = recipe_of(base)
        return [h for h in recipe.hub if not hub_marker(self.hub_home(), h).is_file()]

    def hub_env(self) -> dict[str, str]:
        """Where a run reads a recipe's files: the Hugging Face cache, and the models (MODELS_PATH,
        ComfyUI's layout)."""
        return {"HF_HOME": str(self.hub_home()), "MODELS_PATH": str(self.models_root())}

    def hub_state(self) -> dict[str, Any]:
        out = dict(self._hub)
        if out.get("state") == "fetching":
            out["bytes_done"] = folder_bytes(self.hub_home() / "hub")
        return out

    def fetch_hub(self, base: str, confirm_bytes: int) -> dict[str, Any]:
        """Start fetching the training files of `base` after the person agreed to their size."""
        try:
            recipe = recipe_of(base)
        except KeyError:
            raise ValueError("This model cannot be taught yet.") from None
        if self._hub_task is not None and not self._hub_task.done():
            raise ValueError("Training files are being fetched already.")
        if why := where_taught(recipe):
            raise ValueError(why)
        tool = find_tool(self.data_dir)
        if tool is None:
            raise ValueError("Training is not set up on this computer yet. Set it up first.")
        missing = self.hub_missing(base)
        need = sum(h.bytes for h in missing)
        if missing and confirm_bytes != need:
            raise ValueError("The size changed since you were asked. Look again.")
        self._hub = {
            "base": base, "state": "fetching", "bytes_total": need,
            "bytes_start": folder_bytes(self.hub_home() / "hub"), "error": None,
        }  # fmt: skip
        self._hub_task = asyncio.create_task(self._fetch(tool[0], missing))
        return self.hub_state()

    async def _fetch(self, home: Path, missing: list[HubFiles]) -> None:
        env = {
            k: v for k, v in os.environ.items() if not k.startswith(("VIRTUAL_ENV", "PYTHONHOME"))
        }
        env |= {"HF_HOME": str(self.hub_home()), "PYTHONUNBUFFERED": "1"}
        env.pop("HF_HUB_OFFLINE", None)
        token = self.hub_token() if self.hub_token is not None else None
        if token:
            env["HF_TOKEN"] = token
        try:
            for files in missing:
                proc = await asyncio.create_subprocess_exec(
                    str(venv_python(home)), "-P", "-c", HUB_FETCH, files.repo, files.revision,
                    json.dumps(list(files.patterns)),
                    str(self.models_root()) if files.into_models else "", cwd=str(home), env=env,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                    stdin=asyncio.subprocess.DEVNULL,
                )  # fmt: skip
                out, _ = await proc.communicate()
                if proc.returncode != 0:
                    text = out.decode(errors="replace")
                    log_tail = text.strip().splitlines()[-1:] or ["no output"]
                    gated = "401" in text or "403" in text or "gated" in text.lower()
                    self._hub |= {
                        "state": "error",
                        "error": (
                            f"{files.repo} needs your Hugging Face token and its terms accepted "
                            "on huggingface.co."
                            if gated
                            else "The training files could not be fetched: " + log_tail[0][-200:]
                        ),
                    }
                    return
                marker = hub_marker(self.hub_home(), files)
                await asyncio.to_thread(marker.parent.mkdir, parents=True, exist_ok=True)
                await asyncio.to_thread(marker.write_text, files.repo)
            self._hub |= {"state": "done"}
        except asyncio.CancelledError:
            self._hub |= {"state": "idle"}
            raise
        except OSError as e:
            why = f"The training files could not be fetched: {e}"
            self._hub |= {"state": "error", "error": why}

    async def cancel_hub(self) -> dict[str, Any]:
        if self._hub_task is not None and not self._hub_task.done():
            self._hub_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._hub_task
        return self.hub_state()

    def model_files(self, base: str | None = None) -> dict[str, Path] | None:
        """The image model's files the recipe of `base` is taught from, by part (transformer,
        text_encoder, vae), where the Models screen keeps them; None when one is missing."""
        recipe = picture_base(base or self.base)
        entry = self.models.catalogue.get(recipe.model) if self.models is not None else None
        env = os.environ.get(MODEL_DIR_ENV)
        found: dict[str, Path] = {}
        for part, name in recipe.files.items():
            path = None
            for f in entry.files if entry is not None else ():
                if f.name == name:
                    path = self.models.locate(f)
            if path is None and env:
                hits = sorted(Path(env).expanduser().glob(f"*/{name}"))
                path = hits[0] if hits else None
            if path is None:
                return None
            found[part] = path
        return found

    def ready(self) -> bool:
        return self.problem() is None

    def fit(self, base: str | None = None) -> dict[str, Any]:
        key = base or self.base
        recipe = PICTURE_BASES.get(key) or PICTURE_BASES.get(KLEIN_4B.id)
        need = recipe.need_gb if recipe else NEED_GB
        return assess_fit(need_declared(need), read_machine()).public()

    def state(self) -> dict[str, Any]:
        return {"engine": self.engine, "preview": False, "base": self.base, "setup": self.problem()}

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
        python = venv_python(tool[0])
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

    async def publish(self, adapter: Path, title: str, run_id: str, base: str = BASE) -> str | None:
        """The adapter taught on `base` in ComfyUI's key names, in the `loras` folder of the models:
        the name an image workflow gives it, or None when there is no folder to put it in."""
        if self.models_dir is None:
            return None
        from wasifyai_training import comfy_lora

        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "model"
        name = f"wasify-{slug}-{run_id[:8]}.safetensors"
        target = self.models_dir / "loras" / name
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(comfy_lora.convert, adapter, target, base)
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

        try:
            recipe = picture_base(getattr(job, "base", None))
        except KeyError:
            raise RuntimeError("This picture model cannot be taught yet.") from None
        hub = bool(recipe.hub)
        tool = find_tool(self.data_dir)
        small = find_base(self.data_dir, base=None if hub else recipe.id)
        files = {} if hub else self.model_files(recipe.id)
        why = self.problem(recipe.id)
        if tool is None or small is None or files is None or why:
            raise RuntimeError(
                why or f"{recipe.title} is not on this computer yet. Set it up first."
            )
        home = tool[0]
        folder = job.samples.parent
        work, out = folder / "work", folder / "out"
        saves = out / NAME
        cfg = folder / "train.json"
        started = time.monotonic()
        self._pausing = False
        keep = False  # a paused run keeps its pictures and checkpoints
        try:
            await asyncio.to_thread(job.samples.mkdir, parents=True, exist_ok=True)
            if resume:
                # AI Toolkit picks a run up from its newest checkpoint when given the same config
                if latest_checkpoint(saves) is None or not work.is_dir() or not cfg.is_file():
                    raise RuntimeError("What was kept of this run is gone. Start it again.")
            else:
                await asyncio.to_thread(shutil.rmtree, work, True)
                await asyncio.to_thread(shutil.rmtree, out, True)
                prompts = await asyncio.to_thread(prepare_data, job, work)
                if not hub:
                    te = await asyncio.to_thread(
                        text_encoder_dir, small[0], files["text_encoder"], folder / "text-encoder"
                    )
                    files = {**files, "text_encoder": te}
                config = training_config(
                    job.steps, work, out, files,
                    sample_every=max(1, job.steps // 4), prompts=prompts, kind=job.kind,
                    side=int(job.settings.get("side", recipe.side_for(job.kind))), recipe=recipe,
                )  # fmt: skip
                if hub:
                    config = in_models_folder(config, self.models_root())
                await asyncio.to_thread(cfg.write_text, json.dumps(config, indent=2))
            if hub:
                await asyncio.to_thread(link_models, self.models_root(), recipe.model_links)
            try:
                await self._run(
                    home, [str(cfg)], saves, job, report, sample,
                    self.hub_env() if hub else None,
                )  # fmt: skip
            except RuntimeError:
                if not self._pausing:
                    raise
                step = checkpoint_step(latest_checkpoint(saves))
                if step is None:
                    raise Stopped(
                        "It was stopped before its first checkpoint, so nothing was kept."
                    ) from None
                keep = True
                raise Paused(step) from None
            adapter = folder / "adapter.safetensors"
            final = saves / f"{NAME}.safetensors"
            if not final.is_file():
                raise RuntimeError("The training tool finished without an adapter.")
            await asyncio.to_thread(shutil.copyfile, final, adapter)
            return TrainResult(
                adapter, time.monotonic() - started, self.engine,
                peak_bytes=self.peak_bytes,
            )  # fmt: skip
        finally:
            if not keep:
                for gone in (work, out, folder / "text-encoder"):
                    # links only in the text encoder's folder: the model's own files stay
                    await asyncio.to_thread(shutil.rmtree, gone, True)

    async def _run(
        self, home: Path, args: list[str], saves: Path, job: Any,
        report: Callable[[int, str], None], sample: Callable[[str], None],
        extra_env: dict[str, str] | None = None,
    ) -> None:  # fmt: skip
        env = {
            k: v for k, v in os.environ.items() if not k.startswith(("VIRTUAL_ENV", "PYTHONHOME"))
        }
        env |= {
            "PYTHONUNBUFFERED": "1",
            "HF_HUB_OFFLINE": "1",  # every file is on the computer or the run does not start
        } | (extra_env or {})
        report(0, "Loading the model")
        tail: list[str] = []
        seen: set[str] = set()
        self.peak_bytes = 0
        holder = self.slot.hold("training") if self.slot is not None else _no_slot()
        apart: dict[str, Any] = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}  # type: ignore[attr-defined]
            if sys.platform == "win32"
            else {"start_new_session": True}
        )
        async with holder:
            proc = await asyncio.create_subprocess_exec(
                str(venv_python(home)), "-P", str(LAUNCHER), str(home), *args, cwd=str(home),
                env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                stdin=asyncio.subprocess.DEVNULL, **apart,
            )  # fmt: skip
            self._proc = proc
            sampler = asyncio.create_task(self._sample_memory(proc))
            try:
                await self._watch(proc, saves, job, report, sample, tail, seen)
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
        self, proc: asyncio.subprocess.Process, saves: Path, job: Any,
        report: Callable[[int, str], None], sample: Callable[[str], None],
        tail: list[str], seen: set[str],
    ) -> None:  # fmt: skip
        assert proc.stdout is not None
        buffer = ""
        reported = -1

        def progress(text: str) -> None:
            """The bar is redrawn in place: a step is known as soon as it is written, not when the
            next one starts."""
            nonlocal reported
            bar = parse_progress(text)
            # the tool draws other bars (caching latents, loading): only the training one counts
            if bar is not None and bar[1] == job.steps and bar[0] != reported:
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
            await asyncio.to_thread(self._copy_samples, saves, job, sample, seen)
        await asyncio.to_thread(self._copy_samples, saves, job, sample, seen)

    @staticmethod
    def _copy_samples(saves: Path, job: Any, sample: Callable[[str], None], seen: set[str]) -> None:
        """Each new sample picture of AI Toolkit becomes a sample of the run, as a PNG:
        `step-0000-1.png` is what the model drew before it learned anything, the later ones what
        it draws now. A run picked up again does not add the ones it already has."""
        folder = saves / "samples"
        for path in sorted(folder.iterdir()) if folder.is_dir() else []:
            found = _SAMPLE_FILE.search(path.name)
            if found is None or path.name in seen:
                continue
            seen.add(path.name)
            name = f"step-{int(found.group(1)):04d}-{int(found.group(2)) + 1}.png"
            if (job.samples / name).is_file():
                continue
            try:
                with Image.open(path) as im:
                    im.convert("RGB").save(job.samples / name, "PNG")
            except OSError:
                seen.discard(path.name)  # still being written: the next look takes it
                continue
            sample(name)


@contextlib.asynccontextmanager
async def _no_slot():  # type: ignore[no-untyped-def]
    yield


def make_trainer(
    data_dir: Path | None,
    models_dir: Path | None = None,
    setup: TrainingSetup | None = None,
    models: Any = None,
) -> Any:
    """The trainer of this engine, or None when the training product is not part of this build.
    `models` (the Models screen's catalogue and folders) is where the image model's files are."""
    try:
        import wasifyai_training  # noqa: F401
    except ImportError:
        return None
    trainer = AiToolkitTrainer(data_dir, models_dir, setup, models)
    if setup is not None and hasattr(setup, "picture_model"):
        setup.picture_model = trainer.model_files
        entry = models.catalogue.get(KLEIN_4B.model) if models is not None else None
        setup.picture_model_bytes = entry.total_bytes if entry is not None else 0
        setup.picture_model_title = KLEIN_4B.use_with
    return trainer
