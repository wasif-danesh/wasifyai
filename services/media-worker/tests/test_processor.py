import asyncio

import httpx
import pytest
from wasifyai_media_worker.comfy import ComfyClient
from wasifyai_media_worker.gpu import LocalGpuLock, unload_llms
from wasifyai_media_worker.processor import ComfyRunner, JobProcessor, RetryJob, StubRunner
from wasifyai_media_worker.settings import WorkerSettings
from wasifyai_media_worker.state import InMemoryJobState
from wasifyai_platform_sdk import (
    InMemoryEventLog,
    InMemoryUsageRecorder,
    JobRequest,
    memory_storage,
    object_key,
)

RUN, THREAD = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"


GRAPH = {
    "8": {"class_type": "KSampler", "inputs": {}},
    "10": {"class_type": "SaveImage", "inputs": {}},
}


def job(graph=None, **kw) -> JobRequest:
    kw = {"product_id": "p1", **kw}
    return JobRequest(
        tenant_id="t1",
        user_id="u1",
        run_id=RUN,
        thread_id=THREAD,
        capability="image.generate",
        workflow="demo",
        prompt=graph or GRAPH,
        outputs={"image": {"node": "10", "type": "image"}},
        **kw,
    )


class Rig:
    def __init__(self, runner, settings=None, http=None):
        self.log, self.storage, self.usage = (
            InMemoryEventLog(),
            memory_storage(),
            InMemoryUsageRecorder(),
        )
        self.state = InMemoryJobState()
        self.p = JobProcessor(
            settings or WorkerSettings(max_attempts=2, ollama_base_url=""),
            self.log, self.storage, self.usage, runner, LocalGpuLock(), self.state, http,
        )  # fmt: skip

    async def events(self):
        return await self.log.read("t1", RUN, 0, 1)


@pytest.fixture
def comfy_rig(comfy):
    base, fake = comfy
    client = ComfyClient(base)
    return Rig(ComfyRunner(client, 10)), fake


async def test_completed_job_stores_output_reports_progress_and_usage(comfy_rig):
    rig, fake = comfy_rig
    result = await rig.p.process(job())

    assert result.status == "completed" and result.gpu_seconds > 0
    out = result.outputs["image"]
    assert (
        out.key.startswith("jobs/")
        and out.key.endswith("/image.png")
        and out.content_type == "image/png"
    )
    # stored under the owner's tenant/product/user prefix, and the result key is relative to it
    stored = object_key("t1", "p1", "u1", out.key)
    assert (await rig.storage.get(stored)).startswith(b"\x89PNG")
    assert fake.freed == 1  # ComfyUI was asked to release its models afterwards

    ev = await rig.events()
    statuses = [e["status"] for e in ev if e["event"] == "job_progress"]
    assert statuses[0] == "running" and statuses[-1] == "completed"
    progress = [e["progress"] for e in ev if e["status"] == "running"]
    assert progress[0] == 0.0 and progress == sorted(progress)  # never goes backwards
    assert ev[-1]["progress"] == 1.0 and [e["seq"] for e in ev] == list(range(1, len(ev) + 1))

    kinds = {e.kind: e for e in rig.usage.events}
    assert kinds["job.completed"].quantity == 1
    assert kinds["gpu.seconds"].quantity == result.gpu_seconds
    assert (kinds["job.completed"].tenant_id, kinds["job.completed"].user_id) == ("t1", "u1")


async def test_redelivered_job_is_not_run_again(comfy_rig):
    rig, fake = comfy_rig
    first = await rig.p.process(job(job_id="same"))
    n_events, n_submitted = len(await rig.events()), len(fake.submitted)
    again = await rig.p.process(job(job_id="same"))

    # the same result; only its `trace` differs (each delivery is a span of its own)
    assert again.model_copy(update={"trace": {}}) == first.model_copy(update={"trace": {}})
    assert len(fake.submitted) == n_submitted and len(await rig.events()) == n_events


async def test_failed_job_reports_a_generic_error_and_no_completion_usage(comfy):
    base, _ = comfy
    rig = Rig(ComfyRunner(ComfyClient(base), 10))
    result = await rig.p.process(
        job(
            {
                "1": {"class_type": "Boom", "inputs": {}},
                "10": {"class_type": "SaveImage", "inputs": {}},
            }
        )
    )

    assert result.status == "failed" and result.error.code == "execution_failed"  # type: ignore[union-attr]
    assert "CUDA" not in result.error.message  # type: ignore[union-attr]
    assert (await rig.events())[-1]["status"] == "failed"
    kinds = {e.kind for e in rig.usage.events}
    assert "job.completed" not in kinds and "gpu.seconds" in kinds  # the GPU time was still spent


