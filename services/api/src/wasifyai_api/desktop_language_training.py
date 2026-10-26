"""The language training engine of the desktop profile (ADR-0074, ADR-0073).

On a Mac with Apple silicon it is `mlx-lm` (MIT), run as a separate process of its own:
`mlx_lm.lora` (through `language_train.py`, which switches thinking off in the chat template so
that what is learnt is what chat serves) reads a folder of chat records, writes an adapter as it
goes and reports the loss.
This module builds
the data folder and the config, reads the progress and the losses, keeps the adapter and asks the
same environment how a model answers (before and after). It holds the one big-model slot while it
runs (ADR-0056) and kills the process group when the run is stopped.

The engine of ADR-0074 decision 3 is Unsloth's MLX backend, with `mlx-lm` as the named fallback. The
fallback is used first because the spike (docs/spikes/training-t0.md) measured it at 0.06 s a step
and 0.98 GB on Qwen3-0.6B against 0.31 s and 1.19 GB, and because it is one MIT package instead of a
2.1 GB AGPL environment; it needs 6.3 GB on a Qwen3.5 0.8B where Unsloth needs 1.8 GB, which
the base
descriptor records. Both write a standard adapter, so the result format does not change.

The base model's files must already be on the computer: nothing is downloaded silently."""

import asyncio
import contextlib
import json
import os
import re
import shutil
import signal
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from wasifyai_api.desktop_fit import assess_fit, need_declared, read_machine
from wasifyai_api.desktop_models import free_disk_bytes
from wasifyai_api.desktop_training import _kill_group, _no_slot, process_footprint
from wasifyai_api.language_setup import find_model as find_base
from wasifyai_api.language_setup import find_python
from wasifyai_api.training_setup import apple_silicon

ENGINE = "mlx-lm"
ANSWER_SCRIPT = Path(__file__).with_name("language_answer.py")
TRAIN_SCRIPT = Path(__file__).with_name("language_train.py")  # `mlx_lm lora`, thinking off
RANK = 16
LEARNING_RATE = 2e-4  # the spike's: it learned the style in 30 steps
MAX_SEQ = 1024
RUN_DISK_BYTES = 1024**3  # an adapter is tens of megabytes; checkpoints and the data a little more
CHECKPOINT_EVERY = 25
# the machine's memory a run needs beyond the model, by the spike: 1 GB for a 0.6B 4-bit model; the
# base descriptor says the model's own need
HEADROOM_GB = 2.0

_VAL = re.compile(r"Iter (\d+): Val loss ([\d.]+)")


Report = Callable[[int, str], None]


