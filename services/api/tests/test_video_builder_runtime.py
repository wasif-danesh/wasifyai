"""The Video Builder component (V1a): pins, what counts as installed, the installer on stand-ins,
the environment a render runs in, and removing it."""

import hashlib
import io
import json
import stat
import tarfile
import zipfile
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from wasifyai_api import video_builder_runtime as vb
from wasifyai_api.audio_runtime import InstallError, platform_key

# ---- pins ----------------------------------------------------------------------------------------


def test_the_pins_are_exact_and_the_shipped_lock_is_the_one_pinned():
    pins = vb.load_pins()
    assert (
        pins.node.url.startswith("https://nodejs.org/dist/v") and pins.node.version in pins.node.url
    )
    assert pins.shell.url.startswith("https://storage.googleapis.com/chrome-for-testing-public/")
    assert pins.shell.version in pins.shell.url
    assert vb._sha256_file(pins.lock) == pins.lock_sha256  # noqa: SLF001
    assert vb._sha256_file(pins.package) == pins.package_sha256  # noqa: SLF001
    assert pins.platforms == ("darwin-arm64",)
    package = json.loads(pins.package.read_text())
    # exact versions, nothing that floats
    assert package["dependencies"] == {
        "hyperframes": "0.8.171",
        "gsap": "3.15.0",
        "@fontsource-variable/inter": "5.3.0",
        "@fontsource-variable/source-serif-4": "5.3.1",
    }
    lock = json.loads(pins.lock.read_text())
    entries = [v for k, v in lock["packages"].items() if k]
    assert all(v["resolved"].startswith("https://registry.npmjs.org/") for v in entries)
    assert all(v["integrity"].startswith("sha512-") for v in entries)


def test_a_pin_without_a_hash_is_refused(tmp_path):
    raw = json.loads(vb.PINS_FILE.read_text())
    raw["shell"]["sha256"] = "abc"
    bad = tmp_path / "pins.json"
    bad.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="SHA-256"):
        vb.load_pins(bad)


def test_the_install_plan_names_every_download_with_size_source_and_licence(tmp_path):
    inst = vb.VideoBuilderInstaller(tmp_path)
    plan = inst.plan()
    assert plan["bytes"] == sum(p["bytes"] for p in plan["parts"]) == inst.total_bytes
    assert {p["name"] for p in plan["parts"]} == {
        "Node.js",
        "Chrome headless shell",
        "HyperFrames and GSAP",
    }
    assert all(p["licence"] and p["source"] for p in plan["parts"])


# ---- what counts as installed --------------------------------------------------------------------


def managed(tmp_path: Path, **state) -> Path:
    pins = vb.load_pins()
    root = vb.component_root(tmp_path)
    install = vb._layout(root, "managed")  # noqa: SLF001
    for p in (install.node, install.shell, install.cli):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")
    record = {
        "schema": 1,
        "node": pins.node.sha256,
        "shell": pins.shell.sha256,
        "lock_sha256": pins.lock_sha256,
        **state,
    }
    (root / "state.json").write_text(json.dumps(record))
    return root


def test_nothing_is_installed_until_the_record_matches_the_pins(tmp_path, monkeypatch):
    monkeypatch.delenv("WASIFYAI_VIDEO_BUILDER_HOME", raising=False)
    assert vb.find_install(tmp_path) is None
    managed(tmp_path)
    found = vb.find_install(tmp_path)
    assert found is not None and found.source == "managed"
    assert found.shell.name == "chrome-headless-shell" and found.cli.name == "hyperframes.mjs"


@pytest.mark.parametrize("key", ["node", "shell", "lock_sha256"])
def test_a_record_from_other_pins_is_not_an_install(tmp_path, monkeypatch, key):
    monkeypatch.delenv("WASIFYAI_VIDEO_BUILDER_HOME", raising=False)
    managed(tmp_path, **{key: "0" * 64})
    assert vb.find_install(tmp_path) is None


