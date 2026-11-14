"""The coding engine's server as the engine's child (stage C1a): finding the install, the sandbox
profile, the start (a free port, a new key, a clean environment, its own session), the stop that
reaches everything it started, and the guard that ends it when the engine goes away. The server is
the fake (`fake_agent_server.py`); the real one is `tests/integration/test_coding_sandbox.py`."""

import asyncio
import json
import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from wasifyai_api import coding_server
from wasifyai_api.coding_server import (
    CLOSED,
    PROFILE_TEMPLATE,
    SANDBOX_EXEC,
    CodingError,
    CodingServer,
    fill_profile,
    find_install,
)
from wasifyai_api.desktop_coding import router
from wasifyai_api.identity import get_identity
from wasifyai_api.services import ApiServices
from wasifyai_platform_sdk import Identity

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the fake server is a shell script")

FAKE = Path(__file__).with_name("fake_agent_server.py")
FILES = Path(__file__).resolve().parents[2] / "coding-engine"
ON_MAC = sys.platform == "darwin" and Path(SANDBOX_EXEC).is_file()


def fake_python(path: Path, **env: str) -> None:
    """A "python" that runs the fake server with whatever it is started with."""
    path.parent.mkdir(parents=True, exist_ok=True)
    exports = "".join(f"export {k}='{v}'\n" for k, v in env.items())
    path.write_text(f'#!/bin/sh\n{exports}exec "{sys.executable}" "{FAKE}" "$@"\n')
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def install(data: Path, **env: str) -> Path:
    root = data / "engine" / "coding"
    fake_python(root / "venv" / "bin" / "python", **env)
    (root / "extensions" / "0.42.0" / "skills").mkdir(parents=True)
    (root / "state.json").write_text(json.dumps({
        "schema": 1, "version": "1.62.0", "python": "3.12.15", "python_path": "venv/bin/python",
        "lock_sha256": "0" * 64,
        "extensions": {"version": "0.42.0", "sha256": "1" * 64, "dir": "extensions/0.42.0"},
    }))  # fmt: skip
    return root


def server(data: Path, **kwargs) -> CodingServer:
    return CodingServer(data, FILES, startup_timeout_s=20, sandbox_exec=None, **kwargs)


def gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return True
    return False


