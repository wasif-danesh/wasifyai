"""The product's config and workflows are consistent, and a picture reaches the right node."""

from pathlib import Path

import pytest
from wasifyai_platform_sdk import (
    CapabilityBinding,
    InMemoryJobSink,
    RunContext,
    load_product_config,
    reset_context,
    set_context,
)
from wasifyai_platform_sdk.providers.comfyui import ComfyUIProvider
from wasifyai_platform_sdk.workflows import Workflow, workflow_problems

PRODUCTS = Path(__file__).resolve().parents[2]
WORKFLOWS = PRODUCTS / "wasifyai-image" / "workflows"


def test_the_product_config_loads_and_binds_both_modes():
    cfg = load_product_config(PRODUCTS, "wasifyai-image", environ={})
    assert cfg.capabilities["image.generate"].workflow == "flux2-klein-4b"
    assert cfg.capabilities["image.edit"].workflow == "flux2-klein-4b-edit"
    assert cfg.capabilities["text.moderate"].model == "moderator"
    picture = cfg.capabilities["text.moderate_image"]
    assert picture.model == "multimodal" and picture.inputs == ["text", "image"]
    assert cfg.quotas == {"images_per_user_per_day": 20}
    assert cfg.uploads["image"].max_bytes == 10 * 1024 * 1024


@pytest.mark.parametrize("name", ["flux2-klein-4b", "flux2-klein-4b-edit"])
def test_every_mapped_node_exists_in_its_workflow(name):
    assert workflow_problems(WORKFLOWS, name) == []


def test_the_edit_workflow_takes_a_picture_and_no_size():
    wf = Workflow.load(WORKFLOWS, "flux2-klein-4b-edit")
    assert set(wf.map.inputs) == {"prompt", "seed", "steps", "image"}
    graph = wf.fill({"prompt": "make it dusk", "seed": 5, "image": "wasifyai-JOB.png"})
    loaders = [n for n in graph.values() if n["class_type"] == "LoadImage"]
    assert [n["inputs"]["image"] for n in loaders] == ["wasifyai-JOB.png"]
    assert wf.map.outputs["image"].type == "image"


def test_the_text_workflow_takes_a_size():
    wf = Workflow.load(WORKFLOWS, "flux2-klein-4b")
    graph = wf.fill({"prompt": "a fox", "width": 1152, "height": 864})
    sizes = [
        (n["inputs"]["width"], n["inputs"]["height"])
        for n in graph.values()
        if n["class_type"] in ("EmptyFlux2LatentImage", "Flux2Scheduler")
    ]
    assert sizes == [(1152, 864), (1152, 864)]


async def test_an_edit_job_names_the_picture_for_the_worker_and_fills_the_workflow():
    sink = InMemoryJobSink()
    provider = ComfyUIProvider(WORKFLOWS, sink)
    binding = CapabilityBinding(provider="comfyui", workflow="flux2-klein-4b-edit")
    token = set_context(RunContext("t1", "wasifyai-image", "u1", "run-1", "th-1"))
    try:
        handle = await provider.generate(
            "image.edit",
            binding,
            {"prompt": "make it dusk", "seed": 1, "image_key": "uploads/a.png"},
        )
    finally:
        reset_context(token)
    (job,) = sink.submitted
    assert job.job_id == handle.job_id and job.capability == "image.edit"
    # the workflow points at a per-job file name; the worker uploads the user's picture under it
    assert job.prompt["6"]["inputs"]["image"] == f"wasifyai-{job.job_id}.png"
    assert job.inputs["image_key"] == "uploads/a.png"  # for the worker, not the workflow
    assert "image_key" not in str(job.prompt)


async def test_a_workflow_without_a_picture_input_refuses_an_edit():
    provider = ComfyUIProvider(WORKFLOWS, InMemoryJobSink())
    binding = CapabilityBinding(provider="comfyui", workflow="flux2-klein-4b")
    token = set_context(RunContext("t1", "wasifyai-image", "u1"))
    try:
        with pytest.raises(ValueError, match="no picture input"):
            await provider.generate(
                "image.edit", binding, {"prompt": "x", "image_key": "uploads/a.png"}
            )
    finally:
        reset_context(token)