def test_a_missing_file_is_not_an_install(tmp_path, monkeypatch):
    monkeypatch.delenv("WASIFYAI_VIDEO_BUILDER_HOME", raising=False)
    root = managed(tmp_path)
    vb._layout(root, "managed").shell.unlink()  # noqa: SLF001
    assert vb.find_install(tmp_path) is None


def test_a_copy_set_up_by_hand_is_used_as_it_is(tmp_path, monkeypatch):
    home = tmp_path / "hand"
    install = vb._layout(home, "env")  # noqa: SLF001
    for p in (install.node, install.shell, install.cli):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")
    monkeypatch.setenv("WASIFYAI_VIDEO_BUILDER_HOME", str(home))
    found = vb.find_install(tmp_path / "elsewhere")
    assert found is not None and found.source == "env" and found.root == home


# ---- the environment a render runs in ------------------------------------------------------------


def test_the_render_environment_starts_empty_and_has_no_telemetry(tmp_path, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://secret-proxy:3128")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    root = managed(tmp_path)
    install = vb._layout(root, "managed")  # noqa: SLF001
    env = vb.render_env(install, {"EXTRA": "1"})
    assert "HTTPS_PROXY" not in env and "GITHUB_TOKEN" not in env
    assert env["HYPERFRAMES_NO_TELEMETRY"] == "1" and env["HYPERFRAMES_SKIP_SKILLS"] == "1"
    assert env["DO_NOT_TRACK"] == "1" and env["EXTRA"] == "1"
    # a home of its own inside the component, so ~/.hyperframes is never touched
    assert env["HOME"] == str(root / "home") and Path(env["HOME"]).is_dir()
    assert env["PATH"].startswith(str(install.node.parent))


# ---- the installer on stand-ins ------------------------------------------------------------------


def fake_node_tar() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, data, mode in (
            ("node-v0/bin/node", b"#!/bin/sh\n", 0o755),
            ("node-v0/lib/node_modules/npm/bin/npm-cli.js", b"//", 0o644),
        ):
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), mode
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def fake_shell_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        info = zipfile.ZipInfo("chrome-headless-shell-mac-arm64/chrome-headless-shell")
        info.external_attr = (stat.S_IFREG | 0o755) << 16
        z.writestr(info, "#!/bin/sh\n")
    return buf.getvalue()


def stand_ins(tmp_path, monkeypatch, *, node_bytes=None, ok_npm=True, ok_browser=True):
    monkeypatch.delenv("WASIFYAI_VIDEO_BUILDER_HOME", raising=False)
    node, shell = node_bytes or fake_node_tar(), fake_shell_zip()
    pins = vb.load_pins()
    pins = replace(
        pins,
        node=replace(
            pins.node, url="https://example.test/node.tgz", size=len(node),
            sha256=hashlib.sha256(node).hexdigest(),
        ),
        shell=replace(
            pins.shell, url="https://example.test/shell.zip", size=len(shell),
            sha256=hashlib.sha256(shell).hexdigest(),
        ),
        packages_bytes=1000,
        platforms=(platform_key(),),
    )  # fmt: skip
    served = {
        "https://example.test/node.tgz": fake_node_tar(),
        "https://example.test/shell.zip": shell,
    }
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200, content=served[str(request.url)])

    inst = vb.VideoBuilderInstaller(
        tmp_path, pins,
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )  # fmt: skip
    commands: list[list[str]] = []

    async def run(args, cwd, env, limit_s=600):
        commands.append(args)
        if "ci" in args:
            if not ok_npm:
                return False, "boom"
            cli = Path(cwd) / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"
            cli.parent.mkdir(parents=True)
            cli.write_text("")
            assert env["HYPERFRAMES_NO_TELEMETRY"] == "1"  # the install runs quietly too
            return True, ""
        if "--version" in args:
            if args[0].endswith("chrome-headless-shell") and not ok_browser:
                return False, ""
            return True, "Chrome 152.0.7977.30" if args[0].endswith("headless-shell") else "0.8.171"
        return True, ""

    inst.run = run
    return inst, asked, commands


