# ruff: noqa: E501  (the stand-in program and a model entry read better on one line)
"""The desktop's real picture trainer (AI Toolkit), driven through a stand-in for AI Toolkit's
`run.py`: the config it builds, the progress and sample pictures it reads, the adapter it takes
out, a failure in words, a stopped run and a paused one picked up again. The real program is run
by hand (ADR-0073, amendment 2026-11-07)."""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from PIL import Image
from wasifyai_api import desktop_training as dt
from wasifyai_training.trainer import TrainJob

FAKE = """
import json, os, sys, time
from pathlib import Path
from PIL import Image
cfg = json.loads(Path(sys.argv[1]).read_text())
p = cfg["config"]["process"][0]
name = cfg["config"]["name"]
out = Path(p["training_folder"]) / name
(out / "samples").mkdir(parents=True, exist_ok=True)
total = p["train"]["steps"]
every = p["sample"]["sample_every"]
saves = sorted(out.glob(name + "_*.safetensors"))
first = int(saves[-1].stem.rsplit("_", 1)[1]) + 1 if saves else 1
Path(os.environ["FAKE_PID_FILE"]).write_text(str(os.getpid()))
from extensions_built_in.diffusion_models.flux2.flux2_klein_model import Flux2Klein4BModel
cfg["klein_te"] = Flux2Klein4BModel.flux2_klein_te_path
cfg["hf_home"] = os.environ.get("HF_HOME")
Path(os.environ["FAKE_CFG_FILE"]).write_text(json.dumps(cfg))
mode = os.environ.get("FAKE_MODE", "ok")
pictures = len(list(Path(p["datasets"][0]["folder_path"]).glob("*.png")))
def samples(n):
    for k in range(len(p["sample"]["prompts"])):
        Image.new("RGB", (8, 8), (n, k * 40, 90)).save(out / "samples" / f"17000{n}__{n:09d}_{k}.jpg")
def save(n):
    (out / f"{name}_{n:09d}.safetensors").write_bytes(b"checkpoint")
sys.stderr.write(f"\\rCaching latents: 100%|##| {pictures}/{pictures} [00:01<00:00]\\n")
if not saves:
    samples(0)
for step in range(first, total + 1):
    sys.stderr.write(f"\\r{name}:  50%|#####     | {step}/{total} [00:01<00:01,  1.0s/it, loss: 0.3]")
    sys.stderr.flush()
    if mode == "fail" and step == 2:
        sys.stderr.write("\\nRuntimeError: MPS backend out of memory\\n")
        sys.exit(3)
    if mode == "hang" and step == 2:
        time.sleep(600)
    if mode == "pause" and step == 5 and first == 1:
        save(3)
        time.sleep(600)
    if mode == "pause_early" and step == 2:
        time.sleep(600)
    if step % every == 0:
        samples(step)
    time.sleep(0.01)
(out / f"{name}.safetensors").write_bytes(b"adapter-bytes")
"""


# AI Toolkit's klein classes as the launcher finds them; the fake `run.py` writes down where klein reads its
# text encoder from
KLEIN = """
class Flux2KleinModel:
    flux2_klein_te_path = None
class Flux2Klein4BModel(Flux2KleinModel):
    arch = "flux2_klein_4b"
    flux2_klein_te_path = "Qwen/Qwen3-4B"
"""


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in AI Toolkit folder, its small files and the image model's files."""
    tool = tmp_path / "ai-toolkit"
    (tool / ".venv" / "bin").mkdir(parents=True)
    (tool / "run.py").write_text(FAKE)
    klein = tool / "extensions_built_in" / "diffusion_models" / "flux2"
    klein.mkdir(parents=True)
    for d in (klein.parent.parent, klein.parent, klein):
        (d / "__init__.py").write_text("")
    (klein / "flux2_klein_model.py").write_text(KLEIN)
    python = tool / ".venv" / "bin" / "python"
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    python.chmod(0o755)
    small = tmp_path / "small"
    for f in ("text_encoder/config.json", "tokenizer/tokenizer.json", "tokenizer/vocab.json"):
        (small / f).parent.mkdir(parents=True, exist_ok=True)
        (small / f).write_text("{}")
    models = tmp_path / "comfy"
    for folder, name in (
        ("diffusion_models", "flux-2-klein-4b.safetensors"),
        ("text_encoders", "qwen_3_4b.safetensors"),
        ("vae", "flux2-vae.safetensors"),
    ):
        (models / folder).mkdir(parents=True, exist_ok=True)
        (models / folder / name).write_bytes(b"weights")
    monkeypatch.setenv("WASIFYAI_AI_TOOLKIT_DIR", str(tool))
    monkeypatch.setenv(dt.MODEL_DIR_ENV, str(models))
    monkeypatch.setenv("FAKE_PID_FILE", str(tmp_path / "pid"))
    monkeypatch.setenv("FAKE_CFG_FILE", str(tmp_path / "cfg.json"))
    monkeypatch.setattr(dt, "picture_supported", lambda: True)
    monkeypatch.setattr(dt, "find_base", lambda *_, **__: (small, "cache"))
    return tmp_path


