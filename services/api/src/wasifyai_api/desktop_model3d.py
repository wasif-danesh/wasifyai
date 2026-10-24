"""The 3D engine of the desktop app (ADR-0080, TD1): what the engine holds (the installer and what
is installed), and the two runs a 3D model is made of, each a separate process of the pinned
`trellis-cli`: the cut-out of the picture, and the 3D run.

A process per run, not the resident `trellis-server`, because the server loads its weights for every
request anyway, has no progress and no cancel, and keeps 2.5 GB after a job (TD0, section 6): a
process shows its progress on its output, stops when it is killed, and gives all its memory back
when it exits. The product (`wasifyai_model3d`) imports nothing from this package; it reads the
service from the app state, as the Motion graphics does."""

import asyncio
import contextlib
import os
import re
import shutil
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from wasifyai_platform_sdk import Identity

from wasifyai_api import model3d_runtime as m3
from wasifyai_api.audio_runtime import InstallError
from wasifyai_api.desktop_fit import assess_fit, need_declared, read_machine
from wasifyai_api.identity import get_identity

CUTOUT_WALL_S = 900.0
GENERATE_WALL_S = 4 * 3600.0
ATLAS = {"light": 1024, "standard": 2048, "detailed": 4096}  # decision 7, corrected after TD0


@dataclass
class RunResult:
    ok: bool
    reason: str | None = None  # cancelled | wall_time | failed | missing
    message: str = ""
    seconds: float = 0.0
    peak_gb: float = 0.0
    output: Path | None = None
    log_tail: str = ""
    lines: list[str] = field(default_factory=list)


# ---- progress, read from what the engine prints ------------------------------------------------

STAGE = re.compile(r"^\[(\d)/6\]")
FLOW = re.compile(r"^\s*\[flow\]\s+\[[#.]*\]\s+(\d+)/(\d+)")
# where each stage starts, as a share of the whole run (a 741 s run of TD0: the structure flow 13 %,
# the shape 45 %, the decode 2 %, the texture 25 %, the mesh and the file the rest)
STAGE_START = {0: 0.0, 1: 0.0, 2: 0.0, 3: 0.13, 4: 0.58, 5: 0.60, 6: 0.86}
STAGE_WORDS = {
    0: "Looking at the picture",
    1: "Looking at the picture",
    2: "Placing the object in space",
    3: "Building the shape",
    4: "Cleaning up the mesh",
    5: "Painting the surface",
    6: "Saving the file",
}
LOW_RES_SHARE = 0.15  # of the shape stage: its first flow is the small one


class ProgressReader:
    """`(fraction 0..1, plain words)` from the lines `trellis-cli` prints while it works."""

    def __init__(self) -> None:
        self.stage = 0
        self.flows = 0  # flows seen in this stage
        self.fraction = 0.0
        self.words = STAGE_WORDS[0]

    def feed(self, line: str) -> tuple[float, str]:
        if m := STAGE.match(line):
            self.stage, self.flows = int(m.group(1)), 0
            self.words = STAGE_WORDS.get(self.stage, self.words)
            self.fraction = max(self.fraction, STAGE_START.get(self.stage, self.fraction))
        elif m := FLOW.match(line):
            done, total = int(m.group(1)), max(1, int(m.group(2)))
            if done == 0:
                self.flows += 1
            share = min(1.0, done / total)
            begin = STAGE_START.get(self.stage, 0.0)
            end = STAGE_START.get(self.stage + 1, 1.0) if self.stage < 6 else 1.0
            if self.stage == 3:  # two flows: the small one first
                low = 1 if self.flows <= 1 else 0
                part = share * LOW_RES_SHARE if low else LOW_RES_SHARE + share * (1 - LOW_RES_SHARE)
            else:
                part = share
            self.fraction = max(self.fraction, begin + (end - begin) * part)
        elif line.startswith("done in"):
            self.fraction, self.words = 1.0, "Done"
        return min(self.fraction, 0.99 if self.words != "Done" else 1.0), self.words


# ---- running a process --------------------------------------------------------------------------


