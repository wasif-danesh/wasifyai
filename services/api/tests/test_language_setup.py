"""Setting up the writing trainer: what is offered and what it costs, what counts as already there,
and the install through stand-ins for `uv` and the model's server (the real run is by hand)."""

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from wasifyai_api import language_setup as ls
from wasifyai_api import training_setup as ts
from wasifyai_api.desktop_models import DownloadManager

FILES = {
    "config.json": b'{"num_hidden_layers": 2}',
    "model.safetensors": b"W" * 300,
    "tokenizer.json": b"T" * 120,
}


def small_pins() -> ts.Pins:
    base = ls.load_language_pins()
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
    monkeypatch.delenv("WASIFYAI_MLXLM_DIR", raising=False)
    monkeypatch.delenv("WASIFYAI_LANGUAGE_BASE_DIR", raising=False)
    monkeypatch.setattr(ts, "apple_silicon", lambda: True)


def test_the_pins_name_every_file_with_a_size_and_a_checksum():
    p = ls.load_language_pins()
    assert p.base_repo == "mlx-community/Qwen3-0.6B-4bit" and p.base_licence == "Apache-2.0"
    assert len(p.base_revision) == 40 and p.tool_version == "0.31.3"
    names = {f.path for f in p.base_files}
    assert {"config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json"} <= names
    assert 340e6 < p.base_bytes < 360e6
    assert all(len(f.sha256) == 64 for f in p.base_files)
    # the base the descriptor offers is the base these pins fetch
    from wasifyai_training import bases

    assert bases.descriptors("language")[0].id == p.base_id == p.base_folder


def test_the_lock_is_committed_and_hashed():
    lock = Path(__file__).parents[3] / "products/wasifyai-training/trainer" / ls.LOCK_NAME
    text = lock.read_text()
    assert "mlx-lm==0.31.3" in text and "mlx==0.32.3" in text and "--hash=sha256:" in text
    assert "torch" not in text  # no 2 GB of torch for a trainer that runs on MLX


def test_the_trainer_is_found_in_a_setting_or_the_app_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    pins = small_pins()
    assert ls.find_python(tmp_path, pins) is None
    home = ls.component_root(tmp_path) / "venv"
    (home / "bin").mkdir(parents=True)
    (home / "bin" / "python").write_text("")
    assert ls.find_python(tmp_path, pins) is None  # no installed.json: not whole yet
    (ls.component_root(tmp_path) / ts.STATE_FILE).write_text(
        json.dumps({"schema": 1, "pins": pins.digest})
    )
    assert ls.find_python(tmp_path, pins) == home / "bin" / "python"
    (ls.component_root(tmp_path) / ts.STATE_FILE).write_text(
        json.dumps({"schema": 1, "pins": "an older pin"})
    )
    assert ls.find_python(tmp_path, pins) is None  # a changed pin asks for a new install
    other = tmp_path / "mine"
    (other / "bin").mkdir(parents=True)
    (other / "bin" / "python").write_text("")
    monkeypatch.setenv("WASIFYAI_MLXLM_DIR", str(other))
    assert ls.find_python(tmp_path, pins) == other / "bin" / "python"


def test_the_model_counts_only_when_every_file_is_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    pins = small_pins()
    own = ls.component_root(tmp_path) / "models" / pins.base_id
    write_model(own, skip="tokenizer.json")
    assert ls.find_model(tmp_path, pins.base_id, pins) is None  # a download still going
    write_model(own)
    assert ls.find_model(tmp_path, pins.base_id, pins) == own
    assert ls.find_model(tmp_path, "another-model", pins) is None
    # a developer's folder of models is used where it is
    mine = tmp_path / "models"
    (mine / "qwen3-test").mkdir(parents=True)
    (mine / "qwen3-test" / "config.json").write_text("{}")
    monkeypatch.setenv("WASIFYAI_LANGUAGE_BASE_DIR", str(mine))
    assert ls.find_model(tmp_path, "qwen3-test", pins) == mine / "qwen3-test"


