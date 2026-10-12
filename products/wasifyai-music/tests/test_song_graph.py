"""The song graph end to end with scripted fake models and an in-memory queue: no GPU, no
network. The "worker" is the test itself, resuming the graph with a job result."""

from typing import Any

import pytest
from conftest import GOOD_LYRICS, draft, make_rig, verdict
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from wasifyai_music.graphs.song import MAX_REGENERATIONS, build_song_graph
from wasifyai_music.songs import FixedQuota, InMemorySongStore
from wasifyai_platform_sdk import JobError, JobFailed, JobOutput, JobResult, RunError, object_key

CONFIG: Any = {"configurable": {"thread_id": "th-1"}}
IDEA: Any = {"idea": "a rainy night in Tokyo", "genre": "indie pop", "mood": "mellow"}


def lyrics_prompts(rig) -> list:
    """What `text.lyrics` was asked. (One fake provider serves every text capability, so its
    recorded prompts include the guardrail's; lyrics requests are the ones with an <idea>.)"""
    provider = rig.caps.text._bound["lyrics"][1]
    return [p for p in provider.prompts if "<idea>" in str(p)]


class Story:
    """Drives a run: start it, answer interrupts, play the media worker."""

    def __init__(self, rig, quota=None):
        self.rig = rig
        self.songs = InMemorySongStore()
        self.quota = quota or FixedQuota(0)
        self.graph = build_song_graph(rig.caps, InMemorySaver(), self.songs, self.quota)
        self.state: dict = {}

    async def start(self, input: Any = None):
        self.state = await self.graph.ainvoke(input or IDEA, CONFIG)
        return self

    async def answer(self, value: Any):
        self.state = await self.graph.ainvoke(Command(resume=value), CONFIG)
        return self

    @property
    def waiting(self) -> dict:
        """What the run is waiting for (an interrupt's payload), or {} if it is not waiting."""
        intr = self.state.get("__interrupt__")
        return intr[0].value if intr else {}

    async def finish_job(self, name: str, ext: str, status="completed"):
        """What the media worker does: store the file, report the result."""
        job = self.rig.sink.submitted[-1]
        assert self.waiting == {"kind": "job", "job_id": job.job_id}
        if status == "completed":
            rel = f"jobs/{job.job_id}/{name}.{ext}"
            await self.rig.raw.put(object_key("t1", "wasifyai-music", "u1", rel), b"data")
            result = JobResult(
                job_id=job.job_id,
                status="completed",
                outputs={name: JobOutput(key=rel, content_type="x/y", size=4)},
            )
        else:
            result = JobResult(
                job_id=job.job_id,
                status="failed",
                error=JobError(code="job_failed", message="The generation failed."),
            )
        return await self.answer(result.model_dump())

    async def approve(self, **edits):
        return await self.answer({"action": "approve", **edits})

    async def to_approval(self):
        await self.start()
        assert self.waiting and self.waiting["kind"] == "approve_lyrics"
        return self


async def test_a_song_from_idea_to_finished_files(tmp_path, ctx):
    rig = make_rig(tmp_path)
    s = await Story(rig).to_approval()
    assert s.waiting["title"] == "Sing It Out Loud" and s.waiting["lyrics"] == GOOD_LYRICS
    assert s.waiting["regenerations_left"] == MAX_REGENERATIONS and s.waiting["error"] == ""

    await s.approve()
    music = rig.sink.submitted[0]
    assert music.capability == "music.generate" and music.prompt["lyrics"] == GOOD_LYRICS
    assert (
        music.prompt["style"] == "indie pop, mellow, female vocal, 100 bpm"
    )  # request tags + model's
    assert (music.tenant_id, music.product_id, music.user_id) == ("t1", "wasifyai-music", "u1")

    await s.finish_job(
        "audio", "mp3"
    )  # music done -> cover job is queued next, one after the other
    assert [j.capability for j in rig.sink.submitted] == ["music.generate", "image.generate"]
    assert "rainy city window" in rig.sink.submitted[1].prompt["prompt"]

    await s.finish_job("image", "png")
    final = s.state
    assert final["status"] == "done" and "__interrupt__" not in final
    sid = final["song_id"]
    # files are re-keyed to the documented layout and the temporary job paths are gone
    assert final["audio_key"] == f"{sid}/audio.mp3" and final["cover_key"] == f"{sid}/cover.png"
    assert await rig.raw.exists(object_key("t1", "wasifyai-music", "u1", f"{sid}/audio.mp3"))
    assert not await rig.raw.exists(
        object_key("t1", "wasifyai-music", "u1", f"jobs/{music.job_id}/audio.mp3")
    )
    assert final["audio_url"].endswith(f"{sid}/audio.mp3") and final["cover_url"].endswith(
        f"{sid}/cover.png"
    )
    # recorded: the song, and one usage event
    (song,) = s.songs.songs
    assert (song.id, song.title, song.audio_key) == (sid, "Sing It Out Loud", f"{sid}/audio.mp3")
    assert song.user_id == "u1" and song.thread_id == "th-1" and song.run_id == "run-1"
    created = [e for e in rig.usage.events if e.kind == "song.created"]
    assert len(created) == 1 and created[0].meta["song_id"] == sid


