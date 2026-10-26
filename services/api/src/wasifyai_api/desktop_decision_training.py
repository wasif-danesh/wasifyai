# ruff: noqa: E501  (prose in the docstrings and a script in a string are easier to read on one line)
"""The decision training engine of the desktop profile (ADR-0075, ADR-0073).

On a Mac with Apple silicon it is Laya (Apache-2.0) on PyTorch, which uses the graphics chip. It runs
as a separate process of its own: `decision_train.py` reads a job (the question, the examples, the
texts to check on) and prints what the model said before it was taught, its progress, and what it says
after; `decision_answer.py` asks a finished model about some texts. This module builds the job, reads
the events, keeps the model and turns the raw answers into `Said`. It holds the one big-model slot
while it runs (ADR-0056) and kills the process group when the run is stopped.

Laya teaches the whole model (it is 420 million numbers, not a large language model), so the result
is a full copy of it, about 840 MB, not a small adapter; the spike's Studio route did the same
(docs/spikes/training-t0.md, section 5). The model's files must already be on the computer: nothing is
downloaded silently."""

import asyncio
import contextlib
import json
import os
import shutil
import signal
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from wasifyai_api.decision_setup import find_model, find_python
from wasifyai_api.desktop_fit import assess_fit, need_declared, read_machine
from wasifyai_api.desktop_models import free_disk_bytes
from wasifyai_api.desktop_training import _kill_group, _no_slot, process_footprint
from wasifyai_api.training_setup import apple_silicon

ENGINE = "laya"
TRAIN_SCRIPT = Path(__file__).with_name("decision_train.py")
ANSWER_SCRIPT = Path(__file__).with_name("decision_answer.py")
RUN_DISK_BYTES = 3 * 1024**3  # the model is copied (840 MB), and the trainer keeps a copy per pass
HEADROOM_GB = 2.0

Report = Callable[[int, str], None]


def to_job(job: Any, base: Path, out: Path) -> dict[str, Any]:
    """The job file `decision_train.py` reads."""
    q = job.question
    return {
        "base": str(base), "out": str(out), "question": q.laya(),
        "train": [{"text": r.text, "expected": q.expected(r.answer)} for r in job.train],
        "held": [r.text for r in job.held], "peek": list(job.peek),
        "epochs": job.epochs, "batch": 8, "steps": job.steps, "seed": 3407,
    }  # fmt: skip


