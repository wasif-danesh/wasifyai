"""The agent programs a coding session can run on with the person's own plan (ADR-0107; stage H1):
the ACP adapters OpenHands pins, which carry Claude Code and Codex, as an optional part.

    1 check     a Mac with the coding engine and Node set up, the build carries the lock (its
                SHA-256 checked), there is room
    2 packages  `npm ci` from the lock into `<app data>/engine/harness/<version>/`: every package
                is checked by npm against its integrity hash in the lock, and no install script
                is run
    3 verify    each program answers `--version`; then `engine/harness/state.json`

Nothing is fetched while a session runs: the adapters are started by our Node from this folder,
never through `npx` (ADR-0107, decision 4). The program the person installed themselves is not
used yet; this part's copy is.
"""

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk.installer import (
    Installer,
    InstallError,
    Runner,
    Step,
    check_disk,
    clean_env,
    folder_bytes,
    read_state,
    run_command,
    sha256_of,
    status_installed,
    status_missing,
    status_unsupported,
    write_state,
)

from wasifyai_api.coding_harness import HARNESSES, find_harness_install
from wasifyai_api.components.manifest import Manifest, Pins
from wasifyai_api.components.node import find_node

ID = "harness"
TITLE = "Agent programs (Claude Code, Codex)"
STEPS = (
    Step("check", "Checking this computer"),
    Step("packages", "Getting the agent programs"),
    Step("verify", "Checking that they start"),
)
UNSUPPORTED = "The agent programs are not available for this computer yet."
NEEDS = "Set up the coding engine and Node for coding projects first."


class HarnessComponent:
    id = ID
    title = TITLE

    def __init__(
        self,
        data_dir: Path,
        manifest: Manifest,
        files: Path | None,
        supported: bool,
        run: Runner = run_command,
    ):
        """`files` is the build's `services/coding-engine` folder; `supported` is whether this
        computer has the coding engine's sandbox."""
        self.data_dir = data_dir
        self.root = data_dir / "engine" / "harness"
        self.pins: Pins | None = manifest.get(ID)
        self.files = files
        self.supported = supported
        self.installer = Installer(ID, STEPS, data_dir / "logs")
        self._run = run

    # ---- what is there ---------------------------------------------------------------------

    def offered(self) -> Pins | None:
        p = self.pins
        if p is None or not p.extra.get("lock") or not self.supported:
            return None
        return p

    def _file(self, p: Pins, key: str) -> Path | None:
        """A file of the build named by the pins, when its SHA-256 is the pinned one."""
        name = str(p.extra.get(key) or "")
        if self.files is None or not name:
            return None
        path = (self.files / name).resolve()
        if self.files.resolve() not in path.parents or not path.is_file():
            return None
        return path if sha256_of(path) == p.extra.get(f"{key}_sha256") else None

    def installed(self) -> dict[str, Any] | None:
        p = self.offered()
        state = read_state(self.root / "state.json")
        if p is None or state is None:
            return None
        if (
            state.get("schema") != 1
            or state.get("version") != p.version
            or state.get("lock_sha256") != p.extra.get("lock_sha256")
            or find_harness_install(self.data_dir) is None
        ):
            return None
        return state

    def needs_bytes(self, p: Pins) -> int:
        return int(p.extra.get("install_bytes") or p.min_free_bytes)

    def status(self) -> dict[str, Any]:
        if (now := self.installer.current()) is not None:
            return now
        p = self.offered()
        if p is None:
            return status_unsupported(UNSUPPORTED)
        if (state := self.installed()) is not None:
            return status_installed(str(state["version"]))
        return status_missing(self.needs_bytes(p))

    # ---- changing it -----------------------------------------------------------------------

    def install(self, confirm_bytes: int | None, repair: bool = False) -> None:
        p = self.offered()
        if p is None:
            raise InstallError(UNSUPPORTED)
        if not repair and self.installed() is not None:
            raise InstallError("The agent programs are already set up.")
        if confirm_bytes is not None and confirm_bytes != self.needs_bytes(p):
            raise InstallError("The size shown is out of date. Look at it again.")
        self.installer.start(lambda inst: self._steps(inst, p), self.status)

    def cancel(self) -> bool:
        return self.installer.cancel()

    async def wait(self) -> None:
        await self.installer.wait()

    def uninstall(self) -> int:
        if self.installer.running:
            raise InstallError("The agent programs are being set up. Stop it first.")
        freed = folder_bytes(self.root)
        shutil.rmtree(self.root, ignore_errors=True)
        self.installer.failed = None
        return freed

    async def _steps(self, inst: Installer, p: Pins) -> None:
        inst.at("check")
        lock = await asyncio.to_thread(self._file, p, "lock")
        manifest = await asyncio.to_thread(self._file, p, "manifest")
        if lock is None or manifest is None:
            raise InstallError(
                "This build carries no package list for the agent programs. Build the engine "
                "files again with scripts/build-engine-bundle.sh.",
                "check",
            )
        node = find_node(self.data_dir)
        if node is None or not (self.data_dir / "engine" / "coding" / "state.json").is_file():
            raise InstallError(NEEDS, "check")
        await asyncio.to_thread(
            check_disk, self.root, p.min_free_bytes, "The agent programs", "check"
        )
        (self.root / "state.json").unlink(missing_ok=True)
        folder = self.root / p.version
        await asyncio.to_thread(shutil.rmtree, folder, True)
        folder.mkdir(parents=True)
        shutil.copyfile(manifest, folder / "package.json")
        shutil.copyfile(lock, folder / "package-lock.json")

        inst.at("packages")
        npm = node / "npm"
        env = clean_env(
            extra={"PATH": f"{node}:/usr/bin:/bin", "npm_config_update_notifier": "false"}
        )
        code, out = await self._run(
            [str(npm), "ci", "--ignore-scripts", "--omit=dev", "--no-audit", "--no-fund",
             "--prefer-offline"],
            env, folder,
        )  # fmt: skip
        inst.line(out.strip()[-300:])
        if code != 0:
            raise InstallError(
                "The agent programs could not be installed. Are you online?", "packages"
            )

        inst.at("verify")
        adapters: dict[str, str] = {}
        for harness_id, package in dict(p.extra.get("adapters") or {}).items():
            harness = HARNESSES.get(str(harness_id))
            if harness is None:
                continue
            adapters[harness.id] = await asyncio.to_thread(_entry, folder, str(package))
            program = folder / "node_modules" / Path(*harness.program)
            code, out = await self._run([str(program), "--version"], clean_env(), folder)
            said = out.strip().splitlines()[-1] if out.strip() else ""
            inst.line(f"{harness.title}: {said[-120:]}")
            if code != 0 or not said:
                raise InstallError(f"{harness.title} does not start.", "verify")
        write_state(
            self.root / "state.json",
            {
                "schema": 1, "version": p.version, "dir": p.version,
                "lock_sha256": str(p.extra.get("lock_sha256") or ""), "adapters": adapters,
            },
        )  # fmt: skip


def _entry(folder: Path, package: str) -> str:
    """The adapter's program file, from its `package.json`, relative to `folder`."""
    pkg = folder / "node_modules" / package
    data = json.loads((pkg / "package.json").read_text())
    bin_ = data.get("bin")
    entry = next(iter(bin_.values())) if isinstance(bin_, dict) else bin_
    if not isinstance(entry, str):
        raise InstallError(f"{package} names no program.", "verify")
    path = (pkg / entry).resolve()
    if folder.resolve() not in path.parents or not path.is_file():
        raise InstallError(f"{package} names no program.", "verify")
    return str(path.relative_to(folder.resolve()))
