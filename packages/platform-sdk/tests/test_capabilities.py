import pytest
from wasifyai_platform_sdk import (
    CapabilityNotConfigured,
    InMemoryJobSink,
    InMemoryUsageRecorder,
    ProviderDeps,
    build_capabilities,
    load_product_config,
)


def build(products, **kw):
    usage, sink = InMemoryUsageRecorder(), InMemoryJobSink()
    cfg = load_product_config(products, "demo", environ={})
    caps = build_capabilities(
        cfg, ProviderDeps(products, usage=usage, job_sink=sink, embedding_dims=16, **kw)
    )
    return caps, usage, sink


async def test_text_stream_and_complete_record_usage(products, ctx):
    caps, usage, _ = build(products)
    assert await caps.text.complete("chat", "be brief", "say hi") == "hi there "
    kinds = {e.kind for e in usage.events}
    assert kinds == {"llm.input_tokens", "llm.output_tokens"}
    e = usage.events[0]
    assert (e.tenant_id, e.product_id, e.user_id, e.run_id) == ("t1", "demo", "u1", "r1")


async def test_embed_is_deterministic_and_recorded(products, ctx):
    caps, usage, _ = build(products)
    a, b = await caps.text.embed("embed", ["the cat sat", "the cat sat"])
    assert a == b and len(a) == 16
    assert usage.events[-1].kind == "llm.embedding_tokens"


async def test_video_generate_builds_job_without_waiting(products, ctx):
    caps, _, sink = build(products)
    handle = await caps.video.generate(lyrics="[verse] la la", seed=7)
    assert handle.status == "queued" and handle.capability == "video.generate"
    job = sink.submitted[0]
    assert job.job_id == handle.job_id
    assert (job.tenant_id, job.product_id, job.user_id) == ("t1", "demo", "u1")
    # mapped inputs landed on the right nodes; config defaults applied; template untouched
    assert job.prompt["14"]["inputs"] == {"lyrics": "[verse] la la", "seconds": 60}
    assert job.prompt["3"]["inputs"]["seed"] == 7
    assert job.outputs == {"audio": {"node": "14", "type": "audio"}}


async def test_unknown_workflow_input_is_rejected(products, ctx):
    caps, _, _ = build(products)
    with pytest.raises(ValueError, match="no input"):
        await caps.video.generate(volume=11)


async def test_unconfigured_capability_names_the_product(products, ctx):
    caps, _, _ = build(products)
    with pytest.raises(CapabilityNotConfigured, match="'text.lyrics'.*'demo'"):
        await caps.text.complete("lyrics", "", "x")
    with pytest.raises(CapabilityNotConfigured, match="image.generate"):
        await caps.image.generate(prompt="x")


async def test_capabilities_require_a_run_context(products):
    caps, _, _ = build(products)
    with pytest.raises(RuntimeError, match="RunContext"):
        await caps.text.complete("chat", "", "x")


async def test_one_input_can_drive_several_nodes(products, ctx):
    (products / "demo" / "workflows" / "tiny.map.yaml").write_text(
        """
workflow: tiny.json
inputs:
  duration_s:
    - { node: "14", field: seconds }
    - { node: "3", field: seed }
outputs:
  audio: { node: "14", type: audio }
"""
    )
    caps, _, sink = build(products)
    await caps.video.generate(duration_s=45)
    job = sink.submitted[0]
    assert job.prompt["14"]["inputs"]["seconds"] == 45 and job.prompt["3"]["inputs"]["seed"] == 45


def two_models(products):
    """The demo product with two image models (ADR-0097): `big` does generate and edit, `small`
    only generate, each on its own workflow."""
    d = products / "demo"
    (d / "workflows" / "other.json").write_text((d / "workflows" / "tiny.json").read_text())
    (d / "workflows" / "other.map.yaml").write_text(
        (d / "workflows" / "tiny.map.yaml").read_text().replace("tiny.json", "other.json")
    )
    (d / "product.yaml").write_text(
        """
id: demo
capabilities:
  text.chat: { provider: fake }
models:
  - id: big
    capabilities:
      image.generate: { provider: comfyui, workflow: tiny }
      image.edit:     { provider: comfyui, workflow: tiny }
  - id: small
    capabilities:
      image.generate: { provider: comfyui, workflow: other, defaults: { duration_s: 5 } }
    settings: { frames_per_second: 16 }
"""
    )
    return build(products)


async def test_a_request_names_its_model_and_gets_that_models_workflow(products, ctx):
    caps, _, sink = two_models(products)
    await caps.image.generate(lyrics="a", seed=1)  # no model: the first
    await caps.image.generate(lyrics="b", seed=1, model="small")
    first, second = sink.submitted
    assert first.prompt["14"]["inputs"]["seconds"] == 30  # tiny, no defaults
    assert second.prompt["14"]["inputs"]["seconds"] == 5  # other, with its own defaults
    assert caps.image.models() == {"big": ["edit", "generate"], "small": ["generate"]}


async def test_a_model_that_cannot_do_a_thing_or_is_not_offered_says_so(products, ctx):
    caps, _, _ = two_models(products)
    with pytest.raises(CapabilityNotConfigured, match="'image.edit' of model 'small'"):
        await caps.image.edit(lyrics="x", model="small")
    with pytest.raises(CapabilityNotConfigured, match="model 'nope' is not offered"):
        await caps.image.generate(lyrics="x", model="nope")


def test_a_model_says_what_a_graph_needs_to_know_and_the_first_answers_for_none(products):
    caps, _, _ = two_models(products)
    assert caps.image.setting("small", "frames_per_second") == 16
    assert caps.image.setting(None, "frames_per_second", 24) == 24  # `big`, the first, says nothing
    assert caps.image.setting("nope", "frames_per_second", 24) == 24
