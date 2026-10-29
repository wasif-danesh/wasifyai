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
WORKFLOWS = PRODUCTS / "wasifyai-video" / "workflows"
NAMES = ["ltx-video-2b-t2v", "ltx-video-2b-i2v", "ltx-video-2b-extend"]


def test_the_product_config_loads_and_binds_every_mode():
    cfg = load_product_config(PRODUCTS, "wasifyai-video", environ={})
    assert cfg.capabilities["video.generate"].workflow == "ltx-video-2b-t2v"
    assert cfg.capabilities["video.animate"].workflow == "ltx-video-2b-i2v"
    assert cfg.capabilities["video.extend"].workflow == "ltx-video-2b-extend"
    assert "text.moderate" not in cfg.capabilities
    assert cfg.capabilities["text.enhance"].model == "prompt-enhancer"
    assert cfg.capabilities["text.describe_image"].model == "multimodal"
    assert cfg.capabilities["text.describe_image"].inputs == ["text", "image"]
    assert cfg.uploads["image"].max_bytes == 10 * 1024 * 1024
    assert (
        cfg.enhance["image_to_video"].needs_picture
        and not cfg.enhance["text_to_video"].needs_picture
    )


@pytest.mark.parametrize("name", NAMES)
def test_every_mapped_node_exists_in_its_workflow(name):
    assert workflow_problems(WORKFLOWS, name) == []


@pytest.mark.parametrize("name", NAMES)
def test_the_sampler_is_fully_wired_and_the_clip_is_saved_as_video(name):
    """A real run found a missing `sigmas` link once: every required sampler input must be set."""
    graph = Workflow.load(WORKFLOWS, name).graph
    sampler = graph["72"]["inputs"]
    for required in ("model", "positive", "negative", "sampler", "sigmas", "latent_image"):
        assert required in sampler, required
    wf = Workflow.load(WORKFLOWS, name)
    assert wf.map.outputs["video"].type == "video" and graph["81"]["class_type"] == "SaveVideo"


def test_the_text_workflow_takes_a_size_and_a_length():
    wf = Workflow.load(WORKFLOWS, "ltx-video-2b-t2v")
    assert set(wf.map.inputs) == {"prompt", "seed", "steps", "width", "height", "length"}
    graph = wf.fill({"prompt": "a fox", "width": 512, "height": 768, "length": 121, "seed": 3})
    latent = graph["77"]["inputs"]
    assert (latent["width"], latent["height"], latent["length"]) == (512, 768, 121)
    assert graph["6"]["inputs"]["text"] == "a fox" and graph["72"]["inputs"]["noise_seed"] == 3


def test_the_picture_workflow_holds_the_first_frame_at_full_strength_and_takes_no_size():
    wf = Workflow.load(WORKFLOWS, "ltx-video-2b-i2v")
    assert set(wf.map.inputs) == {"prompt", "seed", "steps", "length", "image"}
    graph = wf.fill({"prompt": "snow falls", "image": "wasifyai-JOB.png", "length": 49})
    loaders = [n for n in graph.values() if n["class_type"] == "LoadImage"]
    assert [n["inputs"]["image"] for n in loaders] == ["wasifyai-JOB.png"]
    # at the template's 0.15 the model ignored the picture and drew the prompt (ADR-0037)
    assert graph["77"]["inputs"]["strength"] == 1.0
    assert graph["77"]["inputs"]["length"] == 49


async def test_an_animate_job_names_the_picture_for_the_worker_and_fills_the_workflow():
    sink = InMemoryJobSink()
    provider = ComfyUIProvider(WORKFLOWS, sink)
    binding = CapabilityBinding(provider="comfyui", workflow="ltx-video-2b-i2v")
    token = set_context(RunContext("t1", "wasifyai-video", "u1", "run-1", "th-1"))
    try:
        handle = await provider.generate(
            "video.animate",
            binding,
            {"prompt": "snow falls", "seed": 1, "length": 121, "image_key": "uploads/a.png"},
        )
    finally:
        reset_context(token)
    (job,) = sink.submitted
    assert job.job_id == handle.job_id and job.capability == "video.animate"
    assert job.prompt["78"]["inputs"]["image"] == f"wasifyai-{job.job_id}.png"
    assert job.inputs["image_key"] == "uploads/a.png" and "image_key" not in str(job.prompt)
    assert job.outputs["video"] == {"node": "81", "type": "video"}


