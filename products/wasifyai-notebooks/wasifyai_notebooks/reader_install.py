# SPDX-License-Identifier: Apache-2.0
"""Setting up the document reader (ADR-0065 decision 7): an environment of its own with Docling and
its model weights, under `<data>/components/reader/`.

Steps, the same shape as the other components (named, in order, checked at the end):

    1 disk       enough free space, said before anything is downloaded
    2 environment  `uv venv` from the engine's own interpreter (no download)
    3 packages     `uv pip install --require-hashes -r <lock for this platform>`
    4 weights      each file fetched, SHA-256 checked, moved into place
    5 check        the reader reads a small picture of text; only then `installed.json` is written

A failed install removes what it made, so the next try starts clean. Nothing is installed without
a request that repeats the size the person was shown.
"""

import asyncio
import json
import logging
import os
import platform
import shutil
import sys
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from wasifyai_platform_sdk import installer

log = logging.getLogger(__name__)

STEPS = ("disk", "environment", "packages", "weights", "check")
STEP_TEXT = {
    "disk": "Checking free space",
    "environment": "Preparing the reader's environment",
    "packages": "Installing the reader's packages (about 1 GB)",
    "weights": "Downloading the reader's models (about 400 MB)",
    "check": "Checking that it reads",
}
MIN_FREE_BYTES = 3 * 1024**3
# an estimate of what packages add to the weights, shown before the person agrees
PACKAGES_BYTES = 1_050_000_000


class InstallError(Exception):
    """`str(e)` is a sentence safe to show; `step` is where it stopped."""

    def __init__(self, step: str, message: str):
        super().__init__(message)
        self.step = step


def uv_target() -> str:
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if sys.platform == "darwin":
        return "aarch64-apple-darwin" if arm else "x86_64-apple-darwin"
    if sys.platform == "win32":
        return "x86_64-pc-windows-msvc"
    return "aarch64-unknown-linux-gnu" if arm else "x86_64-unknown-linux-gnu"


@dataclass(frozen=True)
class WeightFile:
    path: str
    url: str
    size: int
    sha256: str


def load_weights(manifest: Path) -> list[WeightFile]:
    raw = yaml.safe_load(manifest.read_text()) or {}
    out = []
    for f in raw.get("files", []):
        parts = Path(f["path"]).parts
        if ".." in parts or Path(f["path"]).is_absolute():
            raise ValueError(f"{f['path']}: not a relative path")
        if (
            urlparse(f["url"]).scheme != "https"
            or len(str(f["sha256"])) != 64
            or int(f["size"]) <= 0
        ):
            raise ValueError(f"{f['path']}: needs an https URL, a size and a SHA-256")
        out.append(WeightFile(f["path"], f["url"], int(f["size"]), str(f["sha256"]).lower()))
    return out


@dataclass
class Progress:
    state: str = "idle"  # idle | installing | ready | failed
    step: str | None = None
    message: str = ""
    done_bytes: int = 0
    total_bytes: int = 0

    def public(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "step": self.step,
            "steps": list(STEPS),
            "message": self.message,
            "done_bytes": self.done_bytes,
            "total_bytes": self.total_bytes,
        }


Runner = Callable[[list[str], dict[str, str]], Awaitable[tuple[int, str]]]
Fetcher = Callable[[WeightFile, Path, Callable[[int], None]], Awaitable[None]]


async def run_command(args: list[str], env: dict[str, str]) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, env=env, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )  # fmt: skip
    out, _ = await proc.communicate()
    return proc.returncode or 0, out.decode(errors="replace")


async def fetch_file(item: WeightFile, target: Path, tick: Callable[[int], None]) -> None:
    """One file to `target` through the engine's one installer (stage F2): continued where it
    stopped, its size and SHA-256 checked before it is kept."""
    seen = [0]

    def moved(done: int, _total: int) -> None:
        tick(done - seen[0])
        seen[0] = done

    try:
        await installer.download(
            installer.Archive(item.url, item.size, item.sha256, "file"), target, "weights", moved
        )
    except installer.InstallError:
        raise InstallError(
            "weights", f"{target.name} did not download correctly (checksum)."
        ) from None


