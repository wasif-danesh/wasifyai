"""Extend video: the last frames of a clip start a new clip, and the two are joined (VX0).
The "worker" is the test itself; the clips are real tiny H.264 files, so the join is real."""

from typing import Any

import pytest
from test_video_graph import Story, exists  # noqa: I001
from video_rig import frame_count, make_rig, mp4
from wasifyai_platform_sdk import JobFailed, RunError, object_key
from wasifyai_video.schemas import LENGTHS, OVERLAP_FRAMES
from wasifyai_video.videos import InMemoryVideoStore, VideoRecord, join_clips

NEW = LENGTHS[5]  # the new part of a five second extension


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
    assert job.prompt["length"] == NEW and job.prompt["prompt"] == "the fox keeps walking"
    temp = job.prompt["video_key"]  # the worker reads only the user's uploads
    assert temp.startswith("uploads/extend-") and temp.endswith(".mp4")
    assert await exists(rig, temp)
    row = next(v for v in store.videos if v.id != vid)
    assert (row.status, row.mode, row.frames, row.seconds) == ("working", "extend", 40 + NEW, 7)

    await s.finish_job(data=mp4(frames=NEW))
    final = s.state
    assert final["status"] == "done" and final["mode"] == "extend" and final["seconds"] == 7
    joined = await rig.raw.get(
        object_key("t1", "wasifyai-video", "u1", f"{final['video_id']}/video.mp4")
    )
    assert frame_count(joined) == 40 + NEW  # 40 kept, the whole new clip
    assert not await exists(rig, temp) and not await exists(rig, f"jobs/{job.job_id}/video.mp4")
    assert await exists(rig, f"{vid}/video.mp4")  # the original stays
    assert {v.id for v in store.videos} == {vid, final["video_id"]}
    (created,) = [e for e in rig.usage.events if e.kind == "video.created"]
    assert created.meta["mode"] == "extend"


async def test_a_longer_extension_can_be_asked_for_and_the_new_part_is_that_long(tmp_path, ctx):
    rig, store = make_rig(tmp_path), InMemoryVideoStore()
    vid = await make_source(rig, store, frames=49)
    s = await Story(rig, videos=store).start(
        {"mode": "extend", "prompt": "the fox keeps walking", "source_id": vid, "seconds": 8}
    )
    (job,) = rig.sink.submitted
    assert job.prompt["length"] == LENGTHS[8] == 193
    await s.finish_job(data=mp4(frames=LENGTHS[8]))
    row = next(v for v in store.videos if v.id == s.state["video_id"])
    assert (row.frames, s.state["seconds"]) == (40 + 193, 10)


@pytest.mark.parametrize("seconds", [2, 6, 10])
async def test_only_the_lengths_that_are_offered_can_be_asked_for(tmp_path, ctx, seconds):
    rig, store = make_rig(tmp_path), InMemoryVideoStore()
    vid = await make_source(rig, store)
    s = await Story(rig, videos=store).start(
        {"mode": "extend", "prompt": "x", "source_id": vid, "seconds": seconds}
    )
    assert s.state["status"] == "refused" and "5 or 8 seconds" in s.state["refusal"]["message"]
    assert rig.sink.submitted == []


@pytest.mark.parametrize("frames", [89, 121, 300])
async def test_a_clip_of_any_length_can_be_carried_on_again_and_again(tmp_path, ctx, frames):
    """No cap on the length (owner, 2026-10-21): the engine is given only the last second."""
    rig, store = make_rig(tmp_path), InMemoryVideoStore()
    vid = await make_source(rig, store, frames=frames, mode="extend")
    s = await start(rig, store, vid)
    (job,) = rig.sink.submitted
    assert job.prompt["from_frame"] == 24 - OVERLAP_FRAMES
    sent = await rig.raw.get(object_key("t1", "wasifyai-video", "u1", job.prompt["video_key"]))
    assert frame_count(sent) == 24
    await s.finish_job(data=mp4(frames=NEW))
    row = next(v for v in store.videos if v.id == s.state["video_id"])
    assert row.frames == frames - OVERLAP_FRAMES + NEW


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


async def test_one_clip_at_a_time_applies_to_extending_too(tmp_path, ctx):
    rig, store = make_rig(tmp_path), InMemoryVideoStore()
    vid = await make_source(rig, store)
    other = await make_source(rig, store, status="working", vid="busy-1")
    assert other
    s = await start(rig, store, vid)
    assert s.state["refusal"]["code"] == "busy"
    assert rig.sink.submitted == []


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
    assert rig.asked() == []  # nothing judges what the person added
    await s.finish_job(data=mp4(frames=NEW))
    row = next(v for v in store.videos if v.id == s.state["video_id"])
    assert (row.mode, row.frames) == ("extend", 191 + NEW)
    joined = await rig.raw.get(object_key("t1", "wasifyai-video", "u1", f"{row.id}/video.mp4"))
    assert frame_count(joined) == 191 + NEW
    assert not await exists(rig, job.prompt["video_key"])


async def test_a_clip_the_model_made_is_not_looked_at_again(tmp_path, ctx):
    rig, store = make_rig(tmp_path), InMemoryVideoStore()
    vid = await make_source(rig, store, frames=49, mode="text")
    await start(rig, store, vid)
    assert rig.asked() == []
