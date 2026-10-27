"""The video graph end to end with scripted fake models and an in-memory queue: no GPU, no network.
The "worker" is the test itself, resuming the graph with a job result."""

from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from video_rig import make_rig, mp4, put_upload, verdict
from wasifyai_platform_sdk import JobError, JobFailed, JobOutput, JobResult, RunError, object_key
from wasifyai_video.graphs.video import build_video_graph
from wasifyai_video.schemas import LENGTHS, SHAPES
from wasifyai_video.videos import FixedQuota, InMemoryVideoStore, VideoRecord

CONFIG: Any = {"configurable": {"thread_id": "th-1"}}


class Story:
    """Drives a run: start it, play the media worker."""

    def __init__(self, rig, quota=None, videos=None):
        self.rig = rig
        self.videos = videos or InMemoryVideoStore()
        self.graph = build_video_graph(
            rig.caps, InMemorySaver(), self.videos, rig.uploads, quota or FixedQuota(0)
        )
        self.state: dict = {}

    async def start(self, input: Any):
        self.state = await self.graph.ainvoke(input, CONFIG)
        return self

    @property
    def waiting(self) -> dict:
        intr = self.state.get("__interrupt__")
        return intr[0].value if intr else {}

    async def finish_job(self, status="completed", data: bytes | None = None):
        """What the media worker does: store the file, report the result."""
        job = self.rig.sink.submitted[-1]
        assert self.waiting == {"kind": "job", "job_id": job.job_id}
        if status == "completed":
            rel = f"jobs/{job.job_id}/video.mp4"
            await self.rig.raw.put(object_key("t1", "wasifyai-video", "u1", rel), data or mp4())
            result = JobResult(
                job_id=job.job_id,
                status="completed",
                outputs={"video": JobOutput(key=rel, content_type="video/mp4", size=4)},
            )
        else:
            result = JobResult(
                job_id=job.job_id,
                status="failed",
                error=JobError(code="job_failed", message="The generation failed on the GPU."),
            )
        self.state = await self.graph.ainvoke(Command(resume=result.model_dump()), CONFIG)
        return self


async def exists(rig, rel: str) -> bool:
    return await rig.raw.exists(object_key("t1", "wasifyai-video", "u1", rel))


# ---- text to video -----------------------------------------------------------------------


@pytest.mark.parametrize("shape", list(SHAPES))
@pytest.mark.parametrize("seconds", list(LENGTHS))
async def test_text_to_video_from_description_to_saved_clip(tmp_path, ctx, shape, seconds):
    rig = make_rig(tmp_path)
    s = await Story(rig).start(
        {"mode": "text", "prompt": "a red fox in the snow", "shape": shape, "seconds": seconds}
    )
    job = rig.sink.submitted[0]
    width, height = SHAPES[shape]
    assert job.capability == "video.generate"
    assert (job.prompt["width"], job.prompt["height"]) == (width, height)
    assert job.prompt["length"] == LENGTHS[seconds]
    assert job.prompt["prompt"] == "a red fox in the snow" and "image_key" not in job.prompt
    assert (job.tenant_id, job.product_id, job.user_id) == ("t1", "wasifyai-video", "u1")
    # the row exists from the moment the job starts, so the site can show "being made"
    (row,) = s.videos.videos
    assert (row.status, row.mode, row.seconds, row.frames) == (
        "working",
        "text",
        seconds,
        LENGTHS[seconds],
    )
    assert row.video_key is None

    await s.finish_job()
    final = s.state
    assert final["status"] == "done" and "__interrupt__" not in final
    vid = final["video_id"]
    assert final["video_key"] == f"{vid}/video.mp4" and final["poster_key"] == f"{vid}/poster.jpg"
    assert await exists(rig, f"{vid}/video.mp4") and await exists(rig, f"{vid}/poster.jpg")
    assert not await exists(rig, f"jobs/{job.job_id}/video.mp4")
    assert (final["width"], final["height"]) == (128, 96)  # the real size of what was made
    assert final["video_url"].endswith(f"{vid}/video.mp4")
    (done,) = s.videos.videos
    assert (done.id, done.status, done.width, done.height) == (vid, "done", 128, 96)
    assert done.video_key == final["video_key"] and done.poster_key == final["poster_key"]
    assert done.user_id == "u1" and done.thread_id == "th-1" and done.run_id == "run-1"
    created = [e for e in rig.usage.events if e.kind == "video.created"]
    assert len(created) == 1 and created[0].meta["video_id"] == vid
    assert created[0].meta["seconds"] == seconds


