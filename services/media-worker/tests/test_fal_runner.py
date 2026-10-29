"""Images and video on fal.ai with the person's key (ADR-0095, stage K3), against a fake fal.ai:
the queue is followed to the end, the key goes to the queue only, a refusal is in fal.ai's words."""

import asyncio
import base64
import json

import httpx
import pytest
from wasifyai_media_worker.backends import FalRunner
from wasifyai_media_worker.comfy import ComfyError
from wasifyai_platform_sdk import JobRequest

KEY = "fal-key-good"
PNG = b"\x89PNG\r\n\x1a\nPICTURE"
MP4 = b"\x00\x00\x00\x18ftypmp42CLIP"


def job(capability="image.generate", kind="image", **inputs) -> JobRequest:
    return JobRequest(
        tenant_id="t1", product_id="wasifyai-image", user_id="u1", capability=capability,
        workflow="w", prompt={}, inputs={"prompt": "a red fox in snow", **inputs},
        outputs={kind: {"node": "1", "type": kind}},
    )  # fmt: skip


class Fal:
    """A fake fal.ai: answers the queue, then serves the file from another host."""

    def __init__(self, submit=200, status_after=1, error=None, video=False, said=None):
        self.requests: list[httpx.Request] = []
        self.submit, self.status_after, self.error, self.video = submit, status_after, error, video
        self.said = said
        self.polls = 0
        self.waiting = asyncio.Event()  # set once the job has been asked about twice

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        url = str(req.url)
        if req.method == "POST":
            if self.submit != 200:
                return httpx.Response(self.submit, json={"detail": self.said} if self.said else {})
            return httpx.Response(200, json={
                "request_id": "r1", "status_url": "https://queue.fal.run/fal-ai/x/requests/r1/status",
                "response_url": "https://queue.fal.run/fal-ai/x/requests/r1",
                "cancel_url": "https://queue.fal.run/fal-ai/x/requests/r1/cancel",
            })  # fmt: skip
        if url.endswith("/status"):
            self.polls += 1
            if self.polls >= 2:
                self.waiting.set()
            done = self.polls > self.status_after
            body = {"status": "COMPLETED" if done else "IN_QUEUE"}
            if done and self.error:
                body["error"] = self.error
            return httpx.Response(200, json=body)
        if url.endswith("/cancel"):
            return httpx.Response(202, json={})
        if url.startswith("https://queue.fal.run"):
            if self.video:
                clip = {"url": "https://v3.fal.media/c.mp4", "content_type": "video/mp4"}
                return httpx.Response(200, json={"video": clip})
            picture = {"url": "https://v3.fal.media/a.png", "content_type": "image/png"}
            return httpx.Response(200, json={"images": [picture]})
        return httpx.Response(200, content=MP4 if self.video else PNG)

    def body(self, n=0) -> dict:
        posts = [r for r in self.requests if r.method == "POST"]
        return json.loads(posts[n].content)


def runner(fal: Fal, model="fal-ai/flux-2") -> FalRunner:
    http = httpx.AsyncClient(transport=httpx.MockTransport(fal))
    return FalRunner(KEY, model, http, timeout_s=30, poll_s=0)


async def progress(_p: float) -> None:
    return None


async def test_a_picture_is_made_with_the_size_and_seed_asked_and_the_key_stays_with_fal():
    fal = Fal()
    files = await runner(fal).run(job(width=1152, height=864, seed=7), progress)
    assert files == {"image": (PNG, "image/png", "png")}
    post = fal.requests[0]
    assert str(post.url) == "https://queue.fal.run/fal-ai/flux-2"
    size = {"width": 1152, "height": 864}
    assert fal.body() == {"prompt": "a red fox in snow", "image_size": size, "seed": 7}
    for r in fal.requests:
        on_queue = str(r.url).startswith("https://queue.fal.run")
        assert (
            r.headers.get("authorization") == f"Key {KEY}"
        ) is on_queue  # never to the file host


