"""The newer video models taught with AI Toolkit (ADR-0097, MV5): the config from the recipe, which
trainer a model goes to, what stops a model being taught here, and a run with a stand-in tool."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from wasifyai_api import desktop_training as dt
from wasifyai_api.desktop_video_aitk import AitkVideoTrainer, VideoTrainers, video_config
from wasifyai_api.desktop_video_training import LtxTrainer
from wasifyai_training.picture_bases import NVIDIA
from wasifyai_training.video import VideoJob, VideoMedia
from wasifyai_training.video_bases import LTX_25, MINIMAX_H3, VIDEO_BASES

from tests.test_desktop_training import home  # noqa: F401  (the stand-in AI Toolkit)


class Models:
    """The Models screen's catalogue: Create's files of each video model, all on this computer."""

    def __init__(self, root: Path, have: bool = True) -> None:
        self.models_dir = root
        f = SimpleNamespace(name="ltx.safetensors")
        self.catalogue = {v.model: SimpleNamespace(files=[f]) for v in VIDEO_BASES.values()}
        self.have = have

    def locate(self, f):  # noqa: ANN001
        return self.models_dir / f.name if self.have else None


def trainers(root: Path, have: bool = True) -> VideoTrainers:
    models = Models(root / "models", have)
    pictures = dt.AiToolkitTrainer(root / "data", models_dir=root / "models", models=models)
    ltx = LtxTrainer(root / "data", models)
    return VideoTrainers(ltx, AitkVideoTrainer(pictures, ltx))


def test_the_config_takes_the_recipes_files_frames_and_defaults():
    cfg = video_config(MINIMAX_H3, 30, Path("/w"), Path("/o"))["config"]["process"][0]
    model, data = cfg["model"], cfg["datasets"][0]
    assert model["name_or_path"] == "Comfy-Org/MiniMax-H3" and model["arch"] == "minimax_h3"
    assert model["qtype"] == "convrot8" and model["qtype_te"] == "nvfp4"
    assert model["assistant_lora_path"].startswith("ostris/minimax_h3_training_adapter/")
    assert data["num_frames"] == 39 and data["do_audio"] is False and data["fps"] == 24
    assert cfg["network"]["network_kwargs"] == {"ignore_if_contains": ["adaln_proj"]}
    assert cfg["train"]["steps"] == 30 and cfg["train"]["disable_sampling"] is True
    assert cfg["train"]["timestep_type"] == "shift"


def test_each_model_goes_to_its_own_trainer(tmp_path: Path):
    t = trainers(tmp_path)
    assert t.for_base("ltx-video-2b") is t.ltx
    assert t.for_base("ltx-2.5") is t.aitk and t.for_base("minimax-h3") is t.aitk
    assert t.fetch_bytes(SimpleNamespace(id="ltx-video-2b")) == 0
    assert t.fetch_bytes(SimpleNamespace(id="ltx-2.5")) == LTX_25.hub_bytes
    assert t.engine == t.ltx.engine  # the rest is LTX-Video's


def test_it_says_what_stops_a_video_model_being_taught(
    home: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(dt.sys, "platform", "darwin")
    t = trainers(home)
    assert "NVIDIA graphics card" in (t.aitk.problem("minimax-h3") or "")
    assert NVIDIA in VIDEO_BASES["wan2.2-14b"].devices
    assert "training files of LTX-2.5" in (t.aitk.problem("ltx-2.5") or "")
    assert "Select video model" in (trainers(home, have=False).aitk.problem("ltx-2.5") or "")


async def test_a_run_writes_the_clips_and_pictures_and_returns_the_adapter(
    home: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(dt.sys, "platform", "darwin")
    t = trainers(home)
    marker = dt.hub_marker(t.aitk.pictures.hub_home(), LTX_25.hub[0])
    marker.parent.mkdir(parents=True)
    marker.write_text("done")
    pics = []
    for n in range(3):
        p = home / f"v{n}.png"
        Image.new("RGB", (64, 64), (n * 40, 90, 150)).save(p)
        pics.append(VideoMedia(p, "picture", f"wordq7x, picture {n}"))
    job = VideoJob("wordq7x", pics, 512, 512, 49, 6, False, settings={"base": "ltx-2.5"})
    steps: list[int] = []
    result = await t.aitk.train(job, home / "run", lambda step, _stage: steps.append(step))
    assert result.adapter.read_bytes() == b"adapter-bytes" and result.engine == "ai-toolkit"
    assert steps[-1] == 6
    cfg = json.loads((home / "cfg.json").read_text())
    process = cfg["config"]["process"][0]
    assert process["model"]["arch"] == "ltx2.5" and process["datasets"][0]["num_frames"] == 49
    assert cfg["hf_home"] == str(home / "models" / "huggingface")
    assert not (home / "run" / "work").exists()  # the copies of the pictures are gone
