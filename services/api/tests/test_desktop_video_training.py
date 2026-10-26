# ruff: noqa: E501  (prose in the docstrings and a script in a string are easier to read on one line)
"""The video trainer's engine: the job it builds, what it reads from the tool's output, a run through a
stand-in for the trainer's Python (the real run is by hand: docs/spikes/video-training-tv0.md) and the
look it publishes for the video engine."""

import asyncio
import json
import stat
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from wasifyai_api import desktop_video_training as dv
from wasifyai_api import training_setup as ts
from wasifyai_api.desktop_models import ModelFile
from wasifyai_training import comfy_lora
from wasifyai_training.trainer import Stopped
from wasifyai_training.video import VideoJob, VideoMedia

FAKE = f"""#!{sys.executable}
import json, os, struct, sys, time
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
job = json.load(open(args[3]))
mode = os.environ.get("FAKE_MODE", "ok")
def emit(**e): print(json.dumps(e), flush=True)
print("a line from a library", flush=True)
emit(event="status", message="Reading the descriptions")
emit(event="status", message="Loading the video model")
for i in range(1, job["steps"] + 1):
    if mode == "slow": time.sleep(5)
    emit(event="progress", step=i, total=job["steps"], loss=1.0 / i, seconds=0.1)
if mode == "crash":
    print("ValueError: something broke", flush=True); sys.exit(2)
if mode != "no_adapter":
    os.makedirs(job["out"], exist_ok=True)
    head = {{"transformer.transformer_blocks.0.attn1.to_q.lora_A.weight": {{"dtype": "BF16", "shape": [2, 4], "data_offsets": [0, 16]}},
             "transformer.transformer_blocks.0.attn1.to_q.lora_B.weight": {{"dtype": "BF16", "shape": [4, 2], "data_offsets": [16, 32]}}}}
    blob = json.dumps(head).encode(); blob += b" " * (-len(blob) % 8)
    open(job["out"] + "/pytorch_lora_weights.safetensors", "wb").write(struct.pack("<Q", len(blob)) + blob + bytes(32))
emit(event="done", seconds=1.0, peak_bytes=9 * 1024**3, adapter=job["out"], loss_first=1.2, loss_last=0.5)
"""


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    py = tmp_path / "venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text(FAKE)
    py.chmod(py.stat().st_mode | stat.S_IXUSR)
    small = tmp_path / "small"
    (small / "tokenizer").mkdir(parents=True)
    monkeypatch.setenv("WASIFYAI_VIDEO_TRAINER_DIR", str(tmp_path / "venv"))
    monkeypatch.setenv("WASIFYAI_VIDEO_SMALL_DIR", str(small))
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "calls.log"))
    monkeypatch.delenv("FAKE_MODE", raising=False)
    monkeypatch.setattr(ts, "apple_silicon", lambda: True)
    monkeypatch.setattr(dv, "apple_silicon", lambda: True)
    return tmp_path


class FakeModels:
    """The models service as far as the trainer uses it: the catalogue entry and where files are."""

    def __init__(self, root: Path, present: bool = True):
        self.models_dir = root / "models"
        files = (
            ModelFile("checkpoints", "ltx-video-2b-v0.9.5.safetensors", "https://x/a", 4, "0" * 64),
            ModelFile("text_encoders", "t5xxl_fp16.safetensors", "https://x/b", 4, "0" * 64),
        )
        self.catalogue = {"ltx-video-2b": SimpleNamespace(files=files, total_bytes=8)}
        self.present = present
        for f in files:
            (root / "models" / f.folder).mkdir(parents=True, exist_ok=True)
            if present:
                (root / "models" / f.folder / f.name).write_bytes(b"abcd")

    def locate(self, f: ModelFile) -> Path | None:
        p = self.models_dir / f.folder / f.name
        return p if p.is_file() and p.stat().st_size == f.size else None


def job(steps: int = 3, tmp: Path | None = None) -> VideoJob:
    media = [
        VideoMedia(Path("/x/picture.png"), "picture", "marlo, a fox"),
        VideoMedia(Path("/x/clip.mp4"), "clip", "marlo, a fox runs", 3.2),
    ]
    return VideoJob("marlo", media, 768, 512, 25, steps, True)


def calls(home: Path) -> list[list[str]]:
    return [json.loads(line) for line in (home / "calls.log").read_text().splitlines()]


def test_the_job_names_the_files_the_size_and_every_picture_and_clip_with_its_description(home):
    eng = dv.LtxTrainer(home, FakeModels(home))
    files = eng.model_files()
    assert (
        files is not None
        and files[0].name == "ltx-video-2b-v0.9.5.safetensors"
        and files[1].name == "t5xxl_fp16.safetensors"
    )
    j = dv.to_job(job(), files, home / "small", "/usr/bin/ffmpeg", home / "out")
    assert (j["width"], j["height"], j["window_frames"], j["steps"], j["rank"], j["lr"]) == (
        768,
        512,
        25,
        3,
        32,
        2e-4,
    )
    assert j["checkpointing"] is True and j["ffmpeg"] == "/usr/bin/ffmpeg" and j["seed"] == 3407
    assert j["items"] == [
        {"path": "/x/picture.png", "kind": "picture", "caption": "marlo, a fox", "seconds": 0.0},
        {"path": "/x/clip.mp4", "kind": "clip", "caption": "marlo, a fox runs", "seconds": 3.2},
    ]  # fmt: skip


