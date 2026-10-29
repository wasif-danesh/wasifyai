"""The two modes that take more than one picture: `reference` (two pictures and a size) and
`inpaint` (a picture and a painted area). Fake models and an in-memory queue, as in
test_image_graph.py."""

import pytest
from image_rig import make_rig, mask_png, png, put_upload
from test_image_graph import Story, exists
from wasifyai_image.schemas import SIZES

SECOND = png((800, 600), (200, 80, 40))


async def left(rig, *uploads) -> list[bool]:
    return [
        await rig.uploads.find("t1", "wasifyai-image", "u1", u.key) is not None for u in uploads
    ]


# ---- reference ----------------------------------------------------------------------------


@pytest.mark.parametrize("size", ["square", "wide"])
async def test_reference_makes_a_new_picture_from_two_and_forgets_both(tmp_path, ctx, size):
    rig = make_rig(tmp_path)
    a, b = await put_upload(rig), await put_upload(rig, data=SECOND)
    s = await Story(rig).start(
        {"mode": "reference", "prompt": "the cat from picture 1 on the chair from picture 2",
         "image_key": a.key, "image2_key": b.key, "size": size}
    )  # fmt: skip
    (job,) = rig.sink.submitted
    assert job.capability == "image.reference"
    assert job.prompt["image_key"] == a.key and job.prompt["image2_key"] == b.key
    assert (job.prompt["width"], job.prompt["height"]) == SIZES[size]
    assert rig.asked() == []  # nothing judges the words or the pictures
    assert await left(rig, a, b) == [True, True]  # kept while the job runs

    await s.finish_job()
    assert s.state["status"] == "done"
    assert await left(rig, a, b) == [False, False]
    assert not await exists(rig, a.key) and not await exists(rig, b.key)
    (image,) = s.images.images
    assert image.mode == "reference" and image.recipe is not None
    assert image.recipe["size"] == size and image.recipe["mode"] == "reference"
    assert [e.meta["mode"] for e in rig.usage.events if e.kind == "image.created"] == ["reference"]


async def test_reference_with_a_missing_second_picture_is_refused_and_keeps_nothing(tmp_path, ctx):
    rig = make_rig(tmp_path)
    a = await put_upload(rig)
    s = await Story(rig).start(
        {"mode": "reference", "prompt": "x", "image_key": a.key, "image2_key": "uploads/nope.png"}
    )
    assert s.state["status"] == "refused" and "pictures again" in s.state["refusal"]["message"]
    assert rig.sink.submitted == [] and rig.asked() == []
    assert await left(rig, a) == [False]  # the one that was there is deleted too


async def test_reference_refuses_an_unknown_size_and_deletes_both(tmp_path, ctx):
    rig = make_rig(tmp_path)
    a, b = await put_upload(rig), await put_upload(rig, data=SECOND)
    s = await Story(rig).start(
        {
            "mode": "reference",
            "prompt": "x",
            "image_key": a.key,
            "image2_key": b.key,
            "size": "huge",
        }
    )
    assert s.state["status"] == "refused" and rig.sink.submitted == []
    assert await left(rig, a, b) == [False, False]


async def test_a_failed_reference_job_keeps_neither_picture(tmp_path, ctx):
    rig = make_rig(tmp_path)
    a, b = await put_upload(rig), await put_upload(rig, data=SECOND)
    s = await Story(rig).start(
        {"mode": "reference", "prompt": "x", "image_key": a.key, "image2_key": b.key}
    )
    with pytest.raises(Exception):  # noqa: B017, PT011 (the graph raises the worker's failure)
        await s.finish_job(status="failed")
    assert await left(rig, a, b) == [False, False]


# ---- inpaint ------------------------------------------------------------------------------


async def test_inpaint_changes_a_painted_area_and_forgets_both_uploads(tmp_path, ctx):
    rig = make_rig(tmp_path)
    a, m = await put_upload(rig), await put_upload(rig, data=mask_png())
    s = await Story(rig).start(
        {"mode": "inpaint", "prompt": "a red cushion", "image_key": a.key, "mask_key": m.key}
    )
    (job,) = rig.sink.submitted
    assert job.capability == "image.inpaint"
    assert job.prompt["image_key"] == a.key and job.prompt["mask_key"] == m.key
    # the model is told in words what to put in the white area; the person's own words are kept
    assert job.prompt["prompt"] == (
        "Fill the white area with: a red cushion. Keep everything else exactly the same."
    )
    assert rig.asked() == []  # nothing judges the words or the picture

    await s.finish_job()
    assert s.state["status"] == "done"
    assert await left(rig, a, m) == [False, False]
    (image,) = s.images.images
    assert image.mode == "inpaint" and image.prompt == "a red cushion"
    assert image.recipe is not None
    assert image.recipe["size"] is None  # the shape is the picture's


@pytest.mark.parametrize(
    ("mask", "says"),
    [
        (mask_png(box=None), "Paint the part"),
        (mask_png(box=(0, 0, 640, 480)), "unpainted"),
        (mask_png(size=(200, 400)), "does not fit"),
        (b"not a picture", "could not be read"),
    ],
    ids=["nothing painted", "everything painted", "another shape", "unreadable"],
)
async def test_inpaint_refuses_a_mask_that_cannot_be_used_and_deletes_both(
    tmp_path, ctx, mask, says
):
    rig = make_rig(tmp_path)
    a, m = await put_upload(rig), await put_upload(rig, data=mask)
    s = await Story(rig).start(
        {"mode": "inpaint", "prompt": "x", "image_key": a.key, "mask_key": m.key}
    )
    assert s.state["status"] == "refused" and says in s.state["refusal"]["message"]
    assert s.state["refusal"]["code"] == "invalid_mask"
    assert rig.sink.submitted == [] and rig.asked() == []
    assert await left(rig, a, m) == [False, False]


async def test_inpaint_without_a_mask_is_refused(tmp_path, ctx):
    rig = make_rig(tmp_path)
    a = await put_upload(rig)
    s = await Story(rig).start({"mode": "inpaint", "prompt": "x", "image_key": a.key})
    assert s.state["status"] == "refused" and rig.sink.submitted == []
    assert await left(rig, a) == [False]


async def test_a_mask_in_image_mode_is_not_used_and_text_mode_ignores_all_keys(tmp_path, ctx):
    rig = make_rig(tmp_path)
    a, m = await put_upload(rig), await put_upload(rig, data=mask_png())
    await Story(rig).start(
        {"mode": "image", "prompt": "make it dusk", "image_key": a.key, "mask_key": m.key}
    )
    (job,) = rig.sink.submitted
    assert job.capability == "image.edit" and "mask_key" not in job.prompt
