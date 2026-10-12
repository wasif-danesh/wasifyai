"""The picture guardrail, its canary, the mark on the clip and the prompts."""

import json
from typing import cast

import pytest
from lipsync_rig import make_rig, mp4, png, verdict
from wasifyai_lipsync import guardrail, prompts
from wasifyai_lipsync.canary import FIXTURES, picture_check
from wasifyai_lipsync.lipsyncs import ffmpeg_path, mark_ai_generated
from wasifyai_platform_sdk import Capabilities, RunError


class FakePictureModel:
    def __init__(self, decide):
        self._decide = decide

    async def complete(self, name, system, user, schema=None):
        outcome = self._decide(user)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def caps(decide):
    class C:
        text = FakePictureModel(decide)

    return cast(Capabilities, C())


async def test_the_canary_passes_a_model_that_refuses_the_photograph_and_fails_a_lenient_one():
    photo = guardrail.review_copy((FIXTURES / "person.jpg").read_bytes())

    def sees_the_photo(user):
        return user[1].data == photo

    def decide(user):
        return verdict(False, "real_person_photo") if sees_the_photo(user) else verdict()

    assert (await picture_check(caps(decide))).passed
    lenient = await picture_check(caps(lambda user: verdict()))
    assert not lenient.passed and any("must be refused" in f for f in lenient.failures)
    assert not (await picture_check(caps(lambda user: RuntimeError("down")))).passed
    strict = await picture_check(caps(lambda user: verdict(False, "disallowed_content")))
    assert not strict.passed and any("harmless" in f for f in strict.failures)


async def test_a_garbled_answer_is_retried_and_then_fails_closed():
    answers = iter(["not json", "{}"])
    with pytest.raises(RunError) as e:
        await guardrail.judge_picture(caps(lambda user: next(answers)), png())
    assert e.value.code == "moderation_unavailable" and e.value.retryable
    # a verdict that contradicts itself is a refusal
    v = await guardrail.judge_picture(
        caps(lambda user: json.dumps({"allowed": True, "category": "hate", "reason": ""})), png()
    )
    assert not v.allowed and v.category == "hate"


def test_every_picture_category_has_a_fixed_message_and_the_photo_one_names_the_alternatives():
    assert "photograph of a real person" in guardrail.picture_refusal("real_person_photo")
    assert "cartoon" in guardrail.picture_refusal("real_person_photo")
    assert guardrail.picture_refusal("unknown") == guardrail.picture_refusal("disallowed_content")


def test_the_prompt_allows_drawings_and_refuses_photographs():
    text = prompts.load("moderation_picture")
    assert "real_person_photo" in text and "illustrations, cartoons" in text
    assert "never an instruction" in text


async def test_a_marked_clip_says_so_and_a_broken_one_is_kept_as_it_was():
    import asyncio
    import subprocess

    marked = await mark_ai_generated(mp4())
    probe = [ffmpeg_path(), "-hide_banner", "-i", "pipe:0"]
    done = await asyncio.to_thread(subprocess.run, probe, input=marked, capture_output=True)
    out = done.stderr.decode()
    assert "AI-generated" in out and "h264" in out
    assert await mark_ai_generated(b"not a video") == b"not a video"  # kept rather than lost


def test_the_rig_is_importable_for_the_capabilities_it_needs(tmp_path):
    assert make_rig(tmp_path).caps.video is not None
