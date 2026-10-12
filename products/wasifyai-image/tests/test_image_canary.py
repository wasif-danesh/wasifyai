"""The guardrail canaries (ADR-0025): what a model must get right before an admin can use it."""

import json
from typing import cast

import yaml
from wasifyai_image.canary import CASES, FIXTURES, moderation_check, picture_check
from wasifyai_platform_sdk import Capabilities

CASE_FILE = yaml.safe_load(CASES.read_text())
TEXT_REFUSE = {c["text"] for c in CASE_FILE["text"]["refuse"]}
TEXT_ALLOW = [c["text"] for c in CASE_FILE["text"]["allow"]]
PIC_REFUSE = {c["text"] for c in CASE_FILE["picture"]["refuse"]}
PIC_ALLOW = [c["text"] for c in CASE_FILE["picture"]["allow"]]


class FakeText:
    def __init__(self, decide):
        self._decide = decide

    async def complete(self, name, system, user, schema=None):
        text = user if isinstance(user, str) else str(user[0])
        outcome = self._decide(name, text)
        if isinstance(outcome, Exception):
            raise outcome
        category = "ok" if outcome else "disallowed_content"
        return json.dumps({"allowed": outcome, "category": category, "reason": ""})


def caps(decide):
    class C:
        text = FakeText(decide)

    return cast(Capabilities, C())


def has(text, wanted):
    return any(w in text for w in wanted)


async def test_the_text_canary_passes_a_model_that_judges_correctly():
    r = await moderation_check(caps(lambda name, t: not has(t, TEXT_REFUSE)))
    assert r.passed and r.failures == [] and r.ran == len(TEXT_REFUSE) + len(TEXT_ALLOW)


async def test_the_picture_canary_passes_a_model_that_judges_correctly():
    r = await picture_check(caps(lambda name, t: not has(t, PIC_REFUSE)))
    assert r.passed and r.ran == len(PIC_REFUSE) + len(PIC_ALLOW)


async def test_each_canary_uses_its_own_capability():
    seen: set[str] = set()

    def decide(name, text):
        seen.add(name)
        return not has(text, TEXT_REFUSE | PIC_REFUSE)

    await moderation_check(caps(decide))
    assert seen == {"moderate"}
    seen.clear()
    await picture_check(caps(decide))
    assert seen == {"moderate_image"}


async def test_a_model_that_allows_everything_fails_every_must_refuse_case():
    t = await moderation_check(caps(lambda n, text: True))
    assert not t.passed and len([f for f in t.failures if "must be refused" in f]) == len(
        TEXT_REFUSE
    )
    p = await picture_check(caps(lambda n, text: True))
    assert not p.passed and len([f for f in p.failures if "must be refused" in f]) == len(
        PIC_REFUSE
    )


async def test_a_model_that_refuses_everything_is_too_strict():
    for check in (moderation_check, picture_check):
        r = await check(caps(lambda n, text: False))
        assert not r.passed and "harmless requests" in r.failures[0]


async def test_one_false_refusal_is_tolerated_but_two_are_not():
    one = await moderation_check(caps(lambda n, t: not (has(t, TEXT_REFUSE) or TEXT_ALLOW[0] in t)))
    two = await moderation_check(
        caps(lambda n, t: not (has(t, TEXT_REFUSE) or TEXT_ALLOW[0] in t or TEXT_ALLOW[1] in t))
    )
    assert one.passed and not two.passed


async def test_a_model_that_errors_cannot_be_trusted():
    for check in (moderation_check, picture_check):
        r = await check(caps(lambda n, t: RuntimeError("bad model name")))
        assert not r.passed and all("no valid verdict" in f for f in r.failures)


def test_every_picture_the_canary_names_exists():
    for group in CASE_FILE["picture"].values():
        for case in group:
            assert (FIXTURES / f"{case['picture']}.jpg").is_file(), case