# ---- the guardrail -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "category",
    ["artist_voice", "existing_lyrics", "disallowed_content"],
)
async def test_refused_requests_stop_before_any_generation(tmp_path, ctx, category):
    rig = make_rig(tmp_path, moderate=[verdict(False, category, "SECRET-REASON")])
    s = await Story(rig).start({"idea": "sing like someone famous"})
    assert s.state["status"] == "refused" and s.state["refusal"]["code"] == category
    assert s.state["refusal"]["message"] and "SECRET-REASON" not in s.state["refusal"]["message"]
    assert rig.sink.submitted == [] and "lyrics" not in s.state  # nothing written, nothing queued
    assert s.songs.songs == [] and not [e for e in rig.usage.events if e.kind == "song.created"]


@pytest.mark.parametrize(
    "idea, fragment",
    [("", "describe the song"), ("   \n\t ", "describe the song"), ("x" * 501, "under 500")],
)
async def test_invalid_ideas_are_refused_without_calling_a_model(tmp_path, ctx, idea, fragment):
    rig = make_rig(tmp_path)
    s = await Story(rig).start({"idea": idea})
    assert (
        s.state["refusal"]["code"] == "invalid_request"
        and fragment in s.state["refusal"]["message"]
    )
    assert rig.usage.events == []  # no LLM call was made, so nothing was metered


async def test_quota_is_checked_first_and_costs_nothing(tmp_path, ctx):
    rig = make_rig(tmp_path, quotas={"songs_per_user_per_day": 3})
    s = await Story(rig, FixedQuota(used=3)).start()
    assert (
        s.state["refusal"]["code"] == "quota_exceeded"
        and "limit of 3 songs" in s.state["refusal"]["message"]
    )
    assert rig.usage.events == []  # refused before the guardrail model, let alone the GPU


async def test_quota_is_checked_again_just_before_the_gpu(tmp_path, ctx):
    rig = make_rig(tmp_path, quotas={"songs_per_user_per_day": 3})
    story = Story(rig, FixedQuota(used=2))
    await story.to_approval()
    story.quota.used = 3  # the user's other tab finished a song meanwhile
    with pytest.raises(RunError) as e:
        await story.approve()
    assert e.value.code == "quota_exceeded" and rig.sink.submitted == []


async def test_no_configured_limit_means_no_quota(tmp_path, ctx):
    rig = make_rig(tmp_path, quotas={})
    s = await Story(rig, FixedQuota(used=999)).to_approval()
    assert s.waiting["kind"] == "approve_lyrics"


# ---- lyrics -------------------------------------------------------------------------------


async def test_lyrics_stream_to_the_client_as_they_are_written(tmp_path, ctx):
    rig = make_rig(tmp_path)
    graph = build_song_graph(rig.caps, InMemorySaver(), InMemorySongStore(), FixedQuota(0))
    tokens, starts = [], []
    async for chunk in graph.astream(IDEA, CONFIG, stream_mode="custom"):
        if chunk["type"] == "token":
            tokens.append(chunk["text"])
        elif chunk.get("status") == "started":
            starts.append(chunk["label"])
    assert "".join(tokens) == GOOD_LYRICS  # only the lyrics, never the JSON around them
    assert starts == ["Checking your request", "Writing lyrics"]


async def test_bad_lyrics_are_retried_with_feedback_and_the_ui_is_told_to_reset(tmp_path, ctx):
    no_chorus = draft(lyrics="[verse]\n" + "\n".join(f"line {i}" for i in range(10)))
    rig = make_rig(tmp_path, lyrics=[no_chorus, draft()])
    graph = build_song_graph(rig.caps, InMemorySaver(), InMemorySongStore(), FixedQuota(0))
    starts = [
        c["label"]
        async for c in graph.astream(IDEA, CONFIG, stream_mode="custom")
        if c.get("status") == "started"
    ]
    assert starts == ["Checking your request", "Writing lyrics", "Rewriting lyrics"]
    prompts = lyrics_prompts(rig)
    assert (
        len(prompts) == 2
        and "Fix this from your previous attempt" in prompts[1]
        and "[chorus]" in prompts[1]
    )


async def test_giving_up_on_lyrics_ends_the_run_with_a_clean_error(tmp_path, ctx):
    rig = make_rig(tmp_path, lyrics=["garbage"])
    with pytest.raises(RunError) as e:
        await Story(rig).start()
    assert e.value.code == "lyrics_failed" and e.value.retryable and "rephrasing" in e.value.message
    assert len(lyrics_prompts(rig)) == 3  # three attempts, no more


# ---- approval -----------------------------------------------------------------------------


