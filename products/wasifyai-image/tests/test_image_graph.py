"""The image graph end to end with scripted fake models and an in-memory queue: no GPU, no network.
The "worker" is the test itself, resuming the graph with a job result."""

from typing import Any

import pytest
from image_rig import make_rig, png, put_upload, verdict
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from wasifyai_image.graphs.image import build_image_graph
from wasifyai_image.images import FixedQuota, InMemoryImageStore
from wasifyai_image.schemas import SIZES
from wasifyai_platform_sdk import (
    Image,
    JobError,
    JobFailed,
    JobOutput,
    JobResult,
    RunError,
    object_key,
)

CONFIG: Any = {"configurable": {"thread_id": "th-1"}}


class Story:
    """Drives a run: start it, play the media worker."""

    def __init__(self, rig, quota=None):
        self.rig = rig
        self.images = InMemoryImageStore()
        self.graph = build_image_graph(
            rig.caps, InMemorySaver(), self.images, rig.uploads, quota or FixedQuota(0)
        )
        self.state: dict = {}

    async def start(self, input: Any):
        self.state = await self.graph.ainvoke(input, CONFIG)
        return self

    @property
    def waiting(self) -> dict:
        intr = self.state.get("__interrupt__")
        return intr[0].value if intr else {}

    async def finish_job(self, status="completed", ext="png"):
        """What the media worker does: store the file, report the result."""
        job = self.rig.sink.submitted[-1]
        assert self.waiting == {"kind": "job", "job_id": job.job_id}
        if status == "completed":
            rel = f"jobs/{job.job_id}/image.{ext}"
            await self.rig.raw.put(object_key("t1", "wasifyai-image", "u1", rel), png((1024, 768)))
            result = JobResult(
                job_id=job.job_id,
                status="completed",
                outputs={"image": JobOutput(key=rel, content_type="image/png", size=4)},
            )
        else:
            result = JobResult(
                job_id=job.job_id,
                status="failed",
                error=JobError(code="job_failed", message="The generation failed."),
            )
        self.state = await self.graph.ainvoke(Command(resume=result.model_dump()), CONFIG)
        return self


async def exists(rig, rel: str) -> bool:
    return await rig.raw.exists(object_key("t1", "wasifyai-image", "u1", rel))


# ---- text to image -----------------------------------------------------------------------


@pytest.mark.parametrize("size", list(SIZES))
async def test_text_to_image_from_description_to_saved_image(tmp_path, ctx, size):
    rig = make_rig(tmp_path)
    s = await Story(rig).start({"mode": "text", "prompt": "a red fox in the snow", "size": size})
    job = rig.sink.submitted[0]
    width, height = SIZES[size]
    assert job.capability == "image.generate"
    assert (job.prompt["width"], job.prompt["height"]) == (width, height)
    assert job.prompt["prompt"] == "a red fox in the snow" and "image_key" not in job.prompt
    assert (job.tenant_id, job.product_id, job.user_id) == ("t1", "wasifyai-image", "u1")

    await s.finish_job()
    final = s.state
    assert final["status"] == "done" and "__interrupt__" not in final
    iid = final["image_id"]
    # re-keyed to the documented layout; the temporary job path is gone; a thumbnail was made
    assert final["image_key_final"] == f"{iid}/image.png"
    assert await exists(rig, f"{iid}/image.png") and await exists(rig, f"{iid}/thumb.jpg")
    assert not await exists(rig, f"jobs/{job.job_id}/image.png")
    assert (final["width"], final["height"]) == (1024, 768)  # the real size of what was made
    assert final["image_url"].endswith(f"{iid}/image.png")
    assert final["thumb_url"].endswith(f"{iid}/thumb.jpg")
    (image,) = s.images.images
    assert (image.id, image.mode, image.prompt) == (iid, "text", "a red fox in the snow")
    assert image.user_id == "u1" and image.thread_id == "th-1" and image.run_id == "run-1"
    created = [e for e in rig.usage.events if e.kind == "image.created"]
    assert len(created) == 1 and created[0].meta == {"image_id": iid, "mode": "text"}


async def test_the_size_defaults_to_square(tmp_path, ctx):
    rig = make_rig(tmp_path)
    await Story(rig).start({"mode": "text", "prompt": "a fox"})
    job = rig.sink.submitted[0]
    assert (job.prompt["width"], job.prompt["height"]) == SIZES["square"]


async def test_text_mode_never_touches_uploads_or_the_picture_model(tmp_path, ctx):
    rig = make_rig(tmp_path)
    await Story(rig).start({"mode": "text", "prompt": "a fox", "image_key": "uploads/nope.png"})
    assert rig.picture_checks() == []  # no picture to look at
    assert rig.sink.submitted[0].capability == "image.generate"
    assert "image_key" not in rig.sink.submitted[0].prompt


# ---- image to image ----------------------------------------------------------------------


