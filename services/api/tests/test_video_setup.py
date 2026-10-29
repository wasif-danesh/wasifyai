# ruff: noqa: E501  (prose in the docstrings and made-up files are easier to read on one line)
"""Setting up the video trainer: what is offered and what it costs, what counts as already there, the
video model it needs (found, never fetched here) and the install through stand-ins for `uv` and the
model's server (the real run is by hand)."""

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from wasifyai_api import training_setup as ts
from wasifyai_api import video_setup as vs
from wasifyai_api.desktop_models import DownloadManager

FILES = {
    "tokenizer/spiece.model": b"S" * 100,
    "tokenizer/tokenizer_config.json": b"{}",
    "text_encoder/config.json": b'{"d_model": 4096}',
}


def small_pins() -> ts.Pins:
    base = vs.load_video_pins()
    return replace(
        base, packages_bytes=1000,
        base_files=tuple(ts.BaseFile(p, len(d), hashlib.sha256(d).hexdigest()) for p, d in FILES.items()),
    )  # fmt: skip


@pytest.fixture(autouse=True)
def alone(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("WASIFYAI_VIDEO_TRAINER_DIR", raising=False)
    monkeypatch.delenv("WASIFYAI_VIDEO_SMALL_DIR", raising=False)
    monkeypatch.setattr(ts, "apple_silicon", lambda: True)


def test_the_pins_name_every_small_file_with_a_size_and_a_checksum():
    p = vs.load_video_pins()
    assert p.base_repo == "Lightricks/LTX-Video" and p.tool_version == "0.42.0"
    assert len(p.base_revision) == 40 and all(len(f.sha256) == 64 for f in p.base_files)
    assert {f.path for f in p.base_files} == {
        "tokenizer/added_tokens.json", "tokenizer/special_tokens_map.json", "tokenizer/spiece.model",
        "tokenizer/tokenizer_config.json", "text_encoder/config.json",
    }  # fmt: skip
    assert p.base_bytes < 1_000_000  # the big model is not fetched here
    # the revision is the one the video product pins its model at
    video = (Path(__file__).parents[3] / "products/wasifyai-video/models.yaml").read_text()
    assert p.base_revision in video


def test_the_lock_is_committed_and_hashed():
    lock = Path(__file__).parents[3] / "products/wasifyai-training/trainer" / vs.LOCK_NAME
    text = lock.read_text()
    for name in (
        "torch==",
        "diffusers==",
        "peft==",
        "transformers==",
        "sentencepiece==",
        "--hash=sha256:",
    ):
        assert name in text, name
    assert (
        "mlx" not in text and "laya" not in text
    )  # the other trainers' packages are other environments


def test_the_trainer_is_found_in_a_setting_or_the_app_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    pins = small_pins()
    assert vs.find_python(tmp_path, pins) is None
    home = vs.component_root(tmp_path) / "venv"
    (home / "bin").mkdir(parents=True)
    (home / "bin" / "python").write_text("")
    assert vs.find_python(tmp_path, pins) is None  # no installed.json: not whole yet
    (vs.component_root(tmp_path) / ts.STATE_FILE).write_text(
        json.dumps({"schema": 1, "pins": pins.digest})
    )
    assert vs.find_python(tmp_path, pins) == home / "bin" / "python"
    (vs.component_root(tmp_path) / ts.STATE_FILE).write_text(
        json.dumps({"schema": 1, "pins": "older"})
    )
    assert vs.find_python(tmp_path, pins) is None
    other = tmp_path / "mine"
    (other / "bin").mkdir(parents=True)
    (other / "bin" / "python").write_text("")
    monkeypatch.setenv("WASIFYAI_VIDEO_TRAINER_DIR", str(other))
    assert vs.find_python(tmp_path, pins) == other / "bin" / "python"


def setup_for(tmp_path: Path, **over) -> tuple[vs.VideoSetup, list[list[str]], list[str]]:
    lock = tmp_path / "lock.txt"
    lock.write_text("diffusers==0.42.0\n")
    p = small_pins()
    served = {
        f"https://hub.test/{p.base_repo}/resolve/{p.base_revision}/{n}": d for n, d in FILES.items()
    }
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200, content=served[str(request.url)])

    commands: list[list[str]] = []
    root = vs.component_root(tmp_path)

    async def run(args: list[str], env: dict[str, str]) -> tuple[int, str]:
        commands.append(args)
        if args[1:2] == ["venv"]:
            os.makedirs(Path(args[-1], "bin"))  # noqa: ASYNC240
            return 0, ""
        if args[1:3] == ["pip", "install"]:
            (root / "venv" / "bin" / "python").write_text("#!/bin/sh\n")  # noqa: ASYNC240
            return (1, "no network") if over.get("pip_fails") else (0, "")
        if "-c" in args:
            return (1, "ImportError") if over.get("check_fails") else (0, "ok 0.42.0")
        return 0, ""

    setup = vs.VideoSetup(
        tmp_path, lock=lock, uv="uv", pins=p, base_url="https://hub.test", run=run,
        downloads=DownloadManager(lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True), chunk=64),
    )  # fmt: skip
    return setup, commands, asked


