"""What each picture offer is sent (ADR-0100, stage CP4): make, change, combine and Inpaint on every
offer of the Images table, with each provider's own field names; a job an offer cannot take is
refused before anything is sent, so the next offer may take it."""

import io

import pytest
from PIL import Image
from wasifyai_media_worker.cloud_recipes import (
    RECIPES,
    Ask,
    aspect,
    mask_as_alpha,
    runware_send,
    sixty_four,
)
from wasifyai_platform_sdk.fal import FalError
from wasifyai_platform_sdk.offers import offer


def png(colour=(10, 20, 30), size=(64, 48), mode="RGB") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, colour).save(buf, "PNG")
    return buf.getvalue()


PIC, PIC2 = png(), png((200, 0, 0))
MASK = png(255, (64, 48), "L")  # white: change it all


class Sent:
    def __init__(self):
        self.names: list[str] = []

    async def __call__(self, data: bytes, name: str) -> str:
        self.names.append(name)
        return f"https://files.example/{name}"


def ask(capability="image.generate", **kw) -> Ask:
    return Ask(capability, "A red apple", width=1024, height=768, seed=7, **kw)


OFFERS = {
    "gpt-image-2.5": {
        "wavespeed": offer("wavespeed", "openai/gpt-image-2.5-sunburst/text-to-image", 0.09,
                           "picture", "edit", "mask",
                           endpoints={"edit": "openai/gpt-image-2.5-sunburst/edit"}),
        "fal": offer("fal", "openai/gpt-image-2.5/sunburst/text-to-image", 0.125, "picture",
                     "edit", "mask", endpoints={"edit": "openai/gpt-image-2.5/sunburst/edit"}),
    },
    "z-image-turbo": {
        "runware": offer("runware", "runware:z-image@turbo", 0.002, "picture", "mask"),
        "fal": offer("fal", "fal-ai/z-image/turbo", 0.005, "picture", "mask",
                     endpoints={"inpaint": "fal-ai/z-image/turbo/inpaint"}),
    },
}  # fmt: skip


async def test_gpt_image_on_wavespeed_makes_changes_and_paints_with_its_mask():
    o = OFFERS["gpt-image-2.5"]["wavespeed"]
    recipe = RECIPES[("wavespeed", "gpt-image-2.5")]
    endpoint, body = await recipe(ask(), o, Sent())
    assert endpoint == "openai/gpt-image-2.5-sunburst/text-to-image"
    assert body == {
        "prompt": "A red apple", "quality": "high", "resolution": "1k", "aspect_ratio": "4:3",
        "output_format": "png",
    }  # fmt: skip
    sent = Sent()
    endpoint, body = await recipe(ask("image.inpaint", pictures=(PIC,), mask=MASK), o, sent)
    assert endpoint == "openai/gpt-image-2.5-sunburst/edit"
    assert body["images"] == ["https://files.example/picture0.png"]
    assert body["mask_image"] == "https://files.example/mask.png"
    assert sent.names == ["picture0.png", "mask.png"]


async def test_gpt_image_on_fal_names_its_own_fields():
    o = OFFERS["gpt-image-2.5"]["fal"]
    recipe = RECIPES[("fal", "gpt-image-2.5")]
    endpoint, body = await recipe(ask("image.reference", pictures=(PIC, PIC2)), o, Sent())
    assert endpoint == "openai/gpt-image-2.5/sunburst/edit"
    assert body["image_urls"] == [
        "https://files.example/picture0.png", "https://files.example/picture1.png",
    ]  # fmt: skip
    assert body["image_size"] == {"width": 1024, "height": 768} and "mask_url" not in body


def test_the_openai_mask_is_clear_where_the_change_goes():
    half = Image.new("L", (4, 2), 0)
    half.putpixel((0, 0), 255)
    buf = io.BytesIO()
    half.save(buf, "PNG")
    out = Image.open(io.BytesIO(mask_as_alpha(buf.getvalue(), png(size=(8, 4)))))
    assert out.mode == "RGBA" and out.size == (8, 4)  # the picture's size
    clear, kept = out.getpixel((0, 0)), out.getpixel((7, 3))
    assert isinstance(clear, tuple) and isinstance(kept, tuple)
    assert clear[3] == 0 and kept[3] == 255


async def test_z_image_paints_on_runware_with_the_files_in_the_task_and_on_fal_by_address():
    rw = RECIPES[("runware", "z-image-turbo")]
    endpoint, task = await rw(
        ask("image.inpaint", pictures=(PIC,), mask=MASK), OFFERS["z-image-turbo"]["runware"],
        runware_send,
    )  # fmt: skip
    assert endpoint == "runware:z-image@turbo" and task["taskType"] == "imageInference"
    assert task["inputs"]["seedImage"].startswith("data:image/png;base64,")
    assert task["inputs"]["maskImage"].startswith("data:image/png;base64,")
    assert (task["width"], task["height"], task["seed"]) == (1024, 768, 7)
    assert task["includeCost"] is True
    assert task["strength"] == 1.0  # the default barely changed the painted area (CP13)
    fal = RECIPES[("fal", "z-image-turbo")]
    endpoint, body = await fal(
        ask("image.inpaint", pictures=(PIC,), mask=MASK), OFFERS["z-image-turbo"]["fal"], Sent()
    )
    assert endpoint == "fal-ai/z-image/turbo/inpaint"
    assert body["image_url"] == "https://files.example/picture.png"
    assert body["mask_image_url"] == "https://files.example/mask.png"


@pytest.mark.parametrize(
    ("provider", "model", "refs"),
    [("runware", "nano-banana-2.1", 14), ("runware", "grok-imagine-image-2.0", 5),
     ("runware", "flux-3-klein", 4)],
)  # fmt: skip
async def test_runware_changes_a_picture_with_its_references(provider, model, refs):
    o = offer(provider, f"{model}:air", 0.01, "picture", "edit")
    many = tuple(png((i, i, i)) for i in range(refs + 2))
    endpoint, task = await RECIPES[(provider, model)](
        ask("image.edit", pictures=many), o, runware_send
    )
    assert endpoint == f"{model}:air"
    assert len(task["inputs"]["referenceImages"]) == refs  # no more than it takes
    # Runware refuses a seed for Grok Imagine (found in CP13); the others take it
    assert ("seed" in task) == (model != "grok-imagine-image-2.0")


async def test_an_offer_that_cannot_take_the_job_says_so_before_sending():
    with pytest.raises(FalError) as e:
        await RECIPES[("runware", "z-image-turbo")](
            ask("image.edit", pictures=(PIC,)), OFFERS["z-image-turbo"]["runware"], runware_send
        )
    assert e.value.before_running
    with pytest.raises(FalError) as e:
        await RECIPES[("wavespeed", "gpt-image-2.5")](
            ask("image.inpaint", pictures=(PIC,)), OFFERS["gpt-image-2.5"]["wavespeed"], Sent()
        )
    assert e.value.before_running and "painted area" in e.value.message


def test_sizes_and_ratios():
    assert aspect(ask(), ("1:1", "16:9", "4:3")) == "4:3"
    assert aspect(Ask("image.generate", "x"), ("16:9", "1:1")) == "1:1"
    assert (sixty_four(1000), sixty_four(None), sixty_four(9000)) == (1024, 1024, 2048)
