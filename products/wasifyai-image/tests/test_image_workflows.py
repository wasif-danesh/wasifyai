"""The product's config and workflows are consistent, and a picture reaches the right node."""

from pathlib import Path

import pytest
from wasifyai_platform_sdk import (
    CapabilityBinding,
    InMemoryJobSink,
    RunContext,
    input_image_name,
    load_product_config,
    reset_context,
    set_context,
)
from wasifyai_platform_sdk.providers.comfyui import ComfyUIProvider
from wasifyai_platform_sdk.workflows import Workflow, workflow_problems

PRODUCTS = Path(__file__).resolve().parents[2]
WORKFLOWS = PRODUCTS / "wasifyai-image" / "workflows"


def test_the_product_config_loads_and_binds_every_mode():
    cfg = load_product_config(PRODUCTS, "wasifyai-image", environ={})
    assert cfg.capabilities["image.generate"].workflow == "flux2-klein-4b"
    assert cfg.capabilities["image.edit"].workflow == "flux2-klein-4b-edit"
    assert cfg.capabilities["image.reference"].workflow == "flux2-klein-4b-reference"
    assert cfg.capabilities["image.inpaint"].workflow == "flux2-klein-4b-inpaint"
    assert cfg.capabilities["text.moderate"].model == "moderator"
    picture = cfg.capabilities["text.moderate_image"]
    assert picture.model == "multimodal" and picture.inputs == ["text", "image"]
    assert cfg.quotas == {"images_per_user_per_day": 20}
    assert cfg.uploads["image"].max_bytes == 10 * 1024 * 1024


ALL = [
    "flux2-klein-4b",
    "flux2-klein-4b-edit",
    "flux2-klein-4b-reference",
    "flux2-klein-4b-inpaint",
]


@pytest.mark.parametrize("name", ALL)
def test_every_mapped_node_exists_in_its_workflow(name):
    assert workflow_problems(WORKFLOWS, name) == []


def test_the_edit_workflow_takes_a_picture_and_no_size():
    wf = Workflow.load(WORKFLOWS, "flux2-klein-4b-edit")
    assert set(wf.map.inputs) == {"prompt", "seed", "steps", "image"}
    graph = wf.fill({"prompt": "make it dusk", "seed": 5, "image": "wasifyai-JOB.png"})
    loaders = [n for n in graph.values() if n["class_type"] == "LoadImage"]
    assert [n["inputs"]["image"] for n in loaders] == ["wasifyai-JOB.png"]
    assert wf.map.outputs["image"].type == "image"


def test_the_reference_workflow_takes_two_pictures_and_a_size():
    wf = Workflow.load(WORKFLOWS, "flux2-klein-4b-reference")
    assert set(wf.map.inputs) == {"prompt", "seed", "steps", "width", "height", "image", "image2"}
    graph = wf.fill(
        {
            "prompt": "x",
            "seed": 5,
            "width": 1344,
            "height": 768,
            "image": "a.png",
            "image2": "b.png",
        }
    )
    loaders = [n["inputs"]["image"] for n in graph.values() if n["class_type"] == "LoadImage"]
    assert sorted(loaders) == ["a.png", "b.png"]
    sizes = {
        (n["inputs"]["width"], n["inputs"]["height"])
        for n in graph.values()
        if n["class_type"] in ("EmptyFlux2LatentImage", "Flux2Scheduler")
    }
    assert sizes == {(1344, 768)}
    # both pictures reach both conditionings, one after the other (two reference latents each)
    refs = [n for n in graph.values() if n["class_type"] == "ReferenceLatent"]
    assert len(refs) == 4


def test_the_inpaint_workflow_takes_a_picture_and_a_mask_and_pastes_the_result_back():
    wf = Workflow.load(WORKFLOWS, "flux2-klein-4b-inpaint")
    assert set(wf.map.inputs) == {"prompt", "seed", "steps", "image", "mask"}
    graph = wf.fill({"prompt": "x", "seed": 5, "image": "a.png", "mask": "m.png"})
    assert [n["inputs"]["image"] for n in graph.values() if n["class_type"] == "LoadImage"] == [
        "a.png"
    ]
    assert [n["inputs"]["image"] for n in graph.values() if n["class_type"] == "LoadImageMask"] == [
        "m.png"
    ]
    # what is saved is the picture with only the masked area replaced, not the model's own picture
    saved = graph[wf.map.outputs["image"].node]["inputs"]["images"]
    pasted = graph[saved[0]]
    assert pasted["class_type"] == "ImageCompositeMasked"
    decoded = graph[pasted["inputs"]["source"][0]]
    assert decoded["class_type"] == "VAEDecode"
    assert graph[pasted["inputs"]["destination"][0]]["class_type"] == "ImageScaleToTotalPixels"


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


