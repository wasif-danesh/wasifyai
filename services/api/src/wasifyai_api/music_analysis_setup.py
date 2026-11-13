# ruff: noqa: E501  (prose in the docstrings is easier to read on one line)
"""Setting up the song analysis tool (ADR-0090, CS1): beat_this, librosa and PyTorch in an environment of
their own, and the small beat model, under `<app data>/components/music-analysis/`. The same shape as
the trainers' setup (`decision_setup`): nothing is fetched before the person has seen what it is and
how large, and has agreed; the packages come from a committed hashed lock
(`scripts/lock-music-analysis.sh`) and the model file has a pinned size and SHA-256 (its part of
`components/manifests/<platform>.yaml`).

Where the tool is already on the computer (a copy named by `WASIFYAI_MUSIC_ANALYSIS_DIR`) it is used
where it is and nothing is offered."""

import asyncio
import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wasifyai_api.components.manifest import part_pins
from wasifyai_api.desktop_models import DownloadError, ModelEntry, ModelFile
from wasifyai_api.training_setup import (
    STATE_FILE,
    InstallError,
    Pins,
    TrainingSetup,
    load_pins,
)

PART = "music-analysis"  # its pins in the component manifests
LOCK_NAME = "requirements-aarch64-apple-darwin.lock"
COMPONENT = "music-analysis"
STEP_TEXT = {
    "disk": "Checking free space",
    "environment": "Preparing the tool's environment",
    "packages": "Installing the tool's packages (about 1 GB)",
    "model": "Getting the beat model",
    "check": "Checking that it starts",
}
TIMEOUT_S = 600  # a long song on a slow computer; a stuck tool must not hold a plan for ever


class AnalysisFailed(Exception):
    """The tool ran and could not read this recording, with the sentence the person is shown."""


def load_analysis_pins() -> Pins:
    return load_pins(part=PART)


def component_root(data_dir: Path) -> Path:
    return data_dir / "components" / COMPONENT


def _python_in(home: Path) -> Path:
    return home / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def find_python(data_dir: Path | None, pins: Pins | None = None) -> Path | None:
    """The Python with beat_this: a copy named by `WASIFYAI_MUSIC_ANALYSIS_DIR` (development and CI), or
    the one this app installed, when it still matches the pins."""
    env = os.environ.get("WASIFYAI_MUSIC_ANALYSIS_DIR")
    if env and _python_in(Path(env).expanduser()).is_file():
        return _python_in(Path(env).expanduser())
    if data_dir is None:
        return None
    root, pins = component_root(data_dir), pins or load_analysis_pins()
    try:
        state = json.loads((root / STATE_FILE).read_text())
    except (OSError, ValueError):
        return None
    python = _python_in(root / "venv")
    if state.get("schema") == 1 and pins.made_from(state.get("pins")) and python.is_file():
        return python
    return None


