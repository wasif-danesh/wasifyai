"""Runs one job: take the GPU, free it of LLMs, generate, store the outputs, report."""

import asyncio
import contextlib
import hashlib
import logging
import mimetypes
import re
import time
from pathlib import Path
from typing import Any, Protocol

import httpx
from wasifyai_platform_sdk import (
    PICTURE_SLOTS,
    EventLog,
    JobError,
    JobOutput,
    JobRequest,
    JobResult,
    Storage,
    UsageEvent,
    UsageRecorder,
    input_image_name,
    object_key,
    tracing,
)
from wasifyai_platform_sdk.jobs import progress_event
from wasifyai_platform_sdk.usage import record_safely
from websockets.exceptions import WebSocketException

from wasifyai_media_worker.comfy import ComfyClient, ComfyError, ProgressFn, use_picture
from wasifyai_media_worker.gpu import GpuLock, unload_llms
from wasifyai_media_worker.metrics import record_job
from wasifyai_media_worker.settings import WorkerSettings
from wasifyai_media_worker.state import JobState
from wasifyai_media_worker.stub import run_stub

log = logging.getLogger(__name__)

PROGRESS_MIN_INTERVAL_S = 0.3
JOB_COMPLETED = "job.completed"
GPU_SECONDS = "gpu.seconds"
REMOTE_SECONDS = "media.remote_seconds"

LOOK_DIR = "wasify-user"  # inside a `loras` folder: a person's own looks, for the length of one job
LOOK_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.safetensors$")
TRAINING_PRODUCT = "wasifyai-training"
CANCEL_POLL_S = 1.0  # how often a running job looks whether it was stopped (stage J3)
STOPPED = "Stopped."


class Cancels(Protocol):
    """Where a stop for a job is written (the API) and read (the worker): a Redis key on the web,
    a flag of the desktop's queue."""

    async def is_cancelled(self, job_id: str) -> bool: ...


class _Stopped(Exception):
    """The person stopped the job while it ran."""


# What a runner returns: output name -> (bytes, content type, file extension)
Files = dict[str, tuple[bytes, str, str]]


class RetryJob(Exception):
    """The backend was unreachable; run the job again later."""

    def __init__(self, attempt: int, reason: str):
        super().__init__(reason)
        self.attempt = attempt


# The user's input files for a job, by name ("image": the picture to edit, as PNG bytes)
InputFiles = dict[str, bytes]


class Runner(Protocol):
    backend: str
    local_gpu: bool  # True: runs on this machine's GPU, so the worker takes the GPU lock first

    async def run(
        self, job: JobRequest, on_progress: ProgressFn, files: InputFiles | None = None
    ) -> Files: ...


class Router(Protocol):
    async def resolve(self, job: JobRequest) -> Runner: ...


class _Static:
    """A router that always answers with one runner (a single backend, and the tests)."""

    def __init__(self, runner: Runner):
        self._runner = runner

    async def resolve(self, job: JobRequest) -> Runner:
        return self._runner


class ComfyRunner:
    backend = "comfyui-local"
    local_gpu = True

    def __init__(self, client: ComfyClient, timeout_s: float, free_after_job: bool = True):
        self._client = client
        self._timeout = timeout_s
        # The web profile frees the GPU after every job (it is shared with other models). The
        # desktop keeps the model loaded for the next one; the slot manager unloads it when idle.
        self._free_after_job = free_after_job

    async def run(
        self, job: JobRequest, on_progress: ProgressFn, files: InputFiles | None = None
    ) -> Files:
        graph = job.prompt
        for slot in PICTURE_SLOTS:
            if files and slot in files:
                name = input_image_name(job.job_id, slot)
                graph = use_picture(graph, name, await self._client.upload_image(name, files[slot]))
        try:
            outputs = await self._client.run(graph, job.job_id, on_progress, self._timeout)
        except asyncio.CancelledError:
            # stopped (stage J3): ComfyUI goes on with a prompt nobody waits for; tell it to stop
            await asyncio.shield(self._client.interrupt())
            raise
        produced: Files = {}
        for name, spec in job.outputs.items():
            f = self._client.pick(outputs, str(spec["node"]), spec.get("type", "image"))
            ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else "bin"
            ctype = mimetypes.guess_type(f.filename)[0] or "application/octet-stream"
            produced[name] = (await self._client.fetch(f), ctype, ext)
        if self._free_after_job:
            await self._client.free()
        return produced


