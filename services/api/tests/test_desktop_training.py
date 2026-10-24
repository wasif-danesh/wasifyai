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
cfg = json.loads(Path(sys.argv[sys.argv.index("--config") + 1]).read_text())
out = Path(cfg["checkpoint"]["output_path"])
Path(os.environ["FAKE_PID_FILE"]).write_text(str(os.getpid()))
(out / "preview").mkdir(parents=True)
(out / "checkpoints").mkdir()
mode = os.environ.get("FAKE_MODE", "ok")
total = cfg["training_loop"]["num_epochs"] * len(list(Path(cfg["data"]).glob("*.png")))
def preview(n):
    for k in (1, 2):
        Path(out / "preview" / f"{{n:07d}}_preview_image_preview-{{k}}.png").write_bytes(b"png")
preview(0)
sys.stderr.write("\\r100%|##########| 28/28 [00:30<00:00,  1.0s/it]\\n")  # a sample, not training
for step in range(1, total + 1):
    sys.stderr.write(f"\\r 50%|#####     | {{step}}/{{total}} [00:01<00:01,  1.0s/it]")
    sys.stderr.flush()
    if mode == "fail" and step == 2:
        sys.stderr.write("\\nValueError: out of memory\\n")
        sys.exit(3)
    if mode == "hang" and step == 2:
        time.sleep(600)
    if step % 3 == 0:
        preview(step)
    time.sleep(0.01)
with zipfile.ZipFile(out / "checkpoints" / f"{{total:07d}}_checkpoint.zip", "w") as z:
    z.writestr(f"{{total:07d}}_adapter.safetensors", b"adapter-bytes")
    z.writestr(f"{{total:07d}}_optimizer.safetensors", b"x" * 1000)
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
    monkeypatch.setattr(dt, "base_on_computer", lambda: True)
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
    monkeypatch.setattr(dt, "base_on_computer", lambda: False)
    assert "12 GB" in (trainer.problem() or "") and not trainer.ready()
    monkeypatch.setattr(dt, "apple_silicon", lambda: False)
    assert "Apple silicon" in (trainer.problem() or "") and "NVIDIA" in (trainer.problem() or "")
    monkeypatch.delenv("WASIFYAI_MFLUX_DIR")
    monkeypatch.setattr(dt, "DEV_FALLBACK", home / "nowhere")
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


def test_the_base_model_counts_only_when_its_big_files_are_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    snap = (
        tmp_path / "hub" / "models--black-forest-labs--FLUX.2-klein-base-4B" / "snapshots" / "abc"
    )
    (snap / "transformer").mkdir(parents=True)
    (snap / "transformer" / "config.json").write_text("{}")
    assert not dt.base_on_computer()  # the folders are there, the weights are not (a download)
    for name in (
        "transformer/diffusion_pytorch_model.safetensors",
        "text_encoder/model-00002-of-00002.safetensors",
        "vae/diffusion_pytorch_model.safetensors",
    ):
        (snap / name).parent.mkdir(parents=True, exist_ok=True)
        (snap / name).write_bytes(b"w")
    assert dt.base_on_computer()


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
