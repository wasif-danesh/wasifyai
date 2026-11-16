"""The agent programs as an optional part (ADR-0107; stage H1): offered where the coding engine is,
installed with `npm ci` from the pinned lock (no install script run), checked by starting each
program, and found by the sessions from its state file. `npm` and the programs are pretended."""

import hashlib
import json
from pathlib import Path

import pytest
from wasifyai_api.coding_harness import HARNESSES, find_harness_install
from wasifyai_api.components.harness import HarnessComponent
from wasifyai_api.components.manifest import Manifest, Pins, load_manifest

FILES = Path(__file__).resolve().parents[2] / "coding-engine"


def pins(files: Path) -> Pins:
    lock, manifest = files / "harness/package-lock.json", files / "harness/package.json"
    return Pins(
        "harness", "Agent programs", "0.99.1+2.2.2", "registry.npmjs.org", 0, None,
        {
            "lock": "harness/package-lock.json",
            "lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
            "manifest": "harness/package.json",
            "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            "install_bytes": 694400000,
            "adapters": {"claude-code": "@agentclientprotocol/claude-agent-acp",
                         "codex": "@agentclientprotocol/codex-acp"},
        },
    )  # fmt: skip


def ready(data: Path) -> None:
    """The coding engine and Node, set up (as far as this part looks)."""
    (data / "engine" / "coding").mkdir(parents=True)
    (data / "engine" / "coding" / "state.json").write_text("{}")
    node = data / "engine" / "node" / "24.22.3" / "bin"
    node.mkdir(parents=True)
    (node / "node").write_text("")
    (node / "npm").write_text("")
    (data / "engine" / "node" / "state.json").write_text(json.dumps({"bin": "24.22.3/bin"}))


class Npm:
    """`npm ci` lays out the adapters and the programs; each program says its version."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def __call__(self, args, env, cwd):
        self.calls.append(list(args))
        if args[1] == "ci":
            for h in HARNESSES.values():
                pkg = Path(cwd) / "node_modules" / h.package
                (pkg / "dist").mkdir(parents=True)
                (pkg / "dist" / "index.js").write_text("")
                (pkg / "package.json").write_text(json.dumps({"bin": {h.id: "dist/index.js"}}))
                program = Path(cwd) / "node_modules" / Path(*h.program)
                program.parent.mkdir(parents=True, exist_ok=True)
                program.write_text("")
            return 0, "added 125 packages"
        return 0, "2.1.312 (Claude Code)"


def test_the_part_is_pinned_for_the_mac_with_the_lock_this_build_carries():
    p = load_manifest("darwin-arm64").get("harness")
    assert p is not None
    lock = FILES / str(p.extra["lock"])
    assert hashlib.sha256(lock.read_bytes()).hexdigest() == p.extra["lock_sha256"]
    manifest = FILES / str(p.extra["manifest"])
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == p.extra["manifest_sha256"]
    wanted = json.loads(manifest.read_text())["dependencies"]
    # pinned exactly, and each adapter the part names is one the lock installs
    assert all(v[0].isdigit() for v in wanted.values())
    assert set(p.extra["adapters"].values()) == set(wanted)
    packages = json.loads(lock.read_text())["packages"]
    assert all("integrity" in v for k, v in packages.items() if k and not v.get("link"))


async def test_it_installs_from_the_lock_with_no_install_script_and_checks_each_program(tmp_path):
    ready(tmp_path)
    npm = Npm()
    part = HarnessComponent(tmp_path, Manifest("x", "3.12", {"harness": pins(FILES)}), FILES,
                            True, run=npm)  # fmt: skip
    assert part.status() == {"state": "not_installed", "needs_bytes": 694400000}
    part.install(694400000)
    await part.wait()
    assert part.status()["state"] == "installed", part.status()
    ci = npm.calls[0]
    assert ci[1] == "ci" and "--ignore-scripts" in ci and "--omit=dev" in ci
    assert len(npm.calls) == 3  # npm ci, then each program's --version
    found = find_harness_install(tmp_path)
    assert found is not None
    assert set(found.adapters) == {"claude-code", "codex"}
    adapter = found.adapter(HARNESSES["codex"])
    assert adapter is not None and adapter.is_file()
    assert part.uninstall() >= 0 and find_harness_install(tmp_path) is None


async def test_it_waits_for_the_coding_engine_and_node(tmp_path):
    part = HarnessComponent(tmp_path, Manifest("x", "3.12", {"harness": pins(FILES)}), FILES,
                            True, run=Npm())  # fmt: skip
    part.install(None)
    await part.wait()
    status = part.status()
    assert status["state"] == "failed" and "Node" in status["message"]


def test_it_is_not_offered_without_the_sandbox_or_the_pins(tmp_path):
    no_sandbox = HarnessComponent(tmp_path, Manifest("x", "", {"harness": pins(FILES)}), FILES,
                                  False)  # fmt: skip
    assert no_sandbox.status()["state"] == "unsupported"
    assert HarnessComponent(tmp_path, Manifest("x", "", {}), FILES, True).status()["state"] == (
        "unsupported"
    )


async def test_a_changed_lock_is_refused(tmp_path):
    ready(tmp_path)
    files = tmp_path / "files" / "harness"
    files.mkdir(parents=True)
    for name in ("package.json", "package-lock.json"):
        (files / name).write_bytes((FILES / "harness" / name).read_bytes())
    p = pins(FILES)
    (files / "package-lock.json").write_text("{}")
    part = HarnessComponent(tmp_path, Manifest("x", "", {"harness": p}), files.parent, True,
                            run=Npm())  # fmt: skip
    part.install(None)
    await part.wait()
    assert part.status()["state"] == "failed"
    with pytest.raises(Exception):  # noqa: B017  (the part says so in its own words)
        part.install(1)
