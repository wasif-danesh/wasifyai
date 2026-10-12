"""Media jobs. Capabilities build a JobRequest and hand it to a JobSink; they never wait on the
GPU (rule 6). The Redis-backed sink queues it for a media worker; the graph then pauses with
`await_job`, and the runtime resumes it when the worker reports the result (ADR-0021).

Graph pattern (two nodes, because a paused node re-runs from its start on resume):

    async def start(state):                      # enqueue, remember only the job id
        handle = await caps.image.generate(prompt=state["prompt"])
        return {"job_id": handle.job_id}

    def wait(state):                             # pause until the worker finishes
        result = await_job(state["job_id"])      # raises JobFailed on failure
        return {"image_key": result.outputs["image"].key}
"""

from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from wasifyai_contracts import JobProgressEvent


def _now() -> str:
    return datetime.now(UTC).isoformat()


def input_image_name(job_id: str) -> str:
    """The file name an input picture goes by on the backend for this job. The API puts it in the
    workflow before the job exists; the worker uploads the user's picture under it."""
    return f"wasifyai-{job_id}.png"


class JobRequest(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    product_id: str
    user_id: str
    run_id: str | None = None
    thread_id: str | None = None
    capability: str
    workflow: str
    prompt: dict[str, Any]  # ComfyUI API-format graph with inputs filled in
    # What was asked, before it became a ComfyUI graph (prompt text, size, seed, lyrics, ...): other
    # backends (ADR-0025) work from this and ignore the graph.
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any]  # output name -> {node, type}, from the workflow map
    created_at: str = Field(default_factory=_now)


class JobHandle(BaseModel):
    job_id: str
    capability: str
    status: str = "queued"


class JobOutput(BaseModel):
    key: str  # storage key, relative to the user's prefix: usable with caps.storage
    content_type: str
    size: int


class JobError(BaseModel):
    code: str
    message: str  # user-safe: no stack traces or internal hostnames
    retryable: bool = False


class JobResult(BaseModel):
    job_id: str
    status: Literal["completed", "failed"]
    outputs: dict[str, JobOutput] = Field(default_factory=dict)
    error: JobError | None = None
    gpu_seconds: float = 0.0


class JobFailed(Exception):
    def __init__(self, result: JobResult):
        self.result = result
        err = result.error
        super().__init__(f"job {result.job_id} failed: {err.message if err else 'unknown'}")


def await_job(job_id: str) -> JobResult:
    """Pause the graph until the media worker finishes `job_id`. Call from a node that has no
    side effects before it (see the module docstring)."""
    from langgraph.types import interrupt

    result = JobResult.model_validate(interrupt({"kind": "job", "job_id": job_id}))
    if result.status == "failed":
        raise JobFailed(result)
    return result


def progress_event(
    req: JobRequest,
    status: str,
    queue_position: int | None = None,
    progress: float | None = None,
) -> dict[str, Any] | None:
    """A `job_progress` SSE event for the job's run, or None if the job is not part of a run."""
    if not (req.run_id and req.thread_id):
        return None
    return JobProgressEvent(
        run_id=UUID(req.run_id),
        thread_id=UUID(req.thread_id),
        seq=0,
        job_id=req.job_id,
        capability=req.capability,
        status=status,  # type: ignore[arg-type]
        queue_position=queue_position,
        progress=progress,
    ).model_dump(mode="json")


class JobSink(Protocol):
    async def submit(self, request: JobRequest) -> None: ...


class InMemoryJobSink:
    """Collects submitted jobs; used in tests and Redis-less runs."""

    def __init__(self) -> None:
        self.submitted: list[JobRequest] = []

    async def submit(self, request: JobRequest) -> None:
        self.submitted.append(request)
