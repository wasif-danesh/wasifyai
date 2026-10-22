"""The 3D component for the web, run by an engine worker (ADR-0087, P3).

The 3D product asks its engine to cut a picture out and to make a model from the cut-out. Here the
engine queues a job: the picture goes to the person's own part of object storage, a worker that has
the 3D component runs it, and the result is read back. The shape of the answers is the desktop
component's (`RunResult`), so the product did not change."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from wasifyai_platform_sdk import (
    EngineJob,
    EngineQueue,
    EngineUnavailable,
    model3d_wire,
    require_context,
)
from wasifyai_platform_sdk.storage import object_key

from wasifyai_api.engine_workers import WorkerDirectory

log = logging.getLogger("wasifyai_api.remote_model3d")


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


class RemoteModel3dEngine:
    # a model or a picture can be picked up again after an API restart: its job has its row's id
    resumable = True
    closing = False  # set when this service is stopping: the jobs go on, nobody is told to stop

    def __init__(
        self,
        queue: EngineQueue,
        storage: Any,
        directory: WorkerDirectory,
        timeout_s: float = 3600,
    ):
        self._queue = queue
        self._storage = storage  # the raw `Storage` (keys carry the tenant prefix)
        self._directory = directory
        self._timeout = timeout_s

    # ---- what the product asks before it starts ---------------------------------------------

    def _component(self) -> dict[str, Any] | None:
        return self._directory.component(model3d_wire.COMPONENT)

    def ready(self) -> bool:
        return self.problem() is None

    def problem(self) -> str | None:
        if not self._directory.workers:
            return "The 3D worker is not running. Try again in a moment."
        c = self._component()
        if c is None:
            return "No worker here can make 3D models."
        if c.get("ready"):
            return None
        return str(c.get("problem") or "The 3D component is not set up on the worker.")

    def fit(self) -> dict[str, Any]:
        c = self._component() or {}
        return c.get("fit") or {"verdict": "fits", "reason": ""}  # type: ignore[no-any-return]

    def state(self) -> dict[str, Any]:
        c = self._component() or {}
        return c.get("state") or {}  # type: ignore[no-any-return]

    async def stop(self) -> None:
        return None  # the worker holds the memory; a cancelled job stops its own process

    # ---- the work ---------------------------------------------------------------------------

    async def _run(
        self,
        kind: str,
        params: dict[str, Any],
        files: dict[str, Path],
        on_progress: Callable[[float, str], None] | None = None,
        job_key: str | None = None,
        resume: bool = False,
    ) -> tuple[dict[str, bytes], dict[str, Any]]:
        """Queue a job and wait for it. `job_key` is the id the job goes by (the product's row id,
        so a restarted API can find it); `resume` picks up a job that was already sent."""
        ctx = require_context()
        job_id = job_key or str(uuid4())
        prefix = object_key(ctx.tenant_id, ctx.product_id, ctx.user_id, "engine", job_id)
        keys: dict[str, str] = {}
        staged: list[str] = []
        try:
            if resume:
                if await self._queue.status(job_id) == "lost":
                    raise _Failed("lost", "It was stopped before it finished. Make it again.")
                staged = [f"{prefix}/in/{name}" for name in files]  # sent before the restart
            else:
                for name, path in files.items():
                    key = f"{prefix}/in/{name}"
                    await self._storage.put(
                        key, await asyncio.to_thread(path.read_bytes), "application/octet-stream"
                    )
                    staged.append(key)
                    keys[name] = key
                await self._queue.submit(
                    EngineJob(
                        id=job_id,
                        kind=kind,
                        tenant_id=ctx.tenant_id,
                        product_id=ctx.product_id,
                        user_id=ctx.user_id,
                        prefix=prefix,
                        params=params,
                        files=keys,
                    )
                )

            async def told(fraction: float, label: str) -> None:
                if on_progress is not None:
                    on_progress(fraction, label)

            try:
                outcome = await self._queue.wait(job_id, self._timeout, told)
            except asyncio.CancelledError:
                # the person pressed Stop: tell the worker, which kills the 3D process. When this
                # service is only stopping, the job goes on and the next start picks it up.
                if not self.closing:
                    await asyncio.shield(self._queue.cancel(job_id))
                raise
            except EngineUnavailable:
                await asyncio.shield(self._queue.cancel(job_id))
                raise _Failed("wall_time", "The 3D worker took too long. Try again.") from None
            if not outcome.ok:
                err = outcome.error
                code = err.code if err else "failed"
                raise _Failed(
                    "cancelled" if code == "cancelled" else "failed",
                    err.message if err else "The 3D worker could not do that.",
                    outcome.seconds,
                )
            staged.extend(outcome.outputs.values())
            out = {name: await self._storage.get(key) for name, key in outcome.outputs.items()}
            return out, outcome.meta
        finally:
            for key in staged:
                try:
                    await self._storage.delete(key)
                except Exception:
                    log.warning("could not remove %s", key)

    async def matte(
        self,
        picture: Path,
        out_dir: Path,
        on_line: Callable[[str], None] | None = None,
        *,
        job_key: str | None = None,
        resume: bool = False,
    ) -> RunResult:
        """The cut-out of a picture: a PNG with a real transparent background."""
        try:
            out, meta = await self._run(
                model3d_wire.MATTE, {}, {"picture": picture}, None, job_key, resume
            )
        except _Failed as e:
            return RunResult(False, e.reason, e.message, e.seconds)
        cutout = out_dir / "unused_cutout.png"
        await asyncio.to_thread(cutout.write_bytes, out["cutout"])
        return RunResult(
            True, seconds=float(meta.get("seconds", 0)), peak_gb=float(meta.get("peak_gb", 0)),
            output=cutout,
        )  # fmt: skip

    async def generate(
        self,
        cutout: Path,
        out_glb: Path,
        *,
        seed: int = 42,
        detail: str = "standard",
        on_line: Callable[[str], None] | None = None,
        on_progress: Callable[[float, str], None] | None = None,
        job_key: str | None = None,
        resume: bool = False,
    ) -> RunResult:
        """The 3D model of a cut-out picture, as one GLB."""
        try:
            out, meta = await self._run(
                model3d_wire.GENERATE,
                {"seed": seed, "detail": detail},
                {"cutout": cutout},
                on_progress,
                job_key,
                resume,
            )
        except _Failed as e:
            return RunResult(False, e.reason, e.message, e.seconds)
        await asyncio.to_thread(out_glb.write_bytes, out["glb"])
        return RunResult(
            True, seconds=float(meta.get("seconds", 0)), peak_gb=float(meta.get("peak_gb", 0)),
            output=out_glb,
        )  # fmt: skip


class _Failed(Exception):
    def __init__(self, reason: str, message: str, seconds: float = 0.0):
        super().__init__(message)
        self.reason, self.message, self.seconds = reason, message, seconds
