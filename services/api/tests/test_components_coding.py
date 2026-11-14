"""The coding engine on the one installer (stage C1a): seven steps, the state file
`coding_server.find_install` reads, repair, removal, and the platforms where it is not offered.
uv is a stand-in that makes the environment's "python" the fake Agent Server; the catalogue is
served by a fake transport; the server is started for real (the fake one) in the verify step."""

import hashlib
import io
import json
import re
import sys
import tarfile
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from wasifyai_api.coding_server import CodingServer, find_install
from wasifyai_api.components.coding import CodingComponent, coding_files
from wasifyai_api.components.manifest import MANIFESTS, Manifest, Pins, load_manifest
from wasifyai_api.components.routes import router
from wasifyai_api.identity import Identity, get_identity
from wasifyai_api.services import ApiServices
from wasifyai_platform_sdk.installer import Archive, InstallError, Registry

from tests.test_coding_server import FILES, fake_python, gone, terminal_folders, wait_gone

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the fake server is a shell script")

URL = "https://example.test/extensions-0.42.0.tgz"
LOCK = "requirements-test.lock"
BUILD = "build-constraints.txt"
SIZE = 400_000_000


def catalogue(mark: str = "skills") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        files = {
            f"package/{mark}/hello/SKILL.md": b"# hello\n",
            "package/package.json": b'{"name": "@openhands/extensions", "version": "0.42.0"}',
        }
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def build_files(tmp_path: Path, lock_text: str = "fake==1.0 --hash=sha256:00\n") -> Path:
    """A build's `coding-engine` folder: the real sandbox profile and a lock of the test's."""
    files = tmp_path / "build" / "coding-engine"
    files.mkdir(parents=True)
    (files / "engine.sb.template").write_text((FILES / "engine.sb.template").read_text())
    (files / LOCK).write_text(lock_text)
    (files / BUILD).write_text("setuptools==1.0 --hash=sha256:00\n")
    return files


def manifest_for(body: bytes, files: Path, **extra) -> Manifest:
    pin = Archive(URL, len(body), hashlib.sha256(body).hexdigest(), "tar.gz", strip=1)
    more = {
        "lock": LOCK,
        "lock_sha256": hashlib.sha256((files / LOCK).read_bytes()).hexdigest(),
        "build_constraints": BUILD,
        "build_constraints_sha256": hashlib.sha256((files / BUILD).read_bytes()).hexdigest(),
        "install_bytes": SIZE,
        "extensions": {"version": "0.42.0"},
        **extra,
    }
    pins = Pins("coding", "Coding engine (OpenHands)", "1.62.0", "", 1000, pin, more)
    return Manifest("darwin-arm64", "3.12.15", {"coding": pins})


class FakeUv:
    """`uv python install`, `uv venv` and `uv pip install`: the environment it "makes" has the
    fake Agent Server as its python, saying it is `version`."""

    def __init__(self, version: str = "1.62.0", fail: str | None = None):
        self.calls: list[list[str]] = []
        self.version = version
        self.fail = fail

    async def __call__(self, args: list[str], env: dict[str, str], cwd: Path | None):
        self.calls.append(args)
        verb = " ".join(args[1:3])
        if self.fail and verb.startswith(self.fail):
            return 1, "no network"
        if verb.startswith("venv"):
            fake_python(Path(args[-1]) / "bin" / "python", FAKE_VERSION=self.version)
        return 0, f"ok: {verb}"


def component(tmp_path: Path, body: bytes | None = None, uv: FakeUv | None = None, **extra):
    body = body if body is not None else catalogue()
    files = build_files(tmp_path)
    data = tmp_path / "data"

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == URL
        return httpx.Response(200, content=body)

    client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))  # noqa: E731
    server = CodingServer(data, files, startup_timeout_s=20, sandbox_exec=None)
    c = CodingComponent(
        data, manifest_for(body, files, **extra), files, "uv", server,
        run=uv or FakeUv(), client=client,
    )  # fmt: skip
    return c


@pytest.fixture(autouse=True)
def uv_is_there(monkeypatch):
    from wasifyai_api.components import coding

    monkeypatch.setattr(coding, "_runnable", lambda program: bool(program))