async def test_a_change_to_a_picture_sends_it_inline_to_the_edit_endpoint():
    fal = Fal()
    await runner(fal).run(
        job("image.edit", image_key="uploads/a.png"), progress, files={"image": PNG}
    )
    assert str(fal.requests[0].url) == "https://queue.fal.run/fal-ai/flux-2/edit"
    (uri,) = fal.body()["image_urls"]
    assert uri == "data:image/png;base64," + base64.b64encode(PNG).decode()


async def test_two_pictures_combine_through_the_edit_endpoint():
    fal = Fal()
    await runner(fal).run(
        job("image.reference", width=1024, height=1024), progress,
        files={"image": PNG, "image2": b"\xff\xd8\xffJPEG"},
    )  # fmt: skip
    urls = fal.body()["image_urls"]
    assert len(urls) == 2 and urls[1].startswith("data:image/jpeg;base64,")


@pytest.mark.parametrize(("frames", "seconds"), [(121, 6), (193, 8), (None, 6)])
async def test_a_clip_asks_for_the_nearest_length_fal_makes_and_no_sound(frames, seconds):
    fal = Fal(video=True)
    asked = {"length": frames} if frames else {}
    files = await runner(fal, "fal-ai/ltx-2/text-to-video/fast").run(
        job("video.generate", kind="video", **asked), progress
    )
    assert files == {"video": (MP4, "video/mp4", "mp4")}
    assert fal.body() == {
        "prompt": "a red fox in snow",
        "duration": seconds,
        "generate_audio": False,
    }


async def test_a_picture_is_animated_through_the_image_to_video_endpoint():
    fal = Fal(video=True)
    await runner(fal, "fal-ai/ltx-2/text-to-video/fast").run(
        job("video.animate", kind="video", length=121, image_key="uploads/a.png"), progress,
        files={"image": PNG},
    )  # fmt: skip
    assert str(fal.requests[0].url) == "https://queue.fal.run/fal-ai/ltx-2/image-to-video/fast"
    assert fal.body()["image_url"].startswith("data:image/png;base64,")


@pytest.mark.parametrize(
    ("capability", "inputs", "words"),
    [
        ("image.inpaint", {}, "Painting over part of a picture is not done with your key"),
        ("video.extend", {}, "Making a clip longer is not done with your key"),
        ("image.generate", {"loras": [{"name": "x", "weight": 1}]}, "Styles and looks"),
        ("image.edit", {}, "fal-ai/other cannot"),
    ],
)
async def test_what_cannot_run_on_the_key_is_said_and_nothing_is_sent(capability, inputs, words):
    fal = Fal()
    with pytest.raises(ComfyError) as e:
        await runner(fal, "fal-ai/other").run(job(capability, **inputs), progress, {"image": PNG})
    assert e.value.code == "not_with_key" and words in e.value.message
    assert fal.requests == []


@pytest.mark.parametrize(
    ("status", "said", "words"),
    [(401, None, "fal.ai did not accept the key."), (403, None, "fal.ai did not accept the key."),
     (429, None, "too many requests"),
     (422, [{"msg": "prompt too long"}], "fal.ai could not make it: prompt too long"),
     (500, None, "fal.ai answered 500.")],
)  # fmt: skip
async def test_a_refusal_is_said_in_fals_words_and_never_with_the_key(status, said, words):
    with pytest.raises(ComfyError) as e:
        await runner(Fal(submit=status, said=said)).run(job(), progress)
    assert e.value.code == "provider_refused" and words in e.value.message
    assert KEY not in e.value.message


async def test_a_failed_request_on_fal_is_said():
    with pytest.raises(ComfyError) as e:
        await runner(Fal(error="out of credit")).run(job(), progress)
    assert e.value.message == "fal.ai could not make it: out of credit"


async def test_stopping_a_job_asks_fal_to_stop_it_too():
    fal = Fal(status_after=10_000)
    task = asyncio.create_task(runner(fal).run(job(), progress))
    await fal.waiting.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert any(r.method == "PUT" and str(r.url).endswith("/cancel") for r in fal.requests)


async def test_progress_moves_while_it_waits_and_ends_at_one():
    seen: list[float] = []

    async def note(p: float) -> None:
        seen.append(p)

    await runner(Fal(status_after=2)).run(job(), note)
    assert seen[0] < 0.1 and seen[-1] == 1.0 and seen == sorted(seen)