class StubRunner:
    backend = "stub"
    local_gpu = True  # keeps the GPU-sharing behaviour the same with and without real models

    async def run(
        self, job: JobRequest, on_progress: ProgressFn, files: InputFiles | None = None
    ) -> Files:
        return await run_stub(job.job_id, job.outputs, on_progress)


_TRANSIENT = (
    httpx.TransportError,
    ConnectionError,
    OSError,
    WebSocketException,
)


def _local(runner: "Runner | None") -> bool:
    """Whether the runner uses this machine's GPU. A runner that does not say is assumed to."""
    return True if runner is None else getattr(runner, "local_gpu", True)


def _name(runner: "Runner | None") -> str | None:
    return None if runner is None else getattr(runner, "backend", type(runner).__name__)


def _gpu(runner: "Runner | None", elapsed: float) -> float:
    return elapsed if _local(runner) else 0.0


class JobProcessor:
    def __init__(
        self,
        settings: WorkerSettings,
        log_: EventLog,
        storage: Storage,
        usage: UsageRecorder,
        runner: Runner | Router,
        gpu: GpuLock,
        state: JobState,
        http: httpx.AsyncClient | None = None,
        cancels: Cancels | None = None,
    ):
        self.s = settings
        self.log = log_
        self.storage = storage
        self.usage = usage
        self.router: Router = runner if hasattr(runner, "resolve") else _Static(runner)  # type: ignore[assignment]
        self.gpu = gpu
        self.state = state
        self._http = http or httpx.AsyncClient(timeout=30)
        self.cancels = cancels  # stage J3: a stopped job is not run, or stops where it is

    async def emit(self, job: JobRequest, status: str, **kw: Any) -> None:
        if event := progress_event(job, status, **kw):
            await self.log.append(job.tenant_id, job.run_id or "", event)

    async def process(self, job: JobRequest) -> JobResult:
        """Returns the job's final result. Raises RetryJob for transient infrastructure failures.
        One span per job, in the trace of the run that asked for it (stage O1)."""
        attrs = {"kind": job.capability, "job_id": job.job_id, "product": job.product_id}
        with tracing.span("media job", attrs, parent=job.trace) as current:
            result = await self._process(job)
            result = result.model_copy(update={"trace": tracing.carrier()})
            tracing.set_attrs(current, outcome=result.status)
            if result.error is not None:
                tracing.fail(current, result.error.code)
            return result

    async def _process(self, job: JobRequest) -> JobResult:
        if prior := await self.state.finished(job.tenant_id, job.job_id):
            return prior  # redelivered after a crash: report the same result again
        if await self._stopped(job):  # stopped while it waited in the line: never started
            result = self._failed(job, "cancelled", STOPPED, 0.0, retryable=False)
            await self.state.finish(job.tenant_id, job.job_id, result)
            await self.emit(job, result.status)
            return result
        attempt = await self.state.begin(job.tenant_id, job.job_id)
        await self.emit(job, "running", progress=0.0)

        last = 0.0

        async def on_progress(p: float) -> None:
            nonlocal last
            now = time.monotonic()
            if p >= 1.0 or now - last >= PROGRESS_MIN_INTERVAL_S:
                last = now
                await self.emit(job, "running", progress=round(p, 3))

        elapsed = 0.0
        runner: Runner | None = None
        try:
            runner = await self.router.resolve(job)
            given = await self._input_files(job)  # before the GPU lock: reading is not GPU work
            # Only work on this machine's GPU takes the lock and frees it of LLMs first.
            hold = self.gpu.hold() if _local(runner) else contextlib.nullcontext()
            async with hold:
                if _local(runner) and self.s.unload_llm and self.s.ollama_base_url:
                    await unload_llms(self.s.ollama_base_url, self._http)
                job_run, looks = await self._stage_looks(job)
                started = time.monotonic()
                try:
                    # a runner that takes no input files is called as it always was
                    files = await self._watched(
                        job,
                        runner.run(job_run, on_progress, files=given)
                        if given
                        else runner.run(job_run, on_progress),
                    )
                finally:
                    elapsed = time.monotonic() - started
                    await self._unstage_looks(looks)
            outputs = await self._store(job, files)
            result = JobResult(
                job_id=job.job_id,
                status="completed",
                outputs=outputs,
                gpu_seconds=round(elapsed, 2) if _local(runner) else 0.0,
            )
        except _Stopped:
            result = self._failed(job, "cancelled", STOPPED, _gpu(runner, elapsed), retryable=False)
        except ComfyError as e:
            result = self._failed(
                job, e.code, e.message, _gpu(runner, elapsed), retryable=e.code == "connection_lost"
            )
        except TimeoutError:
            result = self._failed(
                job,
                "timeout",
                "The generation took too long.",
                _gpu(runner, elapsed),
                retryable=True,
            )
        except _TRANSIENT as e:
            if attempt < self.s.max_attempts:
                raise RetryJob(attempt, f"{type(e).__name__}: {e}") from e
            log.error("job %s: backend unavailable after %d attempts", job.job_id, attempt)
            result = self._failed(
                job,
                "backend_unavailable",
                "The generation backend is unavailable.",
                _gpu(runner, elapsed),
                retryable=True,
            )
        except Exception:
            log.exception("job %s failed unexpectedly", job.job_id)
            result = self._failed(
                job, "job_failed", "The generation failed.", _gpu(runner, elapsed), retryable=True
            )

        record_job(job.capability, result.status, elapsed, result.gpu_seconds or 0.0)
        await self._record_usage(job, result, runner, elapsed)
        await self.state.finish(job.tenant_id, job.job_id, result)
        await self.emit(job, result.status, progress=1.0 if result.status == "completed" else None)
        return result

    async def _stopped(self, job: JobRequest) -> bool:
        if self.cancels is None:
            return False
        try:
            return await self.cancels.is_cancelled(job.job_id)
        except Exception:
            log.warning("could not read whether job %s was stopped", job.job_id)
            return False

    async def _watched(self, job: JobRequest, work: Any) -> Files:
        """Run the job, looking now and then whether it was stopped; a stop cancels the run, which
        tells ComfyUI to interrupt it (`ComfyRunner`), so the GPU is free for the next job."""
        task = asyncio.ensure_future(work)
        if self.cancels is None:
            return await task
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=CANCEL_POLL_S)
                if done:
                    return task.result()
                if await self._stopped(job):
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    raise _Stopped
        except asyncio.CancelledError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise

    async def _input_files(self, job: JobRequest) -> InputFiles:
        """The user's uploaded picture for this job, read from their own prefix (ADR-0035). The key
        must be one of their uploads: anything else fails the job, never reading another path."""
        found: InputFiles = {}
        for name, field, noun in (
            ("image", "image_key", "picture"),
            ("image2", "image2_key", "picture"),
            ("mask", "mask_key", "mask"),
            ("video", "video_key", "clip"),
            ("audio", "audio_key", "recording"),
        ):
            key = job.inputs.get(field)
            if not key:
                continue
            if not isinstance(key, str) or not key.startswith("uploads/") or ".." in key:
                raise ComfyError("invalid_input", f"The {noun} for this job is not valid.")
            try:
                found[name] = await self.storage.get(
                    object_key(job.tenant_id, job.product_id, job.user_id, key)
                )
            except (FileNotFoundError, ValueError):
                raise ComfyError(
                    "invalid_input", f"The {noun} for this job could not be found."
                ) from None
        return found

    def _loras_root(self) -> Path | None:
        if self.s.media_loras_dir:
            return Path(self.s.media_loras_dir)
        if self.s.desktop_models_dir:
            return Path(self.s.desktop_models_dir) / "loras"
        if self.s.desktop_data_dir:
            return Path(self.s.desktop_data_dir) / "models" / "loras"
        return None

    async def _stage_looks(self, job: JobRequest) -> tuple[JobRequest, list[Path]]:
        """The looks a person taught, fetched from their own part of storage into a folder ComfyUI
        reads, for this job only; the graph is changed to name the staged files. Anything that is
        not one of this person's looks fails the job."""
        files = job.inputs.get("lora_files")
        if not files:
            return job, []
        root = self._loras_root()
        if root is None or not isinstance(files, dict):
            raise ComfyError("invalid_input", "This worker cannot use a look.")
        mine = object_key(job.tenant_id, TRAINING_PRODUCT, job.user_id, "train", "looks") + "/"
        who = hashlib.sha256(f"{job.tenant_id}/{job.user_id}".encode()).hexdigest()[:12]
        mapped: dict[str, str] = {}
        written: list[Path] = []
        try:
            for name, key in files.items():
                if not isinstance(key, str) or not LOOK_NAME.match(str(name)):
                    raise ComfyError("invalid_input", "One of the looks is not valid.")
                if not key.startswith(mine) or ".." in key:
                    raise ComfyError("invalid_input", "One of the looks is not yours.")
                try:
                    data = await self.storage.get(key)
                except (FileNotFoundError, ValueError):
                    raise ComfyError(
                        "invalid_input", "One of the looks could not be found."
                    ) from None
                rel = f"{LOOK_DIR}/{who}/{job.job_id[:8]}-{name}"
                path = root / rel
                await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
                await asyncio.to_thread(path.write_bytes, data)
                written.append(path)
                mapped[str(name)] = rel
        except BaseException:
            await self._unstage_looks(written)
            raise
        graph = {
            nid: (
                {
                    **node,
                    "inputs": {**node["inputs"], "lora_name": mapped[node["inputs"]["lora_name"]]},
                }
                if node.get("class_type") == "LoraLoaderModelOnly"
                and node.get("inputs", {}).get("lora_name") in mapped
                else node
            )
            for nid, node in job.prompt.items()
        }
        return job.model_copy(update={"prompt": graph}), written

    async def _unstage_looks(self, paths: list[Path]) -> None:
        for path in paths:
            with contextlib.suppress(OSError):
                await asyncio.to_thread(path.unlink, True)

    def _failed(
        self, job: JobRequest, code: str, message: str, gpu_seconds: float, retryable: bool
    ) -> JobResult:
        log.warning("job %s failed: %s", job.job_id, code)
        return JobResult(
            job_id=job.job_id,
            status="failed",
            error=JobError(code=code, message=message, retryable=retryable),
            gpu_seconds=round(gpu_seconds, 2),
        )

    async def _store(self, job: JobRequest, files: Files) -> dict[str, JobOutput]:
        """Outputs go under the owner's prefix; the result carries keys relative to it, which is
        what `caps.storage` expects."""
        out: dict[str, JobOutput] = {}
        for name, (data, ctype, ext) in files.items():
            rel = f"jobs/{job.job_id}/{name}.{ext}"
            await self.storage.put(
                object_key(job.tenant_id, job.product_id, job.user_id, rel), data, ctype
            )
            out[name] = JobOutput(key=rel, content_type=ctype, size=len(data))
        return out

    async def _record_usage(
        self, job: JobRequest, result: JobResult, runner: Runner | None, elapsed: float
    ) -> None:
        def event(kind: str, quantity: float, unit: str) -> UsageEvent:
            return UsageEvent(
                tenant_id=job.tenant_id,
                product_id=job.product_id,
                user_id=job.user_id,
                run_id=job.run_id,
                kind=kind,
                quantity=quantity,
                unit=unit,
                meta={
                    "capability": job.capability,
                    "workflow": job.workflow,
                    "job_id": job.job_id,
                    "backend": _name(runner),
                },
            )

        if result.gpu_seconds:
            await record_safely(self.usage, event(GPU_SECONDS, result.gpu_seconds, "seconds"))
        elif not _local(runner) and elapsed:
            # time on someone else's hardware: not our GPU, but it is what a hosted backend bills
            await record_safely(self.usage, event(REMOTE_SECONDS, round(elapsed, 2), "seconds"))
        if result.status == "completed":
            await record_safely(self.usage, event(JOB_COMPLETED, 1, "jobs"))