def job_in(tmp_path: Path, pictures: int = 4, steps: int = 8) -> TrainJob:
    pics = []
    for n in range(pictures):
        p = tmp_path / f"p{n}.png"
        Image.new("RGB", (64, 64), (n * 20, 50, 90)).save(p)
        pics.append(p)
    folder = tmp_path / "run"
    return TrainJob(
        kind="character", word="enaq7x", steps=steps, pictures=pics,
        captions=[f"enaq7x, picture {n}" for n in range(pictures)], samples=folder / "samples",
    )  # fmt: skip


FILES = {
    "transformer": Path("/m/diffusion_models/flux-2-klein-4b.safetensors"),
    "text_encoder": Path("/run/text-encoder"),
    "vae": Path("/m/vae/flux2-vae.safetensors"),
}


def config(**kw: object) -> dict:
    args = {"sample_every": 50, "prompts": ["a", "b"], **kw}
    return dt.training_config(200, Path("/w"), Path("/o"), FILES, **args)["config"]["process"][0]  # type: ignore[arg-type]


def test_the_config_teaches_the_image_models_own_files_at_rank_16():
    p = config()
    assert p["model"]["arch"] == "flux2_klein_4b"
    assert p["model"]["name_or_path"] == str(FILES["transformer"])
    assert p["model"]["te_name_or_path"] == "/run/text-encoder"
    assert p["model"]["vae_path"] == str(FILES["vae"])
    assert p["model"]["qtype"] == p["model"]["qtype_te"] == "convrot8"
    assert p["network"] == {"type": "lora", "linear": 16, "linear_alpha": 16}
    assert p["train"]["steps"] == 200 and p["train"]["lr"] == 1e-4
    assert p["save"]["save_every"] == dt.CHECKPOINT_EVERY == 25
    assert p["sample"]["sample_every"] == 50 and p["sample"]["prompts"] == ["a", "b"]
    assert p["datasets"][0]["folder_path"] == "/w" and p["datasets"][0]["resolution"] == [512]
    assert p["training_folder"] == "/o"


def test_the_config_runs_on_the_macs_graphics_chip_or_the_first_nvidia_card(monkeypatch):
    monkeypatch.setattr(dt.sys, "platform", "darwin")
    assert config()["device"] == "mps"
    for name in ("linux", "win32"):
        monkeypatch.setattr(dt.sys, "platform", name)
        assert config()["device"] == "cuda:0"


def test_the_config_takes_the_architecture_size_and_rate_from_the_recipe():
    from dataclasses import replace

    from wasifyai_training.picture_bases import KLEIN_4B

    recipe = replace(
        KLEIN_4B, arch="flux2_klein_9b", learning_rate={"style": 5e-5}, quantize="", guidance=4.0
    )
    p = config(kind="style", recipe=recipe, side=768)
    assert p["model"]["arch"] == "flux2_klein_9b" and "qtype" not in p["model"]
    assert p["train"]["lr"] == 5e-5 and p["sample"]["guidance_scale"] == 4.0
    assert p["datasets"][0]["resolution"] == [768]


def test_progress_is_read_from_the_bar():
    assert dt.parse_progress("wasify:  12%|#   | 12/100 [01:30<10:40,  7.3s/it]") == (12, 100)
    assert dt.parse_progress("Loading weights") is None


