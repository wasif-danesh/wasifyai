import pytest
from wasifyai_media_worker.comfy import ComfyClient, ComfyError

GRAPH = {
    "8": {"class_type": "KSampler", "inputs": {}},
    "10": {"class_type": "SaveImage", "inputs": {}},
    "12": {"class_type": "SaveAudio", "inputs": {}},
}


async def collect(client, graph, limit=10.0):
    seen: list[float] = []

    async def progress(p: float) -> None:
        seen.append(p)

    return await client.run(graph, "client-1", progress, limit), seen


async def test_run_reports_progress_and_returns_outputs(comfy):
    base, fake = comfy
    client = ComfyClient(base)
    outputs, seen = await collect(client, GRAPH)

    assert seen == [0.25, 0.5, 0.75, 1.0]  # the other client's progress message is ignored
    assert fake.submitted[0]["client_id"] == "client-1"
    img = client.pick(outputs, "10", "image")
    assert (img.filename, img.type) == ("out_10.png", "output")
    assert (await client.fetch(img)).startswith(b"\x89PNG")
    assert (await client.fetch(client.pick(outputs, "12", "audio"))).startswith(b"RIFF")
    await client.aclose()


def test_a_saved_video_is_found_under_images_but_a_picture_is_not_a_video():
    outputs = {
        "58": {"images": [{"filename": "clip_00001_.mp4", "subfolder": "video", "type": "output"}],
               "animated": [True]},
        "10": {"images": [{"filename": "out_10.png", "subfolder": "", "type": "output"}]},
    }  # fmt: skip
    f = ComfyClient.pick(outputs, "58", "video")
    assert (f.filename, f.subfolder) == ("clip_00001_.mp4", "video")
    with pytest.raises(ComfyError):
        ComfyClient.pick(outputs, "10", "video")


async def test_missing_output_is_a_job_error(comfy):
    base, _ = comfy
    client = ComfyClient(base)
    outputs, _ = await collect(client, GRAPH)
    with pytest.raises(ComfyError) as e:
        client.pick(outputs, "10", "video")
    assert e.value.code == "missing_output"
    await client.aclose()


async def test_invalid_workflow_is_rejected_without_leaking_details(comfy):
    base, _ = comfy
    client = ComfyClient(base)
    with pytest.raises(ComfyError) as e:
        await collect(client, {"1": {"class_type": "Invalid", "inputs": {}}})
    assert e.value.code == "invalid_workflow"
    assert "/srv" not in e.value.message and "secret" not in e.value.message
    await client.aclose()


async def test_execution_error_message_is_generic(comfy):
    base, _ = comfy
    client = ComfyClient(base)
    with pytest.raises(ComfyError) as e:
        await collect(client, {"1": {"class_type": "Boom", "inputs": {}}})
    assert e.value.code == "execution_failed"
    assert (
        "CUDA" not in e.value.message and "/srv" not in e.value.message
    )  # backend details stay in logs
    await client.aclose()


async def test_timeout_interrupts_the_backend(comfy):
    base, fake = comfy
    client = ComfyClient(base)
    with pytest.raises(TimeoutError):
        await collect(client, {"1": {"class_type": "Slow", "inputs": {}}}, limit=0.3)
    assert fake.interrupted == 1
    await client.aclose()


async def test_free_asks_comfyui_to_release_models(comfy):
    base, fake = comfy
    client = ComfyClient(base)
    await client.free()
    assert fake.freed == 1
    await client.aclose()
