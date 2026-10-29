"""Setting up the decision trainer: what is offered and what it costs, what counts as already there,
and the install through stand-ins for `uv` and the model's server (the real run is by hand)."""

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from wasifyai_api import decision_setup as ds
from wasifyai_api import training_setup as ts
from wasifyai_api.desktop_models import DownloadManager

FILES = {
    "rl_agent_config.json": b'{"encoder": "x"}',
    "model.safetensors": b"W" * 300,
    "tokenizer/tokenizer.json": b"T" * 120,
}


def small_pins() -> ts.Pins:
    base = ds.load_decision_pins()
    return replace(
        base,
        packages_bytes=1000,
        base_files=tuple(
            ts.BaseFile(p, len(d), hashlib.sha256(d).hexdigest()) for p, d in FILES.items()
        ),
    )


def write_model(folder: Path, skip: str | None = None) -> None:
    for path, data in FILES.items():
        if path != skip:
            (folder / path).parent.mkdir(parents=True, exist_ok=True)
            (folder / path).write_bytes(data)


@pytest.fixture(autouse=True)
def alone(monkeypatch: pytest.MonkeyPatch):
    """Nothing of the developer's own is found unless a test puts it there."""
    monkeypatch.delenv("WASIFYAI_LAYA_DIR", raising=False)
    monkeypatch.delenv("WASIFYAI_DECISION_BASE_DIR", raising=False)
    monkeypatch.setattr(ts, "apple_silicon", lambda: True)


def test_the_pins_name_every_file_with_a_size_and_a_checksum():
    p = ds.load_decision_pins()
    assert p.base_repo == "convaiinnovations/laya"
    assert len(p.base_revision) == 40 and p.tool_version == "0.4.15"
    assert {f.path for f in p.base_files} == {
        "rl_agent_config.json", "encoder/config.json", "model.safetensors",
        "tokenizer/tokenizer.json", "tokenizer/tokenizer_config.json",
    }  # fmt: skip
    assert 840e6 < p.base_bytes < 850e6 and all(len(f.sha256) == 64 for f in p.base_files)
    cat = ds.catalogue()
    assert [b.id for b in cat] == ["laya-english", "laya-multilingual"]
    assert cat[0].main and not cat[1].main and cat[1].subfolder == "multilingual"
    assert 670e6 < cat[1].bytes < 690e6 and cat[1].revision == cat[0].revision
    # the descriptors the screen offers are the models that can be fetched
    from wasifyai_training import bases

    assert [d.id for d in bases.descriptors("decision")] == [b.id for b in cat]
    assert cat[0].folder == cat[0].id


def test_the_lock_is_committed_and_hashed():
    lock = Path(__file__).parents[3] / "products/wasifyai-training/trainer" / ds.LOCK_NAME
    text = lock.read_text()
    assert "laya==0.4.15" in text and "torch==" in text and "--hash=sha256:" in text
    assert "mlx" not in text  # the writing trainer's packages are another environment


def test_the_trainer_is_found_in_a_setting_or_the_app_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    pins = small_pins()
    assert ds.find_python(tmp_path, pins) is None
    home = ds.component_root(tmp_path) / "venv"
    (home / "bin").mkdir(parents=True)
    (home / "bin" / "python").write_text("")
    assert ds.find_python(tmp_path, pins) is None  # no installed.json: not whole yet
    (ds.component_root(tmp_path) / ts.STATE_FILE).write_text(
        json.dumps({"schema": 1, "pins": pins.digest})
    )
    assert ds.find_python(tmp_path, pins) == home / "bin" / "python"
    (ds.component_root(tmp_path) / ts.STATE_FILE).write_text(
        json.dumps({"schema": 1, "pins": "an older pin"})
    )
    assert ds.find_python(tmp_path, pins) is None  # a changed pin asks for a new install
    other = tmp_path / "mine"
    (other / "bin").mkdir(parents=True)
    (other / "bin" / "python").write_text("")
    monkeypatch.setenv("WASIFYAI_LAYA_DIR", str(other))
    assert ds.find_python(tmp_path, pins) == other / "bin" / "python"