async def test_it_installs_in_seven_steps_and_the_server_finds_it(tmp_path):
    uv = FakeUv()
    c = component(tmp_path, uv=uv)
    data = tmp_path / "data"
    heard: list[dict] = []
    c.installer.listeners.append(lambda cid, s: heard.append(s))
    assert c.status() == {"state": "not_installed", "needs_bytes": SIZE}
    c.install(SIZE)
    await c.wait()
    assert c.status() == {"state": "installed", "version": "1.62.0", "accelerator": ""}
    steps = [s["progress"]["step"] for s in heard if s["state"] == "installing"]
    assert list(dict.fromkeys(steps)) == [
        "check", "uv", "python", "environment", "packages", "extensions", "verify",
    ]  # fmt: skip
    assert heard[-1]["state"] == "installed"

    # the packages came from the hashed lock, and nothing else was allowed in
    install = next(a for a in uv.calls if a[1:3] == ["pip", "install"])
    assert "--require-hashes" in install and "--no-deps" in install
    assert install[install.index("-r") + 1].endswith(LOCK)
    # the build tool of a source-only package is the pinned one, never the newest
    assert install[install.index("--build-constraints") + 1].endswith(BUILD)
    assert uv.calls[0][1:] == ["python", "install", "3.12.15"]

    found = find_install(data)
    assert found is not None and found.version == "1.62.0"
    assert found.python == data / "engine" / "coding" / "venv" / "bin" / "python"
    assert (found.extensions / "skills" / "hello" / "SKILL.md").is_file()
    state = json.loads((data / "engine" / "coding" / "state.json").read_text())
    assert c.pins is not None and c.pins.archive is not None
    assert state["extensions"]["sha256"] == c.pins.archive.sha256
    assert state["lock_sha256"] == c.pins.extra["lock_sha256"]

    log = (data / "logs" / "provision.log").read_text()
    assert "coding: step verify" in log and "answered as 1.62.0 after" in log
    # the check stopped what it started, and the downloads are gone
    assert not c.server.running
    assert not (data / "engine" / "coding" / "downloads").exists()
    assert not terminal_folders()

    # and the server starts from it
    try:
        await c.server.ensure_running()
        assert (await c.server.request("GET", "/server_info")).json()["version"] == "1.62.0"
    finally:
        await c.server.close()


async def test_a_size_that_is_not_the_one_shown_and_a_second_setup_are_refused(tmp_path):
    c = component(tmp_path)
    with pytest.raises(InstallError, match="out of date"):
        c.install(SIZE - 1)
    c.install(SIZE)
    await c.wait()
    with pytest.raises(InstallError, match="already set up"):
        c.install(SIZE)
    await c.server.close()


async def test_an_engine_that_is_not_the_pinned_version_is_not_installed(tmp_path):
    c = component(tmp_path, uv=FakeUv(version="1.63.0"))
    c.install(SIZE)
    await c.wait()
    status = c.status()
    assert status["state"] == "failed" and status["step"] == "verify"
    assert "not the pinned version" in status["message"]
    assert find_install(tmp_path / "data") is None
    assert not c.server.running
    await c.server.close()


async def test_a_catalogue_that_does_not_match_its_checksum_stops_the_setup(tmp_path):
    good = catalogue()
    c = component(tmp_path, body=good)
    assert c.pins is not None and c.pins.archive is not None
    wrong = Archive(URL, c.pins.archive.size, "0" * 64, "tar.gz", strip=1)
    c.pins = Pins("coding", c.pins.title, "1.62.0", "", 1000, wrong, c.pins.extra)
    c.install(SIZE)
    await c.wait()
    status = c.status()
    assert status["state"] == "failed" and status["step"] == "extensions"
    assert "checksum" in status["message"]
    assert find_install(tmp_path / "data") is None
    assert not (tmp_path / "data" / "engine" / "coding" / "extensions" / "0.42.0").exists()


async def test_an_archive_without_a_catalogue_in_it_stops_the_setup(tmp_path):
    c = component(tmp_path, body=catalogue(mark="other"))
    c.install(SIZE)
    await c.wait()
    assert c.status()["state"] == "failed" and c.status()["step"] == "extensions"
    assert find_install(tmp_path / "data") is None


async def test_packages_that_cannot_be_fetched_say_so(tmp_path):
    c = component(tmp_path, uv=FakeUv(fail="pip install"))
    c.install(SIZE)
    await c.wait()
    status = c.status()
    assert status["state"] == "failed" and status["step"] == "packages"
    assert status["message"] == (
        "The coding engine's packages could not be installed. Are you online?"
    )


