"""Lip sync in the worker (ADR-0044): the picture and voice go to the talking-head server, an MP4
comes back; the router picks this runner only for jobs made by the lip sync provider."""

import httpx
import pytest
from wasifyai_media_worker.backends import BackendRouter, BackendUnavailable
from wasifyai_media_worker.comfy import ComfyError
from wasifyai_media_worker.lipsync import LipSyncRunner
from wasifyai_media_worker.processor import StubRunner
from wasifyai_media_worker.settings import WorkerSettings
from wasifyai_platform_sdk import InMemoryMediaBindingStore, JobRequest, SecretBox

RUN, THREAD = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"


def job(workflow="lipsync") -> JobRequest:
    return JobRequest(
        tenant_id="t1", product_id="p1", user_id="u1", run_id=RUN, thread_id=THREAD,
        capability="video.lipsync", workflow=workflow, prompt={},
        inputs={"image_key": "uploads/a.png", "audio_key": "uploads/a.wav"},
        outputs={"video": {"node": "", "type": "video"}},
    )  # fmt: skip


async def progress(_: float) -> None:
    return None


def runner(handler) -> LipSyncRunner:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return LipSyncRunner("http://lip:8191/", 60, http)


async def test_the_picture_and_voice_are_sent_and_the_mp4_comes_back():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["body"] = str(request.url), request.read()
        return httpx.Response(200, content=b"MP4DATA", headers={"content-type": "video/mp4"})

    files = {"image": b"PNGBYTES", "audio": b"WAVBYTES"}
    out = await runner(handler).run(job(), progress, files=files)
    assert out == {"video": (b"MP4DATA", "video/mp4", "mp4")}
    assert seen["url"] == "http://lip:8191/v1/lipsync"
    assert b"PNGBYTES" in seen["body"] and b"WAVBYTES" in seen["body"] and b"25" in seen["body"]


async def test_a_job_without_its_picture_or_voice_is_invalid():
    with pytest.raises(ComfyError) as e:
        await runner(lambda r: httpx.Response(200)).run(job(), progress, files={"image": b"x"})
    assert e.value.code == "invalid_workflow"


async def test_a_picture_with_no_face_gets_a_plain_message():
    files = {"image": b"x", "audio": b"y"}
    with pytest.raises(ComfyError) as e:
        await runner(lambda r: httpx.Response(422, text="no face found")).run(
            job(), progress, files=files
        )
    assert e.value.code == "invalid_input" and "front-facing" in e.value.message


async def test_a_server_that_failed_the_job_is_not_asked_again():
    files = {"image": b"x", "audio": b"y"}
    with pytest.raises(ComfyError) as e:
        await runner(lambda r: httpx.Response(500, text="boom")).run(job(), progress, files=files)
    assert e.value.code == "job_failed" and "could not be made" in e.value.message


async def test_a_server_that_is_down_is_retried_later():
    files = {"image": b"x", "audio": b"y"}
    with pytest.raises(BackendUnavailable):
        await runner(lambda r: httpx.Response(503)).run(job(), progress, files=files)


def router(settings: WorkerSettings) -> BackendRouter:
    box = SecretBox(SecretBox.generate_key())
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    return BackendRouter(StubRunner(), settings, InMemoryMediaBindingStore(), box, http, poll_s=0)


async def test_only_jobs_from_the_lip_sync_provider_go_to_the_server():
    settings = WorkerSettings(
        lipsync_server_url="http://lip:8191", comfyui_video_base_url="http://v:8189"
    )
    r = router(settings)
    assert isinstance(await r.resolve(job()), LipSyncRunner)
    other = await r.resolve(job(workflow="demo"))  # a ComfyUI job is not taken
    assert not isinstance(other, LipSyncRunner)


async def test_without_the_server_address_a_lip_sync_stays_a_placeholder():
    unset = router(
        WorkerSettings(comfyui_mode="real", lipsync_server_url="", comfyui_video_base_url="")
    )
    assert isinstance(await unset.resolve(job()), StubRunner)


async def test_the_server_is_used_even_when_the_gpu_models_are_placeholders():
    """A laptop cluster runs ComfyUI as a placeholder but can reach the native lip sync server."""
    r = router(WorkerSettings(comfyui_mode="stub", lipsync_server_url="http://lip:8191"))
    assert isinstance(await r.resolve(job()), LipSyncRunner)
