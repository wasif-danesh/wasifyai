"""Lip sync on a talking-head server (ADR-0044): a job for the media worker, with no ComfyUI graph.

The request carries the user's picture and voice (`image_key`, `audio_key`, read by the worker from
the user's `uploads/` prefix); the worker sends them to the lip sync server and stores the MP4."""

from typing import Any
from uuid import uuid4

from wasifyai_platform_sdk.config import CapabilityBinding
from wasifyai_platform_sdk.context import require_context
from wasifyai_platform_sdk.jobs import JobHandle, JobRequest, JobSink

WORKFLOW = "lipsync"  # tells the worker's router which runner takes the job


class LipSyncProvider:
    def __init__(self, sink: JobSink):
        self._sink = sink

    async def generate(
        self, capability: str, binding: CapabilityBinding, inputs: dict[str, Any]
    ) -> JobHandle:
        ctx = require_context()
        request = JobRequest(
            job_id=str(uuid4()),
            tenant_id=ctx.tenant_id,
            product_id=ctx.product_id,
            user_id=ctx.user_id,
            run_id=ctx.run_id,
            thread_id=ctx.thread_id,
            capability=capability,
            workflow=WORKFLOW,
            prompt={},
            inputs={**binding.defaults, **inputs},
            outputs={"video": {"node": "", "type": "video"}},
        )
        await self._sink.submit(request)
        return JobHandle(job_id=request.job_id, capability=capability)