def setup_for(tmp_path: Path, **over) -> tuple[ls.LanguageSetup, list[list[str]], list[str]]:
    lock = tmp_path / "lock.txt"
    lock.write_text("mlx-lm==0.31.3\n")
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
    root = ls.component_root(tmp_path)

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
            return (1, "ImportError") if over.get("check_fails") else (0, "mlx_lm 0.31.3")
        return 0, ""

    setup = ls.LanguageSetup(
        tmp_path, lock=lock, uv="uv", pins=p, base_url="https://hub.test", run=run,
        downloads=DownloadManager(factory, chunk=64),
    )  # fmt: skip
    return setup, commands, asked


def test_the_plan_says_what_it_would_fetch_and_nothing_that_is_already_there(tmp_path: Path):
    setup, _, _ = setup_for(tmp_path)
    plan = setup.plan()
    assert plan["bytes"] == 1000 + 24 + 300 + 120 == setup.missing_bytes()
    assert {p["name"] for p in plan["parts"]} == {"Trainer (mlx-lm)", "Qwen3 0.6B (4-bit)"}
    assert all(p["licence"] and p["source"] for p in plan["parts"])
    write_model(ls.component_root(tmp_path) / "models" / setup.pins.base_id)
    assert setup.missing_bytes() == 1000  # the model is there: only the trainer
    assert [p["have"] for p in setup.plan()["parts"]] == [False, True]


def test_it_says_in_words_why_it_cannot_be_set_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    setup, _, _ = setup_for(tmp_path)
    assert setup.problem() is None
    monkeypatch.setattr(ts, "apple_silicon", lambda: False)
    assert "writing model" in (setup.problem() or "") and "NVIDIA" in (setup.problem() or "")
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
    assert "mlx_lm" in commands[-1][-1] and commands[-1][1] == "-I"
    assert len(asked) == 3 and all(u.startswith("https://hub.test/") for u in asked)
    state = setup.state()
    assert state["installed"] and state["tool"] == "managed" and state["base"] == "managed"
    assert setup.missing_bytes() == 0
    # the engine finds what was installed, from the same folder
    assert ls.find_python(tmp_path, setup.pins) == ls.component_root(tmp_path) / "venv/bin/python"
    assert ls.find_model(tmp_path, setup.pins.base_id, setup.pins) is not None


@pytest.mark.asyncio
async def test_a_failed_package_install_leaves_no_environment_and_says_what_to_do(tmp_path: Path):
    setup, _, _ = setup_for(tmp_path, pip_fails=True)
    setup.start(setup.missing_bytes())
    await setup.wait()
    assert setup.progress.state == "failed" and "online" in setup.progress.message
    assert not (ls.component_root(tmp_path) / "venv").exists()
    assert not (ls.component_root(tmp_path) / ts.STATE_FILE).exists()


@pytest.mark.asyncio
async def test_a_trainer_that_does_not_start_is_not_recorded_as_installed(tmp_path: Path):
    setup, _, _ = setup_for(tmp_path, check_fails=True)
    setup.start(setup.missing_bytes())
    await setup.wait()
    assert setup.progress.state == "failed" and "did not start" in setup.progress.message
    assert not (ls.component_root(tmp_path) / ts.STATE_FILE).exists()


@pytest.mark.asyncio
async def test_a_file_that_does_not_match_its_checksum_is_refused_in_words_about_this_model(
    tmp_path: Path,
):
    setup, _, _ = setup_for(tmp_path)
    setup.pins = replace(
        setup.pins,
        base_files=tuple(
            replace(f, sha256="0" * 64) if f.path == "tokenizer.json" else f
            for f in setup.pins.base_files
        ),
    )
    setup.start(setup.missing_bytes())
    await setup.wait()
    assert setup.progress.state == "failed"
    assert "picture" not in setup.progress.message.lower()
    assert not (ls.component_root(tmp_path) / ts.STATE_FILE).exists()


@pytest.mark.asyncio
async def test_removing_it_gives_the_bytes_back(tmp_path: Path):
    setup, _, _ = setup_for(tmp_path)
    setup.start(setup.missing_bytes())
    await setup.wait()
    freed = setup.remove()
    assert freed >= 400 and not ls.component_root(tmp_path).exists()
    assert not setup.state()["installed"]


def test_the_picture_trainers_files_are_not_touched_by_this_one(tmp_path: Path):
    assert ls.component_root(tmp_path) != ts.component_root(tmp_path)
    assert ls.component_root(tmp_path).name == "language-trainer"


