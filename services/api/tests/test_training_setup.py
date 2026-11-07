"""Setting up the picture trainer (AI Toolkit): what is offered and what it costs, what counts as
already there, and the install through stand-ins for AI Toolkit's manager and the servers it is
fetched from (the real run is by hand)."""

import hashlib
import io
import json
import tarfile
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from wasifyai_api import training_setup as ts
from wasifyai_api.desktop_models import DownloadManager

FILES = {
    "text_encoder/config.json": b'{"a": 1}',
    "tokenizer/tokenizer.json": b"T" * 300,
    "tokenizer/vocab.json": b"V" * 100,
}


def source_archive() -> bytes:
    """A stand-in for AI Toolkit's source archive: one top folder with `run.py` and its manager."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, body in (("run.py", b"print('run')"), ("manager/__init__.py", b"")):
            info = tarfile.TarInfo(f"ai-toolkit-abc/{name}")
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
    return buf.getvalue()


ARCHIVE = source_archive()


def small_pins() -> ts.Pins:
    base = ts.load_pins()
    return replace(
        base,
        packages_bytes=1000,
        tool_url="https://github.test/ai-toolkit.tar.gz",
        tool_size=len(ARCHIVE),
        tool_sha256=hashlib.sha256(ARCHIVE).hexdigest(),
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
    monkeypatch.delenv("WASIFYAI_AI_TOOLKIT_DIR", raising=False)
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.setattr(ts, "picture_supported", lambda: True)


def test_the_pins_name_ai_toolkit_and_the_text_encoders_small_files():
    p = ts.load_pins()
    assert p.tool_version == "0.13.25" and "f7a1fb9a" in p.tool_url
    assert p.tool_size > 1_000_000 and len(p.tool_sha256) == 64
    assert p.model == "flux2-klein-4b"  # the image model's own files are taught
    assert p.base_repo == "black-forest-labs/FLUX.2-klein-base-4B"
    paths = {f.path for f in p.base_files}
    assert paths >= {"text_encoder/config.json", "tokenizer/tokenizer.json"}
    assert p.base_bytes < 20e6  # small files only: nothing big is fetched for the trainer
    assert all(len(f.sha256) == 64 for f in p.base_files)


def test_every_platform_pins_the_same_trainer():
    from wasifyai_api.components.manifest import part_pins

    tools = {
        plat: part_pins("trainer-pictures", platform=plat)["tool"]["sha256"]
        for plat in ("darwin-arm64", "darwin-x64", "linux-x64", "linux-arm64", "windows-x64")
    }
    assert len(set(tools.values())) == 1


def test_it_can_teach_on_apple_silicon_or_with_an_nvidia_card(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.undo()
    for plat, arm, nvidia, can in (
        ("darwin", True, False, True),
        ("darwin", False, False, False),
        ("linux", False, True, True),
        ("win32", False, True, True),
        ("win32", False, False, False),
    ):
        monkeypatch.setattr(ts.sys, "platform", plat)
        monkeypatch.setattr(ts, "apple_silicon", lambda a=arm, p=plat: a and p == "darwin")
        monkeypatch.setattr(ts, "nvidia_gpu", lambda nvidia=nvidia: nvidia)
        assert ts.picture_supported() is can, (plat, arm, nvidia)


def test_the_model_counts_only_when_every_file_is_whole(tmp_path: Path):
    pins = small_pins()
    own = ts.component_root(tmp_path) / "models" / pins.base_folder
    write_base(own, skip="tokenizer/vocab.json")
    assert ts.find_base(tmp_path, pins) is None  # a download still going
    write_base(own)
    assert ts.find_base(tmp_path, pins) == (own, "managed")
    write_base(own, short="tokenizer/tokenizer.json")
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


def make_checkout(home: Path) -> None:
    (home / ".venv" / "bin").mkdir(parents=True)
    (home / "run.py").write_text("")
    (home / ".venv" / "bin" / "python").write_text("")


def test_the_tool_is_found_in_a_setting_or_the_app_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    pins = small_pins()
    assert ts.find_tool(tmp_path, pins) is None
    home = ts.component_root(tmp_path) / ts.CHECKOUT
    make_checkout(home)
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
    make_checkout(other)
    monkeypatch.setenv("WASIFYAI_AI_TOOLKIT_DIR", str(other))
    assert ts.find_tool(tmp_path, pins) == (other, "env")


def setup_for(tmp_path: Path, **over) -> tuple[ts.PictureSetup, list[list[str]], list[str]]:
    served = {
        f"https://hub.test/{small_pins().base_repo}/resolve/{small_pins().base_revision}/{p}": d
        for p, d in FILES.items()
    }
    served[small_pins().tool_url] = ARCHIVE
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200, content=served[str(request.url)])

    def factory():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)

    commands: list[list[str]] = []

    async def run(args: list[str], env: dict[str, str]) -> tuple[int, str]:
        commands.append(args)
        if str(ts.INSTALL_SCRIPT) in args:
            checkout = Path(args[-1])
            assert (checkout / "run.py").is_file()  # noqa: ASYNC240  the source was unpacked
            if over.get("manager_fails"):
                return 1, "error: could not reach download.pytorch.org"
            if over.get("unsupported"):
                return 3, "AITK-SETUP-UNSUPPORTED No supported GPU was found."
            (checkout / ".venv" / "bin").mkdir(parents=True)  # noqa: ASYNC240
            (checkout / ".venv" / "bin" / "python").write_text("")  # noqa: ASYNC240
            return 0, "Environment is up to date.\nAITK-SETUP-OK mps"
        if args[1:2] == ["-c"]:
            return 0, "ok 2.13.0"
        return 0, ""

    setup = ts.PictureSetup(
        tmp_path, pins=small_pins(), base_url="https://hub.test",
        run=run, downloads=DownloadManager(factory, chunk=64),
    )  # fmt: skip
    return setup, commands, asked


def test_the_plan_says_what_it_would_fetch_and_nothing_that_is_already_there(tmp_path: Path):
    setup, _, _ = setup_for(tmp_path)
    plan = setup.plan()
    assert plan["bytes"] == len(ARCHIVE) + 1000 + 8 + 300 + 100 == setup.missing_bytes()
    assert [p["name"] for p in plan["parts"]] == [
        "Trainer (AI Toolkit)", "FLUX.2 klein 4B text encoder settings",
    ]  # fmt: skip
    assert all(p["source"] for p in plan["parts"])
    write_base(ts.component_root(tmp_path) / "models" / setup.pins.base_folder)
    assert setup.missing_bytes() == len(ARCHIVE) + 1000  # the small files are there
    assert [p["have"] for p in setup.plan()["parts"]] == [False, True]


def test_the_plan_says_the_image_model_is_needed_and_where_to_get_it(tmp_path: Path):
    setup, _, _ = setup_for(tmp_path)
    setup.picture_model_bytes = 16_000_000_000
    need = setup.plan()["needs"][0]
    assert need["name"] == "The image model (FLUX.2 klein 4B)" and not need["have"]
    assert need["bytes"] == 16_000_000_000 and "Select image model" in need["how"]
    setup.picture_model = lambda: {"transformer": tmp_path / "t"}
    assert setup.plan()["needs"][0]["have"]
    assert setup.missing_bytes() == setup.plan()["bytes"]  # it is never fetched by this setup


def test_it_says_in_words_why_it_cannot_be_set_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    setup, _, _ = setup_for(tmp_path)
    assert setup.problem() is None
    monkeypatch.setattr(ts, "picture_supported", lambda: False)
    assert "Apple silicon" in (setup.problem() or "") and "NVIDIA" in (setup.problem() or "")
    with pytest.raises(ts.InstallError, match="Apple silicon"):
        setup.start(setup.missing_bytes())
    monkeypatch.setattr(ts, "picture_supported", lambda: True)
    setup.pins = replace(setup.pins, tool_url="")
    assert "not part of this build" in (setup.problem() or "")


@pytest.mark.asyncio
async def test_nothing_starts_unless_the_size_shown_is_repeated(tmp_path: Path):
    setup, commands, asked = setup_for(tmp_path)
    with pytest.raises(ts.InstallError, match="out of date"):
        setup.start(setup.missing_bytes() - 1)
    assert commands == [] and asked == []


@pytest.mark.asyncio
async def test_the_install_unpacks_ai_toolkit_runs_its_manager_and_checks_it(tmp_path: Path):
    setup, commands, asked = setup_for(tmp_path)
    setup.start(setup.missing_bytes())
    await setup.wait()
    assert setup.progress.state == "ready", setup.progress.message
    checkout = ts.component_root(tmp_path) / ts.CHECKOUT
    assert commands[0] == [setup.python, "-I", str(ts.INSTALL_SCRIPT), str(checkout)]
    assert commands[-1][0] == str(ts.venv_python(checkout)) and commands[-1][1] == "-c"
    assert asked[0] == setup.pins.tool_url and len(asked) == 1 + len(FILES)
    assert not list((ts.component_root(tmp_path) / "download").glob("*.tar.gz"))
    state = setup.state()
    assert state["installed"] and state["tool"] == "managed" and state["base"] == "managed"
    assert setup.missing_bytes() == 0
    with pytest.raises(ts.InstallError, match="already set up"):
        setup.start(0)


@pytest.mark.asyncio
async def test_a_failed_manager_says_so_and_nothing_counts_as_installed(tmp_path: Path):
    setup, _, _ = setup_for(tmp_path, manager_fails=True)
    setup.start(setup.missing_bytes())
    await setup.wait()
    assert setup.progress.state == "failed" and "did not work" in setup.progress.message
    assert setup.progress.step == "packages"
    assert not (ts.component_root(tmp_path) / ts.STATE_FILE).exists()
    assert not setup.state()["installed"]


@pytest.mark.asyncio
async def test_a_computer_the_manager_cannot_set_up_is_named_in_its_words(tmp_path: Path):
    setup, _, _ = setup_for(tmp_path, unsupported=True)
    setup.start(setup.missing_bytes())
    await setup.wait()
    assert setup.progress.state == "failed"
    assert "No supported GPU was found" in setup.progress.message


@pytest.mark.asyncio
async def test_a_file_that_does_not_match_its_checksum_is_refused(tmp_path: Path):
    setup, _, _ = setup_for(tmp_path)
    bad = replace(
        setup.pins,
        base_files=tuple(
            replace(f, sha256="0" * 64) if f.path.startswith("tokenizer") else f
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
    assert freed >= 400 and not ts.component_root(tmp_path).exists()
    assert not setup.state()["installed"]