async def test_the_defaults_are_landscape_and_five_seconds(tmp_path, ctx):
    rig = make_rig(tmp_path)
    await Story(rig).start({"mode": "text", "prompt": "a fox"})
    job = rig.sink.submitted[0]
    assert (job.prompt["width"], job.prompt["height"]) == SHAPES["landscape"]
    assert job.prompt["length"] == LENGTHS[5] == 121


# ---- image to video ----------------------------------------------------------------------


async def test_image_to_video_uses_the_picture_and_deletes_it_afterwards(tmp_path, ctx):
    rig = make_rig(tmp_path)
    up = await put_upload(rig)
    s = await Story(rig).start(
        {"mode": "image", "prompt": "snow falls softly", "image_key": up.key, "seconds": 5}
    )
    job = rig.sink.submitted[0]
    assert job.capability == "video.animate" and job.prompt["length"] == LENGTHS[5]
    assert "width" not in job.prompt  # the clip takes the picture's shape
    assert job.prompt["image_key"] == up.key  # the fake queue keeps the inputs as they are
    assert await exists(rig, up.key)  # still there while the job runs
    await s.finish_job()
    assert s.state["status"] == "done"
    assert (
        not await exists(rig, up.key)
        and await rig.uploads.find("t1", "wasifyai-video", "u1", up.key) is None
    )
    assert len(rig.picture_checks()) == 1  # the model looked at the picture


async def test_a_missing_or_foreign_picture_is_refused_up_front(tmp_path, ctx):
    rig = make_rig(tmp_path)
    theirs = await put_upload(rig, user_id="someone-else")
    for key in ("", "uploads/nope.png", theirs.key):
        s = await Story(rig).start({"mode": "image", "prompt": "x", "image_key": key})
        assert (
            s.state["status"] == "refused"
            and "upload your picture again" in s.state["refusal"]["message"]
        )
    assert rig.sink.submitted == [] and await exists_for(rig, "someone-else", theirs.key)


async def exists_for(rig, user, rel):
    return await rig.raw.exists(object_key("t1", "wasifyai-video", user, rel))


# ---- refusals ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("input", "message"),
    [
        ({"mode": "nope", "prompt": "x"}, "what kind of video"),
        ({"mode": "text", "prompt": "   "}, "describe the video"),
        ({"mode": "text", "prompt": "x" * 501}, "under 500"),
        ({"mode": "text", "prompt": "x", "shape": "huge"}, "video shapes"),
        ({"mode": "text", "prompt": "x", "seconds": 10}, "5 or 8 seconds"),
        ({"mode": "text", "prompt": "x", "seconds": 2}, "5 or 8 seconds"),
    ],
)
async def test_bad_input_is_refused_before_any_model_is_asked(tmp_path, ctx, input, message):
    rig = make_rig(tmp_path)
    s = await Story(rig).start(input)
    assert s.state["status"] == "refused" and message in s.state["refusal"]["message"]
    assert rig.sink.submitted == [] and rig.asked() == [] and s.videos.videos == []


async def test_an_unsafe_description_is_refused_with_the_fixed_text(tmp_path, ctx):
    rig = make_rig(tmp_path, moderate=[verdict(False, "sexual_content", "nope")])
    s = await Story(rig).start({"mode": "text", "prompt": "something unsafe"})
    assert s.state["status"] == "refused"
    assert s.state["refusal"]["code"] == "sexual_content"
    assert "nudity" in s.state["refusal"]["message"] and "nope" not in s.state["refusal"]["message"]
    assert rig.sink.submitted == [] and s.videos.videos == []


