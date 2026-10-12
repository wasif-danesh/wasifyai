"""Media capabilities backed by ComfyUI workflows.

Phase 3: builds the job (workflow JSON with mapped inputs filled in) and hands it to a JobSink.
It never calls ComfyUI. Phase 4 swaps the sink for a Redis queue and adds the worker.
"""

from pathlib import Path
from typing import Any
from uuid import uuid4

from wasifyai_platform_sdk.config import CapabilityBinding
from wasifyai_platform_sdk.context import require_context
from wasifyai_platform_sdk.jobs import JobHandle, JobRequest, JobSink, input_image_name
from wasifyai_platform_sdk.workflows import Workflow

RESERVED_INPUTS = {"image_key"}  # for the job, not for the workflow


class ComfyUIProvider:
    def __init__(self, workflows_dir: Path, sink: JobSink):
        self._dir = workflows_dir
        self._sink = sink
        self._cache: dict[str, Workflow] = {}

    def _workflow(self, name: str) -> Workflow:
        if name not in self._cache:
            self._cache[name] = Workflow.load(self._dir, name)
        return self._cache[name]

    async def generate(
        self, capability: str, binding: CapabilityBinding, inputs: dict[str, Any]
    ) -> JobHandle:
        ctx = require_context()
        wf = self._workflow(binding.workflow or "")
        job_id = str(uuid4())
        merged = {**binding.defaults, **inputs}
        # `image_key` names the user's uploaded picture. It goes to the worker, which uploads the
        # picture under a per-job name; the workflow's picture input gets that name here.
        workflow_inputs = {k: v for k, v in merged.items() if k not in RESERVED_INPUTS}
        if merged.get("image_key"):
            if "image" not in wf.map.inputs:
                raise ValueError(f"workflow {wf.name!r} has no picture input")
            workflow_inputs["image"] = input_image_name(job_id)
        graph = wf.fill(workflow_inputs)
        request = JobRequest(
            job_id=job_id,
            tenant_id=ctx.tenant_id,
            product_id=ctx.product_id,
            user_id=ctx.user_id,
            run_id=ctx.run_id,
            thread_id=ctx.thread_id,
            capability=capability,
            workflow=wf.name,
            prompt=graph,
            inputs=merged,
            outputs={k: v.model_dump() for k, v in wf.map.outputs.items()},
        )
        await self._sink.submit(request)
        return JobHandle(job_id=request.job_id, capability=capability)