# ---- LoRAs (stage C) ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "guider"),
    [
        ("flux2-klein-4b", "10"),
        ("flux2-klein-4b-edit", "16"),
        ("flux2-klein-4b-reference", "20"),
        ("flux2-klein-4b-inpaint", "26"),
    ],
)
def test_a_lora_goes_between_the_model_and_the_guider(name, guider):
    wf = Workflow.load(WORKFLOWS, name)
    assert wf.accepts_loras
    values = {"prompt": "a fox", "seed": 1}
    for slot in ("image", "image2", "mask"):
        if slot in wf.map.inputs:
            values[slot] = f"wasifyai-JOB-{slot}.png"
    plain = wf.fill(values)
    assert plain[guider]["inputs"]["model"] == ["1", 0]  # without LoRAs the graph is the original

    graph = wf.fill(values, [("ink.safetensors", 0.8), ("style/film.safetensors", 1.25)])
    top = max(int(k) for k in plain)
    first, second = str(top + 1), str(top + 2)
    assert graph[first]["class_type"] == "LoraLoaderModelOnly"
    assert graph[first]["inputs"] == {
        "model": ["1", 0], "lora_name": "ink.safetensors", "strength_model": 0.8,
    }  # fmt: skip
    assert graph[second]["inputs"]["model"] == [first, 0]
    assert graph[second]["inputs"]["lora_name"] == "style/film.safetensors"
    assert graph[guider]["inputs"]["model"] == [second, 0]
    # the original graph object is not changed
    assert wf.graph[guider]["inputs"]["model"] == ["1", 0]


def test_too_many_loras_and_a_workflow_without_a_chain_are_refused():
    wf = Workflow.load(WORKFLOWS, "flux2-klein-4b")
    with pytest.raises(ValueError, match="at most 3"):
        wf.fill({"prompt": "x"}, [(f"{n}.safetensors", 1.0) for n in range(4)])


def test_a_chain_that_points_at_a_missing_node_is_a_problem(tmp_path):
    (tmp_path / "w.json").write_text('{"1": {"class_type": "UNETLoader", "inputs": {}}}')
    (tmp_path / "w.map.yaml").write_text(
        "workflow: w.json\ninputs: {}\nlora_chain:\n  loader: LoraLoaderModelOnly\n"
        "  from: {node: '1', output: 0}\n  to: [{node: '9', field: model}]\n"
    )
    assert workflow_problems(tmp_path, "w") == ["w: lora_chain ends at missing node '9'"]


@pytest.mark.asyncio
async def test_the_provider_puts_loras_in_the_graph_and_in_the_job(ctx):
    sink = InMemoryJobSink()
    provider = ComfyUIProvider(WORKFLOWS, sink)
    binding = CapabilityBinding(provider="comfyui", workflow="flux2-klein-4b")
    loras = [{"name": "ink.safetensors", "weight": 0.7}]
    await provider.generate(
        "image.generate", binding, {"prompt": "a fox", "seed": 3, "loras": loras}
    )
    (job,) = sink.submitted
    assert job.inputs["loras"] == loras  # a backend that ignores the graph can still see them
    chain = [n for n in job.prompt.values() if n["class_type"] == "LoraLoaderModelOnly"]
    assert [n["inputs"]["lora_name"] for n in chain] == ["ink.safetensors"]

    with pytest.raises(ValueError, match="needs a name|each LoRA"):
        await provider.generate(
            "image.generate", binding, {"prompt": "x", "loras": [{"weight": 1}]}
        )


async def test_each_picture_of_a_job_is_named_by_its_slot_for_the_worker():
    sink = InMemoryJobSink()
    provider = ComfyUIProvider(WORKFLOWS, sink)
    token = set_context(RunContext("t1", "wasifyai-image", "u1", "run-1", "th-1"))
    try:
        await provider.generate(
            "image.reference",
            CapabilityBinding(provider="comfyui", workflow="flux2-klein-4b-reference"),
            {"prompt": "x", "seed": 1, "width": 1024, "height": 1024,
             "image_key": "uploads/a.png", "image2_key": "uploads/b.png"},
        )  # fmt: skip
        await provider.generate(
            "image.inpaint",
            CapabilityBinding(provider="comfyui", workflow="flux2-klein-4b-inpaint"),
            {"prompt": "x", "seed": 1, "image_key": "uploads/a.png", "mask_key": "uploads/m.png"},
        )
    finally:
        reset_context(token)
    ref, inp = sink.submitted
    names = {n["inputs"]["image"] for n in ref.prompt.values() if n["class_type"] == "LoadImage"}
    assert names == {input_image_name(ref.job_id), input_image_name(ref.job_id, "image2")}
    assert ref.inputs["image2_key"] == "uploads/b.png"  # the keys are for the worker, not the graph
    assert "image2_key" not in str(ref.prompt)
    mask = [n for n in inp.prompt.values() if n["class_type"] == "LoadImageMask"]
    assert mask[0]["inputs"]["image"] == input_image_name(inp.job_id, "mask")
    assert "mask_key" not in str(inp.prompt)


async def test_a_workflow_without_a_second_picture_input_refuses_one():
    provider = ComfyUIProvider(WORKFLOWS, InMemoryJobSink())
    binding = CapabilityBinding(provider="comfyui", workflow="flux2-klein-4b-edit")
    token = set_context(RunContext("t1", "wasifyai-image", "u1"))
    try:
        with pytest.raises(ValueError, match="no picture input 'image2'"):
            await provider.generate(
                "image.reference", binding,
                {"prompt": "x", "image_key": "uploads/a.png", "image2_key": "uploads/b.png"},
            )  # fmt: skip
    finally:
        reset_context(token)