def test_it_says_in_words_why_it_cannot_train(home: Path, monkeypatch: pytest.MonkeyPatch):
    trainer = dt.AiToolkitTrainer(None)
    assert trainer.ready() and trainer.problem() is None
    monkeypatch.setattr(dt, "find_base", lambda *_, **__: None)
    assert "set it up" in (trainer.problem() or "").lower() and not trainer.ready()
    monkeypatch.setattr(dt, "picture_supported", lambda: False)
    assert "Apple silicon" in (trainer.problem() or "") and "NVIDIA" in (trainer.problem() or "")
    monkeypatch.setattr(dt, "picture_supported", lambda: True)
    monkeypatch.setattr(dt, "find_base", lambda *_, **__: (home / "small", "cache"))
    monkeypatch.delenv(dt.MODEL_DIR_ENV)
    assert "Select image model" in (trainer.problem() or "")
    monkeypatch.delenv("WASIFYAI_AI_TOOLKIT_DIR")
    assert "not set up" in (dt.AiToolkitTrainer(home / "data").problem() or "")


def test_the_image_models_files_are_found_where_the_models_screen_keeps_them(tmp_path: Path):
    from wasifyai_api.desktop_models import FolderModels, ModelEntry, ModelFile

    files = [
        ModelFile("diffusion_models", "flux-2-klein-4b.safetensors", "u", 5, "0" * 64),
        ModelFile("text_encoders", "qwen_3_4b.safetensors", "u", 5, "0" * 64),
        ModelFile("vae", "flux2-vae.safetensors", "u", 5, "0" * 64),
    ]
    entry = ModelEntry(
        "flux2-klein-4b", "wasifyai-image", "FLUX.2 klein 4B", "", "", 0, tuple(files)
    )
    shared = tmp_path / "ComfyUI-Shared" / "models"
    models = FolderModels([entry], tmp_path / "own", (shared,))
    trainer = dt.AiToolkitTrainer(None, None, None, models)
    assert trainer.model_files() is None
    for f in files:
        (shared / f.folder).mkdir(parents=True, exist_ok=True)
        (shared / f.folder / f.name).write_bytes(b"12345")
    found = trainer.model_files()
    assert found is not None and found["vae"] == shared / "vae" / "flux2-vae.safetensors"
    assert found["text_encoder"].name == "qwen_3_4b.safetensors"


def test_the_text_encoder_is_one_folder_of_links_beside_the_weights(tmp_path: Path):
    small = tmp_path / "small"
    for f in (
        "text_encoder/config.json", "tokenizer/tokenizer.json",
        # a Hugging Face cache also holds the model's own weights in shards: never taken
        "text_encoder/model-00001-of-00002.safetensors", "text_encoder/model.safetensors.index.json",
    ):  # fmt: skip
        (small / f).parent.mkdir(parents=True, exist_ok=True)
        (small / f).write_text("{}")
    weights = tmp_path / "qwen_3_4b.safetensors"
    weights.write_bytes(b"w" * 10)
    te = dt.text_encoder_dir(small, weights, tmp_path / "te")
    assert sorted(p.name for p in te.iterdir()) == [
        "config.json", "model.safetensors", "tokenizer.json",
    ]  # fmt: skip
    assert (te / "model.safetensors").read_bytes() == weights.read_bytes()
    assert (te / "model.safetensors").is_symlink()  # never an 8 GB copy
    dt.text_encoder_dir(small, weights, tmp_path / "te")  # made again over itself
    import shutil

    shutil.rmtree(te)
    assert weights.is_file()  # removing the run's folder leaves the model's own file


