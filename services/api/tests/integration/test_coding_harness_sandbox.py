"""Hostile tests against a harness's own Agent Server inside its sandbox (ADR-0107, ADR-0102's
amendment of 2026-11-15; stage H1). Opt-in with the rest of `make test-coding`.

A harness's server is opened further than the Wasify AI one, for one program: its own sign-in
folders in the person's home, the keychain for reading, the installed programs for reading, and
the proxy under the harness's own name, which reaches the provider's hosts only. These tests say
what that opening must not let through. The home folder is a throwaway one with pretend sign-in
folders and pretend private files, so nothing of the person's is read or written.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from wasifyai_api.coding_harness import harness_hosts
from wasifyai_api.coding_proxy import InstallProxy
from wasifyai_api.coding_server import SANDBOX_EXEC, CodingServer, find_install

REPO = Path(__file__).resolve().parents[4]
FILES = REPO / "services" / "coding-engine"
APP_DATA = Path(
    os.environ.get("CODING_E2E_DATA")
    or Path.home() / "Library/Application Support/ai.wasifyai.desktop"
)

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("CODING_E2E") != "1", reason="opt-in: CODING_E2E=1 (make test-coding)"
    ),
    pytest.mark.skipif(
        sys.platform != "darwin" or not Path(SANDBOX_EXEC).is_file(),
        reason="the coding engine's sandbox is the Mac's",
    ),
]
pytestmark.append(pytest.mark.asyncio(loop_scope="module"))


class Box:
    def __init__(self, server: CodingServer, home: Path, data: Path, project: Path):
        self.server, self.home, self.data, self.project = server, home, data, project

    async def sh(self, command: str) -> tuple[int, str]:
        r = await self.server.request(
            "POST", "/api/bash/execute_bash_command",
            json={"command": command, "cwd": str(self.project), "timeout": 40}, timeout=90,
        )  # fmt: skip
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        return int(body.get("exit_code") or 0), (body.get("stdout") or "") + (
            body.get("stderr") or ""
        )

    async def works(self, command: str) -> str:
        code, out = await self.sh(command)
        assert code == 0, f"refused: {command!r}: {out}"
        return out

    async def refused(self, command: str) -> str:
        _, out = await self.sh(f"{command}; echo exit=$?")
        said = re.findall(r"^exit=(\d+)$", out, re.M)
        assert said and said[-1] != "0", f"not refused: {command!r}: {out}"
        return out


def _real(path: Path) -> Path:
    return Path(os.path.realpath(path))


@pytest.fixture(scope="module")
async def box(tmp_path_factory):
    if find_install(APP_DATA) is None:
        pytest.fail(f"The coding engine is not set up in {APP_DATA}.")
    data = tmp_path_factory.mktemp("harness-data")
    (data / "engine").mkdir()
    (data / "engine" / "coding").symlink_to(APP_DATA / "engine" / "coding")
    (data / "secrets.json").write_text("the app's own keys would be here")
    home = _real(tmp_path_factory.mktemp("home"))
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").write_text("{}")
    (home / ".claude.json").write_text("{}")
    (home / ".codex").mkdir()
    (home / ".codex" / "auth.json").write_text("another program's sign-in")
    (home / "Documents").mkdir()
    (home / "Documents" / "private.txt").write_text("the person's own")
    (home / ".ssh").mkdir()
    (home / ".ssh" / "id_ed25519").write_text("a key")
    project = _real(tmp_path_factory.mktemp("project"))
    (project / "README.md").write_text("# a project\n")
    main = CodingServer(data, FILES, proxy=InstallProxy(harness_hosts=harness_hosts()), home=home)
    server = main.for_harness("claude-code")
    await server.ensure_running([project])
    try:
        yield Box(server, home, data, project)
    finally:
        await main.close()


async def test_the_programs_own_sign_in_can_be_read_and_written(box):
    await box.works(f"cat {box.home}/.claude/settings.json")
    await box.works(f"echo x > {box.home}/.claude/made-by-the-program")
    await box.works(f"cat {box.home}/.claude.json && echo '{{}}' > {box.home}/.claude.json")
    await box.works(f"echo x > {box.home}/.claude.json.backup")
    await box.works(f"echo x > {box.project}/written")


@pytest.mark.parametrize(
    "target",
    ["Documents/private.txt", ".ssh/id_ed25519", ".codex/auth.json"],
)
async def test_the_rest_of_the_home_folder_cannot_be_read(box, target):
    out = await box.refused(f"cat {box.home}/{target}")
    assert "the person's own" not in out and "a key" not in out and "another program" not in out


@pytest.mark.parametrize(
    "target", ["new-file", "Documents/new", ".codex/new", ".claude-other", ".bashrc"]
)
async def test_nothing_else_in_the_home_folder_can_be_written(box, target):
    await box.refused(f"echo x > {box.home}/{target}")
    assert not (box.home / target).exists()


async def test_the_apps_own_data_cannot_be_read(box):
    out = await box.refused(f"cat {box.data}/secrets.json")
    assert "keys would be here" not in out


async def test_the_internet_is_refused_and_the_proxy_lets_through_only_the_provider(box):
    # straight out: refused by the sandbox
    await box.refused(
        "env -u HTTPS_PROXY -u https_proxy -u ALL_PROXY curl -sS -m 10 https://example.com"
    )
    # through the proxy under the harness's name: another host is refused there
    out = await box.refused("curl -sS -m 10 -o /dev/null https://example.com")
    assert "403" in out or "not_the_provider" in out or "CONNECT" in out
    await box.refused("curl -sS -m 10 -o /dev/null https://pypi.org/simple/")
    # the provider is reached (nothing of the person's is sent: no sign-in is given to curl)
    out = await box.works(
        "curl -sS -m 20 -o /dev/null -w '%{http_code}' https://api.anthropic.com/v1/models"
    )
    assert out.strip()[-3:] in ("401", "403", "404", "405")


def _sleeper() -> subprocess.Popen:
    return subprocess.Popen(["/bin/sleep", "120"])


async def test_a_process_outside_cannot_be_signalled(box):
    outside = _sleeper()
    try:
        await box.refused(f"kill -0 {outside.pid}")
        assert outside.poll() is None
    finally:
        outside.kill()
