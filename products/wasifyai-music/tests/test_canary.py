"""The moderator canary (ADR-0025): what a model must get right before an admin can use it."""

import json
from typing import cast

import yaml
from wasifyai_music.canary import CASES, moderation_check
from wasifyai_platform_sdk import Capabilities

GROUPS = yaml.safe_load(CASES.read_text())
REFUSE = {c["text"] for c in GROUPS["refuse"]}
ALLOW = [c["text"] for c in GROUPS["allow"]]


class FakeText:
    def __init__(self, decide):
        self._decide = decide

    async def complete(self, name, system, user, schema=None):
        outcome = self._decide(user)
        if isinstance(outcome, Exception):
            raise outcome
        allowed = outcome
        return json.dumps(
            {
                "allowed": allowed,
                "category": "ok" if allowed else "disallowed_content",
                "reason": "",
            }
        )


def caps(decide):
    class C:
        text = FakeText(decide)

    return cast(Capabilities, C())


def has(user, texts):
    return any(t in user for t in texts)


async def test_a_model_that_judges_correctly_passes():
    result = await moderation_check(caps(lambda user: not has(user, REFUSE)))
    assert result.passed and result.failures == [] and result.ran == len(REFUSE) + len(ALLOW)


async def test_a_model_that_allows_everything_fails_on_every_must_refuse_case():
    result = await moderation_check(caps(lambda user: True))
    assert not result.passed
    assert len([f for f in result.failures if "must be refused" in f]) == len(REFUSE)


async def test_a_model_that_refuses_everything_is_too_strict():
    result = await moderation_check(caps(lambda user: False))
    assert not result.passed and "harmless requests" in result.failures[0]


async def test_one_false_refusal_is_tolerated_but_two_are_not():
    one = await moderation_check(caps(lambda user: not (has(user, REFUSE) or ALLOW[0] in user)))
    two = await moderation_check(
        caps(lambda user: not (has(user, REFUSE) or ALLOW[0] in user or ALLOW[1] in user))
    )
    assert one.passed and not two.passed


async def test_a_model_that_errors_cannot_be_trusted():
    result = await moderation_check(caps(lambda user: RuntimeError("bad model name")))
    assert not result.passed
    assert all("no valid verdict" in f for f in result.failures)
    assert len(result.failures) == len(REFUSE) + len(ALLOW)