def test_the_model_counts_only_when_every_file_is_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    spec = replace(
        ds.catalogue()[0],
        files=tuple(
            ts.BaseFile(p, len(d), hashlib.sha256(d).hexdigest()) for p, d in FILES.items()
        ),
    )
    own = ds.component_root(tmp_path) / "models" / spec.folder
    write_model(own, skip="tokenizer/tokenizer.json")
    assert ds.find_model(tmp_path, spec.id, spec) is None  # a download still going
    write_model(own)
    assert ds.find_model(tmp_path, spec.id, spec) == own
    assert ds.find_model(tmp_path, "another-model") is None
    mine = tmp_path / "models"  # a developer's folder of models is used where it is
    (mine / "laya-test").mkdir(parents=True)
    (mine / "laya-test" / "rl_agent_config.json").write_text("{}")
    monkeypatch.setenv("WASIFYAI_DECISION_BASE_DIR", str(mine))
    assert ds.find_model(tmp_path, "laya-test") == mine / "laya-test"


def setup_for(tmp_path: Path, **over) -> tuple[ds.DecisionSetup, list[list[str]], list[str]]:
    lock = tmp_path / "lock.txt"
    lock.write_text("laya==0.4.15\n")
    p = small_pins()
    served = {
        f"https://hub.test/{p.base_repo}/resolve/{p.base_revision}/{name}": data
        for name, data in FILES.items()
    }
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200, content=served[str(request.url)])

    def factory():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)

    commands: list[list[str]] = []
    root = ds.component_root(tmp_path)

    async def run(args: list[str], env: dict[str, str]) -> tuple[int, str]:
        commands.append(args)
        if args[1:2] == ["venv"]:
            os.makedirs(Path(args[-1], "bin"))  # noqa: ASYNC240
            return 0, ""
        if args[1:3] == ["pip", "install"]:
            if over.get("pip_fails"):
                return 1, "no network"
            (root / "venv" / "bin" / "python").write_text("#!/bin/sh\n")  # noqa: ASYNC240
            return 0, ""
        if "-c" in args:
            return (1, "ImportError") if over.get("check_fails") else (0, "laya 0.4.15")
        return 0, ""

    setup = ds.DecisionSetup(
        tmp_path, lock=lock, uv="uv", pins=p, base_url="https://hub.test", run=run,
        downloads=DownloadManager(factory, chunk=64),
    )  # fmt: skip
    return setup, commands, asked


def test_the_plan_says_what_it_would_fetch_and_nothing_that_is_already_there(tmp_path: Path):
    setup, _, _ = setup_for(tmp_path)
    plan = setup.plan()
    assert plan["bytes"] == 1000 + 16 + 300 + 120 == setup.missing_bytes()
    assert {p["name"] for p in plan["parts"]} == {"Trainer (Laya and PyTorch)", "Laya"}
    assert all(p["source"] for p in plan["parts"])
    write_model(ds.component_root(tmp_path) / "models" / setup.pins.base_folder)
    assert setup.missing_bytes() == 1000
    assert [p["have"] for p in setup.plan()["parts"]] == [False, True]


def test_it_says_in_words_why_it_cannot_be_set_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    setup, _, _ = setup_for(tmp_path)
    assert setup.problem() is None
    monkeypatch.setattr(ts, "apple_silicon", lambda: False)
    assert "decide" in (setup.problem() or "") and "NVIDIA" in (setup.problem() or "")
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
    assert "import laya, torch" in commands[-1][-1] and commands[-1][1] == "-I"
    assert len(asked) == 3 and all(u.startswith("https://hub.test/") for u in asked)
    state = setup.state()
    assert state["installed"] and state["tool"] == "managed" and state["base"] == "managed"
    assert setup.missing_bytes() == 0
    assert ds.find_python(tmp_path, setup.pins) == ds.component_root(tmp_path) / "venv/bin/python"


@pytest.mark.asyncio
async def test_a_failed_package_install_leaves_no_environment_and_says_what_to_do(tmp_path: Path):
    setup, _, _ = setup_for(tmp_path, pip_fails=True)
    setup.start(setup.missing_bytes())
    await setup.wait()
    assert setup.progress.state == "failed" and "online" in setup.progress.message
    assert not (ds.component_root(tmp_path) / "venv").exists()
    assert not (ds.component_root(tmp_path) / ts.STATE_FILE).exists()


@pytest.mark.asyncio
async def test_a_trainer_that_does_not_start_is_not_recorded_as_installed(tmp_path: Path):
    setup, _, _ = setup_for(tmp_path, check_fails=True)
    setup.start(setup.missing_bytes())
    await setup.wait()
    assert setup.progress.state == "failed" and "did not start" in setup.progress.message
    assert not (ds.component_root(tmp_path) / ts.STATE_FILE).exists()


