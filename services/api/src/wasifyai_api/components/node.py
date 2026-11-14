"""Node for coding projects: the pinned Node LTS release from nodejs.org, as an optional part
(stage C4 of docs/v2-coding-agent-start-plan.md; the owner's yes of 2026-11-15).

A coding session runs its commands inside a sandbox that cannot read a person's home folder, so
a Node the person installed there (nvm, fnm, volta) is not found. This part puts one where the
sandbox can read it and nothing writes it:

    1 check     this computer has a pinned release, and room for it
    2 download  the release archive, size and SHA-256 checked, continued where it stopped
    3 unpack    into `<app data>/engine/node/<version>/` (links inside the tree are kept)
    4 verify    `bin/node --version` says the pinned version, then `engine/node/state.json`

`find_node` gives the folder with `node`, `npm` and `npx` to whoever builds a sandbox's
environment (`coding_server.py`). Packages a project installs go into the project's own
`node_modules`, and npm's cache into the sandbox's own home: nothing is ever written here.
"""

import asyncio
import shutil
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk.installer import (
    ClientFactory,
    Installer,
    InstallError,
    Runner,
    Step,
    check_disk,
    clean_env,
    default_client,
    fetch_archive,
    folder_bytes,
    read_state,
    run_command,
    status_installed,
    status_missing,
    status_unsupported,
    write_state,
)

from wasifyai_api.components.manifest import Manifest, Pins

ID = "node"
TITLE = "Node for coding projects"
STEPS = (
    Step("check", "Checking this computer"),
    Step("download", "Getting Node"),
    Step("unpack", "Unpacking it"),
    Step("verify", "Checking it"),
)
NODE = "bin/node"
NOT_HERE = "Node for coding projects is not available for this computer yet."


def find_node(data_dir: Path) -> Path | None:
    """The folder that holds the installed `node`, `npm` and `npx`; None when the part is not set
    up, is damaged, or points outside its own folder."""
    root = data_dir / "engine" / "node"
    state = read_state(root / "state.json")
    if state is None:
        return None
    try:
        folder = (root / str(state["bin"])).resolve()
    except (KeyError, OSError):
        return None
    if root.resolve() not in folder.parents or not (folder / "node").is_file():
        return None
    return folder


class NodeComponent:
    id = ID
    title = TITLE

    def __init__(
        self,
        data_dir: Path,
        manifest: Manifest,
        run: Runner = run_command,
        client: ClientFactory = default_client,
        allow_http: bool = False,
    ):
        self.data_dir = data_dir
        self.root = data_dir / "engine" / "node"
        self.pins: Pins | None = manifest.get(ID)
        self.installer = Installer(ID, STEPS, data_dir / "logs")
        self._run = run
        self._client = client
        self._allow_http = allow_http

    # ---- what is there ---------------------------------------------------------------------

    def installed(self) -> dict[str, Any] | None:
        """The state record of the pinned release, when its `node` is there."""
        p = self.pins
        state = read_state(self.root / "state.json")
        if p is None or p.archive is None or state is None:
            return None
        if (
            state.get("version") != p.version
            or state.get("asset_sha256") != p.archive.sha256
            or find_node(self.data_dir) is None
        ):
            return None
        return state

    def status(self) -> dict[str, Any]:
        if (now := self.installer.current()) is not None:
            return now
        p = self.pins
        if p is None or p.archive is None:
            return status_unsupported(NOT_HERE)
        if (state := self.installed()) is not None:
            return status_installed(str(state["version"]), "")
        return status_missing(p.archive.size)

    # ---- changing it -----------------------------------------------------------------------

    def install(self, confirm_bytes: int | None, repair: bool = False) -> None:
        p = self.pins
        if p is None or p.archive is None:
            raise InstallError(NOT_HERE)
        if not repair and self.installed() is not None:
            raise InstallError("Node is already set up.")
        if confirm_bytes is not None and confirm_bytes != p.archive.size:
            raise InstallError("The size shown is out of date. Look at it again.")
        self.installer.start(lambda inst: self._steps(inst, p, repair), self.status)

    def cancel(self) -> bool:
        return self.installer.cancel()

    async def wait(self) -> None:
        await self.installer.wait()

    def uninstall(self) -> int:
        if self.installer.running:
            raise InstallError("Node is being set up. Stop it first.")
        freed = folder_bytes(self.root)
        shutil.rmtree(self.root, ignore_errors=True)
        self.installer.failed = None
        return freed

    async def _steps(self, inst: Installer, p: Pins, repair: bool) -> None:
        assert p.archive is not None
        inst.at("check")
        await asyncio.to_thread(check_disk, self.root, p.min_free_bytes, "Node", "check")
        (self.root / "state.json").unlink(missing_ok=True)
        folder = self.root / p.version
        if repair:
            shutil.rmtree(folder, ignore_errors=True)
        await fetch_archive(
            inst, p.archive, self.root / "downloads", folder, NODE, "download", "unpack",
            self._client, self._allow_http,
        )  # fmt: skip
        inst.at("verify")
        code, out = await self._run([str(folder / NODE), "--version"], clean_env(), folder)
        said = out.strip().splitlines()[-1] if out.strip() else ""
        inst.line(said[-300:])
        if code != 0 or said != f"v{p.version}":
            raise InstallError("Node does not start.", "verify")
        write_state(
            self.root / "state.json",
            {
                "schema": 1, "version": p.version, "asset_sha256": p.archive.sha256,
                "bin": f"{p.version}/bin",
            },
        )  # fmt: skip
        shutil.rmtree(self.root / "downloads", ignore_errors=True)