# ---- the other models and the chat copies: asked for one at a time -------------------------------

CHAT = b"G" * 500
OTHER = {"config.json": b'{"num_hidden_layers": 2}', "model.safetensors": b"M" * 400}
OTHER_CHAT = b"C" * 700


def other_spec() -> ls.BaseSpec:
    main = ls.main_spec(small_pins(), None)
    return ls.BaseSpec(
        id="qwen3-test-4bit", title="Qwen3 test", repo="acme/qwen3-test", revision="r" * 40,
        licence="Apache-2.0", source="huggingface.co", folder="qwen3-test-4bit",
        files=tuple(
            ts.BaseFile(p, len(d), hashlib.sha256(d).hexdigest()) for p, d in OTHER.items()
        ),
        chat=replace(
            main.chat, id="qwen3-test-q8", title="Qwen3 test for chat", repo="acme/qwen3-test-gguf",
            revision="s" * 40, file="Qwen3-test-Q8_0.gguf", size=len(OTHER_CHAT),
            sha256=hashlib.sha256(OTHER_CHAT).hexdigest(), folder="qwen3-test-q8",
        ),
    )  # fmt: skip


def bases_setup(tmp_path: Path, tamper: str | None = None):
    setup, _, asked = setup_for(tmp_path)
    main_chat = replace(setup.chat_pins, size=len(CHAT), sha256=hashlib.sha256(CHAT).hexdigest())
    setup.chat_pins = main_chat
    other = other_spec()
    setup.bases = [ls.main_spec(setup.pins, main_chat), other]
    served = {
        f"https://hub.test/{main_chat.repo}/resolve/{main_chat.revision}/{main_chat.file}": CHAT,
        f"https://hub.test/{other.chat.repo}/resolve/{other.chat.revision}/{other.chat.file}": (
            b"X" * len(OTHER_CHAT) if tamper == "chat" else OTHER_CHAT
        ),
    }
    for path, data in OTHER.items():
        served[f"https://hub.test/{other.repo}/resolve/{other.revision}/{path}"] = data

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200, content=served[str(request.url)])

    setup.downloads = DownloadManager(
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True),
        chunk=64,
    )
    return setup, other, asked


def test_the_pins_of_the_larger_models_name_every_file_and_a_chat_copy_of_each():
    found = ls.load_more_bases()
    assert [b.id for b in found] == ["qwen3-1.7b-4bit", "qwen3-4b-4bit"]
    for b in found:
        assert b.licence == "Apache-2.0" and b.repo.startswith("mlx-community/Qwen3-")
        assert len(b.revision) == 40 and all(len(f.sha256) == 64 for f in b.files)
        assert {"config.json", "model.safetensors", "tokenizer.json"} <= {f.path for f in b.files}
        assert len(b.chat.sha256) == 64 and b.chat.file.endswith(".gguf")
        assert b.chat.repo.startswith("Qwen/Qwen3-") and b.chat.size > 1e9
    assert 0.9e9 < found[0].train_bytes < 1.1e9 and 2.2e9 < found[1].train_bytes < 2.4e9
    cat = ls.catalogue()
    assert cat[0].main and cat[0].id == "qwen3-0.6b-4bit" and not any(b.main for b in cat[1:])
    assert ls.spec_of("qwen3-4b-4bit") is not None and ls.spec_of("nope") is None
    # the descriptors the screen offers are the models that can be fetched
    from wasifyai_training import bases

    assert [d.id for d in bases.descriptors("language")] == [b.id for b in cat]


def test_every_base_says_what_is_on_this_computer_and_what_the_rest_would_cost(tmp_path: Path):
    setup, other, _ = bases_setup(tmp_path)
    rows = {r["id"]: r for r in setup.bases_state()}
    assert rows[other.id]["model"] == {
        "have": False, "bytes": 24 + 400, "title": "Qwen3 test",
        "needs_free_bytes": 24 + 400 + 1024**3,
        "progress": {"state": "idle", "message": "", "done_bytes": 0, "total_bytes": 0},
    }  # fmt: skip
    assert rows[other.id]["chat"]["bytes"] == len(OTHER_CHAT) and rows[other.id]["main"] is False
    assert (
        rows["qwen3-0.6b-4bit"]["main"] is True
        and rows["qwen3-0.6b-4bit"]["model"]["have"] is False
    )
    write_model(ls.component_root(tmp_path) / "models" / setup.pins.base_id)
    assert setup.bases_state()[0]["model"]["have"] is True and setup.has_model(setup.catalogue()[0])


