"""The language engine: llama.cpp's prebuilt `llama-server` (stage D of phase 2), set up by the
engine (stage F2; it was the shell's `llamacpp.rs`).

    1 check     this computer has a pinned release, and room for it
    2 download  the release archive, size and SHA-256 checked, continued where it stopped
    3 unpack    into `<app data>/engine/llamacpp/<release>/` (links inside the tree are kept)
    4 verify    `llama-server --version` answers, then `engine/llamacpp/state.json`

The state file is the one `llama_server.find_install` has always read, so a release the shell set up
before is still found and not fetched again.
"""

import asyncio
import shutil
import sys
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

ID = "llamacpp"
STEPS = (
    Step("check", "Checking this computer"),
    Step("download", "Getting the language engine"),
    Step("unpack", "Unpacking it"),
    Step("verify", "Checking it"),
)
SERVER = "llama-server.exe" if sys.platform == "win32" else "llama-server"


class LlamaCppComponent:
    id = ID
    title = "Language engine (llama.cpp)"

    def __init__(
        self,
        data_dir: Path,
        manifest: Manifest,
        run: Runner = run_command,
        client: ClientFactory = default_client,
        allow_http: bool = False,
    ):
        self.root = data_dir / "engine" / "llamacpp"
        self.pins: Pins | None = manifest.get(ID)
        self.installer = Installer(ID, STEPS, data_dir / "logs")
        self._run = run
        self._client = client
        self._allow_http = allow_http

    # ---- what is there ---------------------------------------------------------------------

    def installed(self) -> dict[str, Any] | None:
        """The state record of the pinned release, when its server is there."""
        p = self.pins
        state = read_state(self.root / "state.json")
        if p is None or p.archive is None or state is None:
            return None
        server = (self.root / str(state.get("server", ""))).resolve()
        inside = self.root.resolve() in server.parents
        if (
            state.get("version") != p.version
            or state.get("asset_sha256") != p.archive.sha256
            or not inside
            or not server.is_file()
        ):
            return None
        return state

    def status(self) -> dict[str, Any]:
        if (now := self.installer.current()) is not None:
            return now
        p = self.pins
        if p is None or p.archive is None:
            return status_unsupported("The language engine is not available for this computer yet.")
        if (state := self.installed()) is not None:
            return status_installed(str(state["version"]), str(state.get("backend", "")))
        return status_missing(p.archive.size)

    # ---- changing it -----------------------------------------------------------------------

    def install(self, confirm_bytes: int | None, repair: bool = False) -> None:
        p = self.pins
        if p is None or p.archive is None:
            raise InstallError("The language engine is not available for this computer yet.")
        if not repair and self.installed() is not None:
            raise InstallError("The language engine is already set up.")
        if confirm_bytes is not None and confirm_bytes != p.archive.size:
            raise InstallError("The size shown is out of date. Look at it again.")
        self.installer.start(lambda inst: self._steps(inst, p, repair), self.status)

    def cancel(self) -> bool:
        return self.installer.cancel()

    async def wait(self) -> None:
        await self.installer.wait()

    def uninstall(self) -> int:
        if self.installer.running:
            raise InstallError("The language engine is being set up. Stop it first.")
        freed = folder_bytes(self.root)
        shutil.rmtree(self.root, ignore_errors=True)
        self.installer.failed = None
        return freed

    async def _steps(self, inst: Installer, p: Pins, repair: bool) -> None:
        assert p.archive is not None
        inst.at("check")
        await asyncio.to_thread(
            check_disk, self.root, p.min_free_bytes, "The language engine", "check"
        )
        (self.root / "state.json").unlink(missing_ok=True)
        folder = self.root / p.version
        if repair:
            shutil.rmtree(folder, ignore_errors=True)
        await fetch_archive(
            inst, p.archive, self.root / "downloads", folder, SERVER, "download", "unpack",
            self._client, self._allow_http,
        )  # fmt: skip
        inst.at("verify")
        extra = {"LD_LIBRARY_PATH": str(folder)} if sys.platform.startswith("linux") else {}
        env = clean_env(extra=extra)
        code, out = await self._run([str(folder / SERVER), "--version"], env, folder)
        line = next((ln for ln in out.splitlines() if ln.startswith("version:")), "")
        inst.line(line or out.strip()[-300:])
        if code != 0 or not line:
            raise InstallError("The language engine does not start.", "verify")
        write_state(
            self.root / "state.json",
            {
                "schema": 1, "version": p.version, "asset_sha256": p.archive.sha256,
                "backend": str(p.extra.get("backend", "cpu")), "server": f"{p.version}/{SERVER}",
            },
        )  # fmt: skip
        shutil.rmtree(self.root / "downloads", ignore_errors=True)