async def test_a_build_without_the_lock_or_a_changed_lock_is_refused_before_any_fetch(tmp_path):
    uv = FakeUv()
    c = component(tmp_path, uv=uv)
    assert c.files is not None
    (c.files / LOCK).write_text("tampered==6.6.6 --hash=sha256:66\n")
    c.install(SIZE)
    await c.wait()
    assert c.status()["state"] == "failed" and "damaged" in c.status()["message"]
    assert not any(a[1:3] == ["pip", "install"] for a in uv.calls)
    (c.files / LOCK).unlink()
    c.install(None, repair=True)
    await c.wait()
    status = c.status()
    assert status["state"] == "failed" and status["step"] == "check"
    assert "carries no package list" in status["message"]


async def test_a_changed_build_tool_pin_is_refused_before_any_fetch(tmp_path):
    uv = FakeUv()
    c = component(tmp_path, uv=uv)
    assert c.files is not None
    (c.files / BUILD).write_text("setuptools==6.6.6\n")  # no hash: uv would take anything
    c.install(SIZE)
    await c.wait()
    status = c.status()
    assert status["state"] == "failed" and status["step"] == "check"
    assert not any(a[1:2] == ["venv"] for a in uv.calls)


async def test_repair_stops_a_running_server_and_makes_it_again(tmp_path):
    uv = FakeUv()
    c = component(tmp_path, uv=uv)
    c.install(SIZE)
    await c.wait()
    data = tmp_path / "data"
    await c.server.ensure_running()
    pid = c.server.pid
    assert pid is not None
    (data / "engine" / "coding" / "venv" / "bin" / "python").write_text("broken")
    skill = data / "engine" / "coding" / "extensions" / "0.42.0" / "skills" / "hello" / "SKILL.md"
    skill.unlink()
    c.install(None, repair=True)
    await c.wait()
    assert await wait_gone(pid, 5)  # the one that was running was stopped first
    assert c.status()["state"] == "installed"
    found = find_install(data)
    assert found is not None and (found.extensions / "skills" / "hello" / "SKILL.md").is_file()
    assert sum(1 for a in uv.calls if a[1:2] == ["venv"]) == 2
    await c.server.close()


async def test_removing_it_stops_the_server_and_leaves_the_persons_work(tmp_path):
    c = component(tmp_path)
    c.install(SIZE)
    await c.wait()
    data = tmp_path / "data"
    await c.server.ensure_running()
    pid = c.server.pid
    assert pid is not None
    kept = data / "coding" / "workspace" / "mine.txt"
    kept.write_text("my work")
    freed = c.uninstall()
    assert freed > 0
    assert await wait_gone(pid, 5) and gone(pid)
    assert not (data / "engine" / "coding").exists()
    assert kept.read_text() == "my work"
    assert c.status() == {"state": "not_installed", "needs_bytes": SIZE}
    assert not terminal_folders()
    await c.server.close()


async def test_a_change_of_a_pin_asks_for_a_new_setup(tmp_path):
    c = component(tmp_path)
    c.install(SIZE)
    await c.wait()
    assert c.pins is not None
    for changed in (
        Pins("coding", c.pins.title, "1.63.0", "", 1000, c.pins.archive, c.pins.extra),
        Pins("coding", c.pins.title, "1.62.0", "", 1000, c.pins.archive,
             {**c.pins.extra, "lock_sha256": "f" * 64}),
        Pins("coding", c.pins.title, "1.62.0", "", 1000,
             Archive(URL, 1, "e" * 64, "tar.gz", strip=1), c.pins.extra),
    ):  # fmt: skip
        was, c.pins = c.pins, changed
        assert c.status()["state"] == "not_installed"
        c.pins = was
    assert c.status()["state"] == "installed"
    await c.server.close()


# ---- where it is offered -------------------------------------------------------------------------


