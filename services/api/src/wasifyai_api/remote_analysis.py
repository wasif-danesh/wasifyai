"""A song's analysis for the web, run by an engine worker (ADR-0090, ADR-0087).

`music.analyse` asks its tool for the beats, downbeats, tempo and sections of a recording. On the
desktop the tool runs on the computer (`music_analysis_setup.MusicAnalysis`); here it is a job: the
recording goes to the person's own part of object storage, a worker that has the tool set up runs
it, and the answer comes back as the job's numbers. The answer has the desktop tool's shape, so the
voice product did not change. An admin sets the tool up on a worker (Admin > Workers)."""

import logging
from typing import Any
from uuid import uuid4

from wasifyai_platform_sdk import (
    EngineJob,
    EngineQueue,
    EngineUnavailable,
    analysis_wire,
    require_context,
)
from wasifyai_platform_sdk.jobpolicy import JobLimitReached
from wasifyai_platform_sdk.storage import object_key

from wasifyai_api.engine_workers import WorkerDirectory, record_engine_seconds

log = logging.getLogger("wasifyai_api.remote_analysis")


class AnalysisFailed(Exception):
    """What `analyse` raises, in words a person can read."""


class RemoteMusicAnalysis:
    Failed = AnalysisFailed
    supported = True  # whether it can run is a worker's to say (`ready`, `problem`)
    remote = True  # set up by an admin, not by the person

    def __init__(
        self,
        queue: EngineQueue,
        storage: Any,
        directory: WorkerDirectory,
        timeout_s: float = 900,
        usage: Any = None,
    ):
        self._queue = queue
        self._storage = storage  # the raw `Storage` (keys carry the tenant prefix)
        self._directory = directory
        self._timeout = timeout_s
        self._usage = usage

    def _component(self) -> dict[str, Any] | None:
        return self._directory.component(analysis_wire.COMPONENT)

    def ready(self) -> bool:
        return self.problem() is None

    def problem(self) -> str | None:
        if not self._directory.workers:
            return "No worker is running. Try again in a moment."
        c = self._component()
        if c is None:
            return "No worker here can find the beats of a song."
        if c.get("ready"):
            return None
        return "Song analysis is not set up on the worker yet. Ask an admin to set it up."

    def state(self) -> dict[str, Any]:
        c = self._component() or {}
        return c.get("state") or {}  # type: ignore[no-any-return]

    async def analyse(self, audio: bytes) -> dict[str, Any]:
        """Beats, downbeats, tempo and sections of a recording (a WAV file's bytes)."""
        ctx = require_context()
        job_id = str(uuid4())
        prefix = object_key(ctx.tenant_id, ctx.product_id, ctx.user_id, "engine", job_id)
        song = f"{prefix}/in/song"
        staged = [song]
        try:
            await self._storage.put(song, audio, "audio/wav")
            job = EngineJob(
                id=job_id, kind=analysis_wire.ANALYSE, tenant_id=ctx.tenant_id,
                product_id=ctx.product_id, user_id=ctx.user_id, prefix=prefix, params={},
                files={"song": song},
            )  # fmt: skip
            try:
                await self._queue.submit(job, timeout_s=self._timeout)
            except JobLimitReached as e:
                raise AnalysisFailed(e.message) from None
            try:
                outcome = await self._queue.wait(job_id, self._timeout)
            except EngineUnavailable:
                await self._queue.cancel(job_id)
                raise AnalysisFailed(
                    "The worker took too long to find the beats. Try again."
                ) from None
            await record_engine_seconds(self._usage, ctx, analysis_wire.ANALYSE, outcome)
            staged.extend(outcome.outputs.values())
            if not outcome.ok:
                err = outcome.error
                raise AnalysisFailed(err.message if err else "The beats could not be found.")
            return dict(outcome.meta)
        finally:
            for key in staged:
                try:
                    await self._storage.delete(key)
                except Exception:
                    log.warning("could not remove %s", key)