async def test_timeout_is_a_retryable_failure(comfy):
    base, fake = comfy
    rig = Rig(ComfyRunner(ComfyClient(base), 0.3))
    result = await rig.p.process(job({"1": {"class_type": "Slow", "inputs": {}}}))
    assert (result.status, result.error.code, result.error.retryable) == ("failed", "timeout", True)  # type: ignore[union-attr]
    assert fake.interrupted == 1


class Unreachable:
    async def run(self, job, on_progress):
        raise httpx.ConnectError("connection refused")


async def test_unreachable_backend_retries_then_gives_up():
    rig = Rig(Unreachable())
    j = job()
    with pytest.raises(RetryJob) as e:
        await rig.p.process(j)  # attempt 1 of 2
    assert e.value.attempt == 1 and "ConnectError" in str(e.value)
    result = await rig.p.process(j)  # attempt 2 of 2: give up with a clean failure
    assert result.error.code == "backend_unavailable" and "refused" not in result.error.message  # type: ignore[union-attr]


async def test_stub_runner_makes_placeholder_files_without_a_gpu():
    rig = Rig(StubRunner())
    picture = job()
    picture.outputs = {"image": {"node": "1", "type": "image"}}
    result = await rig.p.process(picture)
    assert result.status == "completed"
    assert (
        await rig.storage.get(object_key("t1", "p1", "u1", result.outputs["image"].key))
    ).startswith(b"\x89PNG")


async def test_one_job_at_a_time_on_a_gpu():
    active = peak = 0

    class Tracking:
        async def run(self, job, on_progress):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.05)
            active -= 1
            return {"image": (b"x", "image/png", "png")}

    rig = Rig(Tracking())
    await asyncio.gather(*(rig.p.process(job(job_id=f"j{i}")) for i in range(4)))
    assert peak == 1


async def test_llms_are_unloaded_before_generation_starts():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path == "/api/ps":
            return httpx.Response(
                200, json={"models": [{"name": "gemma4:e4b"}, {"name": "nomic-embed-text:latest"}]}
            )
        assert request.method == "POST" and b'"keep_alive":0' in request.content.replace(b" ", b"")
        return httpx.Response(200, json={})

    class Recording:
        async def run(self, job, on_progress):
            calls.append("GENERATE")
            return {"image": (b"x", "image/png", "png")}

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    rig = Rig(
        Recording(), WorkerSettings(ollama_base_url="http://ollama:11434", unload_llm=True), http
    )
    await rig.p.process(job())
    assert calls == ["GET /api/ps", "POST /api/generate", "POST /api/generate", "GENERATE"]


async def test_unload_is_best_effort_when_ollama_is_down():
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("down")))
    )
    assert await unload_llms("http://ollama:11434", http) == []  # logged, never raised


# ---- input pictures -----------------------------------------------------------------------

PICTURE = b"\x89PNG\r\n\x1a\n" + b"the-users-picture"


def edit_job2(**over) -> JobRequest:
    graph = {
        "5": {"class_type": "LoadImage", "inputs": {"image": "wasifyai-JOB1.png"}},
        "10": {"class_type": "SaveImage", "inputs": {}},
    }
    return job(graph).model_copy(
        update={
            "job_id": "JOB1",
            "capability": "image.edit",
            "inputs": {"prompt": "x", "image_key": "uploads/abc.png"},
            **over,
        }
    )


async def test_the_users_picture_is_read_from_their_prefix_and_uploaded_to_temp(comfy):
    base, fake = comfy
    rig = Rig(ComfyRunner(ComfyClient(base), 10))
    await rig.storage.put(object_key("t1", "p1", "u1", "uploads/abc.png"), PICTURE)
    result = await rig.p.process(edit_job2())
    assert result.status == "completed"
    content_type, body = fake.uploads[0]
    assert PICTURE in body and b'filename="wasifyai-JOB1.png"' in body
    assert b'name="type"\r\n\r\ntemp' in body  # ComfyUI's temp folder, cleared on its restart
    # the workflow loads it by the temp reference
    graph = fake.submitted[0]["prompt"]
    assert graph["5"]["inputs"]["image"] == "wasifyai-uploaded.png [temp]"