async def wait_gone(pid: int, seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if gone(pid):
            return True
        await asyncio.sleep(0.1)
    return gone(pid)


def terminal_folders() -> set[Path]:
    """The terminal folders in /tmp now: a test that leaves one has failed."""
    return set(Path("/tmp").glob("wasify-coding-*"))


def real(path: str | Path) -> Path:
    return Path(os.path.realpath(path))


def there(path: Path) -> bool:
    return path.exists()


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def sleeper() -> subprocess.Popen:
    """A process outside the sandbox, for a test that tries to signal it."""
    return subprocess.Popen(["/bin/sleep", "120"])


async def started_with(s: CodingServer) -> dict:
    return (await s.request("GET", "/fake/env")).json()


# ---- the install ---------------------------------------------------------------------------------


def test_the_install_is_found_from_the_state_file(tmp_path):
    assert find_install(tmp_path) is None
    root = install(tmp_path)
    found = find_install(tmp_path)
    assert found is not None
    assert (found.version, found.extensions_version) == ("1.62.0", "0.42.0")
    assert found.python == root / "venv" / "bin" / "python"
    assert found.extensions == (root / "extensions" / "0.42.0").resolve()


def test_a_state_file_that_points_outside_or_is_damaged_is_not_an_install(tmp_path):
    root = install(tmp_path)
    state = json.loads((root / "state.json").read_text())
    outside = tmp_path / "elsewhere"
    (outside / "skills").mkdir(parents=True)
    (root / "state.json").write_text(
        json.dumps({**state, "extensions": {**state["extensions"], "dir": "../../elsewhere"}})
    )
    assert find_install(tmp_path) is None
    (root / "state.json").write_text(json.dumps({**state, "python_path": "../../elsewhere/py"}))
    assert find_install(tmp_path) is None
    (root / "state.json").write_text("not json")
    assert find_install(tmp_path) is None
    (root / "state.json").write_text(json.dumps(state))
    (root / "venv" / "bin" / "python").unlink()
    assert find_install(tmp_path) is None


# ---- the profile ---------------------------------------------------------------------------------


def template() -> str:
    return (FILES / PROFILE_TEMPLATE).read_text()


def test_the_profile_names_what_may_be_written_read_and_what_is_closed():
    text = fill_profile(
        template(),
        write=[Path("/data/coding"), Path("/Users/me/project")],
        read_only=[Path("/data/engine/coding")],
        closed=[Path("/Users"), Path("/data")],
    )
    assert "{{" not in text
    write = text.split("(allow file-write*")[1].split("; Reads")[0]
    assert '(subpath "/data/coding")' in write and '(subpath "/Users/me/project")' in write
    assert '(subpath "/data/engine/coding")' not in write  # its own packages are read only
    closed = text.split("(deny file-read*")[1].split("(allow file-read*")[0]
    assert '(subpath "/Users")' in closed and '(subpath "/data")' in closed
    opened = text.split("(allow file-read*")[1].split("(allow file-read-metadata")[0]
    for path in ("/data/coding", "/Users/me/project", "/data/engine/coding"):
        assert f'(subpath "{path}")' in opened
    way = text.split("(allow file-read-metadata")[1].split("; Network")[0]
    for folder in ("/Users", "/Users/me", "/data", "/data/engine"):
        assert f'(literal "{folder}")' in way
    assert '(subpath "/Users/me")' not in text  # the way there is a name, never the contents
    # the order decides: what is closed comes before what is opened again
    assert text.index("(deny file-read*") < text.index("(allow file-read*")
    assert text.index("(deny file-write*") < text.index("(allow file-write*")
    for rule in ("(deny network-outbound)", "(deny signal)", "(deny lsopen)",
                 "(deny appleevent-send)", "(deny job-creation)"):  # fmt: skip
        assert rule in text


def test_a_folder_name_that_could_end_a_rule_is_refused():
    for bad in ('/data/a"b', "/data/a\\b", "/data/a\nb"):
        with pytest.raises(CodingError, match="bad_path"):
            fill_profile(template(), write=[Path(bad)], read_only=[], closed=[])


def test_a_template_with_a_list_this_code_does_not_fill_is_refused():
    with pytest.raises(CodingError, match="bad_profile"):
        fill_profile(template() + "\n{{EXTRA}}\n", write=[], read_only=[], closed=[])


@pytest.mark.skipif(not ON_MAC, reason="needs the macOS sandbox")
async def test_the_profile_a_start_writes_holds_in_the_real_sandbox(tmp_path):
    """The real `sandbox-exec` with the profile of a real start, and a shell in place of the
    server: no model, no network, none of OpenHands' packages."""
    install(tmp_path)
    (tmp_path / "secrets.json").write_text("the app's own data")
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "note.txt").write_text("someone else's file")
    project = tmp_path.parent / f"{tmp_path.name}-project"
    project.mkdir()
    s = server(tmp_path)
    try:
        await s.ensure_running([project])
        profile = s.run_dir / "engine.sb"
        victim = sleeper()

        def inside(command: str) -> subprocess.CompletedProcess:
            return subprocess.run(
                [SANDBOX_EXEC, "-f", str(profile), "/bin/sh", "-c", command],
                capture_output=True, text=True, timeout=30, cwd=str(s.run_dir / "workspace"),
            )  # fmt: skip

        try:
            assert inside("echo ok > in.txt && cat in.txt").stdout.strip() == "ok"
            assert inside(f"echo ok > '{project}/in.txt' && cat '{project}/in.txt'").returncode == 0
            assert inside(f"ls '{tmp_path}/engine/coding/extensions'").returncode == 0
            for refused in (
                f"echo x > '{outside}/new.txt'",
                f"echo x > '{tmp_path}/engine/coding/venv/bin/new'",  # its own packages
                f"echo x > '{Path.home()}/wasify-c1a-unit-test.txt'",
                "echo x > /tmp/wasify-c1a-unit-test.txt",
                f"cat '{outside}/note.txt'",
                f"cat '{tmp_path}/secrets.json'",
                f"ls '{tmp_path}'",
                f"ls '{Path.home()}'",
                "ls /tmp",
                f"kill -TERM {victim.pid}",
                "/usr/bin/open -g -j -a Calculator",
            ):
                done = inside(refused)
                assert done.returncode != 0, f"{refused!r} was not refused: {done.stdout}"
            assert victim.poll() is None
            assert not (outside / "new.txt").exists()
            assert not (Path.home() / "wasify-c1a-unit-test.txt").exists()
            assert not there(Path("/tmp/wasify-c1a-unit-test.txt"))
        finally:
            victim.kill()
    finally:
        await s.close()


# ---- the start -----------------------------------------------------------------------------------