async def test_an_unsafe_picture_is_refused_and_the_upload_is_deleted(tmp_path, ctx):
    rig = make_rig(tmp_path, moderate_image=[verdict(False, "minors")])
    up = await put_upload(rig)
    s = await Story(rig).start({"mode": "image", "prompt": "he smiles", "image_key": up.key})
    assert s.state["status"] == "refused" and s.state["refusal"]["code"] == "minors"
    assert not await exists(rig, up.key) and rig.sink.submitted == []


async def test_a_moderator_that_cannot_answer_fails_closed(tmp_path, ctx):
    rig = make_rig(tmp_path, moderate=["garbage"])
    with pytest.raises(RunError) as e:
        await Story(rig).start({"mode": "text", "prompt": "a fox"})
    assert e.value.code == "moderation_unavailable" and e.value.retryable
    assert rig.sink.submitted == []


async def test_only_one_clip_is_made_at_a_time(tmp_path, ctx):
    rig = make_rig(tmp_path)
    store = InMemoryVideoStore()
    await store.add(
        VideoRecord(
            "v0", "t1", "wasifyai-video", "u1", None, None, "text", "working", "x", 2, 49, 24
        )
    )
    s = await Story(rig, videos=store).start({"mode": "text", "prompt": "a fox"})
    assert s.state["status"] == "refused" and s.state["refusal"]["code"] == "busy"
    assert rig.asked() == [] and rig.sink.submitted == []
    other = InMemoryVideoStore()
    await other.add(
        VideoRecord(
            "v1",
            "t1",
            "wasifyai-video",
            "someone-else",
            None,
            None,
            "text",
            "working",
            "x",
            2,
            49,
            24,
        )
    )
    s2 = await Story(rig, videos=other).start({"mode": "text", "prompt": "a fox"})
    assert s2.state.get("status") != "refused" and len(rig.sink.submitted) == 1


async def test_the_daily_quota_is_checked_before_any_model_is_asked(tmp_path, ctx):
    rig = make_rig(tmp_path)
    s = await Story(rig, quota=FixedQuota(5)).start({"mode": "text", "prompt": "a fox"})
    assert (
        s.state["refusal"]["code"] == "quota_exceeded"
        and "limit of 5 videos" in s.state["refusal"]["message"]
    )
    assert rig.asked() == [] and rig.sink.submitted == []


# ---- failures ----------------------------------------------------------------------------


async def test_a_failed_job_marks_the_row_failed_and_deletes_the_picture(tmp_path, ctx):
    rig = make_rig(tmp_path)
    up = await put_upload(rig)
    s = await Story(rig).start({"mode": "image", "prompt": "snow falls", "image_key": up.key})
    with pytest.raises(JobFailed):
        await s.finish_job("failed")
    (row,) = s.videos.videos
    assert row.status == "failed" and row.error == "The generation failed on the GPU."
    assert not await exists(rig, up.key)
    assert not [e for e in rig.usage.events if e.kind == "video.created"]


async def test_a_clip_that_cannot_be_read_fails_the_row_and_the_run(tmp_path, ctx):
    rig = make_rig(tmp_path)
    s = await Story(rig).start({"mode": "text", "prompt": "a fox"})
    with pytest.raises(RunError) as e:
        await s.finish_job(data=b"not a video")
    assert e.value.code == "video_failed" and e.value.retryable
    (row,) = s.videos.videos
    assert row.status == "failed" and "couldn't be made" in (row.error or "")
    assert not [e for e in rig.usage.events if e.kind == "video.created"]


