"""The extra media backends and the router that picks one per job (ADR-0025). The remote services
are played by httpx mock transports, so no network or key is involved."""

import base64
import itertools
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from wasifyai_media_worker.backends import (
    BackendRouter,
    BackendUnavailable,
    ComfyApiRunner,
    OpenAIImagesRunner,
)
from wasifyai_media_worker.comfy import ComfyError
from wasifyai_media_worker.processor import ComfyRunner, JobProcessor, StubRunner
from wasifyai_media_worker.settings import WorkerSettings
from wasifyai_media_worker.state import InMemoryJobState
from wasifyai_platform_sdk import (
    InMemoryEventLog,
    InMemoryMediaBindingStore,
    InMemoryUsageRecorder,
    JobRequest,
    MediaBinding,
    SecretBox,
    memory_storage,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 50
MP3 = b"ID3" + b"y" * 50
RUN, THREAD = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
KEY = "comfyui-0123456789abcdef0123456789abcdef"


def job(capability="image.generate", outputs=None, **inputs) -> JobRequest:
    return JobRequest(
        tenant_id="t1",
        product_id="p1",
        user_id="u1",
        run_id=RUN,
        thread_id=THREAD,
        capability=capability,
        workflow="demo",
        prompt={"10": {"class_type": "SaveImage", "inputs": {}}},
        inputs=inputs,
        outputs=outputs or {"image": {"node": "10", "type": "image"}},
    )


class Progress:
    def __init__(self):
        self.values: list[float] = []

    async def __call__(self, p: float) -> None:
        self.values.append(p)


def client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---- Comfy API v2 -------------------------------------------------------------------------


def comfy_api(statuses, outputs=None, content=None, calls=None):
    """A Comfy API v2 server: `statuses` is the sequence of job states it reports."""
    calls = calls if calls is not None else []
    states = itertools.chain(statuses, itertools.repeat(statuses[-1]))  # the last one repeats
    outputs = (
        outputs
        if outputs is not None
        else [{"node_id": "10", "type": "image", "content_type": "image/png", "id": "asset-1"}]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url), request.headers.get("authorization")))
        path = request.url.path
        if request.method == "POST" and path == "/api/v2/jobs":
            return httpx.Response(201, json={"id": "remote-1", "status": "queued"})
        if request.method == "POST" and path.endswith("/cancel"):
            return httpx.Response(200, json={})
        if path == "/api/v2/jobs/remote-1":
            status = next(states)
            body = {"id": "remote-1", "status": status["status"], "progress": status.get("p", {})}
            if status["status"] == "succeeded":
                body["outputs"] = outputs
            if status["status"] == "failed":
                body["error"] = {"code": "oom", "message": "CUDA out of memory at node 7"}
            return httpx.Response(200, json=body)
        if path == "/api/v2/assets/asset-1/content":
            if content is not None:
                return httpx.Response(200, content=content, headers={"content-type": "image/png"})
            return httpx.Response(302, headers={"location": "https://storage.example/signed?sig=1"})
        if request.url.host == "storage.example":
            return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
        return httpx.Response(404)

    return handler, calls


def runner(handler, timeout=5.0) -> ComfyApiRunner:
    return ComfyApiRunner("https://comfy.example", KEY, timeout, client(handler), poll_s=0)


async def test_comfy_api_runs_a_job_and_never_sends_the_key_to_the_storage_host():
    handler, calls = comfy_api(
        [
            {"status": "queued"},
            {"status": "running", "p": {"value": 0.4}},
            {"status": "succeeded"},
        ]
    )
    progress = Progress()
    files = await runner(handler).run(job(), progress)

    assert files["image"][0] == PNG and files["image"][1:] == ("image/png", "png")
    assert progress.values == [0.4, 1.0]
    api_calls = [c for c in calls if "comfy.example" in c[1]]
    assert api_calls and all(c[2] == f"Bearer {KEY}" for c in api_calls)
    (storage_call,) = [c for c in calls if "storage.example" in c[1]]
    assert storage_call[2] is None  # the signed URL got no credentials