async def test_regenerating_writes_a_new_draft_and_counts_it(tmp_path, ctx):
    second = draft(title="Second Try")
    rig = make_rig(tmp_path, lyrics=[draft(), second])
    s = await Story(rig).to_approval()
    await s.answer({"action": "regenerate"})
    assert (
        s.waiting["title"] == "Second Try"
        and s.waiting["regenerations_left"] == MAX_REGENERATIONS - 1
    )
    assert rig.sink.submitted == []  # nothing queued yet


async def test_the_regeneration_limit_is_enforced(tmp_path, ctx):
    rig = make_rig(tmp_path)
    s = await Story(rig).to_approval()
    for _ in range(MAX_REGENERATIONS):
        await s.answer({"action": "regenerate"})
    await s.answer({"action": "regenerate"})  # one too many: asked again, with the reason
    assert s.waiting["kind"] == "approve_lyrics" and "limit" in s.waiting["error"]
    await s.approve()  # approving still works
    assert rig.sink.submitted[0].capability == "music.generate"


async def test_edited_lyrics_are_what_gets_sung(tmp_path, ctx):
    edited = GOOD_LYRICS.replace("Rain on the window", "Snow on the window")
    rig = make_rig(tmp_path)
    s = await Story(rig).to_approval()
    await s.approve(lyrics=edited, title="  Snow Song ", style="folk, gentle")
    job = rig.sink.submitted[0]
    assert "Snow on the window" in job.prompt["lyrics"] and "Rain on" not in job.prompt["lyrics"]
    assert job.prompt["style"] == "indie pop, mellow, folk, gentle"
    await s.finish_job("audio", "mp3")
    await s.finish_job("image", "png")
    assert s.songs.songs[0].title == "Snow Song"


@pytest.mark.parametrize(
    "edit, fragment",
    [
        ({"lyrics": "just some words with no structure"}, "[verse]"),
        ({"lyrics": "[verse]\na\n[chorus]\nb"}, "at least 6 lines"),
        ({"title": "   "}, "cannot be empty"),
        ({"lyrics": GOOD_LYRICS + "\nx" * 3000}, "too long"),
    ],
)
async def test_invalid_edits_ask_again_with_the_reason(tmp_path, ctx, edit, fragment):
    rig = make_rig(tmp_path)
    s = await Story(rig).to_approval()
    await s.approve(**edit)
    assert s.waiting["kind"] == "approve_lyrics" and fragment in s.waiting["error"]
    assert rig.sink.submitted == []
    await s.approve()  # a valid answer then goes through
    assert rig.sink.submitted[0].capability == "music.generate"


async def test_a_malformed_answer_is_asked_again(tmp_path, ctx):
    rig = make_rig(tmp_path)
    s = await Story(rig).to_approval()
    await s.answer({"action": "launch the rockets"})
    assert s.waiting["kind"] == "approve_lyrics" and s.waiting["error"]


async def test_edited_lyrics_are_screened_before_any_gpu_work(tmp_path, ctx):
    rig = make_rig(tmp_path, moderate=[verdict(), verdict(False, "existing_lyrics")])
    s = await Story(rig).to_approval()  # the request passes
    await s.approve(lyrics=GOOD_LYRICS.replace("Rain", "Snow"))  # the screen refuses the edit
    assert s.waiting["kind"] == "approve_lyrics" and "existing song lyrics" in s.waiting["error"]
    assert rig.sink.submitted == []


# ---- media jobs ---------------------------------------------------------------------------


async def test_a_refused_cover_prompt_gets_a_neutral_cover_not_a_lost_song(tmp_path, ctx):
    rig = make_rig(tmp_path, moderate=[verdict(), verdict(), verdict(False, "disallowed_content")])
    s = await Story(rig).to_approval()
    await s.approve()
    await s.finish_job("audio", "mp3")
    cover_job = rig.sink.submitted[1]
    assert (
        cover_job.prompt["prompt"].startswith("abstract album cover art")
        and "rainy" not in cover_job.prompt["prompt"]
    )
    await s.finish_job("image", "png")
    assert s.state["status"] == "done"


async def test_a_failed_cover_job_still_delivers_the_song(tmp_path, ctx):
    rig = make_rig(tmp_path)
    s = await Story(rig).to_approval()
    await s.approve()
    await s.finish_job("audio", "mp3")
    await s.finish_job("image", "png", status="failed")
    st = s.state
    assert st["status"] == "done" and st["cover_url"] == "" and st["audio_url"]
    assert s.songs.songs[0].cover_key is None
    assert "cover_error" in st


async def test_a_failed_music_job_ends_the_run_with_the_jobs_error(tmp_path, ctx):
    rig = make_rig(tmp_path)
    s = await Story(rig).to_approval()
    await s.approve()
    with pytest.raises(JobFailed) as e:
        await s.finish_job("audio", "mp3", status="failed")
    assert e.value.result.error is not None
    assert (
        e.value.result.error.message == "The generation failed."
    )  # the API turns this into an error event
    assert len(rig.sink.submitted) == 1 and s.songs.songs == []  # no cover job, no song
