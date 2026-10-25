"""The desktop's real trainer (mflux), driven through a stand-in for the `mflux-train` program: the
config it builds, the progress and sample pictures it reads, the adapter it takes out, a failure in
words and a stopped run. The real program is run by hand (ADR-0073, "Built: the real trainer")."""

import asyncio
import os
import stat
import sys
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from wasifyai_api import desktop_training as dt
from wasifyai_training.trainer import TrainJob

FAKE = """#!{python}
import json, os, sys, time, zipfile
from pathlib import Path
argv = sys.argv
resume = "--resume" in argv
if resume:
    out = Path(argv[argv.index("--resume") + 1]).parent.parent
    total = int((out / "total.txt").read_text())
    first = int(Path(argv[argv.index("--resume") + 1]).name[:7]) + 1
else:
    cfg = json.loads(Path(argv[argv.index("--config") + 1]).read_text())
    out = Path(cfg["checkpoint"]["output_path"])
    (out / "preview").mkdir(parents=True)
    (out / "checkpoints").mkdir()
    total = cfg["training_loop"]["num_epochs"] * len(list(Path(cfg["data"]).glob("*.png")))
    (out / "total.txt").write_text(str(total))
    first = 1
Path(os.environ["FAKE_PID_FILE"]).write_text(str(os.getpid()))
mode = os.environ.get("FAKE_MODE", "ok")
def preview(n):
    for k in (1, 2):
        Path(out / "preview" / f"{{n:07d}}_preview_image_preview-{{k}}.png").write_bytes(b"png")
def checkpoint(n):
    with zipfile.ZipFile(out / "checkpoints" / f"{{n:07d}}_checkpoint.zip", "w") as z:
        z.writestr(f"{{n:07d}}_adapter.safetensors", b"adapter-bytes")
        z.writestr(f"{{n:07d}}_optimizer.safetensors", b"x" * 1000)
if not resume:
    preview(0)
    sys.stderr.write("\\r100%|##########| 28/28 [00:30<00:00,  1.0s/it]\\n")  # a sample
for step in range(first, total + 1):
    sys.stderr.write(f"\\r 50%|#####     | {{step}}/{{total}} [00:01<00:01,  1.0s/it]")
    sys.stderr.flush()
    if mode == "fail" and step == 2:
        sys.stderr.write("\\nValueError: out of memory\\n")
        sys.exit(3)
    if mode == "hang" and step == 2:
        time.sleep(600)
    if mode == "pause" and step == 5 and not resume:
        checkpoint(3)
        time.sleep(600)
    if mode == "pause_early" and step == 2:
        time.sleep(600)
    if step % 3 == 0:
        preview(step)
    time.sleep(0.01)
checkpoint(total)
"""


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir = tmp_path / "mflux" / "bin"
    bin_dir.mkdir(parents=True)
    tool = bin_dir / dt.EXECUTABLE
    tool.write_text(FAKE.format(python=sys.executable))
    tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("WASIFYAI_MFLUX_DIR", str(tmp_path / "mflux"))
    monkeypatch.setenv("FAKE_PID_FILE", str(tmp_path / "pid"))
    monkeypatch.setattr(dt, "apple_silicon", lambda: True)
    monkeypatch.setattr(dt, "find_base", lambda *_: (tmp_path / "base", "cache"))
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


def test_the_config_makes_epochs_of_the_pictures_and_trains_both_kinds_of_block():
    cfg = dt.training_config(200, 12, Path("/w"), Path("/o"), sample_every=51)
    assert cfg["model"] == "flux2-klein-base-4b"
    assert cfg["training_loop"]["num_epochs"] == 17  # 17 x 12 = 204 steps, at least the 200 asked
    assert (cfg["training_loop"]["timestep_low"], cfg["training_loop"]["timestep_high"]) == (0, 28)
    paths = [t["module_path"] for t in cfg["lora_layers"]["targets"]]
    assert "transformer_blocks.{block}.attn.to_q" in paths
    assert "single_transformer_blocks.{block}.attn.to_qkv_mlp_proj" in paths
    assert all(t["rank"] == 16 for t in cfg["lora_layers"]["targets"])
    assert cfg["monitoring"]["generate_image_frequency"] == 51


