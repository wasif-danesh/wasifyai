# ruff: noqa: E501
"""The trainers a worker runs for the web (ADR-0073 amendment 2026-10-27, `docs/train-web-plan.md`): the desktop's own engine classes,
on this worker's data folder. Each is a component the worker lists, with what the API needs to decide whether it can take a run."""

import asyncio
import hashlib
import re
import shutil
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk import object_key, train_wire

# what a run of each family asks of the computer, in GB (the descriptors in `wasifyai_training.bases`); the
# picture trainer reads its own figure
NEED_GB = {"video": 12.0, "decision": 11.0, "writing": 4.0}


class ModelCache:
    """Taught models fetched from a person's own part of storage for asking, kept for the next question.
    A decision model is about 850 MB: it is fetched once, and the least recently used are dropped."""

    def __init__(self, root: Path, keep: int = 3):
        self._root = root
        self._keep = keep

    async def folder(self, storage: Any, tenant: str, user: str, model_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", model_id):
            raise ValueError("not a model")
        prefix = (
            object_key(tenant, "wasifyai-training", user, "train", "models", model_id) + "/model/"
        )
        who = hashlib.sha256(f"{tenant}/{user}".encode()).hexdigest()[:12]
        folder = self._root / who / model_id
        mark = folder / ".whole"
        if not mark.is_file():
            keys = await storage.list(prefix)
            if not keys:
                raise FileNotFoundError(model_id)
            await asyncio.to_thread(shutil.rmtree, folder, True)
            for key in keys:
                rel = key[len(prefix) :]
                if not rel or ".." in rel:
                    continue
                target = folder / rel
                await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
                await asyncio.to_thread(target.write_bytes, await storage.get(key))
            await asyncio.to_thread(mark.write_text, "1")
        await asyncio.to_thread(mark.touch)  # used now
        await asyncio.to_thread(self._trim, folder)
        return folder

    def _trim(self, current: Path) -> None:
        made = sorted(
            (p for p in self._root.glob("*/*") if (p / ".whole").is_file()),
            key=lambda p: (p / ".whole").stat().st_mtime,
        )
        for old in made[: -self._keep]:
            if old != current:
                shutil.rmtree(old, ignore_errors=True)


class TrainComponents:
    """`video` and `image` (and later `decision`, `writing`): the engine of each family, or None where it is not
    here, with the set-up an admin can start for it."""

    def __init__(
        self,
        video: Any = None,
        image: Any = None,
        decision: Any = None,
        writing: Any = None,
        setups: dict[str, Any] | None = None,
        cache: ModelCache | None = None,
    ):
        self.video = video
        self.image = image
        self.decision = decision
        self.writing = writing
        self.cache = cache
        self.setups = setups or {}  # component key -> its set-up (plan, install)

    def kinds(self) -> list[str]:
        out: list[str] = []
        if self.video is not None:
            out.append(train_wire.VIDEO)
        if self.image is not None:
            out += [train_wire.IMAGE, train_wire.IMAGE_TOKENIZE]
        if self.decision is not None:
            out += [train_wire.DECISION, train_wire.DECISION_ANSWER]
        if self.writing is not None:
            out += [train_wire.WRITING, train_wire.WRITING_ANSWER]
        return out

    @staticmethod
    def _words(problem: str | None) -> str | None:
        """The engine's sentence for the desktop, said for a worker (an admin sets it up, not the person)."""
        if not problem:
            return problem
        return (
            problem.replace(
                "Choose Select video model on a Video screen to get it.",
                "Ask an admin to get the video model onto the worker.",
            )
            .replace("Set it up first.", "Ask an admin to set it up on the worker.")
            .replace("this computer", "the worker")
        )

    def _state(self, name: str, key: str, trainer: Any) -> dict[str, Any]:
        ready = trainer.ready()
        need = NEED_GB.get(name)
        args = (need,) if need is not None else ()
        out: dict[str, Any] = {
            "ready": ready,
            "problem": self._words(trainer.problem()),
            "fit": trainer.fit(*args) if ready else None,
            "preflight": (
                trainer.preflight(*args) if ready and hasattr(trainer, "preflight") else None
            ),
            "state": trainer.state(),
        }
        setup = self.setups.get(key)
        if setup is not None:  # what setting it up would fetch, for the admin's button
            try:
                plan = setup.plan()
                out["setup"] = {"supported": bool(plan["supported"]), "bytes": int(plan["bytes"])}
            except Exception:
                out["setup"] = None
        if name in ("decision", "writing"):  # which of the models it can teach are on this worker
            from wasifyai_training import bases

            out["bases"] = {
                d.id: bool(trainer.ready(d.id))
                for d in bases.descriptors("decision" if name == "decision" else "language")
            }
        return out

    def components(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.video is not None:
            out[train_wire.COMPONENT_VIDEO] = self._state("video", "video-trainer", self.video)
        if self.image is not None:
            out[train_wire.COMPONENT_IMAGE] = self._state("image", "image-trainer", self.image)
        if self.decision is not None:
            out[train_wire.COMPONENT_DECISION] = self._state(
                "decision", "decision-trainer", self.decision
            )
        if self.writing is not None:
            out[train_wire.COMPONENT_WRITING] = self._state(
                "writing", "writing-trainer", self.writing
            )
        return out

    def trainer_of(self, kind: str) -> Any:
        if kind == train_wire.VIDEO:
            return self.video
        if kind in (train_wire.IMAGE, train_wire.IMAGE_TOKENIZE):
            return self.image
        if kind in (train_wire.DECISION, train_wire.DECISION_ANSWER):
            return self.decision
        return self.writing if kind in (train_wire.WRITING, train_wire.WRITING_ANSWER) else None

    async def stop(self, kind: str) -> None:
        trainer = self.trainer_of(kind)
        if trainer is not None:
            await trainer.stop()