async def test_comfy_api_accepts_bytes_served_directly_by_a_self_hosted_proxy():
    handler, _ = comfy_api([{"status": "succeeded"}], content=PNG)
    files = await runner(handler).run(job(), Progress())
    assert files["image"][0] == PNG


async def test_comfy_api_picks_the_output_by_node_and_kind():
    outputs = [
        {"node_id": "3", "type": "image", "content_type": "image/png", "id": "asset-0"},
        {"node_id": "10", "type": "image", "content_type": "image/png", "id": "asset-1"},
    ]
    handler, calls = comfy_api([{"status": "succeeded"}], outputs=outputs)
    await runner(handler).run(job(), Progress())
    assert any("asset-1" in c[1] for c in calls) and not any("asset-0" in c[1] for c in calls)


async def test_comfy_api_audio_output():
    outputs = [{"node_id": "8", "type": "audio", "content_type": "audio/mpeg", "id": "asset-1"}]

    def handler(request):
        if request.method == "POST":
            return httpx.Response(201, json={"id": "remote-1"})
        if request.url.path == "/api/v2/jobs/remote-1":
            return httpx.Response(200, json={"status": "succeeded", "outputs": outputs})
        return httpx.Response(200, content=MP3, headers={"content-type": "audio/mpeg"})

    music = job("music.generate", outputs={"audio": {"node": "8", "type": "audio"}})
    files = await runner(handler).run(music, Progress())
    assert files["audio"] == (MP3, "audio/mpeg", "mp3")


async def test_comfy_api_missing_output_is_reported():
    handler, _ = comfy_api([{"status": "succeeded"}], outputs=[])
    with pytest.raises(ComfyError) as caught:
        await runner(handler).run(job(), Progress())
    assert caught.value.code == "missing_output"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "backend_auth"),
        (403, "backend_auth"),
        (402, "backend_credits"),
        (422, "invalid_workflow"),
    ],
)
async def test_comfy_api_maps_rejections_to_safe_errors(status, code):
    handler = lambda request: httpx.Response(status, json={"error": f"secret detail {KEY}"})  # noqa: E731
    with pytest.raises(ComfyError) as caught:
        await runner(handler).run(job(), Progress())
    assert caught.value.code == code
    assert KEY not in caught.value.message and "secret detail" not in caught.value.message


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_comfy_api_rate_limits_and_server_errors_are_retried(status):
    handler = lambda request: httpx.Response(status)  # noqa: E731
    with pytest.raises(BackendUnavailable):
        await runner(handler).run(job(), Progress())


async def test_comfy_api_failed_job_does_not_leak_the_backends_error_text():
    handler, _ = comfy_api([{"status": "failed"}])
    with pytest.raises(ComfyError) as caught:
        await runner(handler).run(job(), Progress())
    assert caught.value.code == "execution_failed" and "CUDA" not in caught.value.message


async def test_comfy_api_gives_up_and_cancels_when_a_job_takes_too_long():
    handler, calls = comfy_api([{"status": "running"}])
    with pytest.raises(TimeoutError):
        await runner(handler, timeout=0.2).run(job(), Progress())
    assert any(c[0] == "POST" and c[1].endswith("/cancel") for c in calls)


# ---- OpenAI-compatible images -------------------------------------------------------------


def images(runner_args=None, reply=None, seen=None):
    seen = seen if seen is not None else []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "cdn.example":
            return httpx.Response(200, content=PNG, headers={"content-type": "image/webp"})
        return (
            reply(request)
            if reply
            else httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(PNG).decode()}]})
        )

    args = {"size": None, "api_key": KEY, **(runner_args or {})}
    return OpenAIImagesRunner(
        "https://images.example/v1",
        "gpt-image-1",
        args["size"],
        args["api_key"],
        5.0,
        client(handler),
    ), seen


async def test_openai_images_sends_the_prompt_and_the_requested_size():
    r, seen = images()
    files = await r.run(job(prompt="a lighthouse", width=1024, height=1024), Progress())
    assert files["image"] == (PNG, "image/png", "png")
    body = json.loads(seen[0].content)
    assert body == {"model": "gpt-image-1", "prompt": "a lighthouse", "n": 1, "size": "1024x1024"}
    assert seen[0].url.path == "/v1/images/generations"
    assert seen[0].headers["authorization"] == f"Bearer {KEY}"