def test_progress_is_read_from_the_bar():
    assert dt.parse_progress(" 12%|#   | 12/100 [01:30<10:40,  7.3s/it]") == (12, 100)
    assert dt.parse_progress("Loading weights") is None


def test_it_says_in_words_why_it_cannot_train(home: Path, monkeypatch: pytest.MonkeyPatch):
    trainer = dt.MfluxTrainer(None)
    assert trainer.ready() and trainer.problem() is None
    monkeypatch.setattr(dt, "find_base", lambda *_: None)
    assert "set it up" in (trainer.problem() or "").lower() and not trainer.ready()
    monkeypatch.setattr(dt, "apple_silicon", lambda: False)
    assert "Apple silicon" in (trainer.problem() or "") and "NVIDIA" in (trainer.problem() or "")
    monkeypatch.delenv("WASIFYAI_MFLUX_DIR")
    monkeypatch.setattr(dt, "apple_silicon", lambda: True)
    assert "not set up" in (dt.MfluxTrainer(home / "data").problem() or "")


@pytest.mark.asyncio
async def test_a_run_reports_steps_keeps_the_samples_and_returns_the_adapter(home: Path):
    job = job_in(home)
    steps: list[tuple[int, str]] = []
    samples: list[str] = []
    result = await dt.MfluxTrainer(None).train(
        job, lambda s, w: steps.append((s, w)), samples.append
    )
    assert steps[0] == (0, "Loading the model")
    assert steps[1][0] == 1  # the sample's own bar (28 of 28) is not a training step
    assert [s for s, _ in steps] == sorted(s for s, _ in steps) and steps[-1][0] == job.steps
    assert samples[0] == "step-0000-1.png" and "step-0000-2.png" in samples
    assert all((job.samples / n).is_file() for n in samples)
    assert result.engine == "mflux" and result.adapter.read_bytes() == b"adapter-bytes"
    assert not (job.samples.parent / "work").exists()  # the pictures copy and checkpoints are gone
    assert not (job.samples.parent / "out").exists()


