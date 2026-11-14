"""The coding engine: OpenHands' Agent Server in a Python environment of its own, with the pinned
extensions catalogue (ADR-0101, ADR-0102, ADR-0104; stage C1a of
docs/v2-coding-agent-start-plan.md), set up by the one installer.

    1 check        this computer is a Mac with the sandbox, the build carries the package list
                   and the sandbox profile, there is room
    2 uv           the app's own uv (the shell put it there on the first run)
    3 python       `uv python install <the app's Python>` (already there after the first run)
    4 environment  `uv venv` for the coding engine alone
    5 packages     the hashed lock of `services/coding-engine/`: only what is imported; the one
                   build tool a source-only package needs is pinned by hash too
    6 extensions   the pinned catalogue archive, size and SHA-256 checked, unpacked
    7 verify       the server is started inside its sandbox, says the pinned version, is stopped;
                   then `engine/coding/state.json`

Everything is under `<app data>/engine/coding/`. What the server writes while it runs (sessions,
its home, the default workspace) is under `<app data>/coding/` and is the person's work: removing
the part leaves it. `wasifyai_api/coding_server.py` reads the state file written here.

On Windows and Linux, and on Intel Macs, the part says it is not available yet: how the engine
is held there is a later decision (ADR-0102, decision 10).
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
    default_client,
    fetch_archive,
    folder_bytes,
    make_environment,
    read_state,
    run_command,
    sha256_of,
    status_installed,
    status_missing,
    status_unsupported,
    venv_python,
    write_state,
)

from wasifyai_api.coding_server import PROFILE_TEMPLATE, CodingError, CodingInstall, CodingServer
from wasifyai_api.components.comfyui import uv_env
from wasifyai_api.components.manifest import Manifest, Pins

ID = "coding"
TITLE = "Coding engine (OpenHands)"
STEPS = (
    Step("check", "Checking this computer"),
    Step("uv", "Getting the installer"),
    Step("python", "Installing Python"),
    Step("environment", "Creating the coding engine's environment"),
    Step("packages", "Installing the coding engine's packages"),
    Step("extensions", "Getting the extensions catalogue"),
    Step("verify", "Checking that it starts in its sandbox"),
)
UNSUPPORTED = "The coding engine is not available for this computer yet."
CATALOGUE_MARK = "skills"  # a folder every catalogue archive has


def coding_files(products_dir: Path | None) -> Path | None:
    """The build's copy of `services/coding-engine/` (the lock and the sandbox profile): beside
    the products a packaged app runs (the engine bundle's `coding-engine/`), else a checkout's."""
    if products_dir is None:
        return None
    candidates = [
        products_dir.parent / "coding-engine",
        products_dir.parent / "services" / "coding-engine",
    ]
    return next((c for c in candidates if (c / PROFILE_TEMPLATE).is_file()), None)


def _runnable(program: str | None) -> bool:
    return bool(program) and (
        Path(str(program)).is_file() or shutil.which(str(program)) is not None
    )


class CodingComponent:
    id = ID
    title = TITLE

    def __init__(
        self,
        data_dir: Path,
        manifest: Manifest,
        files: Path | None,
        uv: str | None,
        server: CodingServer,
        run: Runner = run_command,
        client: ClientFactory = default_client,
        allow_http: bool = False,
    ):
        self.engine_root = data_dir / "engine"
        self.root = self.engine_root / "coding"
        self.python = manifest.python
        self.pins: Pins | None = manifest.get(ID)
        self.files = files
        self.uv = uv
        self.server = server
        self.installer = Installer(ID, STEPS, data_dir / "logs")
        self._run = run
        self._client = client
        self._allow_http = allow_http

    # ---- what is there ---------------------------------------------------------------------

    def offered(self) -> Pins | None:
        """The pins, when this computer can run the part: a platform with a lock and a
        catalogue pinned, and the sandbox."""
        p = self.pins
        if p is None or p.archive is None or not p.extra.get("lock") or not self.server.supported:
            return None
        return p

    def lock(self, p: Pins) -> Path | None:
        """The hashed package list this build carries for this computer."""
        if self.files is None:
            return None
        path = (self.files / str(p.extra["lock"])).resolve()
        if self.files.resolve() not in path.parents or not path.is_file():
            return None
        return path

    def build_constraints(self, p: Pins) -> Path | None:
        """The pinned build tool for the lock's one package that is published as source only.
        Without it uv would fetch the newest one, unchecked, while installing."""
        name = str(p.extra.get("build_constraints") or "")
        if self.files is None or not name:
            return None
        path = (self.files / name).resolve()
        if self.files.resolve() not in path.parents or not path.is_file():
            return None
        if sha256_of(path) != p.extra.get("build_constraints_sha256"):
            return None
        return path

    def _extensions_version(self, p: Pins) -> str:
        return str((p.extra.get("extensions") or {}).get("version") or "")

    def installed(self) -> dict[str, Any] | None:
        p = self.offered()
        state = read_state(self.root / "state.json")
        if p is None or p.archive is None or state is None:
            return None
        ext = state.get("extensions") or {}
        whole = (
            venv_python(self.root / "venv").is_file()
            and (self.root / "extensions" / self._extensions_version(p) / CATALOGUE_MARK).is_dir()
        )
        if (
            state.get("schema") != 1
            or state.get("version") != p.version
            or state.get("python") != self.python
            or state.get("lock_sha256") != p.extra.get("lock_sha256")
            or ext.get("sha256") != p.archive.sha256
            or not whole
        ):
            return None
        return state

    def needs_bytes(self, p: Pins) -> int:
        """What the person is shown: the room it takes once set up."""
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
            raise InstallError("The coding engine is already set up.")
        if confirm_bytes is not None and confirm_bytes != self.needs_bytes(p):
            raise InstallError("The size shown is out of date. Look at it again.")
        self.installer.start(lambda inst: self._steps(inst, p, repair), self.status)

    def cancel(self) -> bool:
        return self.installer.cancel()

    async def wait(self) -> None:
        await self.installer.wait()

    def uninstall(self) -> int:
        if self.installer.running:
            raise InstallError("The coding engine is being set up. Stop it first.")
        self.server.stop_now()
        freed = folder_bytes(self.root)
        shutil.rmtree(self.root, ignore_errors=True)
        self.installer.failed = None
        return freed

    async def _steps(self, inst: Installer, p: Pins, repair: bool) -> None:
        assert p.archive is not None
        inst.at("check")
        await self.server.stop()  # a running one would hold the files that are replaced
        lock = await asyncio.to_thread(self.lock, p)
        constraints = await asyncio.to_thread(self.build_constraints, p)
        if (
            lock is None
            or constraints is None
            or self.files is None
            or not (self.files / PROFILE_TEMPLATE).is_file()
        ):
            raise InstallError(
                "This build carries no package list or sandbox profile for the coding engine. "
                "Build the engine files again with scripts/build-engine-bundle.sh.",
                "check",
            )
        await asyncio.to_thread(
            check_disk, self.root, p.min_free_bytes, "The coding engine", "check"
        )
        venv = self.root / "venv"
        catalogue = self.root / "extensions" / self._extensions_version(p)
        (self.root / "state.json").unlink(missing_ok=True)
        if repair:
            await asyncio.to_thread(shutil.rmtree, self.root / "extensions", True)

        inst.at("uv")
        uv = self.uv
        if uv is None or not await asyncio.to_thread(_runnable, uv):
            raise InstallError("The installer (uv) is missing. Repair the app and try again.", "uv")
        env = uv_env(self.engine_root)

        inst.at("python")
        code, out = await self._run([uv, "python", "install", self.python], env, None)
        inst.line(out.strip()[-300:])
        if code != 0:
            raise InstallError("Python could not be installed. Are you online?", "python")

        py = await make_environment(
            uv, self.python, venv, lock, str(p.extra.get("lock_sha256") or ""), "environment",
            "packages", self._run, env, on_step=inst.at, on_line=inst.line,
            owner="The coding engine", extra_args=["--build-constraints", str(constraints)],
        )  # fmt: skip

        if not (catalogue / CATALOGUE_MARK).is_dir():
            await asyncio.to_thread(shutil.rmtree, self.root / "extensions", True)
            await fetch_archive(
                inst, p.archive, self.root / "downloads", catalogue, CATALOGUE_MARK, "extensions",
                client=self._client, allow_http=self._allow_http,
            )  # fmt: skip
        else:
            inst.at("extensions")

        inst.at("verify")
        found = CodingInstall(p.version, self.root, py, catalogue, self._extensions_version(p))
        try:
            said = await self.server.check(found)
        except CodingError as e:
            raise InstallError(e.message, "verify") from None
        inst.line(f"answered as {said['version']} after {said['start_seconds']} s")
        if said["version"] != p.version:
            raise InstallError(
                "The coding engine that was installed is not the pinned version.", "verify"
            )
        write_state(
            self.root / "state.json",
            {
                "schema": 1, "version": p.version, "python": self.python,
                "python_path": str(py.relative_to(self.root)),
                "lock_sha256": str(p.extra.get("lock_sha256") or ""),
                "extensions": {
                    "version": self._extensions_version(p), "sha256": p.archive.sha256,
                    "dir": str(catalogue.relative_to(self.root)),
                },
            },
        )  # fmt: skip
        await asyncio.to_thread(shutil.rmtree, self.engine_root / "cache", True)
        await asyncio.to_thread(shutil.rmtree, self.root / "downloads", True)