def config_for(
    job: Any, base: Path, data: Path, adapter: Path, *, resume: Path | None = None
) -> dict[str, Any]:
    """The `mlx_lm.lora` config: LoRA at rank 16 on every projection of every layer (on a 4-bit base
    that is QLoRA), the answer only in the loss, and a held-out loss before and after."""
    layers = json.loads((base / "config.json").read_text()).get("num_hidden_layers", 28)
    every = max(10, job.steps // 4)
    config: dict[str, Any] = {
        "model": str(base), "train": True, "data": str(data), "fine_tune_type": "lora",
        "num_layers": int(layers), "batch_size": job.batch, "iters": job.steps,
        "learning_rate": LEARNING_RATE, "max_seq_length": MAX_SEQ, "mask_prompt": True,
        "steps_per_report": 1, "steps_per_eval": every, "val_batches": -1,
        "save_every": CHECKPOINT_EVERY, "seed": 3407, "grad_checkpoint": True,
        "adapter_path": str(adapter),
        "lora_parameters": {
            "rank": RANK, "scale": 1.0, "dropout": 0.0,
            "keys": ["self_attn.q_proj", "self_attn.k_proj", "self_attn.v_proj",
                     "self_attn.o_proj", "mlp.gate_proj", "mlp.up_proj", "mlp.down_proj"],
        },
    }  # fmt: skip
    if resume is not None:
        config["resume_adapter_file"] = str(resume)
    return config


def write_data(job: Any, data: Path) -> None:
    data.mkdir(parents=True, exist_ok=True)
    for name, rows in (("train", job.train), ("valid", job.valid)):
        text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
        (data / f"{name}.jsonl").write_text(text, encoding="utf-8")


def parse_line(line: str) -> dict[str, float] | None:
    """What an `mlx_lm.lora` line says: `{step, train}` or `{step, val}`, with the peak memory (GB)
    when the line has it; None for any other line."""
    if (m := _VAL.search(line)) is not None:
        return {"step": int(m.group(1)), "val": float(m.group(2))}
    if line.startswith("Iter") and "Train loss" in line:
        step = re.match(r"Iter (\d+):", line)
        loss = re.search(r"Train loss ([\d.]+)", line)
        peak = re.search(r"Peak mem ([\d.]+) GB", line)
        if step and loss:
            out = {"step": int(step.group(1)), "train": float(loss.group(1))}
            if peak:
                out["peak_gb"] = float(peak.group(1))
            return out
    return None


class MlxLmTrainer:
    """`LanguageJob` in, `LanguageResult` out."""

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
                "Teaching a writing model works on a Mac with Apple silicon for now. Windows and "
                "Linux (with an NVIDIA graphics card) come later."
            )
        if find_python(self.data_dir) is None:
            return "Training is not set up on this computer yet. Set it up first."
        if base_id is not None and find_base(self.data_dir, base_id) is None:
            return "The model to teach is not on this computer yet."
        return None

    def ready(self, base_id: str | None = None) -> bool:
        return self.problem(base_id) is None

    def fit(self, need_gb: float) -> dict[str, Any]:
        return assess_fit(need_declared(need_gb + HEADROOM_GB), read_machine()).public()

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
            return ["There is not enough free disk space for a run. Free up 1 GB first."]
        return []

    # ---- a run --------------------------------------------------------------------------------

    async def train(self, job: Any, base_id: str, folder: Path, report: Report) -> Any:
        """Teach `base_id` and keep the adapter in `folder / "adapter"`. Raises `Stopped` when
        stopped
        and `RuntimeError` with a sentence when the tool fails."""
        from wasifyai_training.language import LanguageResult

        python, base = find_python(self.data_dir), find_base(self.data_dir, base_id)
        if python is None or base is None:
            raise RuntimeError(self.problem(base_id) or "Training is not set up.")
        started = time.monotonic()
        data, adapter = folder / "data", folder / "adapter"
        for old in (data, adapter):
            await asyncio.to_thread(shutil.rmtree, old, True)
        await asyncio.to_thread(write_data, job, data)
        config = config_for(job, base, data, adapter)
        cfg = folder / "train.json"
        await asyncio.to_thread(cfg.write_text, json.dumps(config, indent=2))
        self._stopping = False
        losses: dict[str, float | None] = {"first_val": None, "last_val": None, "last_train": None}
        await self._run(python, cfg, job, report, losses)
        if not (adapter / "adapters.safetensors").is_file():
            raise RuntimeError("The training tool finished without an adapter.")
        return LanguageResult(
            adapter, time.monotonic() - started, self.engine,
            first_val=losses["first_val"], last_val=losses["last_val"],
            last_train=losses["last_train"], peak_bytes=self.peak_bytes,
        )  # fmt: skip

    async def _run(
        self, python: Path, cfg: Path, job: Any, report: Report,
        losses: dict[str, float | None],
    ) -> None:  # fmt: skip
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
            )  # fmt: skip
            self._proc = proc
            sampler = asyncio.create_task(self._sample_memory(proc))
            try:
                assert proc.stdout is not None
                async for raw in proc.stdout:
                    line = raw.decode(errors="replace").strip()
                    if not line:
                        continue
                    tail.append(line[:200])
                    del tail[:-20]
                    got = parse_line(line)
                    if got is None:
                        continue
                    if "val" in got:
                        if losses["first_val"] is None:
                            losses["first_val"] = got["val"]
                        losses["last_val"] = got["val"]
                    else:
                        losses["last_train"] = got["train"]
                        step = min(int(got["step"]), job.steps)
                        report(step, f"Learning, step {step} of {job.steps}")
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
            await asyncio.sleep(5)

    # ---- how it answers ------------------------------------------------------------------------

    async def answer(
        self, base_id: str, questions: list[str], adapter: Path | None = None, max_tokens: int = 120
    ) -> list[str]:
        """The model's answers to `questions`, with the adapter or without it (greedy, no thinking).
        Raises `RuntimeError` with a sentence when the model cannot be run."""
        python, base = find_python(self.data_dir), find_base(self.data_dir, base_id)
        if python is None or base is None:
            raise RuntimeError(self.problem(base_id) or "Training is not set up.")
        spec = json.dumps({
            "model": str(base), "adapter": str(adapter) if adapter else None,
            "questions": questions, "max_tokens": max_tokens,
        })  # fmt: skip
        env = {**os.environ, "HF_HUB_OFFLINE": "1"}
        holder = self.slot.hold("training") if self.slot is not None else _no_slot()
        async with holder:
            proc = await asyncio.create_subprocess_exec(
                str(python), "-I", str(ANSWER_SCRIPT), spec,
                env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL, start_new_session=True,
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
        return list(json.loads(last)["answers"])


def make_language_trainer(data_dir: Path | None) -> MlxLmTrainer | None:
    """The language trainer of this engine, or None when the training product is absent."""
    try:
        import wasifyai_training  # noqa: F401
    except ImportError:
        return None
    return MlxLmTrainer(data_dir)