@pytest.mark.asyncio
async def test_a_model_is_fetched_checked_and_found_once_the_size_is_repeated(tmp_path: Path):
    setup, other, asked = bases_setup(tmp_path)
    with pytest.raises(ts.InstallError, match="out of date"):
        setup.fetch_start(other.id, "model", 1)
    assert asked == []
    setup.fetch_start(other.id, "model", other.train_bytes)
    with pytest.raises(ts.InstallError, match="already being downloaded"):
        setup.fetch_start(other.id, "model", other.train_bytes)
    await setup.fetch_wait()
    assert setup.parts[(other.id, "model")].state == "ready"
    assert len(asked) == 2 and ls.find_model(tmp_path, other.id, setup.pins, other) is not None
    with pytest.raises(ts.InstallError, match="already on this computer"):
        setup.fetch_start(other.id, "model", other.train_bytes)
    assert setup.state()["installed"] is False  # the trainer itself is another matter


@pytest.mark.asyncio
async def test_the_chat_copy_of_a_base_counts_only_when_whole_and_is_separate_per_base(
    tmp_path: Path,
):
    setup, other, asked = bases_setup(tmp_path)
    assert setup.chat_copy(other.id) is None and setup.chat_copy() is None
    setup.fetch_start(other.id, "chat", len(OTHER_CHAT))
    await setup.fetch_wait()
    assert setup.parts[(other.id, "chat")].state == "ready"
    assert setup.chat_copy(other.id) is not None and setup.chat_copy() is None
    assert setup.bases_state()[1]["chat"]["have"] is True
    setup.fetch_start("qwen3-0.6b-4bit", "chat", len(CHAT))
    await setup.fetch_wait()
    assert setup.chat_copy() is not None and len(asked) == 2


@pytest.mark.asyncio
async def test_what_cannot_be_fetched_is_refused_in_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    setup, other, _ = bases_setup(tmp_path)
    with pytest.raises(ts.InstallError, match="not one the app can teach"):
        setup.fetch_start("gpt", "model", 1)
    with pytest.raises(ts.InstallError, match="not one the app can teach"):
        setup.fetch_start(other.id, "weights", 1)
    with pytest.raises(ts.InstallError, match="set up with the trainer"):
        setup.fetch_start("qwen3-0.6b-4bit", "model", 1)
    monkeypatch.setattr(ts, "apple_silicon", lambda: False)
    with pytest.raises(ts.InstallError, match="Apple silicon"):
        setup.fetch_start(other.id, "model", other.train_bytes)


@pytest.mark.asyncio
async def test_a_file_that_does_not_match_its_checksum_is_refused_and_nothing_is_kept(
    tmp_path: Path,
):
    setup, other, _ = bases_setup(tmp_path, tamper="chat")
    setup.fetch_start(other.id, "chat", len(OTHER_CHAT))
    await setup.fetch_wait()
    assert setup.parts[(other.id, "chat")].state == "failed" and setup.chat_copy(other.id) is None


def test_a_chat_copy_found_in_a_setting_is_only_for_the_main_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    mine = tmp_path / "mine.gguf"
    mine.write_bytes(b"x")
    monkeypatch.setenv("WASIFYAI_LANGUAGE_CHAT_COPY", str(mine))
    assert (
        ls.find_chat_copy(tmp_path) == mine
        and ls.find_chat_copy(tmp_path, base_id="qwen3-0.6b-4bit") == mine
    )
    assert ls.find_chat_copy(tmp_path, base_id="qwen3-4b-4bit") is None


def test_removing_the_component_takes_the_other_models_with_it(tmp_path: Path):
    setup, other, _ = bases_setup(tmp_path)
    folder = ls.component_root(tmp_path) / "models" / other.folder
    write = {p: d for p, d in OTHER.items()}
    for path, data in write.items():
        (folder / path).parent.mkdir(parents=True, exist_ok=True)
        (folder / path).write_bytes(data)
    assert setup.has_model(other)
    assert setup.remove() >= 400 and not setup.has_model(other)
