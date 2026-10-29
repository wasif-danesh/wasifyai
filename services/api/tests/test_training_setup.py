"""Setting up the picture trainer: what is offered and what it costs, what counts as already there,
and the install through stand-ins for `uv` and the model's server (the real run is by hand)."""

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from wasifyai_api import training_setup as ts
from wasifyai_api.desktop_models import DownloadManager

FILES = {
    "model_index.json": b'{"a": 1}',
    "transformer/diffusion_pytorch_model.safetensors": b"W" * 300,
    "text_encoder/model-00002-of-00002.safetensors": b"T" * 200,
    "vae/diffusion_pytorch_model.safetensors": b"V" * 100,
}


def small_pins() -> ts.Pins:
    base = ts.load_pins()
    return replace(
        base,
        packages_bytes=1000,
        base_files=tuple(
            ts.BaseFile(p, len(d), hashlib.sha256(d).hexdigest()) for p, d in FILES.items()
        ),
    )


def write_base(folder: Path, skip: str | None = None, short: str | None = None) -> None:
    for path, data in FILES.items():
        if path == skip:
            continue
        target = folder / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data[:-1] if path == short else data)


@pytest.fixture(autouse=True)
def alone(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Nothing of the developer's own is found unless a test puts it there."""
    monkeypatch.delenv("WASIFYAI_MFLUX_DIR", raising=False)
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.setattr(ts, "apple_silicon", lambda: True)


def test_the_pins_name_every_file_with_a_size_and_a_checksum():
    p = ts.load_pins()
    assert p.base_repo == "black-forest-labs/FLUX.2-klein-base-4B"
    assert len(p.base_files) == 19
    assert 15e9 < p.base_bytes < 17e9
    assert all(len(f.sha256) == 64 for f in p.base_files)
    assert p.tool_version == "0.22.0"


def test_the_lock_is_committed_and_hashed():
    lock = Path(__file__).parents[3] / "products/wasifyai-training/trainer" / ts.LOCK_NAME
    text = lock.read_text()
    assert "mflux==0.22.0" in text and "--hash=sha256:" in text


def test_the_model_counts_only_when_every_file_is_whole(tmp_path: Path):
    pins = small_pins()
    own = ts.component_root(tmp_path) / "models" / pins.base_folder
    write_base(own, skip="vae/diffusion_pytorch_model.safetensors")
    assert ts.find_base(tmp_path, pins) is None  # a download still going
    write_base(own)
    assert ts.find_base(tmp_path, pins) == (own, "managed")
    write_base(own, short="transformer/diffusion_pytorch_model.safetensors")
    assert ts.find_base(tmp_path, pins) is None  # a file that is the wrong size is not whole


def test_a_snapshot_in_the_hugging_face_cache_is_used_where_it_is(tmp_path: Path):
    pins = small_pins()
    snap = (
        tmp_path
        / "hf"
        / "hub"
        / "models--black-forest-labs--FLUX.2-klein-base-4B"
        / "snapshots"
        / "abc"
    )
    write_base(snap)
    assert ts.find_base(tmp_path, pins) == (snap, "cache")


def test_the_tool_is_found_in_a_setting_or_the_app_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    pins = small_pins()
    assert ts.find_tool(tmp_path, pins) is None
    home = ts.component_root(tmp_path) / "venv"
    (home / "bin").mkdir(parents=True)
    (home / "bin" / ts.EXECUTABLE).write_text("")
    assert ts.find_tool(tmp_path, pins) is None  # no installed.json: not whole yet
    (ts.component_root(tmp_path) / ts.STATE_FILE).write_text(
        json.dumps({"schema": 1, "pins": pins.digest})
    )
    assert ts.find_tool(tmp_path, pins) == (home, "managed")
    (ts.component_root(tmp_path) / ts.STATE_FILE).write_text(
        json.dumps({"schema": 1, "pins": "an older pin"})
    )
    assert ts.find_tool(tmp_path, pins) is None  # a changed pin asks for a new install
    other = tmp_path / "mine"
    (other / "bin").mkdir(parents=True)
    (other / "bin" / ts.EXECUTABLE).write_text("")
    monkeypatch.setenv("WASIFYAI_MFLUX_DIR", str(other))
    assert ts.find_tool(tmp_path, pins) == (other, "env")


def setup_for(tmp_path: Path, **over) -> tuple[ts.TrainingSetup, list[list[str]], list[str]]:
    lock = tmp_path / "lock.txt"
    lock.write_text("mflux==0.22.0\n")
    served = {
        f"https://hub.test/{small_pins().base_repo}/resolve/{small_pins().base_revision}/{p}": d
        for p, d in FILES.items()
    }
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200, content=served[str(request.url)])

    def factory():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)

    commands: list[list[str]] = []
    root = ts.component_root(tmp_path)

    async def run(args: list[str], env: dict[str, str]) -> tuple[int, str]:
        commands.append(args)
        if args[1:2] == ["venv"]:
            os.makedirs(Path(args[-1], "bin"))  # noqa: ASYNC240
            return 0, ""
        if args[1:3] == ["pip", "install"]:
            if over.get("pip_fails"):
                return 1, "no network"
            (root / "venv" / "bin" / ts.EXECUTABLE).write_text("#!/bin/sh\n")  # noqa: ASYNC240
            return 0, ""
        if args[0].endswith(ts.EXECUTABLE):
            return 0, "usage: mflux-train [-h]"
        return 0, ""

    setup = ts.TrainingSetup(
        tmp_path, lock=lock, uv="uv", pins=small_pins(), base_url="https://hub.test",
        run=run, downloads=DownloadManager(factory, chunk=64),
    )  # fmt: skip
    return setup, commands, asked


