"""Hostile tests against the real Agent Server inside its sandbox (ADR-0102, decision 3; stage C1a
of docs/v2-coding-agent-start-plan.md, section 8). Opt-in, like `make test-comfyui`:

    make test-coding            # CODING_E2E=1 pytest .../integration/test_coding_sandbox.py

They need the coding engine set up by the app (Settings, Optional parts) on a Mac. Its files are
read from the app's data folder (`CODING_E2E_DATA`, by default
`~/Library/Application Support/ai.wasifyai.desktop`); the server itself is started by this
engine's own supervisor on a throwaway data folder, so nothing of the person's is written and a
running app is not disturbed. No model is used: every command goes through the server's own
command endpoint, which is how the agent's commands run.

Each "refused" case names something that must stay out of reach of the server and of everything
it starts. What must keep working is tested too, because a sandbox that refuses everything
proves nothing.
"""

import http.server
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from wasifyai_api.coding_server import SANDBOX_EXEC, CodingServer, find_install

REPO = Path(__file__).resolve().parents[4]
FILES = REPO / "services" / "coding-engine"
HOME = Path.home()
APP_DATA = Path(
    os.environ.get("CODING_E2E_DATA") or HOME / "Library/Application Support/ai.wasifyai.desktop"
)
MARK = "wasify-c1a-hostile"  # in the name of everything a test tries to make outside

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("CODING_E2E") != "1", reason="opt-in: CODING_E2E=1 (make test-coding)"
    ),
    pytest.mark.skipif(
        sys.platform != "darwin" or not Path(SANDBOX_EXEC).is_file(),
        reason="the coding engine's sandbox is the Mac's",
    ),
]


class Box:
    """A running, sandboxed server and the folders around it."""

    def __init__(self, server: CodingServer, data: Path, project: Path, loopback: int):
        self.server, self.data, self.project, self.loopback = server, data, project, loopback
        self.workspace = server.run_dir / "workspace"

    async def sh(self, command: str, cwd: Path | None = None) -> tuple[int, str]:
        """Run a command the way the agent's commands run; its exit code and what it printed."""
        r = await self.server.request(
            "POST", "/api/bash/execute_bash_command",
            json={"command": command, "cwd": str(cwd or self.workspace), "timeout": 40},
            timeout=90,
        )  # fmt: skip
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        return int(body.get("exit_code") or 0), (body.get("stdout") or "") + (
            body.get("stderr") or ""
        )

    async def refused(self, command: str) -> str:
        """The command must fail. What it printed, to check the reason."""
        _, out = await self.sh(f"{command}; echo exit=$?")
        said = re.findall(r"^exit=(\d+)$", out, re.M)
        assert said and said[-1] != "0", f"not refused: {command!r}: {out}"
        return out


