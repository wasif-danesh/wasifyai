"""The speech capability makes a job with no workflow graph (ADR-0042)."""

import yaml
from wasifyai_platform_sdk import (
    InMemoryJobSink,
    ProviderDeps,
    RunContext,
    build_capabilities,
    load_product_config,
    reset_context,
    set_context,
)


async def test_synthesize_queues_a_speech_job_with_what_to_say_and_an_audio_output(tmp_path):
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "product.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "p",
                "capabilities": {
                    "speech.synthesize": {"provider": "speech", "defaults": {"speed": 1.0}}
                },
            }
        )
    )
    sink = InMemoryJobSink()
    caps = build_capabilities(
        load_product_config(tmp_path, "p", environ={}), ProviderDeps(tmp_path, job_sink=sink)
    )
    token = set_context(RunContext("t1", "p", "u1", "run-1", "th-1"))
    try:
        handle = await caps.speech.synthesize(
            text="Hola", engine="kokoro", voice="ef_dora", model="m"
        )
    finally:
        reset_context(token)
    (job,) = sink.submitted
    assert job.job_id == handle.job_id and job.capability == "speech.synthesize"
    assert (job.workflow, job.prompt) == ("speech", {})
    assert job.inputs == {
        "speed": 1.0,
        "text": "Hola",
        "engine": "kokoro",
        "voice": "ef_dora",
        "model": "m",
    }
    assert job.outputs == {"audio": {"node": "", "type": "audio"}}
    assert (job.tenant_id, job.product_id, job.user_id, job.run_id) == ("t1", "p", "u1", "run-1")
