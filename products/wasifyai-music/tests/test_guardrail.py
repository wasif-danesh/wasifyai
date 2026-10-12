import pytest
from conftest import make_rig, verdict
from wasifyai_music import guardrail
from wasifyai_platform_sdk import RunError


async def judge(tmp_path, ctx, replies, text="a song about rain"):
    rig = make_rig(tmp_path, moderate=replies)
    return await guardrail.judge(rig.caps, "song request", text)


async def test_allowed_request_passes(tmp_path, ctx):
    v = await judge(tmp_path, ctx, [verdict()])
    assert v.allowed and v.category == "ok"


@pytest.mark.parametrize("category", ["artist_voice", "existing_lyrics", "disallowed_content"])
async def test_refusals_carry_their_category(tmp_path, ctx, category):
    v = await judge(tmp_path, ctx, [verdict(False, category, "because")])
    assert not v.allowed and v.category == category
    assert guardrail.refusal_message(category) and "because" not in guardrail.refusal_message(
        category
    )


async def test_refusal_text_is_fixed_and_never_the_models_wording():
    assert "imitate a specific artist" in guardrail.refusal_message("artist_voice")
    assert guardrail.refusal_message("something-new") == guardrail.REFUSALS["disallowed_content"]


async def test_an_unparseable_verdict_is_retried_once(tmp_path, ctx):
    v = await judge(tmp_path, ctx, ["I think it's fine!", verdict()])
    assert v.allowed


async def test_it_fails_closed_when_the_classifier_never_answers_properly(tmp_path, ctx):
    with pytest.raises(RunError) as e:
        await judge(tmp_path, ctx, ["maybe", '{"allowed": true}'])
    assert e.value.code == "moderation_unavailable" and e.value.retryable


async def test_a_contradictory_verdict_is_treated_as_a_refusal(tmp_path, ctx):
    v = await judge(
        tmp_path, ctx, [verdict(True, "artist_voice")]
    )  # "allowed" but names a violation
    assert not v.allowed and v.category == "artist_voice"
    v = await judge(tmp_path, ctx, [verdict(False, "ok")])  # refused but says ok
    assert not v.allowed and v.category == "disallowed_content"