async def test_openai_images_size_setting_wins_and_no_key_means_no_header():
    r, seen = images({"size": "512x512", "api_key": None})
    await r.run(job(prompt="x", width=1024, height=1024), Progress())
    assert json.loads(seen[0].content)["size"] == "512x512"
    assert "authorization" not in seen[0].headers


async def test_openai_images_can_return_a_url():
    r, _ = images(
        reply=lambda req: httpx.Response(
            200, json={"data": [{"url": "https://cdn.example/a.webp"}]}
        )
    )
    files = await r.run(job(prompt="x"), Progress())
    assert files["image"] == (PNG, "image/webp", "webp")


@pytest.mark.parametrize("bad", [{}, {"prompt": ""}, {"prompt": 5}])
async def test_openai_images_needs_a_prompt(bad):
    r, seen = images()
    with pytest.raises(ComfyError) as caught:
        await r.run(job(**bad), Progress())
    assert caught.value.code == "invalid_workflow" and not seen


async def test_openai_images_error_mapping_and_empty_answer():
    r, _ = images(reply=lambda req: httpx.Response(401, json={"error": {"message": KEY}}))
    with pytest.raises(ComfyError) as caught:
        await r.run(job(prompt="x"), Progress())
    assert caught.value.code == "backend_auth" and KEY not in caught.value.message
    r, _ = images(reply=lambda req: httpx.Response(200, json={"data": [{}]}))
    with pytest.raises(ComfyError) as caught:
        await r.run(job(prompt="x"), Progress())
    assert caught.value.code == "missing_output"


# ---- the router ---------------------------------------------------------------------------


class Counting(InMemoryMediaBindingStore):
    gets = 0
    broken = False

    async def get(self, tenant_id, product_id, capability):
        Counting.gets += 1
        if Counting.broken:
            raise RuntimeError("database down")
        return await super().get(tenant_id, product_id, capability)


@pytest.fixture
def router_parts():
    Counting.gets, Counting.broken = 0, False
    box = SecretBox(SecretBox.generate_key())
    store = Counting()
    default = StubRunner()
    router = BackendRouter(default, WorkerSettings(comfyui_base_url="http://local:8188"), store,
                           box, client(lambda r: httpx.Response(404)), poll_s=0)  # fmt: skip
    return router, store, box, default


async def test_no_binding_means_the_default_runner(router_parts):
    router, _, _, default = router_parts
    assert await router.resolve(job()) is default


async def test_a_binding_picks_the_backend_and_decrypts_its_key(router_parts):
    router, store, box, _ = router_parts
    binding = MediaBinding(
        "p1", "image.generate", "comfy-api", {"base_url": "https://comfy.example"}, box.encrypt(KEY)
    )
    await store.put("t1", binding)
    chosen = await router.resolve(job())
    assert isinstance(chosen, ComfyApiRunner) and chosen.local_gpu is False
    assert chosen._headers == {"authorization": f"Bearer {KEY}"}
    assert chosen._base == "https://comfy.example"


async def test_bindings_are_per_product_and_capability(router_parts):
    router, store, box, default = router_parts
    await store.put("t1", MediaBinding("p1", "image.generate", "openai-images",
                                       {"model": "m"}, None))  # fmt: skip
    assert isinstance(await router.resolve(job()), OpenAIImagesRunner)
    other = job("music.generate", outputs={"audio": {"node": "8", "type": "audio"}})
    assert await router.resolve(other) is default


async def test_a_local_comfyui_binding_uses_its_own_address(router_parts):
    router, store, _, _ = router_parts
    await store.put("t1", MediaBinding("p1", "image.generate", "comfyui-local",
                                       {"base_url": "http://gpu-box:8188"}, None))  # fmt: skip
    chosen = await router.resolve(job())
    assert isinstance(chosen, ComfyRunner) and chosen.local_gpu
    assert chosen._client._base == "http://gpu-box:8188"
    await router.aclose()