async def test_it_starts_on_a_free_port_with_a_key_only_the_engine_holds(tmp_path, monkeypatch):
    monkeypatch.setenv("SOMETHING_OF_THE_PERSONS", "secret-from-the-shell")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-for-the-sandbox")
    root = install(tmp_path)
    s = server(tmp_path)
    try:
        url = await s.ensure_running()
        assert url.startswith("http://127.0.0.1:")
        key = s.session_key
        assert key and len(key) >= 32
        # the key is on the supervisor's own calls, and nowhere a route or a file would show it
        assert (await s.request("GET", "/server_info")).json()["version"] == "1.62.0"
        async with httpx.AsyncClient() as http:
            assert (await http.get(f"{url}/server_info")).status_code == 401
        assert key not in json.dumps(s.state())
        for path in tmp_path.rglob("*"):
            if path.is_file():
                assert key not in path.read_text(errors="replace"), path

        with_ = await started_with(s)
        env = with_["env"]
        run = real(tmp_path) / "coding"
        assert env["HOME"] == str(run / "home")
        assert env["TMPDIR"] == str(run / "tmp")
        assert env["EXTENSIONS_PATH"] == str((root / "extensions" / "0.42.0").resolve())
        assert env["OH_CONVERSATIONS_PATH"].startswith(str(run / "state"))
        assert env["OH_CONVERSATION_WORKTREE_ROOT"].startswith(str(run / "state"))
        assert env["OH_ENABLE_BROWSER"] == "false" and env["OH_TELEMETRY_CONSENT"] == "false"
        assert env["PATH"].split(os.pathsep)[0] == str(root / "venv" / "bin")
        # a clean environment: nothing of the engine's own, no key of the person's
        assert "SOMETHING_OF_THE_PERSONS" not in env and "ANTHROPIC_API_KEY" not in env
        assert "VIRTUAL_ENV" not in env and "WASIFY_PARENT_FD" not in env
        assert with_["cwd"] == str(run / "state")
        assert with_["args"] == ["--host", "127.0.0.1", "--port", url.rsplit(":", 1)[1]]
        # its own session, so its own process group
        assert with_["sid"] == with_["pid"] == with_["pgid"] == s.pid
        assert with_["sid"] != os.getsid(0)
        # the terminal folder: ours, short enough for a socket, named to the server
        terminal = Path(env["TMUX_TMPDIR"])
        assert there(terminal) and terminal.name.startswith("wasify-coding-")
        assert len(str(terminal)) <= 51
        assert mode(terminal) == 0o700

        state = s.state()
        assert state["running"] and state["installed"] and state["port"] == int(url.rsplit(":")[2])
        assert state["version"] == "1.62.0" and state["extensions"] == "0.42.0"
        assert state["start_seconds"] is not None
        assert "started the coding" not in (tmp_path / "logs" / "coding-server.log").read_text()
        assert "fake agent server on" in (tmp_path / "logs" / "coding-server.log").read_text()
    finally:
        await s.close()