def test_the_plan_says_what_it_would_fetch_and_nothing_that_is_already_there(tmp_path: Path):
    setup, _, _ = setup_for(tmp_path)
    plan = setup.plan()
    assert plan["bytes"] == 1000 + 8 + 300 + 200 + 100 == setup.missing_bytes()
    assert {p["name"] for p in plan["parts"]} == {"Trainer (mflux)", "FLUX.2 klein base 4B"}
    assert all(p["source"] for p in plan["parts"])
    write_base(ts.component_root(tmp_path) / "models" / setup.pins.base_folder)
    assert setup.missing_bytes() == 1000  # the model is there: only the trainer
    assert [p["have"] for p in setup.plan()["parts"]] == [False, True]


def test_it_says_in_words_why_it_cannot_be_set_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    setup, _, _ = setup_for(tmp_path)
    assert setup.problem() is None
    monkeypatch.setattr(ts, "apple_silicon", lambda: False)
    assert "Apple silicon" in (setup.problem() or "") and "NVIDIA" in (setup.problem() or "")
    with pytest.raises(ts.InstallError, match="Apple silicon"):
        setup.start(setup.missing_bytes())
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
async def test_the_install_makes_the_environment_gets_the_model_and_checks_it(tmp_path: Path):
    setup, commands, asked = setup_for(tmp_path)
    setup.start(setup.missing_bytes())
    await setup.wait()
    assert setup.progress.state == "ready", setup.progress.message
    assert [c[1] for c in commands[:2]] == ["venv", "pip"]
    assert "--require-hashes" in commands[1] and str(setup.lock) in commands[1]
    assert commands[-1][0].endswith(ts.EXECUTABLE) and commands[-1][1] == "--help"
    assert len(asked) == 4 and all(u.startswith("https://hub.test/") for u in asked)
    state = setup.state()
    assert state["installed"] and state["tool"] == "managed" and state["base"] == "managed"
    assert setup.missing_bytes() == 0
    with pytest.raises(ts.InstallError, match="already set up"):
        setup.start(0)


@pytest.mark.asyncio
async def test_a_failed_package_install_leaves_no_environment_and_says_what_to_do(tmp_path: Path):
    setup, _, _ = setup_for(tmp_path, pip_fails=True)
    setup.start(setup.missing_bytes())
    await setup.wait()
    assert setup.progress.state == "failed" and "online" in setup.progress.message
    assert not (ts.component_root(tmp_path) / "venv").exists()
    assert not (ts.component_root(tmp_path) / ts.STATE_FILE).exists()


@pytest.mark.asyncio
async def test_a_file_that_does_not_match_its_checksum_is_refused(tmp_path: Path):
    setup, _, _ = setup_for(tmp_path)
    bad = replace(
        setup.pins,
        base_files=tuple(
            replace(f, sha256="0" * 64) if f.path.startswith("vae") else f
            for f in setup.pins.base_files
        ),
    )
    setup.pins = bad
    setup.start(setup.missing_bytes())
    await setup.wait()
    assert setup.progress.state == "failed"
    assert not (ts.component_root(tmp_path) / ts.STATE_FILE).exists()


@pytest.mark.asyncio
async def test_removing_it_gives_the_bytes_back(tmp_path: Path):
    setup, _, _ = setup_for(tmp_path)
    setup.start(setup.missing_bytes())
    await setup.wait()
    freed = setup.remove()
    assert freed >= 600 and not ts.component_root(tmp_path).exists()
    assert not setup.state()["installed"]