@pytest.mark.asyncio
async def test_a_run_reports_steps_keeps_the_samples_and_returns_the_adapter(home: Path):
    job = job_in(home)
    steps: list[tuple[int, str]] = []
    samples: list[str] = []
    result = await dt.AiToolkitTrainer(None).train(
        job, lambda s, w: steps.append((s, w)), samples.append
    )
    assert steps[0] == (0, "Loading the model")
    assert steps[1][0] == 1  # the caching bar (4 of 4) is not a training step
    assert [s for s, _ in steps] == sorted(s for s, _ in steps) and steps[-1][0] == job.steps
    assert samples[0] == "step-0000-1.png" and "step-0000-2.png" in samples
    assert "step-0008-2.png" in samples
    assert all((job.samples / n).is_file() for n in samples)
    with Image.open(job.samples / samples[0]) as im:
        assert im.format == "PNG"
    assert result.engine == "ai-toolkit" and result.adapter.read_bytes() == b"adapter-bytes"
    folder = job.samples.parent
    assert not (folder / "work").exists() and not (folder / "out").exists()
    assert not (folder / "text-encoder").exists()
    seen = json.loads((home / "cfg.json").read_text())
    cfg = seen["config"]["process"][0]
    # klein read the text encoder folder the config names, not the Hub's "Qwen/Qwen3-4B"
    assert seen["klein_te"] == cfg["model"]["te_name_or_path"]
    assert cfg["sample"]["prompts"][0] == "enaq7x, picture 0"
    assert "enaq7x" in cfg["sample"]["prompts"][1] and cfg["sample"]["sample_every"] == 2
    assert Path(cfg["model"]["te_name_or_path"]).name == "text-encoder"
    assert (home / "comfy" / "text_encoders" / "qwen_3_4b.safetensors").is_file()


