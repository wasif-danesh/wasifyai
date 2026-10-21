"""Extend video: the last frames of a clip start a new clip, and the two are joined (VX0).
The "worker" is the test itself; the clips are real tiny H.264 files, so the join is real."""

from typing import Any

import pytest
from test_video_graph import Story, exists  # noqa: I001
from video_rig import frame_count, make_rig, mp4, verdict
from wasifyai_platform_sdk import JobFailed, RunError, object_key
from wasifyai_video.schemas import EXTEND_FRAMES, MAX_EXTENDABLE_FRAMES, OVERLAP_FRAMES
from wasifyai_video.videos import FixedQuota, InMemoryVideoStore, VideoRecord, join_clips


async def make_source(rig, store, frames=49, status="done", mode="text", vid="src-1"):
    """A finished clip of the library: its row and its file."""
    await store.add(
        VideoRecord(
            vid, "t1", "wasifyai-video", "u1", None, None, mode, status, "a fox walks", 2,
            frames, 24, 128, 96,
            video_key=f"{vid}/video.mp4" if status == "done" else None,
            poster_key=f"{vid}/poster.jpg" if status == "done" else None,
        )
    )  # fmt: skip
    if status == "done":
        await rig.raw.put(
            object_key("t1", "wasifyai-video", "u1", f"{vid}/video.mp4"), mp4(frames=frames)
        )
    return vid


async def start(rig, store, vid, prompt="the fox keeps walking"):
    return await Story(rig, videos=store).start(
        {"mode": "extend", "prompt": prompt, "source_id": vid}
    )


async def test_the_new_clip_starts_from_the_last_frames_and_is_joined_on(tmp_path, ctx):
    rig, store = make_rig(tmp_path), InMemoryVideoStore()
    vid = await make_source(rig, store, frames=49)
    s = await Story(rig, videos=store).start(
        {"mode": "extend", "prompt": "the fox keeps walking", "source_id": vid}
    )
    (job,) = rig.sink.submitted
    assert job.capability == "video.extend"
    assert job.prompt["from_frame"] == 49 - OVERLAP_FRAMES == 40
    assert job.prompt["length"] == EXTEND_FRAMES and job.prompt["prompt"] == "the fox keeps walking"
    temp = job.prompt["video_key"]  # the worker reads only the user's uploads
    assert temp.startswith("uploads/extend-") and temp.endswith(".mp4")
    assert await exists(rig, temp)
    row = next(v for v in store.videos if v.id != vid)
    assert (row.status, row.mode, row.frames, row.seconds) == ("working", "extend", 89, 4)

    await s.finish_job(data=mp4(frames=EXTEND_FRAMES))
    final = s.state
    assert final["status"] == "done" and final["mode"] == "extend" and final["seconds"] == 4
    joined = await rig.raw.get(
        object_key("t1", "wasifyai-video", "u1", f"{final['video_id']}/video.mp4")
    )
    assert frame_count(joined) == 40 + EXTEND_FRAMES  # 40 kept, the whole new clip
    assert not await exists(rig, temp) and not await exists(rig, f"jobs/{job.job_id}/video.mp4")
    assert await exists(rig, f"{vid}/video.mp4")  # the original stays
    assert {v.id for v in store.videos} == {vid, final["video_id"]}
    (created,) = [e for e in rig.usage.events if e.kind == "video.created"]
    assert created.meta["mode"] == "extend"


async def test_a_clip_that_was_extended_can_be_extended_once_more(tmp_path, ctx):
    rig, store = make_rig(tmp_path), InMemoryVideoStore()
    vid = await make_source(rig, store, frames=89, mode="extend")
    s = await start(rig, store, vid)
    (job,) = rig.sink.submitted
    # a longer clip is given to the engine as its last second only: nine frames from its 24
    assert job.prompt["from_frame"] == 24 - OVERLAP_FRAMES
    assert (
        frame_count(
            await rig.raw.get(object_key("t1", "wasifyai-video", "u1", job.prompt["video_key"]))
        )
        == 24
    )
    await s.finish_job(data=mp4(frames=EXTEND_FRAMES))
    row = next(v for v in store.videos if v.id == s.state["video_id"])
    assert row.frames == 129 and s.state["seconds"] == 5


@pytest.mark.parametrize("frames", [MAX_EXTENDABLE_FRAMES + 1, 121, 129])
async def test_a_clip_that_is_already_long_is_refused_and_nothing_is_copied(tmp_path, ctx, frames):
    rig, store = make_rig(tmp_path), InMemoryVideoStore()
    vid = await make_source(rig, store, frames=frames)
    s = await start(rig, store, vid)
    assert s.state["status"] == "refused" and s.state["refusal"]["code"] == "clip_too_long"
    assert rig.sink.submitted == [] and rig.asked() == [] and len(store.videos) == 1


@pytest.mark.parametrize("which", ["missing", "working", "someone-else"])
async def test_only_a_finished_clip_of_the_person_can_be_carried_on(tmp_path, ctx, which):
    rig, store = make_rig(tmp_path), InMemoryVideoStore()
    if which == "working":
        vid = await make_source(rig, store, status="working")
    elif which == "someone-else":
        vid = "theirs"
        await store.add(
            VideoRecord(
                vid, "t1", "wasifyai-video", "someone-else", None, None, "text", "done", "x", 2,
                49, 24, 128, 96, video_key="theirs/video.mp4", poster_key="theirs/poster.jpg",
            )
        )  # fmt: skip
    else:
        vid = "nope"
    s = await start(rig, store, vid)
    assert s.state["status"] == "refused" and "finished videos" in s.state["refusal"]["message"]
    assert rig.sink.submitted == []


