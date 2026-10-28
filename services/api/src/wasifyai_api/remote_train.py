# ruff: noqa: E501  (the sentences shown to people are easier to read on one line)
"""Teaching models for the web, run by an engine worker (ADR-0073 amendment 2026-10-27, `docs/train-web-plan.md`).

The training product asks its engine to teach a model. On the desktop that engine runs the trainer on this computer. Here it
queues a job: the pictures and clips go to the person's own part of object storage, a worker that has the trainer's component
runs the same desktop engine class, and the adapter it leaves is read back. The shape of the answers is the desktop engine's
(`VideoResult`), so the product's managers did not change."""

import asyncio
import contextlib
import logging
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from wasifyai_platform_sdk import (
    EngineJob,
    EngineQueue,
    EngineUnavailable,
    require_context,
    train_wire,
)
from wasifyai_platform_sdk.jobpolicy import JobLimitReached
from wasifyai_platform_sdk.storage import object_key

from wasifyai_api.engine_workers import WorkerDirectory, record_engine_seconds

log = logging.getLogger("wasifyai_api.remote_train")

TRAIN_TIMEOUT_S = (
    4 * 3600
)  # a run is planned to take two hours at most; the worker's own limit is looser


class Failed(Exception):
    def __init__(self, code: str, message: str, seconds: float = 0.0):
        super().__init__(message)
        self.code, self.message, self.seconds = code, message, seconds


class RemoteTrainer:
    """What every remote trainer shares: the state of the component it needs, and a job that is queued and waited for."""

    preview = False
    place = "service"  # the work is done on a worker, not on this computer
    component = ""  # the key of the worker's `components` entry

    def __init__(
        self, queue: EngineQueue, storage: Any, directory: WorkerDirectory, usage: Any = None,
        files: Any = None,
    ):  # fmt: skip
        self._queue = queue
        self._storage = storage  # the raw `Storage` (keys carry the tenant prefix)
        self._directory = directory
        self._usage = usage
        self._files = files  # `StorageFiles`, for what a trainer keeps beside its model
        self.closing = (
            False  # set when this service is stopping: jobs go on, nobody is told to stop
        )
        self._job: str | None = (
            None  # the job a run is waiting for (one at a time, as on the desktop)
        )
        self.kept: dict[str, str] = {}  # outputs the last job left in storage: name -> key

    # ---- what the product asks before it starts ---------------------------------------------

    def _component(self) -> dict[str, Any] | None:
        return self._directory.component(self.component)

    def problem(self, base_id: str | None = None) -> str | None:
        if not self._directory.workers:
            return "The training worker is not running. Try again in a moment."
        c = self._component()
        if c is None:
            return "No worker here can teach this kind of model. Ask an admin to set it up."
        if c.get("ready"):
            return None
        return str(c.get("problem") or "Training is not set up on the worker. Ask an admin.")

    def ready(self, base_id: str | None = None) -> bool:
        return self.problem(base_id) is None

    def fit(self, need_gb: float = 0.0) -> dict[str, Any]:
        c = self._component() or {}
        return c.get("fit") or {"verdict": "fits", "reason": ""}  # type: ignore[no-any-return]

    def preflight(self, need_gb: float = 0.0) -> dict[str, Any]:
        c = self._component() or {}
        return c.get("preflight") or {  # type: ignore[no-any-return]
            "ok": True, "blockers": [], "warnings": [],
            "pauses": "The worker's graphics chip is busy while it learns.",
        }  # fmt: skip

    def preflight_blockers(self) -> list[str]:
        return list(self.preflight().get("blockers", []))

    def state(self) -> dict[str, Any]:
        c = self._component() or {}
        return c.get("state") or {"engine": "worker", "preview": False}  # type: ignore[no-any-return]

    async def stop(self) -> None:
        """Stop the run in progress: the worker is told to end its process and the wait ends `cancelled`."""
        if self._job is not None:
            await self._queue.cancel(self._job)

    # ---- the work ---------------------------------------------------------------------------

    async def _submit(self, job: EngineJob, **kw: Any) -> None:
        """Queue a job; a person who already has one in the line is told so, in the policy's
        words, as this job's own failure (ADR-0088)."""
        try:
            await self._queue.submit(job, **kw)
        except JobLimitReached as e:
            raise Failed("busy", e.message) from None

    async def _run(
        self,
        kind: str,
        params: dict[str, Any],
        files: dict[str, Path],
        on_progress: Callable[[float, str], None] | None = None,
        job_key: str | None = None,
        poll: Callable[[str], Awaitable[None]] | None = None,
        keep: str | None = None,
    ) -> tuple[dict[str, bytes], dict[str, Any]]:
        """Queue a job and wait for it; the outputs come back as bytes."""
        ctx = require_context()
        job_id = job_key or str(uuid4())
        prefix = object_key(ctx.tenant_id, ctx.product_id, ctx.user_id, "engine", job_id)
        keys: dict[str, str] = {}
        staged: list[str] = []
        try:
            for name, path in files.items():
                key = f"{prefix}/in/{name}"
                await self._storage.put(
                    key, await asyncio.to_thread(path.read_bytes), "application/octet-stream"
                )
                staged.append(key)
                keys[name] = key
            await self._submit(
                EngineJob(
                    id=job_id, kind=kind, tenant_id=ctx.tenant_id, product_id=ctx.product_id,
                    user_id=ctx.user_id, prefix=prefix, params=params, files=keys,
                ),
                timeout_s=TRAIN_TIMEOUT_S,  # its lease lasts as long as teaching may (ADR-0088)
            )  # fmt: skip
            self._job = job_id

            async def told(fraction: float, label: str) -> None:
                if on_progress is not None:
                    on_progress(fraction, label)
                if poll is not None:  # what the worker has made so far (sample pictures)
                    await poll(prefix)

            try:
                outcome = await self._queue.wait(job_id, TRAIN_TIMEOUT_S, told)
            except asyncio.CancelledError:
                if not self.closing:
                    await asyncio.shield(self._queue.cancel(job_id))
                raise
            except EngineUnavailable:
                await asyncio.shield(self._queue.cancel(job_id))
                raise Failed("wall_time", "The training worker took too long. Try again.") from None
            await record_engine_seconds(self._usage, ctx, kind, outcome)
            if not outcome.ok:
                err = outcome.error
                raise Failed(
                    err.code if err else "failed",
                    err.message if err else "The training worker could not do that.",
                    outcome.seconds,
                )
            # what a worker made that is too big to pass through here stays in storage, to be moved
            self.kept = {n: k for n, k in outcome.outputs.items() if keep and n.startswith(keep)}
            fetched = {n: k for n, k in outcome.outputs.items() if n not in self.kept}
            staged.extend(fetched.values())
            out = {name: await self._storage.get(key) for name, key in fetched.items()}
            return out, outcome.meta
        finally:
            self._job = None
            for key in staged:
                with contextlib.suppress(Exception):
                    await self._storage.delete(key)