@pytest.mark.asyncio
async def test_a_failure_says_what_the_tool_said(home: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FAKE_MODE", "fail")
    with pytest.raises(RuntimeError, match="out of memory"):
        await dt.AiToolkitTrainer(None).train(job_in(home), lambda *_: None, lambda _n: None)


@pytest.mark.asyncio
async def test_stopping_a_run_kills_the_process(home: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FAKE_MODE", "hang")
    trainer = dt.AiToolkitTrainer(None)
    reached = asyncio.Event()

    def report(step: int, _words: str) -> None:
        if step >= 2:
            reached.set()

    task = asyncio.create_task(trainer.train(job_in(home), report, lambda _n: None))
    await asyncio.wait_for(reached.wait(), 20)
    pid = int((home / "pid").read_text())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert not trainer.busy


def test_the_data_folder_holds_pictures_and_captions_and_gives_two_sample_prompts(tmp_path: Path):
    job = job_in(tmp_path, pictures=2)
    work = tmp_path / "work"
    prompts = dt.prepare_data(job, work)
    assert sorted(p.name for p in work.iterdir()) == [
        "pic-001.png", "pic-001.txt", "pic-002.png", "pic-002.txt",
    ]  # fmt: skip
    assert (work / "pic-001.txt").read_text() == "enaq7x, picture 0"
    assert prompts[0] == "enaq7x, picture 0" and "enaq7x" in prompts[1]


@pytest.mark.asyncio
async def test_a_taught_model_is_published_to_the_image_engines_styles_and_removed_again(
    tmp_path: Path,
):
    from wasifyai_training import comfy_lora

    adapter = tmp_path / "adapter.safetensors"
    tensors = {}
    for module, (out, inp) in {
        "double_blocks.0.img_attn.qkv": (12, 4),
        "single_blocks.0.linear2": (4, 10),
    }.items():
        for ab, shape in (("A", [2, inp]), ("B", [out, 2])):
            tensors[f"diffusion_model.{module}.lora_{ab}.weight"] = {
                "dtype": "F32", "shape": shape, "data": bytes(4 * shape[0] * shape[1]),
            }  # fmt: skip
    comfy_lora.write_tensors(adapter, tensors, {"software": "ai-toolkit"})
    trainer = dt.AiToolkitTrainer(None, tmp_path / "models")
    scans: list[int] = []

    async def scan() -> None:
        scans.append(1)

    trainer.on_published = scan
    name = await trainer.publish(adapter, "My Cat!", "abcdef0123456789")
    assert name == "wasify-my-cat-abcdef01.safetensors"
    published = tmp_path / "models" / "loras" / name
    tensors, meta = comfy_lora.read_tensors(published)
    assert "diffusion_model.double_blocks.0.img_attn.qkv.lora_A.weight" in tensors
    assert meta["taught_on"] == "flux2-klein-4b"
    await trainer.unpublish(name)
    assert not published.exists() and scans == [1, 1]
    await trainer.unpublish("../escape.safetensors")  # a name that leaves the folder is ignored
    assert await dt.AiToolkitTrainer(None, None).publish(adapter, "x", "y") is None


@pytest.mark.asyncio
async def test_a_paused_run_keeps_its_checkpoint_and_goes_on_from_it(
    home: Path, monkeypatch: pytest.MonkeyPatch
):
    from wasifyai_training.trainer import Paused

    monkeypatch.setenv("FAKE_MODE", "pause")
    trainer = dt.AiToolkitTrainer(None)
    job = job_in(home, pictures=4, steps=8)
    reached = asyncio.Event()

    def report(step: int, _words: str) -> None:
        if step >= 5:
            reached.set()

    task = asyncio.create_task(trainer.train(job, report, lambda _n: None))
    await asyncio.wait_for(reached.wait(), 20)
    await asyncio.sleep(0.2)
    await trainer.pause()
    with pytest.raises(Paused) as stopped:
        await task
    assert stopped.value.step == 3  # the checkpoint it had written
    folder = job.samples.parent
    assert (folder / "work").is_dir() and dt.latest_checkpoint(folder / "out" / dt.NAME)
    seen: list[int] = []
    result = await trainer.train(job, lambda s, _w: seen.append(s), lambda _n: None, resume=True)
    assert seen and seen[-1] == job.steps and min(s for s in seen if s) >= 4
    assert result.adapter.read_bytes() == b"adapter-bytes"
    assert not (folder / "work").exists() and not (folder / "out").exists()


@pytest.mark.asyncio
async def test_a_run_stopped_before_its_first_checkpoint_keeps_nothing(
    home: Path, monkeypatch: pytest.MonkeyPatch
):
    from wasifyai_training.trainer import Stopped

    monkeypatch.setenv("FAKE_MODE", "pause_early")
    trainer = dt.AiToolkitTrainer(None)
    job = job_in(home)
    reached = asyncio.Event()
    task = asyncio.create_task(
        trainer.train(job, lambda s, _w: reached.set() if s >= 2 else None, lambda _n: None)
    )
    await asyncio.wait_for(reached.wait(), 20)
    await asyncio.sleep(0.2)
    await trainer.pause()
    with pytest.raises(Stopped, match="nothing was kept"):
        await task
    assert not (job.samples.parent / "work").exists()


@pytest.mark.asyncio
async def test_a_run_that_cannot_be_picked_up_says_so(home: Path):
    trainer = dt.AiToolkitTrainer(None)
    with pytest.raises(RuntimeError, match="is gone"):
        await trainer.train(job_in(home), lambda *_: None, lambda _n: None, resume=True)


@pytest.mark.asyncio
async def test_the_most_memory_a_run_held_is_measured(home: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(dt, "process_footprint", lambda pid: 31 * 1024**3)
    result = await dt.AiToolkitTrainer(None).train(job_in(home), lambda *_: None, lambda _n: None)
    assert result.peak_bytes == 31 * 1024**3


def test_the_newest_checkpoint_is_read_by_its_step(tmp_path: Path):
    for n in (25, 50):
        (tmp_path / f"wasify_{n:09d}.safetensors").write_bytes(b"z")
    (tmp_path / "wasify.safetensors").write_bytes(b"final")  # the adapter is not a checkpoint
    (tmp_path / "optimizer.pt").write_bytes(b"o")
    assert dt.checkpoint_step(dt.latest_checkpoint(tmp_path)) == 50
    assert dt.latest_checkpoint(tmp_path / "none") is None


def test_the_battery_and_the_memory_a_process_holds_are_read_in_words_and_numbers(
    monkeypatch: pytest.MonkeyPatch,
):
    class Done:
        def __init__(self, out: str):
            self.stdout = out

    monkeypatch.setattr(
        dt.subprocess,
        "run",
        lambda *a, **k: Done(
            "Now drawing from 'Battery Power'\n -InternalBattery-0\t73%; discharging"
        ),
    )
    assert dt.power_state() == {"source": "battery", "percent": 73}
    monkeypatch.setattr(dt.subprocess, "run", lambda *a, **k: Done("Now drawing from 'AC Power'"))
    assert dt.power_state()["source"] == "mains"
    monkeypatch.setattr(
        dt.subprocess, "run", lambda *a, **k: Done("zsh [1]: 64-bit    Footprint: 28.5 GB (16384)")
    )
    assert dt.process_footprint(1) == int(28.5 * 1024**3)


def test_before_a_run_it_says_what_stops_it_and_what_to_look_out_for(
    home: Path, monkeypatch: pytest.MonkeyPatch
):
    trainer = dt.AiToolkitTrainer(home)
    fit = {
        "verdict": "fits",
        "reason": "",
        "needed_bytes": 28 * 1024**3,
        "budget_bytes": 40 * 1024**3,
    }
    monkeypatch.setattr(trainer, "fit", lambda: fit)
    monkeypatch.setattr(dt, "free_disk_bytes", lambda p: 50 * 1024**3)
    monkeypatch.setattr(dt, "power_state", lambda: {"source": "mains", "percent": 100})
    ok = trainer.preflight()
    assert ok["ok"] and ok["blockers"] == [] and ok["warnings"] == []
    assert "wait" in ok["pauses"] and ok["facts"]["power"] == "mains"
    monkeypatch.setattr(dt, "power_state", lambda: {"source": "battery", "percent": 70})
    warn = trainer.preflight()
    assert warn["ok"] and "battery power (70%)" in warn["warnings"][0]
    monkeypatch.setattr(dt, "power_state", lambda: {"source": "battery", "percent": 12})
    assert "battery is low" in trainer.preflight()["blockers"][0]
    monkeypatch.setattr(dt, "power_state", lambda: {"source": "mains", "percent": 100})
    monkeypatch.setattr(dt, "free_disk_bytes", lambda p: 1 * 1024**3)
    assert "not enough free disk space" in trainer.preflight()["blockers"][0]
    monkeypatch.setattr(dt, "free_disk_bytes", lambda p: 50 * 1024**3)
    monkeypatch.setattr(
        trainer, "fit", lambda: {**fit, "verdict": "too_big", "reason": "Needs 40 GB."}
    )
    assert trainer.preflight()["blockers"] == ["Needs 40 GB."]
    monkeypatch.setattr(trainer, "fit", lambda: {**fit, "verdict": "tight", "reason": "Tight."})
    assert "Close other apps" in trainer.preflight()["warnings"][0]


def test_set_up_finds_only_the_picture_model_it_pinned(tmp_path):
    from wasifyai_api import training_setup as ts

    pins = ts.load_pins()
    assert ts.find_base(tmp_path, pins, base="flux2-klein-9b") is None


# ---- a recipe AI Toolkit loads from Hugging Face -------------------------------------------------

from wasifyai_training import picture_bases as pb  # noqa: E402

HUB_RECIPE = pb.PictureBase(
    id="test-hub", title="Test Hub", model="test-hub", use_with="Test Hub", arch="flux3",
    name_or_path="org/test-base", hub=(pb.HubFiles("org/test-base", "abc123", ("*.json",), 3_000_000_000),),
    need_gb=1.0,
)  # fmt: skip

FETCH = """
import os, sys
from pathlib import Path
home = Path(os.environ["HF_HOME"]) / "hub"
home.mkdir(parents=True, exist_ok=True)
(home / "got.json").write_text(sys.argv[1] + "@" + sys.argv[2] + " " + sys.argv[3])
(home / "token").write_text(os.environ.get("HF_TOKEN", "none"))
sys.exit(1 if sys.argv[1] == "org/gated" else 0)
"""


@pytest.fixture
def hub_recipe(monkeypatch: pytest.MonkeyPatch) -> pb.PictureBase:
    monkeypatch.setitem(pb.PICTURE_BASES, HUB_RECIPE.id, HUB_RECIPE)
    monkeypatch.setattr(dt, "HUB_FETCH", FETCH)
    return HUB_RECIPE


async def test_a_hub_recipe_is_taught_once_its_files_are_fetched(home: Path, hub_recipe):
    trainer = dt.AiToolkitTrainer(home / "data", models_dir=home / "models")
    trainer.hub_token = lambda: "hf_secret"
    why = trainer.problem(hub_recipe.id) or ""
    assert "training files of Test Hub" in why and "3 GB" in why
    assert trainer.problem() is None  # the default model is unaffected
    with pytest.raises(ValueError, match="size changed"):
        trainer.fetch_hub(hub_recipe.id, 1)
    state = trainer.fetch_hub(hub_recipe.id, 3_000_000_000)
    assert state["state"] == "fetching"
    await trainer._hub_task  # noqa: SLF001
    assert trainer.hub_state()["state"] == "done"
    cache = home / "models" / "huggingface" / "hub"
    assert (cache / "got.json").read_text() == 'org/test-base@abc123 ["*.json"]'
    assert (cache / "token").read_text() == "hf_secret"  # in the child's environment only
    assert trainer.problem(hub_recipe.id) is None and trainer.hub_missing(hub_recipe.id) == []


async def test_a_gated_repo_that_cannot_be_fetched_says_what_to_do(
    home: Path, hub_recipe, monkeypatch
):
    gated = pb.PictureBase(
        id="test-gated", title="Gated", model="g", use_with="Gated", arch="x",
        name_or_path="org/gated", hub=(pb.HubFiles("org/gated", "r1", bytes=10),),
    )  # fmt: skip
    monkeypatch.setitem(pb.PICTURE_BASES, gated.id, gated)
    trainer = dt.AiToolkitTrainer(home / "data", models_dir=home / "models")
    trainer.fetch_hub(gated.id, 10)
    await trainer._hub_task  # noqa: SLF001
    out = trainer.hub_state()
    assert out["state"] == "error" and out["error"]
    assert trainer.hub_missing(gated.id)


def test_a_recipe_for_nvidia_only_says_so_on_a_mac(home: Path, monkeypatch: pytest.MonkeyPatch):
    nvidia = pb.PictureBase(
        id="test-nvidia", title="Big One", model="b", use_with="Big One", arch="x",
        devices=(pb.NVIDIA,),
    )  # fmt: skip
    monkeypatch.setitem(pb.PICTURE_BASES, nvidia.id, nvidia)
    monkeypatch.setattr(dt.sys, "platform", "darwin")
    trainer = dt.AiToolkitTrainer(home / "data", models_dir=home / "models")
    assert "NVIDIA graphics card" in (trainer.problem(nvidia.id) or "")
    with pytest.raises(ValueError, match="NVIDIA"):
        trainer.fetch_hub(nvidia.id, 0)


async def test_a_hub_run_reads_its_repo_offline_from_the_cache_beside_the_models(
    home: Path, hub_recipe
):
    trainer = dt.AiToolkitTrainer(home / "data", models_dir=home / "models")
    marker = dt.hub_marker(trainer.hub_home(), hub_recipe.hub[0])
    marker.parent.mkdir(parents=True)
    marker.write_text("done")
    job = job_in(home, steps=4)
    job.base = hub_recipe.id  # type: ignore[attr-defined]
    await trainer.train(job, lambda *_: None, lambda *_: None)
    cfg = json.loads((home / "cfg.json").read_text())
    model = cfg["config"]["process"][0]["model"]
    assert model["name_or_path"] == "org/test-base" and model["arch"] == "flux3"
    assert "te_name_or_path" not in model
    assert cfg["hf_home"] == str(home / "models" / "huggingface")


def test_a_recipe_link_lets_ai_toolkit_use_the_fetched_file(tmp_path: Path):
    links = pb.FLUX3_KLEIN.model_links
    fetched = tmp_path / links[0][1]
    fetched.parent.mkdir(parents=True)
    fetched.write_bytes(b"bf16")
    dt.link_models(tmp_path, links)
    dt.link_models(tmp_path, links)  # a second run keeps the link
    alias = tmp_path / "diffusion_models" / "flux3_image_klein_bf16.safetensors"
    assert alias.is_symlink() and alias.read_bytes() == b"bf16"
    dt.link_models(tmp_path, (("vae/missing.safetensors", "vae/not-there.safetensors"),))
    assert not (tmp_path / "vae").exists()  # nothing to point at: no link


def test_a_recipe_path_in_the_models_folder_becomes_the_real_one(tmp_path: Path):
    config = dt.training_config(
        10, tmp_path / "w", tmp_path / "o", {}, sample_every=5, prompts=[], kind="character",
        side=512, recipe=pb.FLUX3_KLEIN,
    )  # fmt: skip
    model = dt.in_models_folder(config, tmp_path)["config"]["process"][0]["model"]
    assert model["te_name_or_path"].startswith(str(tmp_path / "huggingface" / "hub"))
    assert model["name_or_path"] == "black-forest-labs/flux-3-image-klein-base"
    assert config["config"]["process"][0]["sample"]["neg"] == ""  # not AI Toolkit's False
