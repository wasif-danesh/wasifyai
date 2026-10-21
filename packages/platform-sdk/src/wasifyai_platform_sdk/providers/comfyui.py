"""Media capabilities backed by ComfyUI workflows.

Phase 3: builds the job (workflow JSON with mapped inputs filled in) and hands it to a JobSink.
It never calls ComfyUI. Phase 4 swaps the sink for a Redis queue and adds the worker.
"""

from pathlib import Path
from typing import Any
from uuid import uuid4

from wasifyai_platform_sdk.config import CapabilityBinding
from wasifyai_platform_sdk.context import require_context
from wasifyai_platform_sdk.jobs import (
    PICTURE_SLOTS,
    JobHandle,
    JobRequest,
    JobSink,
    input_image_name,
)
from wasifyai_platform_sdk.workflows import Workflow

RESERVED_INPUTS = {
    *(f"{slot}_key" for slot in PICTURE_SLOTS),
    "loras",
}  # for the job, not the workflow
MAX_LORAS = 8


def _loras(raw: Any) -> list[tuple[str, float]]:
    """`[{"name", "weight"}]` from a job's inputs as pairs; anything else is an error."""
    if not raw:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_LORAS:
        raise ValueError("loras must be a short list")
    out: list[tuple[str, float]] = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError("each LoRA needs a name")
        out.append((item["name"], float(item.get("weight", 1.0))))
    return out


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
        # `image_key` (and `image2_key`, `mask_key`) name the user's uploaded pictures. They go to
        # the worker, which uploads each picture under a per-job name; the workflow's input of the
        # same slot name gets that name here.
        workflow_inputs = {k: v for k, v in merged.items() if k not in RESERVED_INPUTS}
        for slot in PICTURE_SLOTS:
            if merged.get(f"{slot}_key"):
                if slot not in wf.map.inputs:
                    raise ValueError(f"workflow {wf.name!r} has no picture input {slot!r}")
                workflow_inputs[slot] = input_image_name(job_id, slot)
        loras = _loras(merged.get("loras"))
        if loras and not wf.accepts_loras:
            raise ValueError(f"workflow {wf.name!r} does not take LoRAs")
        graph = wf.fill(workflow_inputs, loras or None)
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