async def test_a_picture_job_that_cannot_be_queued_does_not_leave_a_working_row(tmp_path, ctx):
    rig = make_rig(tmp_path)
    up = await put_upload(rig)

    async def boom(**kwargs):
        raise ConnectionError("queue down")

    rig.caps.video.animate = boom  # type: ignore[method-assign]
    with pytest.raises(ConnectionError):
        await Story(rig).start({"mode": "image", "prompt": "snow", "image_key": up.key})
    assert not await exists(rig, up.key)


# ---- looks the person taught (ADR-0073, video amendment) -----------------------------------


@pytest.mark.parametrize("mode", ["text", "image"])
async def test_looks_reach_the_job_in_both_modes(tmp_path, ctx, mode):
    rig = make_rig(tmp_path)
    looks = [{"name": "wasify-video-ena-1a2b3c4d.safetensors", "weight": 1.5}]
    request: dict[str, Any] = {
        "mode": mode,
        "prompt": "enav7qx, a woman on a beach",
        "seconds": 5,
        "loras": looks,
    }
    if mode == "image":
        request["image_key"] = (await put_upload(rig)).key
    await Story(rig).start(request)
    job = rig.sink.submitted[0]
    assert job.prompt["loras"] == looks


async def test_a_run_without_looks_sends_none(tmp_path, ctx):
    rig = make_rig(tmp_path)
    await Story(rig).start({"mode": "text", "prompt": "a red fox", "seconds": 5})
    assert "loras" not in rig.sink.submitted[0].prompt


@pytest.mark.parametrize(
    ("looks", "words"),
    [
        ("a look", "choose the looks"),
        ([{"name": "../x.safetensors"}], "cannot be used"),
        ([{"name": "x.ckpt"}], "cannot be used"),
        ([{"name": "a.safetensors", "weight": "high"}], "must be a number"),
        ([{"name": "a.safetensors", "weight": 9}], "between 0.1 and 2.5"),
        ([{"name": "a.safetensors"}, {"name": "a.safetensors"}], "once"),
        ([{"name": f"{c}.safetensors"} for c in "abc"], "at most 2"),
    ],
)
async def test_looks_that_cannot_be_used_are_refused_in_words_before_any_work(
    tmp_path, ctx, looks, words
):
    rig = make_rig(tmp_path)
    s = await Story(rig).start(
        {"mode": "text", "prompt": "a red fox", "seconds": 5, "loras": looks}
    )
    assert s.state["status"] == "refused" and s.state["refusal"]["code"] == "invalid_request"
    assert words in s.state["refusal"]["message"] and rig.sink.submitted == []


async def test_on_the_web_a_look_is_found_among_the_persons_own_and_its_file_goes_to_the_job(
    tmp_path, ctx
):
    rig = make_rig(tmp_path)
    asked: list[tuple[str, str, list[str]]] = []

    async def mine(tenant, user, names):
        asked.append((tenant, user, names))
        return {n: f"{tenant}/wasifyai-training/{user}/train/looks/r1/{n}" for n in names}

    rig.caps.extras["person_looks"] = mine
    name = "wasify-video-ena-1a2b3c4d.safetensors"
    await Story(rig).start(
        {"mode": "text", "prompt": "a fox", "seconds": 5, "loras": [{"name": name, "weight": 1.5}]}
    )
    job = rig.sink.submitted[0]
    assert asked == [("t1", "u1", [name])]
    assert job.prompt["lora_files"] == {name: f"t1/wasifyai-training/u1/train/looks/r1/{name}"}


async def test_a_look_that_is_not_the_persons_own_is_refused_before_any_work(tmp_path, ctx):
    rig = make_rig(tmp_path)

    async def nobody(tenant, user, names):
        return None

    rig.caps.extras["person_looks"] = nobody
    s = await Story(rig).start(
        {"mode": "text", "prompt": "a fox", "seconds": 5, "loras": [{"name": "x.safetensors"}]}
    )
    assert s.state["status"] == "refused" and "not yours" in s.state["refusal"]["message"]
    assert rig.sink.submitted == []