@dataclass
class ReaderInstaller:
    reader_dir: Path
    lock: Path  # the hashed requirements for this platform
    weights: list[WeightFile]
    worker_script: Path
    uv: str
    python: str = field(default_factory=lambda: sys.executable)
    cache_dir: Path | None = None
    run: Runner = run_command
    fetch: Fetcher = fetch_file
    progress: Progress = field(default_factory=Progress)
    _task: asyncio.Task | None = None

    # ---- what the person is asked to agree to ------------------------------------------------

    @property
    def weights_bytes(self) -> int:
        return sum(w.size for w in self.weights)

    @property
    def total_bytes(self) -> int:
        return PACKAGES_BYTES + self.weights_bytes

    def is_installed(self) -> bool:
        return (self.reader_dir / "installed.json").is_file()

    def offer(self) -> dict[str, Any]:
        return {
            "id": "docling",
            "size_bytes": self.total_bytes,
            "licences": "Docling MIT; layout model Apache-2.0; tables CDLA-Permissive-2.0; "
            "text recognition Apache-2.0",
            "source": "PyPI and Hugging Face / ModelScope (once, on your request)",
            "needs_free_bytes": MIN_FREE_BYTES,
        }

    # ---- the install -------------------------------------------------------------------------

    def start(self, confirm_bytes: int) -> None:
        if confirm_bytes != self.total_bytes:
            raise InstallError("disk", "The size shown is out of date. Open the setup again.")
        if self.progress.state == "installing":
            return
        self.progress = Progress("installing", STEPS[0], STEP_TEXT["disk"], 0, self.weights_bytes)
        self._task = asyncio.create_task(self._run())

    async def wait(self) -> None:
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)

    def _step(self, name: str) -> None:
        self.progress.step = name
        self.progress.message = STEP_TEXT[name]

    async def _run(self) -> None:
        try:
            await self._install()
        except InstallError as e:
            self._fail(str(e), e.step)
        except Exception:
            log.exception("reader setup failed")
            self._fail("Setting up the reader did not work. Try again, or restart the app.", None)
        else:
            done = self.progress.done_bytes
            self.progress = Progress("ready", None, "The reader is ready.", done, done)

    def _fail(self, message: str, step: str | None) -> None:
        shutil.rmtree(self.reader_dir, ignore_errors=True)
        self.progress = Progress("failed", step, message)

    def _env(self) -> dict[str, str]:
        env = {
            k: v for k, v in os.environ.items() if not k.startswith(("VIRTUAL_ENV", "PYTHONHOME"))
        }
        if self.cache_dir is not None:
            env["UV_CACHE_DIR"] = str(self.cache_dir)
        return env

    async def _install(self) -> None:
        self._step("disk")
        parent = self.reader_dir.parent
        parent.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(parent).free
        if free < MIN_FREE_BYTES:
            need = MIN_FREE_BYTES // 1024**3
            raise InstallError(
                "disk", f"There is not enough free space: about {need} GB is needed."
            )
        shutil.rmtree(self.reader_dir, ignore_errors=True)
        self.reader_dir.mkdir(parents=True)
        venv = self.reader_dir / "venv"
        env = self._env()

        extra: list[str] = []
        if "linux" in uv_target():
            # the lock names the CPU build of torch, which only PyTorch's own index serves
            extra = [
                "--extra-index-url", "https://download.pytorch.org/whl/cpu",
                "--index-strategy", "unsafe-best-match",
            ]  # fmt: skip

        async def run(args: list[str], env_: dict[str, str], _cwd: Path | None) -> tuple[int, str]:
            return await self.run(args, env_)

        try:  # the engine's one installer (stage F2)
            py = await installer.make_environment(
                self.uv, self.python, venv, self.lock, None, "environment", "packages", run, env,
                on_step=self._step, on_line=lambda text: log.info("%s", text[-300:]),
                owner="The reader", extra_args=extra,
            )  # fmt: skip
        except installer.InstallError as e:
            raise InstallError(e.step or "packages", str(e)) from None

        self._step("weights")
        models = self.reader_dir / "models"
        for item in self.weights:
            try:
                await self.fetch(item, models / item.path, self._tick)
            except InstallError:
                raise
            except Exception as e:
                log.error("fetching %s failed: %s", item.url, e)
                raise InstallError(
                    "weights", f"{Path(item.path).name} could not be downloaded."
                ) from e

        self._step("check")
        await self._check(py, models)
        (self.reader_dir / "installed.json").write_text(
            json.dumps({"id": "docling", "files": len(self.weights), "target": uv_target()})
        )

    def _tick(self, n: int) -> None:
        self.progress.done_bytes += n

    async def _check(self, py: Path, models: Path) -> None:
        """The reader must read a small picture of text before it counts as installed."""
        with tempfile.TemporaryDirectory(prefix="wasifyai-reader-check-") as tmp:
            picture, out = Path(tmp) / "check.png", Path(tmp) / "out.json"
            draw = (
                "from PIL import Image, ImageDraw, ImageFont;"
                "im = Image.new('RGB', (900, 200), 'white');"
                "ImageDraw.Draw(im).text((30, 50), 'Wasify reader check', fill='black',"
                " font=ImageFont.load_default(size=64));"
                f"im.save({str(picture)!r})"
            )
            code, text = await self.run([str(py), "-I", "-c", draw], self._env())
            if code != 0:
                log.error("check picture failed: %s", text[-500:])
                raise InstallError("check", "The reader could not be checked.")
            code, text = await self.run(
                [str(py), "-I", str(self.worker_script), "--models", str(models),
                 "--file", str(picture), "--out", str(out)],
                self._env(),
            )  # fmt: skip
            if code != 0 or not out.is_file():
                log.error("check read failed: %s", text[-800:])
                raise InstallError(
                    "check", "The reader was installed but could not read a test page."
                )
            markdown = json.loads(out.read_text()).get("markdown", "")
            if "reader" not in markdown.lower():
                raise InstallError(
                    "check", "The reader ran but did not read a test page correctly."
                )


def main(argv: list[str] | None = None) -> int:
    """Set the reader up without a person to ask: `python -m wasifyai_notebooks.reader_install`.
    For building the worker's image, where the size is agreed to by building the image."""
    import argparse

    parser = argparse.ArgumentParser(description="Set up the notebooks' document reader.")
    parser.add_argument("--reader-dir", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True, help="the hashed requirements")
    parser.add_argument("--weights", type=Path, required=True, help="reader/models.yaml")
    parser.add_argument("--uv", default=shutil.which("uv") or "uv")
    args = parser.parse_args(argv)

    async def install() -> int:
        installer = ReaderInstaller(
            reader_dir=args.reader_dir,
            lock=args.lock,
            weights=load_weights(args.weights),
            worker_script=Path(__file__).with_name("docling_worker.py"),
            uv=args.uv,
        )
        installer.start(installer.total_bytes)
        await installer.wait()
        print(installer.progress.message)
        return 0 if installer.progress.state == "ready" else 1

    return asyncio.run(install())


if __name__ == "__main__":
    raise SystemExit(main())