async def test_it_says_what_is_missing(tmp_path, ctx):
    rig, store = make_rig(tmp_path), InMemoryVideoStore()
    vid = await make_source(rig, store)
    s = await start(rig, store, vid, prompt="   ")
    assert "say what should keep happening" in s.state["refusal"]["message"]
    assert rig.sink.submitted == [] and rig.asked() == []


async def test_the_words_are_checked_and_a_refusal_copies_nothing(tmp_path, ctx):
    rig = make_rig(tmp_path, moderate=[verdict(False, "hate", "no")])
    store = InMemoryVideoStore()
    vid = await make_source(rig, store)
    s = await start(rig, store, vid)
    assert s.state["status"] == "refused" and s.state["refusal"]["code"] == "hate"
    assert rig.sink.submitted == [] and len(store.videos) == 1
    assert len(rig.word_checks()) == 1


async def test_one_clip_at_a_time_and_the_daily_limit_apply_to_extending_too(tmp_path, ctx):
    rig, store = make_rig(tmp_path), InMemoryVideoStore()
    vid = await make_source(rig, store)
    other = await make_source(rig, store, status="working", vid="busy-1")
    assert other
    s = await start(rig, store, vid)
    assert s.state["refusal"]["code"] == "busy"
    rig2, store2 = make_rig(tmp_path / "b"), InMemoryVideoStore()
    vid2 = await make_source(rig2, store2)
    s2 = await Story(rig2, videos=store2, quota=FixedQuota(5)).start(
        {"mode": "extend", "prompt": "x", "source_id": vid2}
    )
    assert s2.state["refusal"]["code"] == "quota_exceeded"
    assert rig.sink.submitted == [] and rig2.sink.submitted == []


async def test_a_failed_job_fails_the_row_and_deletes_the_copy(tmp_path, ctx):
    rig, store = make_rig(tmp_path), InMemoryVideoStore()
    vid = await make_source(rig, store)
    s = await start(rig, store, vid)
    temp = rig.sink.submitted[0].prompt["video_key"]
    with pytest.raises(JobFailed):
        await s.finish_job("failed")
    row = next(v for v in store.videos if v.id != vid)
    assert row.status == "failed" and not await exists(rig, temp)
    assert await exists(rig, f"{vid}/video.mp4")


async def test_a_join_that_cannot_be_made_fails_the_row_and_deletes_the_copy(tmp_path, ctx):
    rig, store = make_rig(tmp_path), InMemoryVideoStore()
    vid = await make_source(rig, store)
    s = await start(rig, store, vid)
    temp = rig.sink.submitted[0].prompt["video_key"]
    with pytest.raises(RunError) as e:
        await s.finish_job(data=b"not a video")
    assert e.value.code == "video_failed"
    row = next(v for v in store.videos if v.id != vid)
    assert row.status == "failed" and not await exists(rig, temp)
    assert not [e for e in rig.usage.events if e.kind == "video.created"]


async def test_a_job_that_cannot_be_queued_leaves_no_copy_and_no_working_row(tmp_path, ctx):
    rig, store = make_rig(tmp_path), InMemoryVideoStore()
    vid = await make_source(rig, store)

    async def boom(**kwargs: Any):
        raise ConnectionError("queue down")

    rig.caps.video.extend = boom  # type: ignore[method-assign]
    with pytest.raises(ConnectionError):
        await start(rig, store, vid)
    row = next(v for v in store.videos if v.id != vid)
    assert row.status == "failed"
    listed = [k for k in await rig.raw.list("t1/wasifyai-video/u1/uploads")]
    assert listed == []


async def test_the_join_keeps_the_first_frames_and_all_of_the_new_clip():
    joined = await join_clips(mp4(frames=30), mp4(frames=20), keep=21)
    assert frame_count(joined) == 41


async def test_a_video_the_person_added_can_be_carried_on_whatever_its_length(tmp_path, ctx):
    rig, store = make_rig(tmp_path), InMemoryVideoStore()
    vid = await make_source(rig, store, frames=200, mode="import")  # more than a made clip may be
    s = await start(rig, store, vid, prompt="the people keep walking")
    (job,) = rig.sink.submitted
    assert job.prompt["from_frame"] == 24 - OVERLAP_FRAMES
    temp = object_key("t1", "wasifyai-video", "u1", job.prompt["video_key"])
    assert frame_count(await rig.raw.get(temp)) == 24  # only the end goes to the engine
    assert len(rig.picture_checks()) == 1  # its last frame was looked at, as a picture is
    await s.finish_job(data=mp4(frames=EXTEND_FRAMES))
    row = next(v for v in store.videos if v.id == s.state["video_id"])
    assert (row.mode, row.frames) == ("extend", 191 + EXTEND_FRAMES)
    joined = await rig.raw.get(object_key("t1", "wasifyai-video", "u1", f"{row.id}/video.mp4"))
    assert frame_count(joined) == 191 + EXTEND_FRAMES
    assert not await exists(rig, job.prompt["video_key"])


async def test_an_added_clip_that_the_moderator_refuses_is_not_carried_on(tmp_path, ctx):
    rig = make_rig(tmp_path, moderate_image=[verdict(False, "minors")])
    store = InMemoryVideoStore()
    vid = await make_source(rig, store, frames=49, mode="import")
    s = await start(rig, store, vid)
    assert s.state["status"] == "refused" and s.state["refusal"]["code"] == "minors"
    assert rig.sink.submitted == [] and len(store.videos) == 1


async def test_a_clip_the_model_made_is_not_looked_at_again(tmp_path, ctx):
    rig, store = make_rig(tmp_path), InMemoryVideoStore()
    vid = await make_source(rig, store, frames=49, mode="text")
    await start(rig, store, vid)
    assert rig.picture_checks() == []