def test_it_says_in_words_why_it_cannot_run(home, monkeypatch: pytest.MonkeyPatch):
    eng = dv.LtxTrainer(home, FakeModels(home))
    assert eng.problem() is None and eng.ready()
    assert (
        dv.LtxTrainer(home, FakeModels(home / "no", present=False))
        .problem()
        .startswith("The video model is not on this computer")  # type: ignore[union-attr]
    )
    assert dv.LtxTrainer(home, None).problem().startswith("The video model is not on this computer")  # type: ignore[union-attr]
    monkeypatch.setenv("WASIFYAI_VIDEO_TRAINER_DIR", str(home / "nowhere"))
    assert "not set up" in (eng.problem() or "")
    monkeypatch.setattr(dv, "apple_silicon", lambda: False)
    assert "Apple silicon" in (eng.problem() or "") and "NVIDIA" in (eng.problem() or "")


@pytest.mark.asyncio
async def test_a_run_goes_through_the_script_and_leaves_an_adapter_and_the_losses(home):
    eng = dv.LtxTrainer(home, FakeModels(home))
    seen: list[tuple[int, str]] = []
    result = await eng.train(job(3), home / "run", lambda s, m: seen.append((s, m)))
    assert (
        result.adapter == home / "run" / "out" / "pytorch_lora_weights.safetensors"
        and result.adapter.is_file()
    )
    assert (result.loss_first, result.loss_last, result.peak_bytes) == (
        1.2,
        0.5,
        9 * 1024**3,
    ) or result.peak_bytes >= 9 * 1024**3
    assert (
        seen[0] == (0, "Starting")
        and "Loading the video model" in [m for _, m in seen]
        and seen[-1] == (3, "Learning, step 3 of 3")
    )
    (call,) = calls(home)
    assert call[0] == "-I" and call[1].endswith("video_train.py") and call[2] == "-c"
    assert not (home / "run" / "job.json").exists()  # the job file is not kept


@pytest.mark.asyncio
async def test_a_tool_that_fails_or_leaves_nothing_says_so(home, monkeypatch: pytest.MonkeyPatch):
    eng = dv.LtxTrainer(home, FakeModels(home))
    monkeypatch.setenv("FAKE_MODE", "crash")
    with pytest.raises(RuntimeError, match="something broke"):
        await eng.train(job(2), home / "run", lambda s, m: None)
    monkeypatch.setenv("FAKE_MODE", "no_adapter")
    with pytest.raises(RuntimeError, match="without a model"):
        await eng.train(job(2), home / "run2", lambda s, m: None)


@pytest.mark.asyncio
async def test_stopping_a_run_ends_it_and_keeps_nothing(home, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FAKE_MODE", "slow")
    eng = dv.LtxTrainer(home, FakeModels(home))
    running = asyncio.create_task(eng.train(job(3), home / "run", lambda s, m: None))
    for _ in range(100):
        if eng.busy:
            break
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.5)
    await eng.stop()
    with pytest.raises(Stopped):
        await running
    assert not (home / "run" / "out" / "pytorch_lora_weights.safetensors").exists()


@pytest.mark.asyncio
async def test_a_look_is_published_with_comfyuis_key_names_and_taken_back(home):
    models = FakeModels(home)
    eng = dv.LtxTrainer(home, models)
    told: list[int] = []

    async def scanned() -> None:
        told.append(1)

    eng.on_published = scanned
    result = await eng.train(job(3), home / "run", lambda s, m: None)
    name = await eng.publish(result.adapter, "Ena's look", "a1b2c3d4e5f6")
    assert name == "wasify-video-ena-s-look-a1b2c3d4.safetensors"
    target = models.models_dir / "loras" / name
    tensors, meta = comfy_lora.read_tensors(target)
    assert sorted(tensors) == [
        "transformer_blocks.0.attn1.to_q.lora_A.weight",
        "transformer_blocks.0.attn1.to_q.lora_B.weight",
    ]
    assert (
        meta["taught_on"] == "ltx-video-2b-0.9.5"
        and struct.unpack("<Q", target.read_bytes()[:8])[0] > 0
    )
    assert told == [1]
    await eng.unpublish(name)
    assert not target.exists() and told == [1, 1]
    await eng.unpublish("../outside.safetensors")  # a name with a path is never followed
    assert await dv.LtxTrainer(home, None).publish(result.adapter, "x", "r" * 12) is None


def test_what_to_know_before_a_run_is_read_from_this_computer(
    home, monkeypatch: pytest.MonkeyPatch
):
    eng = dv.LtxTrainer(home, FakeModels(home))
    monkeypatch.setattr(eng, "fit", lambda need_gb: {"verdict": "fits", "reason": ""})
    monkeypatch.setattr(dv, "power_state", lambda: {"source": "ac", "percent": None})
    monkeypatch.setattr(dv, "free_disk_bytes", lambda _: 50 * 1024**3)
    ok = eng.preflight(12.0)
    assert (
        ok["ok"] is True
        and ok["blockers"] == []
        and ok["warnings"] == []
        and "wait while" in ok["pauses"]
    )
    monkeypatch.setattr(dv, "power_state", lambda: {"source": "battery", "percent": 12})
    monkeypatch.setattr(dv, "free_disk_bytes", lambda _: 1024**3)
    monkeypatch.setattr(
        eng, "fit", lambda need_gb: {"verdict": "tight", "reason": "It needs 14 GB."}
    )
    bad = eng.preflight(12.0)
    assert bad["ok"] is False and len(bad["blockers"]) == 2
    assert "disk space" in bad["blockers"][0] and "battery is low (12%)" in bad["blockers"][1]
    assert bad["warnings"] == ["It needs 14 GB. Close other apps first."]