def test_the_extend_workflow_starts_from_the_last_frames_of_a_clip_at_full_strength():
    wf = Workflow.load(WORKFLOWS, "ltx-video-2b-extend")
    assert set(wf.map.inputs) == {"prompt", "seed", "steps", "length", "video", "from_frame"}
    graph = wf.fill({"prompt": "the fox walks", "video": "wasifyai-JOB.mp4", "from_frame": 40})
    (loader,) = [n for n in graph.values() if n["class_type"] == "LoadVideo"]
    assert loader["inputs"]["file"] == "wasifyai-JOB.mp4"
    (picked,) = [n for n in graph.values() if n["class_type"] == "ImageFromBatch"]
    # nine frames (8 * n + 1), from the given index, become the start of the new clip
    assert (picked["inputs"]["batch_index"], picked["inputs"]["length"]) == (40, 9)
    start = graph["77"]["inputs"]
    assert start["strength"] == 1.0 and start["image"] == ["92", 0]
    assert graph["82"]["inputs"]["image"] == ["92", 0]  # the new clip has the old clip's size
    assert "ImageScaleToTotalPixels" not in {n["class_type"] for n in graph.values()}


async def test_an_extend_job_names_the_clip_for_the_worker_and_fills_the_workflow():
    sink = InMemoryJobSink()
    provider = ComfyUIProvider(WORKFLOWS, sink)
    binding = CapabilityBinding(provider="comfyui", workflow="ltx-video-2b-extend")
    token = set_context(RunContext("t1", "wasifyai-video", "u1", "run-1", "th-1"))
    try:
        await provider.generate(
            "video.extend",
            binding,
            {"prompt": "go on", "seed": 1, "length": 49, "from_frame": 80,
             "video_key": "uploads/extend-a.mp4"},
        )  # fmt: skip
    finally:
        reset_context(token)
    (job,) = sink.submitted
    assert job.prompt["90"]["inputs"]["file"] == f"wasifyai-{job.job_id}-video.mp4"
    assert job.prompt["92"]["inputs"]["batch_index"] == 80
    assert job.inputs["video_key"] == "uploads/extend-a.mp4" and "extend-a" not in str(job.prompt)


@pytest.mark.parametrize("name", NAMES)
def test_every_video_workflow_takes_up_to_two_looks_before_the_sampler(name):
    wf = Workflow.load(WORKFLOWS, name)
    assert wf.accepts_loras and wf.map.lora_chain is not None and wf.map.lora_chain.max == 2
    values = {"prompt": "a fox", "seed": 1, "steps": 20, "length": 49}
    if name.endswith("t2v"):
        values.update(width=512, height=512)
    elif name.endswith("i2v"):
        values["image"] = "x.png"
    else:
        values.update(video="x.mp4", from_frame=9)
    graph = wf.fill(values, [("a.safetensors", 1.5), ("b.safetensors", 0.8)])
    loaders = [n for n in graph.values() if n["class_type"] == "LoraLoaderModelOnly"]
    assert [(n["inputs"]["lora_name"], n["inputs"]["strength_model"]) for n in loaders] == [
        ("a.safetensors", 1.5), ("b.safetensors", 0.8),
    ]  # fmt: skip
    # the sampler's model comes from the last loader, the first loader from the checkpoint
    last = next(k for k, n in graph.items() if n["inputs"].get("lora_name") == "b.safetensors")
    assert graph["72"]["inputs"]["model"][0] == last
    assert graph[
        next(k for k, n in graph.items() if n["inputs"].get("lora_name") == "a.safetensors")
    ]["inputs"]["model"] == ["44", 0]
    with pytest.raises(ValueError, match="at most 2"):
        wf.fill(values, [("a.safetensors", 1.0), ("b.safetensors", 1.0), ("c.safetensors", 1.0)])