class RemoteVideoTrainer(RemoteTrainer):
    """`VideoJob` in, `VideoResult` out, like `LtxTrainer`; the look is kept in storage, not in a shared folder."""

    component = train_wire.COMPONENT_VIDEO
    engine = "diffusers"

    async def train(self, job: Any, folder: Path, report: Callable[[int, str], None]) -> Any:
        from wasifyai_training.trainer import Stopped
        from wasifyai_training.video import VideoResult

        names = [f"m{n}{m.path.suffix}" for n, m in enumerate(job.media)]
        files = {name: m.path for name, m in zip(names, job.media, strict=True)}
        params = {
            "items": [
                {"name": name, "kind": m.kind, "caption": m.caption, "seconds": m.seconds}
                for name, m in zip(names, job.media, strict=True)
            ],
            "width": job.width, "height": job.height, "window_frames": job.window_frames,
            "steps": job.steps, "checkpointing": job.checkpointing, "rank": job.rank,
            "lr": job.lr, "word": job.word,
        }  # fmt: skip

        def told(fraction: float, label: str) -> None:
            report(round(fraction * job.steps), label)

        report(0, "Waiting for the training worker")
        try:
            out, meta = await self._run(train_wire.VIDEO, params, files, told, folder.name)
        except Failed as e:
            if e.code == "cancelled":
                raise Stopped("It was stopped, so nothing was kept.") from None
            raise RuntimeError(e.message) from None
        adapter = folder / "out" / "pytorch_lora_weights.safetensors"
        await asyncio.to_thread(adapter.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(adapter.write_bytes, out["adapter"])
        return VideoResult(
            adapter, float(meta.get("seconds", 0.0)), self.engine,
            peak_bytes=int(meta.get("peak_bytes", 0)), loss_first=meta.get("loss_first"),
            loss_last=meta.get("loss_last"),
        )  # fmt: skip

    # ---- the look: kept for the person, given to a worker for one job at a time ---------------

    async def publish(self, adapter: Path, title: str, run_id: str) -> str | None:
        """The adapter in ComfyUI's key names, kept under the person's own prefix: the name a video
        workflow is given; the media job fetches the file by it (never shared with anyone else)."""
        from wasifyai_training import ltx_lora

        ctx = require_context()
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "model"
        name = f"wasify-video-{slug}-{run_id[:8]}.safetensors"
        converted = adapter.with_name(name)
        await asyncio.to_thread(ltx_lora.convert, adapter, converted)
        key = look_key(ctx.tenant_id, ctx.user_id, run_id, name)
        await self._storage.put(
            key, await asyncio.to_thread(converted.read_bytes), "application/octet-stream"
        )
        await asyncio.to_thread(converted.unlink, True)
        return name

    async def unpublish(self, name: str) -> None:
        return None  # `delete_model` removes the person's looks folder with the model


def look_key(tenant: str, user: str, run_id: str, name: str) -> str:
    """Where the look a run made is kept in object storage."""
    return f"{object_key(tenant, 'wasifyai-training', user, 'train', 'looks', run_id)}/{name}"


class UnservedTrainer(RemoteTrainer):
    """A family no worker can teach yet (`docs/train-web-plan.md`, WT2 to WT4): the screen says so in words and offers nothing."""

    engine = "worker"

    def __init__(self, component: str, *args: Any, **kw: Any):
        super().__init__(*args, **kw)
        self.component = component

    async def train(self, *args: Any, **kw: Any) -> Any:
        raise RuntimeError("This kind of model cannot be taught on the web yet.")


class RemoteImageTrainer(RemoteTrainer):
    """`TrainJob` in, `TrainResult` out, like `MfluxTrainer`; the style is kept in storage, not in a shared folder."""

    component = train_wire.COMPONENT_IMAGE
    engine = "mflux"

    def __init__(self, *args: Any, **kw: Any):
        super().__init__(*args, **kw)
        from wasifyai_training.trainer import BASE

        self.base = BASE
        self._words: dict[str, dict[str, Any]] = {}

    async def train(
        self,
        job: Any,
        report: Callable[[int, str], None],
        sample: Callable[[str], None],
        resume: bool = False,
    ) -> Any:
        from wasifyai_training.trainer import Stopped, TrainResult

        if resume:
            raise RuntimeError("A run cannot be picked up again on the web. Start it again.")
        names = [f"p{n}.png" for n in range(len(job.pictures))]
        params = {
            "kind": job.kind, "word": job.word, "steps": job.steps, "pictures": names,
            "captions": job.captions, "settings": job.settings,
        }  # fmt: skip
        folder = job.samples.parent
        await asyncio.to_thread(job.samples.mkdir, parents=True, exist_ok=True)
        seen: set[str] = set()

        async def poll(prefix: str) -> None:
            for key in await self._storage.list(f"{prefix}/out/samples/"):
                name = key.rsplit("/", 1)[1]
                if name not in seen and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", name):
                    seen.add(name)
                    data = await self._storage.get(key)
                    await asyncio.to_thread((job.samples / name).write_bytes, data)
                    sample(name)

        def told(fraction: float, label: str) -> None:
            report(round(fraction * job.steps), label)

        report(0, "Waiting for the training worker")
        try:
            out, meta = await self._run(
                train_wire.IMAGE, params, dict(zip(names, job.pictures, strict=True)), told,
                folder.name, poll,
            )  # fmt: skip
        except Failed as e:
            if e.code == "cancelled":
                raise Stopped("It was stopped, so nothing was kept.") from None
            raise RuntimeError(e.message) from None
        for key, data in out.items():  # samples made after the last progress report
            name = key.removeprefix("samples/")
            if key.startswith("samples/") and name not in seen:
                seen.add(name)
                await asyncio.to_thread((job.samples / name).write_bytes, data)
                sample(name)
        adapter = folder / "adapter.safetensors"
        await asyncio.to_thread(adapter.write_bytes, out["adapter"])
        return TrainResult(
            adapter, float(meta.get("seconds", 0.0)), self.engine,
            peak_bytes=int(meta.get("peak_bytes", 0)),
        )  # fmt: skip

    async def tokenize(self, words: list[str]) -> dict[str, dict[str, Any]] | None:
        """How the picture model's tokenizer splits each word (asked of a worker; None when it
        cannot answer soon: the sound rules of the magic word still apply)."""
        todo = [w for w in dict.fromkeys(words) if w not in self._words]
        if todo and self.ready():
            job_id = str(uuid4())
            try:
                await self._submit(
                    EngineJob(
                        id=job_id, kind=train_wire.IMAGE_TOKENIZE, tenant_id="system",
                        product_id="wasifyai-training", user_id="system",
                        prefix=object_key("system", "wasifyai-training", "system", "engine", job_id),
                        params={"words": todo},
                    )
                )  # fmt: skip
                outcome = await self._queue.wait(job_id, 20)
            except EngineUnavailable:
                await self._queue.cancel(
                    job_id
                )  # the worker is busy teaching: not worth waiting for
                return None
            if not outcome.ok:
                return None
            self._words.update(outcome.meta.get("words") or {})
        found = {w: self._words[w] for w in words if w in self._words}
        return found or None

    async def publish(self, adapter: Path, title: str, run_id: str) -> str | None:
        """The adapter in ComfyUI's key names, kept under the person's own prefix: the name an image
        workflow is given; the media job fetches the file by it (never shared with anyone else)."""
        from wasifyai_training import comfy_lora
        from wasifyai_training.trainer import BASE

        ctx = require_context()
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "model"
        name = f"wasify-{slug}-{run_id[:8]}.safetensors"
        converted = adapter.with_name(name)
        await asyncio.to_thread(comfy_lora.convert, adapter, converted, BASE)
        key = look_key(ctx.tenant_id, ctx.user_id, run_id, name)
        await self._storage.put(
            key, await asyncio.to_thread(converted.read_bytes), "application/octet-stream"
        )
        await asyncio.to_thread(converted.unlink, True)
        return name

    async def unpublish(self, name: str) -> None:
        return None  # `delete_model` removes the person's looks folder with the model


class RemoteDecisionTrainer(RemoteTrainer):
    """`DecisionJob` in, `DecisionResult` out, like `LayaTrainer`. The taught model (about 850 MB) goes from the
    worker to the person's own part of storage and is moved there (`adopt`); it does not pass through this service."""

    component = train_wire.COMPONENT_DECISION
    engine = "laya"

    def problem(self, base_id: str | None = None) -> str | None:
        why = super().problem()
        if why or base_id is None:
            return why
        have = (self._component() or {}).get("bases") or {}
        if have and not have.get(base_id):
            return "The model to teach is not on this computer yet."  # the manager says it for a worker
        return None

    async def train(
        self, job: Any, base_id: str, folder: Path, report: Callable[[int, str], None]
    ) -> Any:
        from wasifyai_training.decision import DecisionResult, said_of
        from wasifyai_training.language import Stopped

        params = {
            "question": job.question.public(),
            "train": [[r.text, r.answer] for r in job.train],
            "held": [[r.text, r.answer] for r in job.held],
            "peek": list(job.peek), "epochs": job.epochs, "steps": job.steps, "base": base_id,
        }  # fmt: skip

        def told(fraction: float, label: str) -> None:
            report(round(fraction * job.steps), label)

        report(0, "Waiting for the training worker")
        try:
            _, meta = await self._run(
                train_wire.DECISION, params, {}, told, folder.name, None, "model/"
            )
        except Failed as e:
            if e.code == "cancelled":
                raise Stopped("It was stopped, so nothing was kept.") from None
            raise RuntimeError(e.message) from None

        def said(items: list[dict[str, Any]]) -> list[Any]:
            return [said_of(x) for x in items]

        return DecisionResult(
            folder / "model", float(meta.get("seconds", 0.0)), self.engine,
            before=said(meta["before"]), after=said(meta["after"]),
            peek_before=said(meta["peek_before"]), peek_after=said(meta["peek_after"]),
            loss=list(meta.get("loss") or []), peak_bytes=int(meta.get("peak_bytes", 0)),
            bytes=int(meta.get("bytes", 0)),
        )  # fmt: skip

    async def adopt(self, identity: Any, model_id: str) -> None:
        """Move the model the worker made into the model's own part of storage (a copy inside storage)."""
        where = object_key(
            identity.tenant_id, "wasifyai-training", identity.user_id, "train", "models", model_id
        )
        for name, key in self.kept.items():
            await self._storage.copy(key, f"{where}/model/{name.removeprefix('model/')}")
            await self._storage.delete(key)
        self.kept = {}

    async def answer_stored(
        self,
        identity: Any,
        model_id: str,
        question: Any,
        texts: list[str],
        base_id: str | None = None,
    ) -> list[Any]:
        """The taught model (or, with `base_id`, the model it started from) answering about each text."""
        from wasifyai_training.decision import said_of

        job_id = str(uuid4())
        prefix = object_key(
            identity.tenant_id, "wasifyai-training", identity.user_id, "engine", job_id
        )
        await self._submit(
            EngineJob(
                id=job_id, kind=train_wire.DECISION_ANSWER, tenant_id=identity.tenant_id,
                product_id="wasifyai-training", user_id=identity.user_id, prefix=prefix,
                params={
                    "question": question.public(), "texts": texts, "model_id": model_id,
                    "base": base_id,
                },
            )
        )  # fmt: skip
        try:
            outcome = await self._queue.wait(job_id, 600)
        except EngineUnavailable:
            await self._queue.cancel(job_id)
            raise RuntimeError("The worker is busy. Try again in a moment.") from None
        if not outcome.ok:
            raise RuntimeError(
                outcome.error.message if outcome.error else "The model could not answer."
            )
        return [said_of(x) for x in outcome.meta["answers"]]


class RemoteWritingTrainer(RemoteTrainer):
    """`LanguageJob` in, `LanguageResult` out, like `MlxLmTrainer`; the adapter (tens of MB) comes back through here."""

    component = train_wire.COMPONENT_WRITING
    engine = "mlx-lm"

    def problem(self, base_id: str | None = None) -> str | None:
        why = super().problem()
        if why or base_id is None:
            return why
        have = (self._component() or {}).get("bases") or {}
        if have and not have.get(base_id):
            return "The model to teach is not on this computer yet."  # the manager says it for a worker
        return None

    async def train(
        self, job: Any, base_id: str, folder: Path, report: Callable[[int, str], None]
    ) -> Any:
        from wasifyai_training.language import LanguageResult, Stopped

        params = {
            "base": base_id, "train": job.train, "valid": job.valid, "steps": job.steps,
            "questions": job.questions, "batch": job.batch,
        }  # fmt: skip

        def told(fraction: float, label: str) -> None:
            report(round(fraction * job.steps), label)

        report(0, "Waiting for the training worker")
        try:
            out, meta = await self._run(train_wire.WRITING, params, {}, told, folder.name)
        except Failed as e:
            if e.code == "cancelled":
                raise Stopped("It was stopped, so nothing was kept.") from None
            raise RuntimeError(e.message) from None
        adapter = folder / "adapter"
        await asyncio.to_thread(adapter.mkdir, parents=True, exist_ok=True)
        for name, data in out.items():
            rel = name.removeprefix("adapter/")
            if name.startswith("adapter/") and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", rel):
                await asyncio.to_thread((adapter / rel).write_bytes, data)
        return LanguageResult(
            adapter, float(meta.get("seconds", 0.0)), self.engine,
            first_val=meta.get("first_val"), last_val=meta.get("last_val"),
            last_train=meta.get("last_train"), peak_bytes=int(meta.get("peak_bytes", 0)),
        )  # fmt: skip

    async def answer(
        self, base_id: str, questions: list[str], adapter: Path | None = None, max_tokens: int = 120
    ) -> list[str]:
        """The model's answers, with the adapter in `adapter` (a folder here) or without it."""
        found = await asyncio.to_thread(lambda: sorted(adapter.iterdir())) if adapter else []
        files = {f"a/{p.name}": p for p in found}
        params = {"base": base_id, "questions": questions, "max_tokens": max_tokens}
        try:
            _, meta = await self._run(train_wire.WRITING_ANSWER, params, files, None, None)
        except Failed as e:
            raise RuntimeError(e.message) from None
        return [str(a) for a in meta["answers"]]