async def test_a_clip_to_carry_on_is_uploaded_as_an_mp4_the_loader_can_read(comfy):
    base, fake = comfy
    rig = Rig(ComfyRunner(ComfyClient(base), 10))
    clip = b"\x00\x00\x00 ftypisom" + b"the-users-clip"
    await rig.storage.put(object_key("t1", "p1", "u1", "uploads/extend-a.mp4"), clip)
    graph = {
        "90": {"class_type": "LoadVideo", "inputs": {"file": "wasifyai-JOB1-video.mp4"}},
        "10": {"class_type": "SaveImage", "inputs": {}},
    }
    job_ = job(graph).model_copy(
        update={
            "job_id": "JOB1",
            "capability": "video.extend",
            "inputs": {"prompt": "x", "video_key": "uploads/extend-a.mp4"},
        }
    )
    result = await rig.p.process(job_)
    assert result.status == "completed"
    content_type, body = fake.uploads[0]
    assert clip in body and b'filename="wasifyai-JOB1-video.mp4"' in body
    assert b"Content-Type: video/mp4" in body
    # the workflow loads it by whatever reference the engine gave (the fake always says .png)
    assert fake.submitted[0]["prompt"]["90"]["inputs"]["file"] == "wasifyai-uploaded.png [temp]"


async def test_another_users_picture_is_never_read(comfy):
    base, fake = comfy
    rig = Rig(ComfyRunner(ComfyClient(base), 10))
    await rig.storage.put(object_key("t1", "p1", "someone-else", "uploads/abc.png"), PICTURE)
    result = await rig.p.process(edit_job2())  # job.user_id is u1: that key is not there for u1
    assert result.status == "failed" and result.error and result.error.code == "invalid_input"
    assert not fake.uploads and not fake.submitted


@pytest.mark.parametrize(
    "key", ["../u2/uploads/abc.png", "jobs/x/image.png", "uploads/../x.png", "", 5]
)
async def test_only_keys_under_uploads_are_accepted(comfy, key):
    base, fake = comfy
    rig = Rig(ComfyRunner(ComfyClient(base), 10))
    result = await rig.p.process(edit_job2(inputs={"prompt": "x", "image_key": key}))
    if key == "":  # no picture asked for: an ordinary job
        assert result.status == "completed"
    else:
        assert result.status == "failed" and result.error and result.error.code == "invalid_input"
        assert not fake.uploads


async def test_a_runner_that_takes_no_files_is_still_called_the_old_way():
    class Plain:
        backend = "plain"
        local_gpu = True

        async def run(self, job, on_progress):
            return {"image": (b"\x89PNGx", "image/png", "png")}

    rig = Rig(Plain())
    result = await rig.p.process(job())  # no picture: no files argument
    assert result.status == "completed"


# ---- a person's own look, for one job (ADR-0073, docs/train-web-plan.md) ----------


class LookRunner:
    """Notes the graph it was given and whether the look's file was there while it ran."""

    backend = "look-test"
    local_gpu = False

    def __init__(self, root):
        self.root, self.graph, self.seen = root, None, None

    async def run(self, job, on_progress, files=None):
        self.graph = job.prompt
        name = job.prompt["90"]["inputs"]["lora_name"]
        self.seen = (self.root / name).read_bytes() if (self.root / name).is_file() else None
        return {"image": (b"\x89PNG", "image/png", "png")}


LOOK = "wasify-video-ena-12345678.safetensors"
LOOK_GRAPH = {
    "90": {
        "class_type": "LoraLoaderModelOnly",
        "inputs": {"model": ["44", 0], "lora_name": LOOK, "strength_model": 1.5},
    },
    "10": {"class_type": "SaveImage", "inputs": {}},
}  # fmt: skip


def look_job(key: str, **over) -> JobRequest:
    inputs = {"loras": [{"name": LOOK, "weight": 1.5}], "lora_files": {LOOK: key}}
    return job(LOOK_GRAPH, inputs=inputs, **over)


async def test_a_persons_own_look_is_there_while_the_job_runs_and_gone_after(tmp_path):
    runner = LookRunner(tmp_path)
    rig = Rig(
        runner, WorkerSettings(max_attempts=1, ollama_base_url="", media_loras_dir=str(tmp_path))
    )
    key = object_key("t1", "wasifyai-training", "u1", "train", "looks", "r1") + f"/{LOOK}"
    await rig.storage.put(key, b"LOOKBYTES")
    result = await rig.p.process(look_job(key))
    assert result.status == "completed", result
    assert runner.seen == b"LOOKBYTES"
    assert runner.graph is not None
    staged = runner.graph["90"]["inputs"]["lora_name"]
    assert staged.startswith("wasify-user/") and staged.endswith(f"-{LOOK}") and staged != LOOK
    assert not any(p.is_file() for p in tmp_path.rglob("*.safetensors"))  # removed after the job