async def test_image_to_image_edits_the_users_picture_and_then_forgets_it(tmp_path, ctx):
    rig = make_rig(tmp_path)
    up = await put_upload(rig)
    s = await Story(rig).start({"mode": "image", "prompt": "make it dusk", "image_key": up.key})
    job = rig.sink.submitted[0]
    assert job.capability == "image.edit"
    assert job.prompt["prompt"] == "make it dusk" and job.prompt["image_key"] == up.key
    # both the words and the picture were checked, and the picture reached the model as an image
    assert len(rig.word_checks()) == 1 and len(rig.picture_checks()) == 1
    parts = rig.picture_checks()[0]
    assert any(isinstance(p, Image) and p.media_type == "image/jpeg" for p in parts)
    assert await exists(rig, up.key)  # still there while the job runs

    await s.finish_job()
    assert s.state["status"] == "done"
    assert not await exists(rig, up.key)  # the original is deleted once the image is saved
    assert await rig.uploads.find("t1", "wasifyai-image", "u1", up.key) is None
    assert s.images.images[0].mode == "image"
    assert [e.meta["mode"] for e in rig.usage.events if e.kind == "image.created"] == ["image"]


async def test_a_job_that_fails_deletes_the_picture_too(tmp_path, ctx):
    rig = make_rig(tmp_path)
    up = await put_upload(rig)
    s = await Story(rig).start({"mode": "image", "prompt": "make it dusk", "image_key": up.key})
    with pytest.raises(JobFailed):
        await s.finish_job(status="failed")
    assert not await exists(rig, up.key)
    assert await rig.uploads.find("t1", "wasifyai-image", "u1", up.key) is None
    assert s.images.images == []


@pytest.mark.parametrize(
    "key", ["", "uploads/missing.png", "../u2/uploads/x.png", "jobs/x/image.png"]
)
async def test_a_picture_that_is_not_the_callers_upload_is_refused(tmp_path, ctx, key):
    rig = make_rig(tmp_path)
    s = await Story(rig).start({"mode": "image", "prompt": "make it dusk", "image_key": key})
    assert s.state["status"] == "refused" and s.state["refusal"]["code"] == "invalid_request"
    assert "upload your picture again" in s.state["refusal"]["message"]
    assert rig.sink.submitted == [] and rig.asked() == []  # no model was asked


async def test_another_users_upload_cannot_be_used(tmp_path, ctx):
    rig = make_rig(tmp_path)
    theirs = await put_upload(rig, user_id="someone-else")
    s = await Story(rig).start({"mode": "image", "prompt": "make it dusk", "image_key": theirs.key})
    assert s.state["status"] == "refused" and rig.sink.submitted == []
    # and their file is untouched by our refusal
    assert await rig.raw.exists(object_key("t1", "wasifyai-image", "someone-else", theirs.key))


# ---- the guardrail -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "category",
    [
        "sexual_content",
        "minors",
        "graphic_violence",
        "hate",
        "real_person_misuse",
        "disallowed_content",
    ],
)
async def test_a_refused_description_stops_before_any_generation(tmp_path, ctx, category):
    rig = make_rig(tmp_path, moderate=[verdict(False, category, "SECRET-REASON")])
    s = await Story(rig).start({"mode": "text", "prompt": "something unsuitable"})
    assert s.state["status"] == "refused" and s.state["refusal"]["code"] == category
    assert s.state["refusal"]["message"] and "SECRET-REASON" not in s.state["refusal"]["message"]
    assert rig.sink.submitted == [] and s.images.images == []
    assert not [e for e in rig.usage.events if e.kind == "image.created"]


async def test_a_refused_edit_instruction_deletes_the_picture(tmp_path, ctx):
    rig = make_rig(tmp_path, moderate=[verdict(False, "sexual_content")])
    up = await put_upload(rig)
    s = await Story(rig).start({"mode": "image", "prompt": "make him naked", "image_key": up.key})
    assert s.state["status"] == "refused" and rig.sink.submitted == []
    assert rig.picture_checks() == []  # the words were enough
    assert not await exists(rig, up.key)  # a refused request leaves nothing behind


async def test_a_picture_the_model_refuses_stops_the_run_and_is_deleted(tmp_path, ctx):
    rig = make_rig(tmp_path, moderate_image=[verdict(False, "minors", "SECRET")])
    up = await put_upload(rig)
    s = await Story(rig).start({"mode": "image", "prompt": "make it dusk", "image_key": up.key})
    assert s.state["status"] == "refused" and s.state["refusal"]["code"] == "minors"
    assert "SECRET" not in s.state["refusal"]["message"] and rig.sink.submitted == []
    assert not await exists(rig, up.key)


async def test_a_contradictory_verdict_is_a_refusal(tmp_path, ctx):
    rig = make_rig(
        tmp_path, moderate=[verdict(True, "sexual_content")]
    )  # "allowed" but names a violation
    s = await Story(rig).start({"mode": "text", "prompt": "x"})
    assert s.state["status"] == "refused" and s.state["refusal"]["code"] == "sexual_content"


