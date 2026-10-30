"""The image graph end to end with scripted fake models and an in-memory queue: no GPU, no network.
The "worker" is the test itself, resuming the graph with a job result."""

from typing import Any

import pytest
from image_rig import make_rig, png, put_upload
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from wasifyai_image.graphs.image import build_image_graph
from wasifyai_image.images import InMemoryImageStore
from wasifyai_image.schemas import SIZES
from wasifyai_platform_sdk import (
    JobError,
    JobFailed,
    JobOutput,
    JobResult,
    object_key,
)

CONFIG: Any = {"configurable": {"thread_id": "th-1"}}


class Story:
    """Drives a run: start it, play the media worker."""

    def __init__(self, rig):
        self.rig = rig
        self.images = InMemoryImageStore()
        self.graph = build_image_graph(rig.caps, InMemorySaver(), self.images, rig.uploads)
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
    assert rig.asked() == []  # nothing judges the words
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
    assert rig.asked() == []  # nothing judges the words or the picture
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
    ("data", "fragment"),
    [
        ({"mode": "text", "prompt": ""}, "describe the image"),
        ({"mode": "text", "prompt": "  \n\t "}, "describe the image"),
        ({"mode": "image", "prompt": "", "image_key": "uploads/x.png"}, "say what to change"),
        ({"mode": "text", "prompt": "x" * 501}, "under 500"),
        ({"mode": "text", "prompt": "a fox", "size": "huge"}, "image sizes"),
        ({"mode": "video", "prompt": "a fox"}, "what kind of picture to make"),
        ({"prompt": "a fox"}, "what kind of picture to make"),
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


# ---- recipes (stage B) -------------------------------------------------------------------


async def test_the_recipe_keeps_the_seed_the_job_used(tmp_path, ctx):
    rig = make_rig(tmp_path)
    s = await Story(rig).start({"mode": "text", "prompt": "a fox", "size": "wide"})
    await s.finish_job()
    (image,) = s.images.images
    job = rig.sink.submitted[0]
    assert image.recipe == {
        "v": 1, "mode": "text", "prompt": "a fox", "size": "wide",
        "width": 1024, "height": 768, "seed": job.prompt["seed"], "loras": [],
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


# ---- LoRAs (stage C) ---------------------------------------------------------------------------


async def test_loras_reach_the_job_and_stay_in_the_recipe(tmp_path, ctx):
    rig = make_rig(tmp_path)
    loras = [{"name": "ink.safetensors", "weight": 0.8}, {"name": "style/film.safetensors"}]
    s = await Story(rig).start({"mode": "text", "prompt": "a fox", "loras": loras})
    assert rig.sink.submitted[0].prompt["loras"] == [
        {"name": "ink.safetensors", "weight": 0.8},
        {"name": "style/film.safetensors", "weight": 1.0},  # a missing strength is 1
    ]
    await s.finish_job()
    (image,) = s.images.images
    assert (
        image.recipe is not None and image.recipe["loras"] == rig.sink.submitted[0].prompt["loras"]
    )


async def test_an_edit_may_use_loras_too(tmp_path, ctx):
    rig = make_rig(tmp_path)
    up = await put_upload(rig)
    s = await Story(rig).start(
        {"mode": "image", "prompt": "make it dusk", "image_key": up.key,
         "loras": [{"name": "ink.safetensors", "weight": 1.0}]}
    )  # fmt: skip
    assert rig.sink.submitted[0].capability == "image.edit"
    assert rig.sink.submitted[0].prompt["loras"][0]["name"] == "ink.safetensors"
    assert s.waiting["kind"] == "job"


@pytest.mark.parametrize(
    ("loras", "fragment"),
    [
        ([{"name": "../secret.safetensors", "weight": 1}], "cannot be used"),
        ([{"name": "/etc/passwd.safetensors", "weight": 1}], "cannot be used"),
        ([{"name": "model.ckpt", "weight": 1}], "cannot be used"),
        ([{"name": "a.safetensors", "weight": 5}], "between"),
        ([{"name": "a.safetensors", "weight": "heavy"}], "number"),
        ([{"name": "a.safetensors"}, {"name": "a.safetensors"}], "once"),
        ([{"name": f"{n}.safetensors"} for n in range(9)], "at most 8"),
        ("ink.safetensors", "from the list"),
    ],
)
async def test_bad_loras_are_refused_before_any_model_is_asked(tmp_path, ctx, loras, fragment):
    rig = make_rig(tmp_path)
    s = await Story(rig).start({"mode": "text", "prompt": "a fox", "loras": loras})
    assert s.state["status"] == "refused" and fragment in s.state["refusal"]["message"]
    assert rig.asked() == [] and rig.sink.submitted == []


# ---- styles by id (ADR-0091) ---------------------------------------------------------------------


def with_styles(rig, known: dict[str, str]):
    """The desktop's resolver: a style id to its file in the `loras` folder, or why not."""

    async def to_files(wanted):
        if any(w["id"] not in known for w in wanted):
            return [], "One of those styles is not on this computer any more."
        return [
            {"name": known[w["id"]], "weight": w["strength"], "sha256": "ab" * 32, "title": w["id"]}
            for w in wanted
        ], ""

    rig.caps.extras["styles"] = to_files


async def test_styles_by_id_reach_the_job_as_their_files_and_the_recipe_keeps_the_ids(
    tmp_path, ctx
):
    rig = make_rig(tmp_path)
    with_styles(rig, {"a1b2c3d4e5f6": "koni.safetensors", "0f0f0f0f0f0f": "ink.safetensors"})
    wanted = [{"id": "a1b2c3d4e5f6", "strength": 0.8}, {"id": "0f0f0f0f0f0f", "strength": 1}]
    s = await Story(rig).start({"mode": "text", "prompt": "a fox", "styles": wanted})
    assert rig.sink.submitted[0].prompt["loras"] == [
        {"name": "koni.safetensors", "weight": 0.8}, {"name": "ink.safetensors", "weight": 1.0},
    ]  # fmt: skip
    s = await s.finish_job()
    (image,) = s.images.images
    assert image.recipe is not None and image.recipe["styles"] == [
        {"id": "a1b2c3d4e5f6", "strength": 0.8, "sha256": "ab" * 32, "title": "a1b2c3d4e5f6"},
        {"id": "0f0f0f0f0f0f", "strength": 1.0, "sha256": "ab" * 32, "title": "0f0f0f0f0f0f"},
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("styles", "fragment"),
    [
        ([{"id": "../ink.safetensors"}], "from the list"),
        ([{"id": "a1b2c3d4e5f6", "strength": 3}], "between"),
        ([{"id": "a1b2c3d4e5f6"}, {"id": "a1b2c3d4e5f6"}], "once"),
        ([{"id": f"{n:012x}"} for n in range(9)], "at most 8"),
        ([{"id": "999999999999"}], "not on this computer"),
    ],
)
async def test_bad_styles_are_refused_before_any_model_is_asked(tmp_path, ctx, styles, fragment):
    rig = make_rig(tmp_path)
    with_styles(rig, {"a1b2c3d4e5f6": "koni.safetensors"})
    s = await Story(rig).start({"mode": "text", "prompt": "a fox", "styles": styles})
    assert s.state["status"] == "refused" and fragment in s.state["refusal"]["message"]
    assert rig.sink.submitted == []


async def test_styles_are_refused_where_nothing_keeps_them(tmp_path, ctx):
    rig = make_rig(tmp_path)  # the web: a person's looks go by name through their own storage
    s = await Story(rig).start(
        {"mode": "text", "prompt": "a fox", "styles": [{"id": "a1b2c3d4e5f6"}]}
    )
    assert s.state["status"] == "refused" and rig.sink.submitted == []


# ---- Advanced: steps and a size of one's own (ADR-0091 S4) ---------------------------------------


async def test_steps_and_a_size_of_ones_own_reach_the_job_and_the_recipe(tmp_path, ctx):
    rig = make_rig(tmp_path)
    s = await Story(rig).start(
        {"mode": "text", "prompt": "a fox", "steps": 8, "width": 1280, "height": 720}
    )
    job = rig.sink.submitted[0]
    assert (job.prompt["width"], job.prompt["height"], job.prompt["steps"]) == (1280, 720, 8)
    s = await s.finish_job()
    (image,) = s.images.images
    assert image.recipe is not None and image.recipe["steps"] == 8 and image.recipe["own_size"]


async def test_without_advanced_the_workflow_keeps_its_own_steps(tmp_path, ctx):
    rig = make_rig(tmp_path)
    await Story(rig).start({"mode": "text", "prompt": "a fox", "size": "wide"})
    job = rig.sink.submitted[0]
    assert "steps" not in job.inputs and (job.prompt["width"], job.prompt["height"]) == (1344, 768)


@pytest.mark.parametrize(
    ("extra", "fragment"),
    [({"steps": 0}, "Steps must"), ({"steps": 51}, "Steps must"), ({"steps": 4.5}, "Steps must"),
     ({"width": 1000, "height": 1024}, "steps of 16"), ({"width": 4096, "height": 1024}, "between"),
     ({"width": 1024}, "whole numbers")],
)  # fmt: skip
async def test_bad_advanced_settings_are_refused_in_words(tmp_path, ctx, extra, fragment):
    rig = make_rig(tmp_path)
    s = await Story(rig).start({"mode": "text", "prompt": "a fox", **extra})
    assert s.state["status"] == "refused" and fragment in s.state["refusal"]["message"]
    assert rig.sink.submitted == []


async def test_a_change_keeps_the_pictures_own_size(tmp_path, ctx):
    rig = make_rig(tmp_path)
    up = await put_upload(rig)
    s = await Story(rig).start(
        {"mode": "image", "prompt": "dusk", "image_key": up.key, "width": 512, "height": 512}
    )
    assert s.state["status"] == "refused" and "own size" in s.state["refusal"]["message"]


async def test_on_the_web_a_service_style_goes_to_the_worker_by_its_key(tmp_path, ctx):
    """ADR-0091 S5: the resolver names the storage key; the looks are asked only for the rest."""
    rig = make_rig(tmp_path)
    key = "t1/wasifyai-image/service/styles/ab12cd34ef56.safetensors"

    async def to_files(wanted):
        return [{"name": "service-ab12cd34ef56.safetensors", "weight": 1.0, "sha256": "ab" * 32,
                 "title": "Anime", "key": key}], ""  # fmt: skip

    asked: list[list[str]] = []

    async def looks(tenant, user, names):
        asked.append(names)
        return {n: f"t1/wasifyai-training/u1/train/looks/r1/{n}" for n in names}

    rig.caps.extras["styles"] = to_files
    rig.caps.extras["person_looks"] = looks
    await Story(rig).start({
        "mode": "text", "prompt": "a fox", "styles": [{"id": "ab12cd34ef56"}],
    })  # fmt: skip
    job = rig.sink.submitted[0]
    assert job.prompt["lora_files"] == {"service-ab12cd34ef56.safetensors": key}
    assert asked == []  # the service's style is not one of the person's looks