async def test_video_jobs_use_the_separate_video_comfyui_when_one_is_set(router_parts):
    _, store, box, default = router_parts
    settings = WorkerSettings(
        comfyui_base_url="http://local:8188", comfyui_video_base_url="http://local:8189"
    )
    router = BackendRouter(
        default, settings, store, box, client(lambda r: httpx.Response(404)), poll_s=0
    )
    video = job("video.generate", outputs={"video": {"node": "58", "type": "video"}})
    chosen = await router.resolve(video)  # no binding: the video ComfyUI, not the default
    assert isinstance(chosen, ComfyRunner) and chosen._client._base == "http://local:8189"
    assert await router.resolve(job()) is default  # images are untouched
    await store.put("t1", MediaBinding("p1", "video.generate", "comfyui-local", {}, None))
    router._cache.clear()
    bound = await router.resolve(video)  # a local binding with no address: still the video one
    assert bound._client._base == "http://local:8189"
    await router.aclose()


@pytest.mark.parametrize("mode", ["stub", "sidecar"])
async def test_the_video_address_is_ignored_in_stub_and_sidecar_mode(router_parts, mode):
    # sidecar: this worker runs the desktop's own ComfyUI, which serves video too; the address in
    # .env is for the containers and does not resolve on the machine itself
    _, store, box, default = router_parts
    settings = WorkerSettings(comfyui_mode=mode, comfyui_video_base_url="http://local:8189")
    router = BackendRouter(
        default, settings, store, box, client(lambda r: httpx.Response(404)), poll_s=0
    )
    video = job("video.generate", outputs={"video": {"node": "58", "type": "video"}})
    assert await router.resolve(video) is default


async def test_the_lookup_is_cached_for_a_moment(router_parts):
    router, _, _, _ = router_parts
    await router.resolve(job())
    await router.resolve(job())
    assert Counting.gets == 1


async def test_a_key_that_cannot_be_decrypted_fails_the_job_cleanly(router_parts):
    router, store, _, _ = router_parts
    stranger = SecretBox(SecretBox.generate_key())  # a different MEDIA_SECRETS_KEY
    await store.put(
        "t1", MediaBinding("p1", "image.generate", "comfy-api", {}, stranger.encrypt(KEY))
    )
    with pytest.raises(ComfyError) as caught:
        await router.resolve(job())
    assert caught.value.code == "backend_misconfigured" and KEY not in caught.value.message


async def test_a_database_failure_is_retried_not_answered_with_another_backend(router_parts):
    router, _, _, _ = router_parts
    Counting.broken = True
    with pytest.raises(ConnectionError):
        await router.resolve(job())


# ---- the processor with a remote backend --------------------------------------------------


class SpyLock:
    def __init__(self):
        self.held = 0

    @asynccontextmanager
    async def hold(self):
        self.held += 1
        yield


async def test_a_remote_backend_takes_no_gpu_lock_and_does_not_unload_llms():
    seen: list[str] = []

    def ollama(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={})

    lock = SpyLock()
    usage, storage = InMemoryUsageRecorder(), memory_storage()
    handler, _ = comfy_api([{"status": "succeeded"}])
    remote = ComfyApiRunner("https://comfy.example", KEY, 5, client(handler), poll_s=0)
    p = JobProcessor(
        WorkerSettings(ollama_base_url="http://ollama:11434", unload_llm=True),
        InMemoryEventLog(), storage, usage, remote, lock, InMemoryJobState(), client(ollama),
    )  # fmt: skip
    result = await p.process(job())

    assert result.status == "completed" and result.gpu_seconds == 0.0
    assert lock.held == 0 and seen == []
    events = {e.kind: e for e in usage.events}
    assert "gpu.seconds" not in events and "media.remote_seconds" in events
    assert events["job.completed"].meta["backend"] == "comfy-api"


