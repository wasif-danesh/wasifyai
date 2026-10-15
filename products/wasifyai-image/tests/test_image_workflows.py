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


# ---- LoRAs (stage C) ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "guider"), [("flux2-klein-4b", "10"), ("flux2-klein-4b-edit", "16")]
)
def test_a_lora_goes_between_the_model_and_the_guider(name, guider):
    wf = Workflow.load(WORKFLOWS, name)
    assert wf.accepts_loras
    values = {"prompt": "a fox", "seed": 1}
    if name.endswith("edit"):
        values["image"] = "wasifyai-JOB.png"
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
    song = Workflow.load(PRODUCTS / "wasifyai-music" / "workflows", "flux2-klein-4b")
    if not song.accepts_loras:
        with pytest.raises(ValueError, match="does not take LoRAs"):
            song.fill({"prompt": "x"}, [("a.safetensors", 1.0)])


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
