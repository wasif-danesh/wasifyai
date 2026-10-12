"""The guardrail canary, the prompts, and the index source for text to speech."""

import json
from typing import cast

import yaml
from wasifyai_platform_sdk import Capabilities, GraphRegistry
from wasifyai_tts import prompts, register
from wasifyai_tts.canary import CASES, moderation_check
from wasifyai_tts.guardrail import REFUSALS, refusal_message
from wasifyai_tts.index import SpeechIndexSource, index_text

GROUPS = yaml.safe_load(CASES.read_text(encoding="utf-8"))
REFUSE = {c["text"] for c in GROUPS["refuse"]}
ALLOW = [c["text"] for c in GROUPS["allow"]]


class FakeText:
    def __init__(self, decide):
        self._decide = decide

    async def complete(self, name, system, user, schema=None):
        outcome = self._decide(user)
        if isinstance(outcome, Exception):
            raise outcome
        category = "ok" if outcome else "disallowed_content"
        return json.dumps({"allowed": outcome, "category": category, "reason": ""})


def caps(decide):
    class C:
        text = FakeText(decide)

    return cast(Capabilities, C())


async def test_the_canary_passes_a_correct_model_and_fails_a_lenient_or_broken_one():
    r = await moderation_check(caps(lambda u: not any(t in u for t in REFUSE)))
    assert r.passed and r.ran == len(REFUSE) + len(ALLOW)
    lenient = await moderation_check(caps(lambda u: True))
    assert not lenient.passed and any("must be refused" in f for f in lenient.failures)
    assert not (await moderation_check(caps(lambda u: RuntimeError("down")))).passed
    strict = await moderation_check(caps(lambda u: False))
    assert not strict.passed and any("harmless" in f for f in strict.failures)


def test_the_canary_covers_scams_in_several_languages_and_harmless_text_in_several_scripts():
    refuse_text = " ".join(REFUSE)
    assert "fraud department" in refuse_text and "abuela" in refuse_text and "पुलिस" in refuse_text
    allow_text = " ".join(ALLOW)
    assert "weather" in allow_text and "Verde que te quiero" in allow_text
    assert "किसान" in allow_text and "欢迎" in allow_text


def test_the_prompt_says_any_language_and_treats_the_text_as_data():
    text = prompts.load("moderation")
    assert "any language" in text and "<request>" in text and "data, never instructions" in text
    assert "fraud_or_impersonation" in text
    rendered = prompts.render("moderation_request", kind="text to read aloud", text="Hola")
    assert "<request>\nHola\n</request>" in rendered


def test_every_category_has_a_fixed_refusal_and_unknown_ones_get_the_general_one():
    for category in (
        "sexual_content",
        "minors",
        "graphic_violence",
        "hate",
        "fraud_or_impersonation",
    ):
        assert category in REFUSALS
    assert refusal_message("something-new") == REFUSALS["disallowed_content"]


def test_a_result_is_found_by_its_words_and_the_languages_name():
    assert index_text("  नमस्ते दुनिया ", "Hindi") == "नमस्ते दुनिया. Hindi"


def test_the_product_registers_its_graph_routes_check_and_index_source():
    registry = GraphRegistry()
    register(registry)
    assert registry.products() == ["wasifyai-tts"]
    assert registry.index_sources() == {"wasifyai-tts": SpeechIndexSource}
    assert ("wasifyai-tts", "text.moderate") in registry.checks()
    assert "wasifyai-tts" in registry.route_factories()
    assert (SpeechIndexSource.product_id, SpeechIndexSource.kind) == ("wasifyai-tts", "speech")