@pytest.mark.asyncio
async def test_a_file_that_does_not_match_its_checksum_is_refused_in_words_about_this_model(
    tmp_path: Path,
):
    setup, _, _ = setup_for(tmp_path)
    setup.pins = replace(
        setup.pins,
        base_files=tuple(
            replace(f, sha256="0" * 64) if f.path.endswith("tokenizer.json") else f
            for f in setup.pins.base_files
        ),
    )
    setup.start(setup.missing_bytes())
    await setup.wait()
    assert setup.progress.state == "failed"
    assert "picture" not in setup.progress.message.lower()
    assert not (ds.component_root(tmp_path) / ts.STATE_FILE).exists()


@pytest.mark.asyncio
async def test_removing_it_gives_the_bytes_back(tmp_path: Path):
    setup, _, _ = setup_for(tmp_path)
    setup.start(setup.missing_bytes())
    await setup.wait()
    freed = setup.remove()
    assert freed >= 400 and not ds.component_root(tmp_path).exists()
    assert not setup.state()["installed"]


def test_the_other_trainers_files_are_not_touched_by_this_one(tmp_path: Path):
    assert ds.component_root(tmp_path) != ts.component_root(tmp_path)
    assert ds.component_root(tmp_path).name == "decision-trainer"


# ---- the model for many languages: asked for when it is chosen -----------------------------------

MULTI = {"rl_agent_config.json": b"{}", "model.safetensors": b"M" * 400}


def multi_setup(tmp_path: Path, tamper: bool = False):
    setup, _, asked = setup_for(tmp_path)
    spec = ds.BaseSpec(
        "laya-multilingual", "Laya (many languages)", "acme/laya", "r" * 40, "laya-multilingual",
        tuple(ts.BaseFile(p, len(d), hashlib.sha256(d).hexdigest()) for p, d in MULTI.items()),
        subfolder="multilingual",
    )  # fmt: skip
    served = {
        f"https://hub.test/{spec.repo}/resolve/{spec.revision}/multilingual/{p}": (
            b"X" * len(d) if tamper else d
        )
        for p, d in MULTI.items()
    }

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200, content=served[str(request.url)])

    setup.downloads = DownloadManager(
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True),
        chunk=64,
    )
    setup.catalogue = lambda: [ds.catalogue(setup.pins)[0], spec]  # type: ignore[method-assign]
    return setup, spec, asked


def test_every_model_says_what_is_on_this_computer_and_what_the_rest_would_cost(tmp_path: Path):
    setup, spec, _ = multi_setup(tmp_path)
    rows = {r["id"]: r for r in setup.bases_state()}
    assert rows[spec.id]["model"]["bytes"] == 402 and rows[spec.id]["model"]["have"] is False
    assert rows[spec.id]["model"]["needs_free_bytes"] == 402 + 1024**3 and not rows[spec.id]["main"]
    assert rows["laya-english"]["main"] is True


@pytest.mark.asyncio
async def test_a_model_is_fetched_from_its_folder_of_the_repository_once_the_size_is_repeated(
    tmp_path: Path,
):
    setup, spec, asked = multi_setup(tmp_path)
    with pytest.raises(ts.InstallError, match="out of date"):
        setup.fetch_start(spec.id, 1)
    with pytest.raises(ts.InstallError, match="set up with the trainer"):
        setup.fetch_start("laya-english", 1)
    assert asked == []
    setup.fetch_start(spec.id, spec.bytes)
    with pytest.raises(ts.InstallError, match="already being downloaded"):
        setup.fetch_start(spec.id, spec.bytes)
    await setup.fetch_wait()
    assert setup.parts[spec.id].state == "ready"
    assert len(asked) == 2 and all("/multilingual/" in u for u in asked)
    assert ds.find_model(tmp_path, spec.id, spec) is not None
    with pytest.raises(ts.InstallError, match="already on this computer"):
        setup.fetch_start(spec.id, spec.bytes)


@pytest.mark.asyncio
async def test_a_model_that_does_not_match_is_refused_and_can_be_stopped(tmp_path: Path):
    setup, spec, _ = multi_setup(tmp_path, tamper=True)
    setup.fetch_start(spec.id, spec.bytes)
    await setup.fetch_wait()
    assert setup.parts[spec.id].state == "failed" and ds.find_model(tmp_path, spec.id, spec) is None
    assert setup.fetch_cancel(spec.id) is False
