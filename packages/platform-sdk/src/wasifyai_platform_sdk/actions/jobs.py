"""Job handles (ADR-0068 decision 3): a long action returns `{job_id, status}` at once, and
`job.status`, `job.wait` and `job.cancel` follow it.

The book is in memory: the engine is a child of the shell and ends with it, and a job started
before a restart is answered from the audit log (it can say how the job ended, not resume it)."""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from wasifyai_platform_sdk.actions.result import ActionResult

JobStatus = Literal["running", "ok", "refused", "error", "cancelled"]
MAX_JOBS = 200  # finished jobs beyond this are forgotten, oldest first


@dataclass
class Job:
    id: str
    action_id: str
    tenant_id: str
    user_id: str
    origin: str
    cancellable: bool
    started: float = field(default_factory=time.monotonic)
    status: JobStatus = "running"
    result: ActionResult | None = None
    progress: dict[str, Any] | None = None
    task: asyncio.Task[Any] | None = None
    finished: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def seconds(self) -> float:
        return round(time.monotonic() - self.started, 1)


class JobBook:
    def __init__(self, limit: int = MAX_JOBS) -> None:
        self._jobs: dict[str, Job] = {}
        self._limit = limit

    def start(
        self, action_id: str, tenant_id: str, user_id: str, origin: str, cancellable: bool
    ) -> Job:
        job = Job(uuid4().hex[:16], action_id, tenant_id, user_id, origin, cancellable)
        self._jobs[job.id] = job
        self._trim()
        return job

    def get(self, tenant_id: str, user_id: str, job_id: str) -> Job | None:
        """A job of this person only: another person's job looks like no job at all."""
        job = self._jobs.get(job_id)
        return job if job and (job.tenant_id, job.user_id) == (tenant_id, user_id) else None

    def running(self, tenant_id: str, user_id: str) -> list[Job]:
        return [
            j
            for j in self._jobs.values()
            if j.status == "running" and (j.tenant_id, j.user_id) == (tenant_id, user_id)
        ]

    def finish(self, job: Job, status: JobStatus, result: ActionResult) -> None:
        job.status, job.result = status, result
        job.finished.set()

    async def wait(self, job: Job, seconds: float) -> bool:
        """Whether the job finished within `seconds`."""
        if job.finished.is_set():
            return True
        try:
            await asyncio.wait_for(job.finished.wait(), timeout=max(0.0, seconds))
        except TimeoutError:
            return False
        return True

    def _trim(self) -> None:
        done = [j for j in self._jobs.values() if j.status != "running"]
        for j in done[: max(0, len(self._jobs) - self._limit)]:
            del self._jobs[j.id]
