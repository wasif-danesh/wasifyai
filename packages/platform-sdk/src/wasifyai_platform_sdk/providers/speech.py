"""Speech capabilities (ADR-0042): a job for the media worker that turns text into speech.

Unlike a ComfyUI workflow there is no graph: the request carries what to say, the language and the
voice, and the worker sends them to the speech server that serves the voice's engine."""

from typing import Any
from uuid import uuid4

from wasifyai_platform_sdk.config import CapabilityBinding
from wasifyai_platform_sdk.context import require_context
from wasifyai_platform_sdk.jobs import JobHandle, JobRequest, JobSink


class SpeechProvider:
    def __init__(self, sink: JobSink):
        self._sink = sink

    async def generate(
        self, capability: str, binding: CapabilityBinding, inputs: dict[str, Any]
    ) -> JobHandle:
        ctx = require_context()
        merged = {**binding.defaults, **inputs}
        request = JobRequest(
            job_id=str(uuid4()),
            tenant_id=ctx.tenant_id,
            product_id=ctx.product_id,
            user_id=ctx.user_id,
            run_id=ctx.run_id,
            thread_id=ctx.thread_id,
            capability=capability,
            workflow="speech",
            prompt={},
            inputs=merged,
            outputs=(
                {"transcript": {"node": "", "type": "json"}}
                if capability == "speech.transcribe"
                else {"audio": {"node": "", "type": "audio"}}
            ),
        )
        await self._sink.submit(request)
        return JobHandle(job_id=request.job_id, capability=capability)