@dataclass
class MusicAnalysis(TrainingSetup):
    """The song analysis component: its setup, and running it on a recording."""

    step_text = STEP_TEXT
    pins: Pins = field(default_factory=load_analysis_pins)
    Failed = AnalysisFailed  # what `analyse` raises, for a product that cannot import this module

    @property
    def root(self) -> Path:
        return component_root(self.data_dir)

    def tool(self) -> tuple[Path, str] | None:  # type: ignore[override]
        python = find_python(self.data_dir, self.pins)
        if python is None:
            return None
        return python.parent.parent, "managed" if self.root in python.parents else "env"

    def _model_file(self) -> Path:
        p = self.pins
        return self.root / "models" / p.base_folder / p.base_files[0].path

    def base(self) -> tuple[Path, str] | None:  # type: ignore[override]
        found = self._model_file()
        try:
            whole = found.stat().st_size == self.pins.base_files[0].size
        except OSError:
            return None
        return (found.parent, "managed") if whole else None

    def ready(self) -> bool:
        return self.tool() is not None and self.base() is not None

    def problem(self) -> str | None:
        if not self.supported:
            return (
                "Finding the beats of a song works on a Mac with Apple silicon for now. Windows and "
                "Linux come later."
            )
        if self.tool() is None and (self.lock is None or not self.lock.is_file() or not self.uv):
            return "The tool that finds the beats is not part of this build."
        return None

    def plan(self) -> dict[str, Any]:
        p = self.pins
        tool, base = self.tool(), self.base()
        return {
            "supported": self.supported,
            "bytes": self.missing_bytes() if self.supported else 0,
            "needs_free_bytes": self.missing_bytes() + 1024**3,
            "parts": [
                {
                    "name": "Song analysis (beat_this, librosa and PyTorch)", "version": p.tool_version,
                    "bytes": 0 if tool else p.packages_bytes, "have": tool is not None,
                    "source": "pypi.org",
                },
                {
                    "name": p.base_title, "version": p.base_revision,
                    "bytes": 0 if base else p.base_bytes, "have": base is not None,
                    "source": "cloud.cp.jku.at",
                },
            ],
        }  # fmt: skip

    async def _get_base(self, before: int) -> None:
        """The model's file: not on the Hugging Face hub, so its address is in the pins."""
        p = self.pins
        url = str(part_pins(PART)["base"]["url"]).rstrip("/")
        entry = ModelEntry(p.base_id, "wasifyai-voice", p.base_title, "", "", 0, ())
        f = p.base_files[0]
        file = ModelFile(p.base_folder, f.path, f"{url}/{f.path}", f.size, f.sha256)
        d = self.downloads.start(entry, [file], self.root / "models")
        try:
            while d.status == "running":
                self._say("model", before + d.bytes_done)
                await asyncio.sleep(0.4)
        except asyncio.CancelledError:
            self.downloads.cancel(d.id)
            raise
        if d.status != "done":
            raise DownloadError(d.error or "The beat model could not be downloaded.")
        self._say("model", before + d.bytes_total)

    async def _check(self) -> None:
        # the record that makes it installed is written after this check: look at the folder itself
        found = self.tool()
        python = found[0] / "bin" / "python" if found else _python_in(self.root / "venv")
        if self.base() is None:
            raise InstallError("The beat model is missing. Try again.", "check")
        if not python.is_file():
            raise InstallError("The tool was installed but could not be found.", "check")
        code, out = await self.run(
            [str(python), "-I", "-c", "import beat_this, librosa, torch; print('analysis ready')"],
            self._env(),
        )
        if code != 0 or "analysis ready" not in out:
            raise InstallError("The tool was installed but did not start.", "check")

    # ---- running it ------------------------------------------------------------------------------

    async def analyse(self, audio: bytes) -> dict[str, Any]:
        """Beats, downbeats, tempo and sections of a recording (a WAV file's bytes). Runs on the
        processor in its own process, so it neither holds the graphics chip nor blocks the engine."""
        found, model = self.tool(), self.base()
        if found is None or model is None:
            raise AnalysisFailed("Song analysis is not set up yet.")
        python = found[0] / "bin" / "python"
        worker = Path(__file__).with_name("music_analysis_worker.py")
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="wasify-analysis-") as tmp:
            song, out = Path(tmp) / "song.wav", Path(tmp) / "out.json"
            await asyncio.to_thread(song.write_bytes, audio)
            proc = await asyncio.create_subprocess_exec(
                str(python), "-I", str(worker), str(song), str(self._model_file()), str(out),
                env=self._env(), stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )  # fmt: skip
            try:
                said, _ = await asyncio.wait_for(proc.communicate(), TIMEOUT_S)
            except BaseException:
                proc.kill()
                await proc.wait()
                raise
            if proc.returncode != 0 or not out.is_file():
                tail = said.decode(errors="replace")[-300:]
                raise AnalysisFailed(f"The beats of this recording could not be found. ({tail})")
            result = json.loads(await asyncio.to_thread(out.read_text))
        return result | {"elapsed_s": round(time.monotonic() - started, 2)}
