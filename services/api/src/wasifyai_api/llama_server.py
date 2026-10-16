"""llama.cpp's `llama-server` as a child of the desktop engine (stage D of phase 2, step D1).

The shell's installer puts a pinned release under `<app data>/engine/llamacpp/<release>/` and writes
`engine/llamacpp/state.json` (apps/desktop/src-tauri/src/llamacpp.rs). This module finds it and runs
one server at a time on loopback with a free port, for one model file. The server speaks the OpenAI
chat API, so the text provider (D2) only needs the base URL.

    LlamaServer.ensure_running(model)   start (or keep) the server for this model, return its URL
    LlamaServer.stop()                  stop it: this is how the model's memory is given back

The boundary is the loopback address and the process being the engine's own child, as for ComfyUI
(ADR-0059). Which model, and whether it fits, is decided by the callers (ADR-0063, desktop_fit).
"""

import asyncio
import contextlib
import json
import logging
import os
import re
import socket
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

STATE = "state.json"
# MiB of host memory for llama-server's prompt cache (its default is 8192; see `_start`)
PROMPT_CACHE_MIB = 512


class LlamaError(Exception):
    """A failure to give a person's request an engine. `message` is safe to show."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class LlamaInstall:
    version: str
    backend: str  # "metal" (Apple GPU) or "cpu"
    dir: Path
    server: Path


def find_install(data_dir: Path) -> LlamaInstall | None:
    """The installed release, from the state file the shell wrote; None when absent or damaged."""
    root = data_dir / "engine" / "llamacpp"
    try:
        state = json.loads((root / STATE).read_text())
        server = (root / str(state["server"])).resolve()
        if not str(server).startswith(str(root.resolve())) or not server.is_file():
            return None
        return LlamaInstall(str(state["version"]), str(state["backend"]), server.parent, server)
    except (OSError, ValueError, KeyError):
        return None


class LlamaServer:
    def __init__(self, data_dir: Path, startup_timeout_s: float = 300.0):
        self._data_dir = data_dir
        self._timeout = startup_timeout_s
        self._proc: asyncio.subprocess.Process | None = None
        self._url: str | None = None
        self._model: Path | None = None
        self._started_with: tuple[Any, ...] | None = None
        self._lock = asyncio.Lock()
        self._http = httpx.AsyncClient(timeout=3)

    # ---- state ---------------------------------------------------------------------------

    @property
    def install(self) -> LlamaInstall | None:
        return find_install(self._data_dir)

    @property
    def installed(self) -> bool:
        return self.install is not None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self.running and self._proc is not None else None

    @property
    def model(self) -> Path | None:
        return self._model if self.running else None

    @property
    def url(self) -> str | None:
        return self._url if self.running else None

    def state(self) -> dict[str, Any]:
        found = self.install
        return {
            "installed": found is not None,
            "version": found.version if found else None,
            "backend": found.backend if found else None,
            "running": self.running,
            "model": str(self._model) if self.running and self._model else None,
            "pid": self.pid,
        }

    # ---- the process ---------------------------------------------------------------------

    async def _healthy(self, url: str) -> bool:
        try:
            r = await self._http.get(f"{url}/health")
        except httpx.HTTPError:
            return False
        return r.status_code == 200

    async def ensure_running(
        self,
        model: Path,
        *,
        context: int = 8192,
        embedding: bool = False,
        extra_args: Sequence[str] = (),
    ) -> str:
        """The base URL of a server running `model`, starting (or restarting) it if needed."""
        want = (model, context, embedding, tuple(extra_args))
        async with self._lock:
            if (
                self.running
                and self._url
                and self._started_with == want
                and await self._healthy(self._url)
            ):
                return self._url
            await self._terminate()
            found = self.install
            if found is None:
                raise LlamaError(
                    "not_installed",
                    "The language engine is not set up yet. Set it up in Settings first.",
                )
            if not await asyncio.to_thread(model.is_file):
                raise LlamaError("model_missing", "That model file is no longer on this computer.")
            return await self._start(found, want)

    def _log_path(self) -> Path:
        return self._data_dir / "logs" / "llama-server.log"

    def _open_log(self) -> Any:
        self._log_path().parent.mkdir(parents=True, exist_ok=True)
        return self._log_path().open("ab")

    def _failure(self, offset: int) -> LlamaError:
        """Why the server stopped, from what it wrote since `offset` (this run's log)."""
        try:
            with self._log_path().open("rb") as f:
                f.seek(offset)
                text = f.read(200_000).decode("utf-8", "replace")
        except OSError:
            text = ""
        if m := re.search(r"unknown model architecture: '([^']+)'", text):
            return LlamaError(
                "unsupported_architecture",
                f"This engine does not know the '{m.group(1)}' model type. A newer engine, or a "
                "file made for llama.cpp, may be needed.",
            )
        if re.search(
            r"out of memory|failed to allocate|cudaMalloc failed|alloc.*failed", text, re.I
        ):
            return LlamaError(
                "out_of_memory",
                "There was not enough memory to load this model. Close other apps or choose a "
                "smaller model.",
            )
        return LlamaError(
            "start_failed",
            "The language model did not start. It may not fit this computer, or the file may be "
            "damaged. Try a smaller model.",
        )

    async def _start(self, found: LlamaInstall, want: tuple[Any, ...]) -> str:
        model, context, embedding, extra = want
        with socket.socket() as s:  # a free port on loopback
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        out = await asyncio.to_thread(self._open_log)
        offset = await asyncio.to_thread(lambda: self._log_path().stat().st_size)
        env = dict(os.environ)
        if sys.platform.startswith("linux"):
            env["LD_LIBRARY_PATH"] = str(found.dir) + os.pathsep + env.get("LD_LIBRARY_PATH", "")
        args = [
            str(found.server), "-m", str(model), "--host", "127.0.0.1", "--port", str(port),
            "-c", str(context), "-np", "1", "--jinja", "--no-webui",
            # llama.cpp keeps old prompts in a host-memory cache of up to 8 GiB by default.
            # Measured on a Mac (E0): 58 long prompts took Qwen3 4B from 1.3 GB to 10.4 GB.
            # A small cache keeps the reuse.
            "--cache-ram", str(PROMPT_CACHE_MIB),
            *(["--embedding"] if embedding else []), *extra,
        ]  # fmt: skip
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *args, cwd=str(found.dir), env=env, stdin=asyncio.subprocess.DEVNULL,
                stdout=out, stderr=asyncio.subprocess.STDOUT,
            )  # fmt: skip
        finally:
            out.close()
        self._started_with, self._model = want, model
        log.info("started llama-server (pid %s) on %s for %s", self._proc.pid, url, model.name)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout
        while loop.time() < deadline:
            if self._proc.returncode is not None:
                break
            if await self._healthy(url):
                self._url = url
                return url
            await asyncio.sleep(0.25)
        code = self._proc.returncode
        await self._terminate()
        log.error("llama-server did not start (exit %s); see logs/llama-server.log", code)
        raise await asyncio.to_thread(self._failure, offset)

    async def _terminate(self) -> None:
        proc, self._proc, self._url, self._model = self._proc, None, None, None
        if proc is None or proc.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()

    async def stop(self) -> bool:
        """Stop the server, giving the model's memory back. Returns whether one was running."""
        async with self._lock:
            was = self.running
            await self._terminate()
            return was

    async def close(self) -> None:
        await self.stop()
        await self._http.aclose()