def _rss_bytes(pid: int) -> int:
    try:
        out = subprocess.run(
            ["/bin/ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, timeout=5
        ).stdout.strip()
        return int(out) * 1024 if out else 0
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def _kill_group(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, signal.SIGTERM)


class Model3dService:
    """What the engine holds for 3D: the installer, and what is installed."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.installer = m3.Model3dInstaller(data_dir)
        self.slot: Any = None  # the SlotManager: a 3D run holds the one big-model slot
        self._proc: asyncio.subprocess.Process | None = None

    def install(self) -> m3.Model3dInstall | None:
        return m3.find_install(self.data_dir, self.installer.pins)

    def state(self) -> dict[str, Any]:
        found = self.install()
        return {
            "installed": found is not None,
            "source": found.source if found is not None else None,
            "plan": self.installer.plan(),
            "progress": self.installer.progress.public(),
            "fit": self.fit() if found is not None else None,
            "about": {
                "built_with": "Built with DINOv3",
                "licence": "Models: MIT, and the DINOv3 licence for the image encoder.",
                "where": "Everything runs on this computer; nothing is sent anywhere.",
            },
        }

    # ---- what the Model3d product calls (it imports nothing from this package) ---------------

    def ready(self) -> bool:
        return self.problem() is None

    def problem(self) -> str | None:
        """Why a model cannot be made now, in words, or None."""
        if not self.installer.supported:
            return "3D models are not available on this kind of computer yet."
        if self.install() is None:
            return "The 3D component is not set up yet. Set it up first."
        return None

    def fit(self) -> dict[str, Any]:
        """Whether a 3D run fits in the memory this computer has now (ADR-0063)."""
        return assess_fit(need_declared(self.installer.pins.need_gb), read_machine()).public()

    @property
    def busy(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def stop(self) -> None:
        """Let go of memory for another model: a run in progress is stopped."""
        if self.busy and self._proc is not None:
            _kill_group(self._proc.pid)

    async def matte(
        self, picture: Path, out_dir: Path, on_line: Callable[[str], None] | None = None
    ) -> RunResult:
        """The cut-out of a picture: a PNG with a real transparent background."""
        found = self.install()
        if found is None:
            return RunResult(False, "missing", self.problem() or "", 0.0)
        glb = out_dir / "unused.glb"
        res = await self._run(
            found,
            [str(found.cli), str(picture), str(glb), "--models", str(found.matte_dir), "--bg-only"],
            out_dir, CUTOUT_WALL_S, on_line,
        )  # fmt: skip
        cutout = out_dir / "unused_cutout.png"
        if res.ok and not cutout.is_file():
            return RunResult(False, "failed", "The cut-out did not make a picture.", res.seconds)
        res.output = cutout if res.ok else None
        return res

    async def generate(
        self,
        cutout: Path,
        out_glb: Path,
        *,
        seed: int = 42,
        detail: str = "standard",
        on_line: Callable[[str], None] | None = None,
        on_progress: Callable[[float, str], None] | None = None,
    ) -> RunResult:
        """The 3D model of a cut-out picture, as one GLB; nothing else is left in the folder.
        `on_progress(fraction, words)` is told when the picture moves by a hundredth or the stage
        changes; `on_line` gets every line the engine prints."""
        reader = ProgressReader()
        told = {"fraction": -1.0, "words": ""}

        def hear(line: str) -> None:
            if on_line:
                on_line(line)
            if on_progress:
                fraction, words = reader.feed(line)
                if words != told["words"] or fraction - float(told["fraction"]) >= 0.01:
                    told["fraction"], told["words"] = fraction, words
                    on_progress(fraction, words)

        found = self.install()
        if found is None:
            return RunResult(False, "missing", self.problem() or "", 0.0)
        work = out_glb.parent / f"work-{out_glb.stem}"
        await asyncio.to_thread(work.mkdir, parents=True, exist_ok=True)
        tmp_glb = work / "model.glb"
        args = [
            str(found.cli), "--sv-image", str(cutout), "--models", str(found.sv_dir),
            "--seed", str(seed), "--res", "1024", "--atlas", str(ATLAS.get(detail, 2048)),
            str(tmp_glb),
        ]  # fmt: skip
        try:
            res = await self._run(found, args, work, GENERATE_WALL_S, hear)
            if res.ok and tmp_glb.is_file():
                tmp_glb.replace(out_glb)  # the .ply, the PNGs and the staging folder stay behind
                res.output = out_glb
            elif res.ok:
                return RunResult(False, "failed", "The 3D run did not make a file.", res.seconds)
            return res
        finally:
            shutil.rmtree(work, ignore_errors=True)

    async def _run(
        self,
        install: m3.Model3dInstall,
        args: list[str],
        cwd: Path,
        wall_s: float,
        on_line: Callable[[str], None] | None,
    ) -> RunResult:
        await asyncio.to_thread(cwd.mkdir, parents=True, exist_ok=True)
        started = time.monotonic()
        peak = 0
        tail: list[str] = []
        lines: list[str] = []
        try:
            holder = self.slot.hold("model3d") if self.slot is not None else _no_slot()
            async with holder:
                proc = await asyncio.create_subprocess_exec(
                    *args, cwd=str(cwd), env=m3.run_env(install),
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                    start_new_session=True,
                )  # fmt: skip
                self._proc = proc
                try:
                    peak = await asyncio.wait_for(self._watch(proc, tail, lines, on_line), wall_s)
                except TimeoutError:
                    _kill_group(proc.pid)
                    await proc.wait()
                    return RunResult(
                        False, "wall_time", "It took too long and was stopped.",
                        time.monotonic() - started, peak / 1e9, log_tail="\n".join(tail[-12:]),
                    )  # fmt: skip
                except asyncio.CancelledError:
                    _kill_group(proc.pid)
                    await proc.wait()
                    raise
                finally:
                    self._proc = None
        except OSError as e:
            return RunResult(False, "failed", f"The 3D engine could not start: {e}", 0.0)
        seconds = time.monotonic() - started
        ok = proc.returncode == 0
        return RunResult(
            ok, None if ok else "failed",
            "Done." if ok else "The 3D engine stopped with an error.",
            seconds, peak / 1e9, log_tail="\n".join(tail[-12:]), lines=lines,
        )  # fmt: skip

    async def _watch(
        self,
        proc: asyncio.subprocess.Process,
        tail: list[str],
        lines: list[str],
        on_line: Callable[[str], None] | None,
    ) -> int:
        """Read the engine's output as it comes, and the memory it holds; the peak of that."""
        peak = 0
        assert proc.stdout is not None

        async def sample() -> None:
            nonlocal peak
            while proc.returncode is None:
                peak = max(peak, await asyncio.to_thread(_rss_bytes, proc.pid))
                await asyncio.sleep(2)

        sampler = asyncio.create_task(sample())
        try:
            async for raw in proc.stdout:
                line = raw.decode(errors="replace").rstrip()
                if not line:
                    continue
                tail.append(line)
                del tail[:-60]
                if len(lines) < 400:
                    lines.append(line)
                if on_line:
                    on_line(line)
            await proc.wait()
        finally:
            sampler.cancel()
        return peak

    def remove(self) -> int:
        if self.installer.running:
            raise InstallError("The 3D component is being set up. Wait for it to finish.")
        return m3.uninstall(self.data_dir)


@contextlib.asynccontextmanager
async def _no_slot():  # type: ignore[no-untyped-def]
    yield


router = APIRouter(prefix="/desktop/model3d", tags=["desktop"])


def _service(request: Request) -> Model3dService:
    service: Model3dService | None = getattr(request.app.state, "model3d", None)
    if service is None:
        raise HTTPException(404, "not available in this deployment")
    return service


class ConfirmInstall(BaseModel):
    """What the person was shown and agreed to: the size of the download."""

    confirm_bytes: int


@router.get("")
async def model3d_state(request: Request, _: Identity = Depends(get_identity)) -> dict[str, Any]:
    return _service(request).state()


@router.post("/install", status_code=202)
async def install_model3d(
    body: ConfirmInstall, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    service = _service(request)
    try:
        service.installer.start(body.confirm_bytes)
    except InstallError as e:
        raise HTTPException(409, str(e)) from None
    return service.state()


@router.post("/install/cancel")
async def cancel_install_model3d(
    request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    service = _service(request)
    service.installer.cancel()
    return service.state()


@router.post("/uninstall")
async def uninstall_model3d(
    request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    service = _service(request)
    try:
        freed = service.remove()
    except InstallError as e:
        raise HTTPException(409, str(e)) from None
    return {"freed_bytes": freed, **service.state()}