def test_it_is_not_available_where_there_is_no_pin_or_no_sandbox(tmp_path, monkeypatch):
    files = build_files(tmp_path)
    data = tmp_path / "data"
    for platform in ("darwin-x64", "linux-arm64", "linux-x64", "windows-x64"):
        server = CodingServer(data, files, sandbox_exec=None)
        c = CodingComponent(data, load_manifest(platform), files, "uv", server)
        assert c.pins is not None, f"{platform} does not name the coding engine"
        assert c.status() == {
            "state": "unsupported",
            "reason": "The coding engine is not available for this computer yet.",
        }
        with pytest.raises(InstallError, match="not available for this computer yet"):
            c.install(None, repair=True)
    # a platform with the pins but without the sandbox (the real server class decides)
    from wasifyai_api import coding_server

    monkeypatch.setattr(coding_server, "supported", lambda: False)
    c = CodingComponent(
        data, manifest_for(catalogue(), files), files, "uv", CodingServer(data, files)
    )
    assert c.status()["state"] == "unsupported"


def test_the_manifests_the_pin_and_the_lock_of_this_build_agree():
    """The one version pin (`services/coding-engine/VERSION`), every manifest and the lock say
    the same; the lock on the Mac is hashed line by line and leaves out what is named in
    `leave-out.txt`."""
    version = (FILES / "VERSION").read_text().strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    for path in sorted(MANIFESTS.glob("*.yaml")):
        entry = yaml.safe_load(path.read_text())["components"]["coding"]
        assert str(entry["version"]) == version, path.name
    mac = load_manifest("darwin-arm64").get("coding")
    assert mac is not None and mac.archive is not None
    assert mac.archive.url.startswith("https://") and "0.42.0" in mac.archive.url
    assert mac.extra["extensions"]["version"] == "0.42.0"
    lock = FILES / str(mac.extra["lock"])
    assert hashlib.sha256(lock.read_bytes()).hexdigest() == mac.extra["lock_sha256"]
    text = lock.read_text()
    pinned = dict(re.findall(r"^([A-Za-z0-9_.\-]+)==(\S+)", text, re.M))
    for package in ("openhands-agent-server", "openhands-sdk", "openhands-tools",
                    "openhands-workspace"):  # fmt: skip
        assert pinned[package] == version
    requirements = [b for b in re.split(r"\n(?=\S)", text) if re.match(r"^[A-Za-z0-9]", b)]
    assert len(requirements) == len(pinned) > 50
    for block in requirements:
        assert "--hash=sha256:" in block, block.splitlines()[0]
    left_out = {
        line.split("#")[0].strip().lower()
        for line in (FILES / "leave-out.txt").read_text().splitlines()
        if line.split("#")[0].strip()
    }
    assert left_out and not left_out & {name.lower() for name in pinned}
    build = FILES / str(mac.extra["build_constraints"])
    assert hashlib.sha256(build.read_bytes()).hexdigest() == mac.extra["build_constraints_sha256"]
    hashed = r"^setuptools==\S+ \\\n\s+--hash=sha256:[0-9a-f]{64}$"
    assert re.search(hashed, build.read_text(), re.M)
    assert int(mac.extra["install_bytes"]) > 100_000_000


def test_the_builds_files_are_found_in_a_checkout_and_in_a_packaged_app(tmp_path):
    repo = Path(__file__).resolve().parents[3]
    assert coding_files(repo / "products") == repo / "services" / "coding-engine"
    bundle = tmp_path / "bundle"
    (bundle / "products").mkdir(parents=True)
    assert coding_files(bundle / "products") is None
    (bundle / "coding-engine").mkdir()
    (bundle / "coding-engine" / "engine.sb.template").write_text("(version 1)")
    assert coding_files(bundle / "products") == bundle / "coding-engine"
    assert coding_files(None) is None


# ---- through the routes --------------------------------------------------------------------------


async def test_it_is_listed_set_up_and_removed_through_the_one_route_family(tmp_path):
    c = component(tmp_path)
    registry = Registry()
    registry.add(c, c.installer)
    app = FastAPI()
    app.include_router(router)
    app.state.services = ApiServices(components=registry)
    app.dependency_overrides[get_identity] = lambda: Identity("t1", "u1")
    with TestClient(app) as client:
        listed = client.get("/components").json()["components"]
        assert listed == [{
            "id": "coding", "title": "Coding engine (OpenHands)",
            "status": {"state": "not_installed", "needs_bytes": SIZE},
            "can": {"stop": True, "repair": True, "remove": True},
        }]  # fmt: skip
        assert client.post("/components/coding/install", json={}).status_code == 422
        r = client.post("/components/coding/install", json={"confirm_bytes": SIZE - 5})
        assert r.status_code == 409