@pytest.fixture(scope="module")
async def box(tmp_path_factory):
    if find_install(APP_DATA) is None:
        pytest.fail(
            f"The coding engine is not set up in {APP_DATA}. Set it up in the app (Settings, "
            "Optional parts), or point CODING_E2E_DATA at a data folder that has it."
        )
    data = tmp_path_factory.mktemp("coding-data")
    (data / "engine").mkdir()
    (data / "engine" / "coding").symlink_to(APP_DATA / "engine" / "coding")
    (data / "secrets.json").write_text("the app's own keys would be here")
    project = tmp_path_factory.mktemp("project")  # a folder the person chose as a workspace
    (project / "README.md").write_text("# a project\n")

    class Hello(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("content-length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format: str, *args: object) -> None:
            pass

    local = http.server.HTTPServer(("127.0.0.1", 0), Hello)  # stands for the model gateway
    threading.Thread(target=local.serve_forever, daemon=True).start()
    server = CodingServer(data, FILES)
    await server.ensure_running([project])
    try:
        yield Box(server, data, project, local.server_address[1])
    finally:
        await server.close()
        local.shutdown()
        for left in _made_outside():
            left.unlink()


def _sleeper() -> subprocess.Popen:
    return subprocess.Popen(["/bin/sleep", "120"])


def _made_outside() -> list[Path]:
    places = (HOME, HOME / "Desktop", HOME / "Documents", Path("/tmp"), REPO)
    return [p for place in places if place.is_dir() for p in place.glob(f"{MARK}*")]


# The session scope of the server needs one event loop for the module.
pytestmark.append(pytest.mark.asyncio(loop_scope="module"))


# ---- what must work ------------------------------------------------------------------------------


async def test_it_runs_the_pinned_version_inside_the_sandbox(box):
    info = (await box.server.request("GET", "/server_info")).json()
    assert info["version"] == (FILES / "VERSION").read_text().strip()
    assert box.server.state()["running"] is True
    code, out = await box.sh("echo $HOME; echo $TMPDIR")
    home, tmp = out.strip().splitlines()[:2]
    assert Path(home) == box.server.run_dir.resolve() / "home"
    assert Path(tmp) == box.server.run_dir.resolve() / "tmp"


async def test_a_write_inside_the_workspace_works(box):
    code, out = await box.sh("echo inside > note.txt && cat note.txt")
    assert (code, out.strip()) == (0, "inside")
    assert (box.workspace / "note.txt").read_text().strip() == "inside"


async def test_a_workspace_the_person_chose_can_be_read_and_written(box):
    code, out = await box.sh("cat README.md && echo changed >> README.md", cwd=box.project)
    assert code == 0 and "# a project" in out
    assert "changed" in (box.project / "README.md").read_text()


async def test_git_works_in_the_workspace_without_complaint(box):
    code, out = await box.sh(
        "git init -q . && git add -A && git -c user.name=t -c user.email=t@example.invalid "
        "commit -qm first && git log --oneline | wc -l"
    )
    assert code == 0 and out.strip().splitlines()[-1].strip() == "1"
    assert "xcrun" not in out and "error" not in out.lower()


async def test_python_runs_and_its_temp_files_stay_in_its_own_state(box):
    code, out = await box.sh(
        'python3 -c "import tempfile; f = tempfile.NamedTemporaryFile(delete=False); print(f.name)"'
    )
    assert code == 0
    assert Path(out.strip()).parent == box.server.run_dir.resolve() / "tmp"


async def test_this_computer_is_reachable_which_the_model_gateway_will_need(box):
    code, out = await box.sh(
        f"curl -s -m 8 -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{box.loopback}/"
    )
    assert out.strip() == "200"


async def test_the_pinned_catalogue_is_what_the_server_offers_with_the_network_closed(box):
    r = await box.server.request("GET", "/api/skills/catalog", timeout=60)
    assert r.status_code == 200
    skills = r.json()["skills"]
    found = find_install(APP_DATA)
    assert found is not None
    on_disk = {p.parent.name for p in (found.extensions / "skills").glob("*/SKILL.md")}
    assert len(skills) > 0 and {s["name"] for s in skills} <= on_disk
    # nothing was copied from the internet into its home
    assert not (box.server.run_dir / "home" / ".openhands" / "skills-cache").exists()


# ---- what must be refused: writes ----------------------------------------------------------------


@pytest.mark.parametrize(
    "target",
    [HOME / f"{MARK}.txt", HOME / "Desktop" / f"{MARK}.txt", Path("/tmp") / f"{MARK}.txt",
     REPO / f"{MARK}.txt"],
    ids=["the home folder", "the Desktop", "/tmp", "this repository"],
)  # fmt: skip
async def test_a_write_outside_is_refused(box, target):
    out = await box.refused(f"echo x > '{target}'")
    assert "Operation not permitted" in out
    assert not target.exists()


async def test_a_change_to_a_file_of_this_repository_is_refused(box):
    readme = REPO / "README.md"
    before = readme.read_bytes()
    await box.refused(f"echo x >> '{readme}'")
    await box.refused(f"rm -f '{readme}'")
    assert readme.read_bytes() == before


async def test_a_write_through_python_is_refused(box):
    target = HOME / f"{MARK}-python.txt"
    out = await box.refused(f"python3 -c \"open('{target}', 'w').write('x')\"")
    assert "PermissionError" in out and not target.exists()


async def test_a_write_through_a_child_of_a_child_is_refused(box):
    target = HOME / f"{MARK}-nested.txt"
    await box.refused(f"bash -c 'sh -c \"echo x > {target}\"'")
    # and through a child that left the group and the session of its parent
    await box.sh(
        "python3 -c \"import os, subprocess; subprocess.Popen(['/bin/sh', '-c', "
        f"'echo x > {target}'], start_new_session=True).wait()\""
    )
    assert not target.exists()


async def test_other_ways_to_copy_a_file_out_are_refused(box):
    target = HOME / "Documents" / f"{MARK}-copy.txt"
    await box.sh("echo secret > mine.txt")
    for way in (f"cp mine.txt '{target}'", f"tee '{target}' < mine.txt", f"mv mine.txt '{target}'",
                f"ln -s {box.workspace}/mine.txt '{target}'"):  # fmt: skip
        await box.refused(way)
    assert not target.exists() and not target.is_symlink()


async def test_its_own_packages_and_its_profile_cannot_be_changed_from_inside(box):
    found = find_install(box.data)
    assert found is not None
    real = (APP_DATA / "engine" / "coding").resolve()
    await box.refused(f"echo x > '{real}/venv/{MARK}.txt'")
    await box.refused(f"echo x >> '{real}/state.json'")
    assert not (real / "venv" / f"{MARK}.txt").exists()


# ---- what must be refused: reads -----------------------------------------------------------------


@pytest.mark.parametrize(
    "folder",
    [HOME / ".ssh", HOME / "Library" / "Application Support", HOME, HOME / "Desktop",
     HOME / "Library" / "Keychains", Path("/tmp"), Path("/Volumes")],
    ids=["~/.ssh", "~/Library/Application Support", "the home folder", "the Desktop",
         "the keychains", "/tmp", "other disks"],
)  # fmt: skip
async def test_a_listing_outside_is_refused(box, folder):
    out = await box.refused(f"ls '{folder}'")
    assert "Operation not permitted" in out


async def test_an_ordinary_file_elsewhere_in_the_home_folder_cannot_be_read(box):
    """The spike's profile allowed this; ADR-0102 decision 3 closes it."""
    out = await box.refused(f"head -c 40 '{REPO / 'README.md'}'")
    assert "Operation not permitted" in out
    out = await box.refused(f"python3 -c \"print(open('{REPO / 'README.md'}').read()[:40])\"")
    assert "PermissionError" in out


async def test_the_apps_own_data_cannot_be_read(box):
    out = await box.refused(f"cat '{box.data / 'secrets.json'}'")
    assert "the app's own keys" not in out
    await box.refused(f"ls '{box.data}'")
    await box.refused(f"ls '{APP_DATA}'")
    await box.refused(f"cat '{APP_DATA}/engine.json'")


# ---- what must be refused: the network and other programs ----------------------------------------


async def test_the_internet_is_refused(box):
    code, out = await box.sh("curl -s -m 8 -o /dev/null -w '%{http_code}' https://example.com")
    assert code != 0 and out.strip() == "000"
    code, out = await box.sh(
        'python3 -c "import urllib.request; '
        "print(urllib.request.urlopen('https://example.com', timeout=8).status)\" 2>&1 | tail -1"
    )
    assert "200" not in out and "Operation not permitted" in out
    # by number too, so no name has to be looked up
    code, out = await box.sh("curl -s -m 8 -o /dev/null -w '%{http_code}' http://1.1.1.1/")
    assert code != 0 and out.strip() == "000"


async def test_a_process_outside_cannot_be_signalled(box):
    victim = _sleeper()
    try:
        out = await box.refused(f"kill -TERM {victim.pid}")
        assert "Operation not permitted" in out
        await box.refused(f"kill -KILL {os.getpid()}")
        assert victim.poll() is None
    finally:
        victim.kill()


async def test_no_app_is_opened_and_no_other_app_is_told_what_to_do(box):
    """`open` hands a file to a program outside the sandbox, which would then run it with the
    person's own rights."""
    await box.sh(f"printf '#!/bin/sh\\necho x > {HOME}/{MARK}-opened.txt\\n' > run.command")
    await box.sh("chmod +x run.command")
    await box.refused("/usr/bin/open -g -j run.command")
    await box.refused("/usr/bin/open -g -j -a Calculator")
    await box.refused(
        "/usr/bin/osascript -e 'tell application \"Finder\" to get name of startup disk'"
    )
    assert not (HOME / f"{MARK}-opened.txt").exists()


async def test_programs_with_special_rights_do_not_start(box):
    """Not a rule of ours: macOS starts no program with special rights inside any sandbox. The
    app has to say so and offer its own list of processes (ADR-0102, decision 9)."""
    for program in ("ps", "sudo -n true"):
        out = await box.refused(program)
        assert "not permitted" in out.lower()
    code, out = await box.sh("pgrep -x zsh >/dev/null; echo ran")
    assert "ran" in out


# ---- afterwards ----------------------------------------------------------------------------------


async def test_nothing_was_made_outside(box):
    assert _made_outside() == []