class LayaTrainer:
    """`DecisionJob` in, `DecisionResult` out."""

    preview = False
    engine = ENGINE

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir
        self.slot: Any = None  # the SlotManager: a run holds the one big-model slot
        self._proc: asyncio.subprocess.Process | None = None
        self._stopping = False
        self.peak_bytes = 0

    # ---- what the product asks ---------------------------------------------------------------

    def problem(self, base_id: str | None = None) -> str | None:
        if not apple_silicon():
            return (
                "Teaching it to decide works on a Mac with Apple silicon for now. Windows and "
                "Linux (with an NVIDIA graphics card) come later."
            )
        if find_python(self.data_dir) is None:
            return "Training is not set up on this computer yet. Set it up first."
        if base_id is not None and find_model(self.data_dir, base_id) is None:
            return "The model to teach is not on this computer yet."
        return None

    def ready(self, base_id: str | None = None) -> bool:
        return self.problem(base_id) is None

    def fit(self, need_gb: float) -> dict[str, Any]:
        return assess_fit(need_declared(need_gb + HEADROOM_GB), read_machine()).public()

    def base_folder(self, base_id: str) -> Path | None:
        """Where a model to teach is on this computer, or None."""
        return find_model(self.data_dir, base_id)

    def state(self) -> dict[str, Any]:
        return {"engine": self.engine, "preview": False, "setup": self.problem()}

    @property
    def busy(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def stop(self) -> None:
        """Let go of memory for another model: a run in progress is stopped."""
        self._stopping = True
        if self.busy and self._proc is not None:
            _kill_group(self._proc.pid)

    def preflight_blockers(self) -> list[str]:
        if free_disk_bytes(self.data_dir or Path.home()) < RUN_DISK_BYTES:
            return ["There is not enough free disk space for a run. Free up 3 GB first."]
        return []

    # ---- a run --------------------------------------------------------------------------------

    async def train(self, job: Any, base_id: str, folder: Path, report: Report) -> Any:
        """Teach `base_id` and keep the model in `folder / "model"`. Raises `Stopped` when stopped
        and `RuntimeError` with a sentence when the tool fails."""
        from wasifyai_training.decision import DecisionResult

        python, base = find_python(self.data_dir), find_model(self.data_dir, base_id)
        if python is None or base is None:
            raise RuntimeError(self.problem(base_id) or "Training is not set up.")
        started = time.monotonic()
        out = folder / "model"
        await asyncio.to_thread(shutil.rmtree, out, True)
        await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
        cfg = folder / "job.json"
        await asyncio.to_thread(cfg.write_text, json.dumps(to_job(job, base, out)))
        self._stopping = False
        got: dict[str, Any] = {"loss": []}
        try:
            await self._run(python, cfg, job, report, got)
        finally:
            await asyncio.to_thread(cfg.unlink, True)
        weights = out / "model.safetensors"
        if not weights.is_file() or not {"before", "after"} <= got.keys():
            raise RuntimeError("The training tool finished without a model.")
        q = job.question

        def read(raws: list[dict[str, Any]]) -> list[Any]:
            return [q.read(r) for r in raws]

        return DecisionResult(
            out, time.monotonic() - started, self.engine,
            before=read(got["before"]["held"]), after=read(got["after"]["held"]),
            peek_before=read(got["before"]["peek"]), peek_after=read(got["after"]["peek"]),
            loss=got["loss"], peak_bytes=self.peak_bytes, bytes=weights.stat().st_size,
        )  # fmt: skip

    async def _run(
        self, python: Path, cfg: Path, job: Any, report: Report, got: dict[str, Any]
    ) -> None:
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "HF_HUB_OFFLINE": "1"}
        report(0, "Loading the model")
        tail: list[str] = []
        self.peak_bytes = 0
        holder = self.slot.hold("training") if self.slot is not None else _no_slot()
        async with holder:
            proc = await asyncio.create_subprocess_exec(
                str(python), "-I", str(TRAIN_SCRIPT), "-c", str(cfg),
                env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                stdin=asyncio.subprocess.DEVNULL, start_new_session=True,
                limit=64 * 1024**2,  # the answers on the held-out texts come in one line
            )  # fmt: skip
            self._proc = proc
            sampler = asyncio.create_task(self._sample_memory(proc))
            step = 0
            try:
                assert proc.stdout is not None
                async for raw in proc.stdout:
                    line = raw.decode(errors="replace").strip()
                    if not line:
                        continue
                    tail.append(line[:200])
                    del tail[:-20]
                    if not line.startswith("{"):
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    match event.get("event"):
                        case "status":
                            report(step, str(event.get("message", "")))
                        case "progress":
                            step = min(int(event["step"]), job.steps)
                            report(step, f"Learning, step {step} of {job.steps}")
                        case "epoch":
                            got["loss"].append(float(event["loss"]))
                        case "before" | "after" as kind:
                            got[kind] = event
                await proc.wait()
            except asyncio.CancelledError:
                _kill_group(proc.pid)
                await proc.wait()
                raise
            finally:
                sampler.cancel()
                self._proc = None
        if self._stopping:
            from wasifyai_training.language import Stopped

            raise Stopped("It was stopped, so nothing was kept.")
        if proc.returncode != 0:
            raise RuntimeError("The training tool stopped with an error: " + " | ".join(tail[-4:]))

    async def _sample_memory(self, proc: asyncio.subprocess.Process) -> None:
        while proc.returncode is None:
            held = await asyncio.to_thread(process_footprint, proc.pid)
            self.peak_bytes = max(self.peak_bytes, held)
            await asyncio.sleep(3)

    # ---- how it answers ------------------------------------------------------------------------

    async def answer(self, model: Path, question: Any, texts: list[str]) -> list[Any]:
        """The model in `model` (a taught one, or a base) answering `question` about each of
        `texts`, as `Said`. Raises `RuntimeError` with a sentence when it cannot be run."""
        python = find_python(self.data_dir)
        if python is None:
            raise RuntimeError(self.problem() or "Training is not set up.")
        if not texts:
            return []
        spec = json.dumps({"model": str(model), "question": question.laya(), "texts": texts})
        env = {**os.environ, "HF_HUB_OFFLINE": "1"}
        holder = self.slot.hold("training") if self.slot is not None else _no_slot()
        async with holder:
            proc = await asyncio.create_subprocess_exec(
                str(python), "-I", str(ANSWER_SCRIPT), spec,
                env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL, start_new_session=True,
                limit=256 * 1024**2,
            )  # fmt: skip
            try:
                out, err = await proc.communicate()
            except asyncio.CancelledError:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGTERM)
                raise
        if proc.returncode != 0:
            raise RuntimeError(
                "The model could not answer: " + err.decode(errors="replace").strip()[-200:]
            )
        last = out.decode(errors="replace").strip().splitlines()[-1]
        return [question.read(r) for r in json.loads(last)["answers"]]


def make_decision_trainer(data_dir: Path | None) -> LayaTrainer | None:
    """The decision trainer of this engine, or None when the training product is absent."""
    try:
        import wasifyai_training  # noqa: F401
    except ImportError:
        return None
    return LayaTrainer(data_dir)