async def test_a_local_backend_still_takes_the_lock_and_records_gpu_seconds():
    lock, usage = SpyLock(), InMemoryUsageRecorder()
    p = JobProcessor(
        WorkerSettings(ollama_base_url=""), InMemoryEventLog(), memory_storage(), usage,
        StubRunner(), lock, InMemoryJobState(),
    )  # fmt: skip
    result = await p.process(job(capability="image.generate"))
    assert result.status == "completed" and lock.held == 1
    assert {e.kind for e in usage.events} >= {"gpu.seconds", "job.completed"}
    assert next(e for e in usage.events if e.kind == "job.completed").meta["backend"] == "stub"


async def test_a_misconfigured_backend_fails_the_job_without_retrying():
    class Broken:
        async def resolve(self, job):
            raise ComfyError(
                "backend_misconfigured", "The generation backend is not set up correctly."
            )

    p = JobProcessor(
        WorkerSettings(ollama_base_url=""), InMemoryEventLog(), memory_storage(),
        InMemoryUsageRecorder(), Broken(), SpyLock(), InMemoryJobState(),
    )  # fmt: skip
    result = await p.process(job())
    assert (
        result.status == "failed" and result.error and result.error.code == "backend_misconfigured"
    )
    assert result.error.retryable is False


# ---- input pictures (image to image, ADR-0035/0036) ---------------------------------------

PICTURE = b"\x89PNG\r\n\x1a\n" + b"the-users-picture"


def edit_job(**over) -> JobRequest:
    graph = {
        "5": {"class_type": "LoadImage", "inputs": {"image": "wasifyai-JOB.png"}},
        "10": {"class_type": "SaveImage", "inputs": {}},
    }
    base = {
        "job_id": "JOB", "capability": "image.edit", "prompt": graph,
        "inputs": {"prompt": "make it dusk", "image_key": "uploads/abc.png"},
    }  # fmt: skip
    return job().model_copy(update={**base, **over})


async def test_comfy_api_uploads_the_picture_and_points_the_workflow_at_it():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/upload/image":
            return httpx.Response(200, json={"name": "wasifyai-JOB.png", "subfolder": ""})
        return comfy_api([{"status": "succeeded"}])[0](request)

    files = await runner(handler).run(edit_job(), Progress(), files={"image": PICTURE})
    assert files["image"][0] == PNG
    upload = next(r for r in seen if r.url.path == "/api/upload/image")
    assert PICTURE in upload.content and b'name="type"' in upload.content
    assert upload.headers["authorization"] == f"Bearer {KEY}" and upload.headers["x-api-key"] == KEY
    submitted = next(r for r in seen if r.url.path == "/api/v2/jobs" and r.method == "POST")
    assert json.loads(submitted.content)["workflow"]["5"]["inputs"]["image"] == "wasifyai-JOB.png"


async def test_a_job_without_a_picture_makes_no_upload():
    seen: list[httpx.Request] = []
    handler, _ = comfy_api([{"status": "succeeded"}])

    def spy(request):
        seen.append(request)
        return handler(request)

    await runner(spy).run(job(), Progress())
    assert not [r for r in seen if r.url.path == "/api/upload/image"]


async def test_openai_images_edit_sends_the_picture_as_a_form():
    r, seen = images()
    files = await r.run(
        edit_job(
            inputs={
                "prompt": "make it dusk",
                "image_key": "uploads/a.png",
                "width": 640,
                "height": 480,
            }
        ),
        Progress(),
        files={"image": PICTURE},
    )
    assert files["image"][0] == PNG
    request = seen[0]
    assert request.url.path == "/v1/images/edits" and request.headers["content-type"].startswith(
        "multipart/form-data"
    )
    assert (
        PICTURE in request.content
        and b"make it dusk" in request.content
        and b"gpt-image-1" in request.content
    )
    assert b'name="size"' not in request.content  # the size follows the picture


async def test_openai_images_edit_keeps_an_admin_chosen_size():
    r, seen = images({"size": "1024x1024"})
    await r.run(edit_job(), Progress(), files={"image": PICTURE})
    assert b"1024x1024" in seen[0].content


async def test_openai_images_edit_without_a_picture_is_refused():
    r, seen = images()
    with pytest.raises(ComfyError) as caught:
        await r.run(edit_job(), Progress())
    assert caught.value.code == "invalid_input" and not seen