def test_the_plan_says_what_it_fetches_and_what_it_needs_but_does_not_fetch(tmp_path: Path):
    setup, _, _ = setup_for(tmp_path)
    setup.video_model_bytes = 16_127_000_000
    plan = setup.plan()
    assert plan["bytes"] == 1000 + 100 + 2 + 17 == setup.missing_bytes()
    assert {p["name"] for p in plan["parts"]} == {
        "Trainer (PyTorch and diffusers)",
        "The video model's tokenizer and settings",
    }
    (need,) = plan["needs"]
    assert (
        need["have"] is False
        and need["bytes"] == 16_127_000_000
        and "Select video model" in need["how"]
    )
    # the big model counts as there once the models screen has it
    setup.video_model = lambda: (tmp_path / "a", tmp_path / "b")
    assert setup.plan()["needs"][0]["have"] is True and setup.plan()["bytes"] == plan["bytes"]


def test_it_says_in_words_why_it_cannot_be_set_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    setup, _, _ = setup_for(tmp_path)
    assert setup.problem() is None
    monkeypatch.setattr(ts, "apple_silicon", lambda: False)
    assert "video model" in (setup.problem() or "") and "NVIDIA" in (setup.problem() or "")
    monkeypatch.setattr(ts, "apple_silicon", lambda: True)
    setup.lock = None
    assert "not part of this build" in (setup.problem() or "")


@pytest.mark.asyncio
async def test_nothing_starts_unless_the_size_shown_is_repeated(tmp_path: Path):
    setup, commands, asked = setup_for(tmp_path)
    with pytest.raises(ts.InstallError, match="out of date"):
        setup.start(setup.missing_bytes() - 1)
    assert commands == [] and asked == []


@pytest.mark.asyncio
async def test_the_install_makes_the_environment_gets_the_small_files_and_checks_it(tmp_path: Path):
    setup, commands, asked = setup_for(tmp_path)
    setup.start(setup.missing_bytes())
    await setup.wait()
    assert setup.progress.state == "ready", setup.progress.message
    assert [c[1] for c in commands[:2]] == ["venv", "pip"] and "--require-hashes" in commands[1]
    assert "import torch, diffusers, peft" in commands[-1][-1] and commands[-1][1] == "-I"
    assert len(asked) == 3 and all(
        u.startswith("https://hub.test/Lightricks/LTX-Video/resolve/") for u in asked
    )
    state = setup.state()
    assert state["installed"] and state["tool"] == "managed" and state["base"] == "managed"
    assert (
        vs.find_python(tmp_path, setup.pins) is not None
        and vs.find_small(tmp_path, setup.pins) is not None
    )
    small = vs.find_small(tmp_path, setup.pins)
    assert small is not None and (small / "tokenizer" / "spiece.model").is_file()


@pytest.mark.asyncio
async def test_a_failed_install_leaves_no_environment_and_says_what_to_do(tmp_path: Path):
    setup, _, _ = setup_for(tmp_path, pip_fails=True)
    setup.start(setup.missing_bytes())
    await setup.wait()
    assert setup.progress.state == "failed" and "online" in setup.progress.message
    assert not (vs.component_root(tmp_path) / "venv").exists()
    (tmp_path / "b").mkdir()
    setup2, _, _ = setup_for(tmp_path / "b", check_fails=True)
    setup2.start(setup2.missing_bytes())
    await setup2.wait()
    assert setup2.progress.state == "failed" and "did not start" in setup2.progress.message


@pytest.mark.asyncio
async def test_removing_it_gives_the_bytes_back_and_the_other_trainers_are_not_touched(
    tmp_path: Path,
):
    setup, _, _ = setup_for(tmp_path)
    setup.start(setup.missing_bytes())
    await setup.wait()
    assert setup.remove() >= 100 and not vs.component_root(tmp_path).exists()
    assert vs.component_root(tmp_path).name == "video-trainer" and vs.component_root(
        tmp_path
    ) != ts.component_root(tmp_path)