async def test_an_unusable_verdict_fails_closed(tmp_path, ctx):
    rig = make_rig(tmp_path, moderate=["not json", "still not json"])
    with pytest.raises(RunError) as caught:
        await Story(rig).start({"mode": "text", "prompt": "a fox"})
    assert caught.value.code == "moderation_unavailable" and caught.value.retryable
    assert rig.sink.submitted == []


async def test_one_bad_answer_is_retried(tmp_path, ctx):
    rig = make_rig(tmp_path, moderate=["oops", verdict()])
    s = await Story(rig).start({"mode": "text", "prompt": "a fox"})
    assert s.waiting and rig.sink.submitted  # allowed on the second try


@pytest.mark.parametrize(
    ("data", "fragment"),
    [
        ({"mode": "text", "prompt": ""}, "describe the image"),
        ({"mode": "text", "prompt": "  \n\t "}, "describe the image"),
        ({"mode": "image", "prompt": "", "image_key": "uploads/x.png"}, "say what to change"),
        ({"mode": "text", "prompt": "x" * 501}, "under 500"),
        ({"mode": "text", "prompt": "a fox", "size": "huge"}, "image sizes"),
        ({"mode": "video", "prompt": "a fox"}, "text to image or image to image"),
        ({"prompt": "a fox"}, "text to image or image to image"),
    ],
)
async def test_invalid_requests_are_refused_without_calling_a_model(tmp_path, ctx, data, fragment):
    rig = make_rig(tmp_path)
    s = await Story(rig).start(data)
    assert s.state["status"] == "refused" and s.state["refusal"]["code"] == "invalid_request"
    assert fragment in s.state["refusal"]["message"]
    assert rig.asked() == [] and rig.sink.submitted == []


async def test_control_characters_in_the_prompt_are_removed(tmp_path, ctx):
    rig = make_rig(tmp_path)
    await Story(rig).start({"mode": "text", "prompt": "a\x00 fox\x07  in   snow"})
    assert rig.sink.submitted[0].prompt["prompt"] == "a fox in snow"


# ---- the daily limit ---------------------------------------------------------------------


async def test_the_daily_limit_stops_a_request_before_any_model_is_used(tmp_path, ctx):
    rig = make_rig(tmp_path, quotas={"images_per_user_per_day": 3})
    up = await put_upload(rig)
    s = await Story(rig, FixedQuota(3)).start(
        {"mode": "image", "prompt": "make it dusk", "image_key": up.key}
    )
    assert s.state["status"] == "refused" and s.state["refusal"]["code"] == "quota_exceeded"
    assert "limit of 3 images" in s.state["refusal"]["message"]
    assert rig.asked() == [] and rig.sink.submitted == []
    assert not await exists(rig, up.key)  # and the picture is not kept


async def test_under_the_limit_is_fine(tmp_path, ctx):
    rig = make_rig(tmp_path, quotas={"images_per_user_per_day": 3})
    s = await Story(rig, FixedQuota(2)).start({"mode": "text", "prompt": "a fox"})
    assert s.waiting and len(rig.sink.submitted) == 1


# ---- recipes (stage B) -------------------------------------------------------------------


async def test_the_recipe_keeps_the_seed_the_job_used(tmp_path, ctx):
    rig = make_rig(tmp_path)
    s = await Story(rig).start({"mode": "text", "prompt": "a fox", "size": "wide"})
    await s.finish_job()
    (image,) = s.images.images
    job = rig.sink.submitted[0]
    assert image.recipe == {
        "v": 1, "mode": "text", "prompt": "a fox", "size": "wide",
        "width": 1024, "height": 768, "seed": job.prompt["seed"],
    }  # fmt: skip
    assert image.recipe is not None and 0 <= image.recipe["seed"] <= 2**31 - 1


async def test_a_given_seed_is_used_as_it_is(tmp_path, ctx):
    rig = make_rig(tmp_path)
    s = await Story(rig).start({"mode": "text", "prompt": "a fox", "seed": 424242})
    assert rig.sink.submitted[0].prompt["seed"] == 424242
    await s.finish_job()
    recipe = s.images.images[0].recipe
    assert recipe is not None and recipe["seed"] == 424242


async def test_each_run_without_a_seed_draws_its_own(tmp_path, ctx):
    seeds = set()
    for n in range(4):
        rig = make_rig(tmp_path / str(n))
        await Story(rig).start({"mode": "text", "prompt": "a fox"})
        seeds.add(rig.sink.submitted[0].prompt["seed"])
    assert len(seeds) > 1


@pytest.mark.parametrize("seed", [-1, 2**31, "7", 1.5, True])
async def test_a_seed_that_is_not_valid_is_refused_before_any_work(tmp_path, ctx, seed):
    rig = make_rig(tmp_path)
    s = await Story(rig).start({"mode": "text", "prompt": "a fox", "seed": seed})
    assert s.state["status"] == "refused" and "seed" in s.state["refusal"]["message"]
    assert rig.asked() == [] and rig.sink.submitted == []