@pytest.mark.parametrize(
    "key_of",
    [
        lambda: (
            object_key("t1", "wasifyai-training", "other", "train", "looks", "r1") + f"/{LOOK}"
        ),  # another person's
        lambda: (
            object_key("t1", "wasifyai-training", "u1", "train", "models", "m1")
            + "/adapter.safetensors"
        ),  # not a look
        lambda: (
            object_key("t1", "wasifyai-training", "u1", "train", "looks", "r1")
            + f"/../models/m1/{LOOK}"
        ),
    ],
)
async def test_a_look_that_is_not_the_persons_own_fails_the_job_and_reads_nothing(tmp_path, key_of):
    runner = LookRunner(tmp_path)
    rig = Rig(
        runner, WorkerSettings(max_attempts=1, ollama_base_url="", media_loras_dir=str(tmp_path))
    )
    key = key_of()
    await rig.storage.put(key, b"SECRET") if ".." not in key else None
    result = await rig.p.process(look_job(key))
    assert result.status == "failed" and result.error is not None
    assert result.error.code == "invalid_input"
    assert runner.graph is None and not list(tmp_path.rglob("*.safetensors"))


async def test_a_style_the_admin_added_is_fetched_for_a_picture_and_only_for_a_picture(tmp_path):
    """ADR-0091 S5: the service's styles live under the image product's `service` part."""
    runner = LookRunner(tmp_path)
    rig = Rig(
        runner, WorkerSettings(max_attempts=1, ollama_base_url="", media_loras_dir=str(tmp_path))
    )
    key = object_key("t1", "wasifyai-image", "service", "styles", "ab12cd34ef56.safetensors")
    await rig.storage.put(key, b"SERVICESTYLE")
    result = await rig.p.process(look_job(key, product_id="wasifyai-image"))
    assert result.status == "completed", result
    assert runner.seen == b"SERVICESTYLE"
    other = await rig.p.process(look_job(key, product_id="wasifyai-video"))  # not on a clip
    assert other.status == "failed" and other.error is not None
    elsewhere = object_key("t2", "wasifyai-image", "service", "styles", "x.safetensors")
    await rig.storage.put(elsewhere, b"OTHERTENANT")
    third = await rig.p.process(look_job(elsewhere, product_id="wasifyai-image"))
    assert third.status == "failed"  # another tenant's service styles are not this one's


async def test_a_worker_with_nowhere_to_put_a_look_says_so(tmp_path):
    rig = Rig(LookRunner(tmp_path), WorkerSettings(max_attempts=1, ollama_base_url=""))
    result = await rig.p.process(look_job("x"))
    assert result.status == "failed" and result.error is not None
    assert "cannot use a look" in result.error.message


# ---- a stopped job (stage J3) ------------------------------------------------------------


class Stops:
    def __init__(self, *ids: str) -> None:
        self.ids = set(ids)

    async def is_cancelled(self, job_id: str) -> bool:
        return job_id in self.ids


async def test_a_job_stopped_while_it_waited_in_the_line_is_never_run(comfy):
    base, fake = comfy
    rig = Rig(ComfyRunner(ComfyClient(base), 10))
    j = job()
    rig.p.cancels = Stops(j.job_id)
    result = await rig.p.process(j)
    err = result.error
    assert result.status == "failed" and err is not None
    assert (err.code, err.retryable) == ("cancelled", False)
    assert fake.submitted == []  # ComfyUI never saw it
    assert "job.completed" not in {e.kind for e in rig.usage.events}


async def test_a_job_stopped_while_running_interrupts_comfyui_and_frees_the_gpu(comfy, monkeypatch):
    import wasifyai_media_worker.processor as processor

    monkeypatch.setattr(processor, "CANCEL_POLL_S", 0.05)
    base, fake = comfy
    rig = Rig(ComfyRunner(ComfyClient(base), 30))
    stops = Stops()
    rig.p.cancels = stops
    j = job({"1": {"class_type": "Slow", "inputs": {}}})  # never finishes on its own
    work = asyncio.create_task(rig.p.process(j))
    await asyncio.sleep(0.3)
    stops.ids.add(j.job_id)
    result = await asyncio.wait_for(work, 5)
    assert (result.status, result.error.code) == ("failed", "cancelled")  # type: ignore[union-attr]
    assert result.error.message == "Stopped."  # type: ignore[union-attr]
    assert fake.interrupted == 1
    # the GPU lock was given back: the next job runs
    assert (await asyncio.wait_for(rig.p.process(job()), 5)).status == "completed"