async def finish(inst: vb.VideoBuilderInstaller) -> None:
    assert inst._task is not None  # noqa: SLF001
    await inst._task  # noqa: SLF001


async def test_it_installs_after_confirmation_and_only_then_is_installed(tmp_path, monkeypatch):
    inst, asked, commands = stand_ins(tmp_path, monkeypatch)
    inst.start(inst.total_bytes)
    await finish(inst)
    assert inst.progress.state == "ready", inst.progress
    found = vb.find_install(tmp_path, inst.pins)
    assert found is not None and found.node.is_file() and found.shell.is_file()
    assert stat.S_IMODE(found.shell.stat().st_mode) & 0o111  # the browser can be run
    assert asked == ["https://example.test/node.tgz", "https://example.test/shell.zip"]
    ci = next(c for c in commands if "ci" in c)
    assert "--ignore-scripts" in ci  # packages run no install scripts
    # the lock the app ships is the one npm installs from
    assert (found.app / "package-lock.json").read_bytes() == inst.pins.lock.read_bytes()
    assert not (vb.component_root(tmp_path) / "cache").exists()  # npm's download cache is removed
    assert not list(vb.component_root(tmp_path).glob("stage-*"))  # nothing is left half-way


async def test_nothing_is_fetched_without_the_size_the_person_saw(tmp_path, monkeypatch):
    inst, asked, _ = stand_ins(tmp_path, monkeypatch)
    with pytest.raises(InstallError, match="changed since it was shown"):
        inst.start(inst.total_bytes + 1)
    assert asked == [] and not inst.running


async def test_a_download_that_is_not_what_was_pinned_keeps_nothing(tmp_path, monkeypatch):
    inst, _, _ = stand_ins(tmp_path, monkeypatch)
    inst.pins = replace(inst.pins, shell=replace(inst.pins.shell, sha256="0" * 64))
    inst.start(inst.total_bytes)
    await finish(inst)
    assert inst.progress.state == "failed" and "did not match" in inst.progress.message
    assert vb.find_install(tmp_path, inst.pins) is None
    assert not list(vb.component_root(tmp_path).glob("stage-*"))


@pytest.mark.parametrize(
    ("kwargs", "words"),
    [
        ({"ok_npm": False}, "packages"),
        ({"ok_browser": False}, "browser"),
    ],
)
async def test_a_failed_step_says_so_in_words_and_leaves_no_install(
    tmp_path, monkeypatch, kwargs, words
):
    inst, _, _ = stand_ins(tmp_path, monkeypatch, **kwargs)
    inst.start(inst.total_bytes)
    await finish(inst)
    assert inst.progress.state == "failed" and words in inst.progress.message
    assert vb.find_install(tmp_path, inst.pins) is None


async def test_a_zip_with_a_path_outside_its_folder_is_refused(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../escape.txt", "x")
    archive = tmp_path / "bad.zip"
    archive.write_bytes(buf.getvalue())
    with pytest.raises(InstallError, match="outside its folder"):
        vb._unpack_zip(archive, tmp_path / "out")  # noqa: SLF001
    assert not (tmp_path / "escape.txt").exists()


async def test_it_is_not_offered_where_it_was_not_measured(tmp_path, monkeypatch):
    inst, _, _ = stand_ins(tmp_path, monkeypatch)
    inst.pins = replace(inst.pins, platforms=("some-other-system",))
    assert not inst.supported and inst.plan()["bytes"] == 0
    with pytest.raises(InstallError, match="not available on this kind of computer"):
        inst.start(inst.total_bytes)


async def test_uninstall_removes_everything_and_says_how_much_came_back(tmp_path, monkeypatch):
    inst, _, _ = stand_ins(tmp_path, monkeypatch)
    inst.start(inst.total_bytes)
    await finish(inst)
    assert vb.uninstall(tmp_path) > 0
    assert not vb.component_root(tmp_path).exists() and vb.find_install(tmp_path, inst.pins) is None
    assert vb.uninstall(tmp_path) == 0  # nothing left to remove