@pytest.mark.asyncio
async def test_a_failure_says_what_the_tool_said(home: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FAKE_MODE", "fail")
    with pytest.raises(RuntimeError, match="out of memory"):
        await dt.MfluxTrainer(None).train(job_in(home), lambda *_: None, lambda _n: None)


@pytest.mark.asyncio
async def test_stopping_a_run_kills_the_process(home: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FAKE_MODE", "hang")
    trainer = dt.MfluxTrainer(None)
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


def test_the_adapter_is_taken_from_the_newest_checkpoint(tmp_path: Path):
    for n, body in ((10, b"old"), (20, b"new")):
        with zipfile.ZipFile(tmp_path / f"{n:07d}_checkpoint.zip", "w") as z:
            z.writestr(f"{n:07d}_adapter.safetensors", body)
    target = tmp_path / "adapter.safetensors"
    assert dt.take_adapter(tmp_path, target) and target.read_bytes() == b"new"
    assert not dt.take_adapter(tmp_path / "none", tmp_path / "x")


def test_the_data_folder_holds_pictures_captions_and_two_sample_prompts(tmp_path: Path):
    job = job_in(tmp_path, pictures=2)
    work = tmp_path / "work"
    dt.prepare_data(job, work)
    assert sorted(p.name for p in work.iterdir()) == [
        "pic-001.png",
        "pic-001.txt",
        "pic-002.png",
        "pic-002.txt",
        "preview-1.txt",
        "preview-2.txt",
    ]
    assert (work / "pic-001.txt").read_text() == "enaq7x, picture 0"
    assert "enaq7x" in (work / "preview-2.txt").read_text()


@pytest.mark.asyncio
async def test_a_taught_model_is_published_to_the_image_engines_styles_and_removed_again(
    tmp_path: Path,
):
    from wasifyai_training import comfy_lora

    adapter = tmp_path / "adapter.safetensors"
    tensors = {}
    for module, (out, inp) in {
        "transformer_blocks.0.attn.to_q": (4, 4),
        "transformer_blocks.0.attn.to_k": (4, 4),
        "transformer_blocks.0.attn.to_v": (4, 4),
        "single_transformer_blocks.0.attn.to_out": (4, 10),
    }.items():
        for ab, shape in (("A", [2, inp]), ("B", [out, 2])):
            n = shape[0] * shape[1]
            tensors[f"transformer.{module}.lora_{ab}.weight"] = {
                "dtype": "F32", "shape": shape, "data": bytes(4 * n),
            }  # fmt: skip
    comfy_lora.write_tensors(adapter, tensors, {})
    trainer = dt.MfluxTrainer(None, tmp_path / "models")
    scans: list[int] = []

    async def scan() -> None:
        scans.append(1)

    trainer.on_published = scan
    name = await trainer.publish(adapter, "My Cat!", "abcdef0123456789")
    assert name == "wasify-my-cat-abcdef01.safetensors"
    published = tmp_path / "models" / "loras" / name
    assert (
        "diffusion_model.double_blocks.0.img_attn.qkv.lora_A.weight"
        in comfy_lora.read_tensors(published)[0]
    )
    await trainer.unpublish(name)
    assert not published.exists() and scans == [1, 1]
    await trainer.unpublish("../escape.safetensors")  # a name that leaves the folder is ignored
    assert await dt.MfluxTrainer(None, None).publish(adapter, "x", "y") is None


def test_each_kind_of_thing_has_its_own_learning_rate():
    rate = lambda kind: dt.training_config(  # noqa: E731
        8, 4, Path("/w"), Path("/o"), sample_every=2, kind=kind
    )["optimizer"]["learning_rate"]
    assert rate("character") == rate("object") == rate("style") == 1e-4
    assert rate("something else") == 1e-4


def test_the_config_names_the_models_own_folder_so_the_trainer_fetches_nothing():
    cfg = dt.training_config(8, 4, Path("/w"), Path("/o"), sample_every=2, base=Path("/m/base"))
    assert cfg["model_path"] == "/m/base"
    assert "model_path" not in dt.training_config(8, 4, Path("/w"), Path("/o"), sample_every=2)


@pytest.mark.asyncio
async def test_a_paused_run_keeps_its_checkpoint_and_goes_on_from_it(
    home: Path, monkeypatch: pytest.MonkeyPatch
):
    from wasifyai_training.trainer import Paused

    monkeypatch.setenv("FAKE_MODE", "pause")
    trainer = dt.MfluxTrainer(None)
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
    assert (folder / "work").is_dir() and (folder / "out" / "checkpoints").is_dir()
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
    trainer = dt.MfluxTrainer(None)
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
    trainer = dt.MfluxTrainer(None)
    with pytest.raises(RuntimeError, match="is gone"):
        await trainer.train(job_in(home), lambda *_: None, lambda _n: None, resume=True)


@pytest.mark.asyncio
async def test_the_most_memory_a_run_held_is_measured(home: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(dt, "process_footprint", lambda pid: 31 * 1024**3)
    result = await dt.MfluxTrainer(None).train(job_in(home), lambda *_: None, lambda _n: None)
    assert result.peak_bytes == 31 * 1024**3


def test_only_the_newest_two_checkpoints_are_kept(tmp_path: Path):
    for n in (25, 50, 75, 100):
        (tmp_path / f"{n:07d}_checkpoint.zip").write_bytes(b"z")
    dt.prune_checkpoints(tmp_path)
    assert [p.name for p in sorted(tmp_path.iterdir())] == [
        "0000075_checkpoint.zip",
        "0000100_checkpoint.zip",
    ]
    assert dt.checkpoint_step(dt.latest_checkpoint(tmp_path)) == 100
    # the checkpoint a picked-up run started from is still read by the trainer: it is never removed
    for n in (50, 125):
        (tmp_path / f"{n:07d}_checkpoint.zip").write_bytes(b"z")
    dt.prune_checkpoints(tmp_path, protect=tmp_path / "0000050_checkpoint.zip")
    names = [p.name for p in sorted(tmp_path.iterdir())]
    assert "0000050_checkpoint.zip" in names and "0000075_checkpoint.zip" not in names
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
    trainer = dt.MfluxTrainer(home)
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


def test_the_config_trains_at_the_side_the_run_asks_for(tmp_path):
    from wasifyai_api.desktop_training import SIDE, training_config

    at_default = training_config(200, 20, tmp_path / "w", tmp_path / "o", sample_every=50)
    at_512 = training_config(200, 20, tmp_path / "w", tmp_path / "o", sample_every=50, side=512)
    assert at_default["max_resolution"] == SIDE == 768 and at_512["max_resolution"] == 512