async def test_the_profile_of_a_start_closes_the_apps_own_data_and_opens_its_own_folders(tmp_path):
    install(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    s = server(tmp_path)
    try:
        await s.ensure_running([project])
        text = (s.run_dir / "engine.sb").read_text()
        data = real(tmp_path)
        closed = text.split("(deny file-read*")[1].split("(allow file-read*")[0]
        for folder in (*CLOSED, str(data)):
            assert f'(subpath "{folder}")' in closed
        write = text.split("(allow file-write*")[1].split("; Reads")[0]
        terminal = (await started_with(s))["env"]["TMUX_TMPDIR"]
        for folder in (data / "coding", data / "project", terminal):
            assert f'(subpath "{folder}")' in write
        assert f'(subpath "{data / "engine" / "coding"}")' not in write
        assert stat.S_IMODE((s.run_dir / "engine.sb").stat().st_mode) == 0o600
        assert s.state()["workspaces"] == [str(data / "project")]
    finally:
        await s.close()


async def test_every_start_has_a_new_key_and_the_same_folders_keep_the_running_server(tmp_path):
    install(tmp_path)
    s = server(tmp_path)
    try:
        url = await s.ensure_running()
        key, pid = s.session_key, s.pid
        assert key is not None and pid is not None
        assert await s.ensure_running() == url and s.pid == pid  # kept
        await s.ensure_running([tmp_path / "other"])  # other folders: a new sandbox
        assert s.pid != pid and s.session_key != key
        assert await wait_gone(pid)
        assert await s.stop() is True
        await s.ensure_running()
        assert s.session_key not in (key, None)
    finally:
        await s.close()


async def test_two_copies_of_the_app_run_side_by_side(tmp_path):
    install(tmp_path / "one")
    install(tmp_path / "two")
    a, b = server(tmp_path / "one"), server(tmp_path / "two")
    try:
        url_a, url_b = await asyncio.gather(a.ensure_running(), b.ensure_running())
        assert url_a != url_b and a.session_key != b.session_key
        assert (await a.request("GET", "/server_info")).status_code == 200
        assert (await b.request("GET", "/server_info")).status_code == 200
        # one's key does not open the other
        other = a.session_key or ""
        async with httpx.AsyncClient() as http:
            r = await http.get(f"{url_b}/server_info", headers={"X-Session-API-Key": other})
            assert r.status_code == 401
        await a.stop()
        assert (await b.request("GET", "/server_info")).status_code == 200
    finally:
        await a.close()
        await b.close()


async def test_it_waits_until_the_server_says_it_is_ready(tmp_path):
    install(tmp_path, FAKE_READY_AFTER="1.5")
    s = server(tmp_path)
    try:
        began = time.monotonic()
        await s.ensure_running()
        assert time.monotonic() - began >= 1.2
        assert s.state()["start_seconds"] >= 1.2
    finally:
        await s.close()


async def test_a_server_that_does_not_start_is_an_error_and_leaves_nothing(tmp_path):
    install(tmp_path, FAKE_EXIT="3")
    before = terminal_folders()
    s = server(tmp_path)
    try:
        with pytest.raises(CodingError, match="start_failed") as e:
            await s.ensure_running()
        assert "Repair" in e.value.message
        assert not s.running and s.url is None and s.session_key is None
        assert terminal_folders() == before
        assert "told to fail" in (tmp_path / "logs" / "coding-server.log").read_text()
    finally:
        await s.close()


async def test_it_does_not_start_before_it_is_set_up_or_without_its_profile(tmp_path):
    s = server(tmp_path)
    with pytest.raises(CodingError, match="not_installed"):
        await s.ensure_running()
    with pytest.raises(CodingError, match="not_running"):
        await s.request("GET", "/server_info")
    await s.close()
    install(tmp_path)
    before = terminal_folders()
    bare = CodingServer(tmp_path, None, sandbox_exec=None)  # a build without the profile
    with pytest.raises(CodingError, match="no_profile"):
        await bare.ensure_running()
    assert terminal_folders() == before
    await bare.close()


async def test_a_computer_without_the_sandbox_does_not_start_it(tmp_path, monkeypatch):
    install(tmp_path)
    before = terminal_folders()
    monkeypatch.setattr(coding_server, "supported", lambda: False)
    s = CodingServer(tmp_path, FILES)  # as the engine makes it: the sandbox is not optional
    assert s.state()["supported"] is False
    with pytest.raises(CodingError, match="unsupported"):
        await s.ensure_running()
    assert not s.running
    assert terminal_folders() == before
    await s.close()


# ---- the stop ------------------------------------------------------------------------------------


async def test_stop_reaches_everything_it_started_and_leaves_nothing_in_tmp(tmp_path):
    install(tmp_path, FAKE_CHILD="1")
    before = terminal_folders()
    s = server(tmp_path)
    try:
        await s.ensure_running()
        with_ = await started_with(s)
        pid, child = with_["pid"], with_["child"]
        # the child is in a session of its own, as a command of the real server is: the group
        # alone would not reach it
        assert os.getpgid(child) != os.getpgid(pid)
        terminal = Path(with_["env"]["TMUX_TMPDIR"])
        (Path(with_["env"]["TMPDIR"]) / "scratch.txt").write_text("x")
        assert await s.memory_bytes() > 0
        assert await s.stop() is True
        assert gone(pid) and await wait_gone(child, 3)
        assert not there(terminal)
        assert terminal_folders() == before
        assert not (s.run_dir / "tmp").exists()
        assert s.state()["running"] is False and s.state()["pid"] is None
        assert await s.stop() is False
        assert await s.memory_bytes() == 0
    finally:
        await s.close()


async def test_stop_now_ends_it_without_waiting(tmp_path):
    install(tmp_path, FAKE_CHILD="1")
    s = server(tmp_path)
    try:
        await s.ensure_running()
        with_ = await started_with(s)
        terminal = Path(with_["env"]["TMUX_TMPDIR"])
        assert s.stop_now() is True
        assert await wait_gone(with_["pid"], 3) and await wait_gone(with_["child"], 3)
        assert not there(terminal) and not s.running
        assert s.stop_now() is False
    finally:
        await s.close()


async def test_a_terminal_folder_left_by_a_run_that_was_not_stopped_is_removed(tmp_path):
    install(tmp_path)
    left = real("/tmp") / "wasify-coding-leftover-test"
    left.mkdir(exist_ok=True)
    precious = tmp_path / "precious"
    precious.mkdir()
    s = server(tmp_path)
    try:
        s.run_dir.mkdir(parents=True)
        (s.run_dir / "terminal").write_text(str(left))
        await s.ensure_running()
        assert not left.exists()
        await s.stop()
        # a note that names any other folder removes nothing
        (s.run_dir / "terminal").write_text(str(precious))
        await s.ensure_running()
        assert precious.is_dir()
    finally:
        await s.close()
        if left.exists():
            left.rmdir()


GUARD_RUNNER = """
import asyncio, sys
from pathlib import Path
from wasifyai_api.coding_server import CodingServer

async def main():
    s = CodingServer(Path(sys.argv[1]), Path(sys.argv[2]), sandbox_exec=None)
    await s.ensure_running()
    r = await s.request("GET", "/fake/env")
    print(r.json()["pid"], r.json()["env"]["TMUX_TMPDIR"], flush=True)
    await asyncio.sleep(600)

asyncio.run(main())
"""


async def test_the_server_ends_itself_when_the_engine_goes_away_without_stopping_it(tmp_path):
    """The engine is killed outright (a crash, a forced quit): nothing calls stop. The server
    watches a pipe the engine held and ends its own group."""
    install(tmp_path)
    engine = await asyncio.create_subprocess_exec(
        sys.executable, "-c", GUARD_RUNNER, str(tmp_path), str(FILES),
        stdout=asyncio.subprocess.PIPE,
    )  # fmt: skip
    try:
        assert engine.stdout is not None
        line = (await asyncio.wait_for(engine.stdout.readline(), 30)).decode().split()
        pid, terminal = int(line[0]), Path(line[1])
        assert not gone(pid) and there(terminal)
        engine.send_signal(signal.SIGKILL)
        await engine.wait()
        assert await wait_gone(pid, 10), "the server outlived the engine"
        assert not there(terminal)
    finally:
        if engine.returncode is None:
            engine.kill()


async def test_the_log_is_kept_to_one_earlier_file(tmp_path, monkeypatch):
    install(tmp_path)
    monkeypatch.setattr(coding_server, "LOG_KEEP_BYTES", 10)
    s = server(tmp_path)
    try:
        await s.ensure_running()
        await s.stop()
        await s.ensure_running()
        logs = sorted(p.name for p in (tmp_path / "logs").iterdir())
        assert logs == ["coding-server.log", "coding-server.log.1"]
    finally:
        await s.close()


# ---- the routes ----------------------------------------------------------------------------------


def app_with(s: CodingServer | None) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.services = ApiServices(coding_server=s)
    app.dependency_overrides[get_identity] = lambda: Identity("local", "u1", "user")
    return TestClient(app)


async def test_the_routes_say_where_it_stands_and_stop_it_without_the_key(tmp_path):
    install(tmp_path)
    s = server(tmp_path)
    app = FastAPI()
    app.include_router(router)
    app.state.services = ApiServices(coding_server=s)
    app.dependency_overrides[get_identity] = lambda: Identity("local", "u1", "user")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://engine.test"
    ) as client:
        first = (await client.get("/desktop/coding-engine")).json()
        assert first["installed"] is True and first["running"] is False
        assert first["memory_bytes"] == 0
        await s.ensure_running()  # as the coding product does when a session needs it
        body = (await client.get("/desktop/coding-engine")).json()
        assert body["running"] is True and body["port"] and body["memory_bytes"] > 0
        assert body["workspaces"] == [] and body["read_only"] == []
        assert s.session_key is not None and s.session_key not in json.dumps(body)
        assert (await client.post("/desktop/coding-engine/stop")).json() == {"stopped": True}
        assert (await client.get("/desktop/coding-engine")).json()["running"] is False
        assert (await client.post("/desktop/coding-engine/stop")).json() == {"stopped": False}
    await s.close()


def test_there_is_no_route_that_starts_it_and_none_where_it_is_not_part_of_the_engine(tmp_path):
    with app_with(server(tmp_path)) as client:
        # the coding product starts it, with the folders a session may reach
        assert client.post("/desktop/coding-engine/start").status_code == 404
    with app_with(None) as client:
        assert client.get("/desktop/coding-engine").status_code == 404
        assert client.post("/desktop/coding-engine/stop").status_code == 404
