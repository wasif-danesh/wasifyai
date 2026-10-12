"""The voice catalog (ADR-0042): what is offered, and plain errors for what is not."""

import pytest
import yaml
from wasifyai_tts.voices import GENDERS, Catalog, NoVoice, load_catalog


def test_the_shipped_catalog_is_consistent_and_every_choice_has_one_default():
    catalog = load_catalog()
    assert len(catalog.voices) >= 40 and len(catalog.languages) == 8
    for lang in catalog.languages:
        assert lang.name and lang.english and lang.whisper
        for g in GENDERS:
            options = catalog.voices_for(lang.id, g)
            assert sum(v.default for v in options) == (1 if options else 0)
    assert len({v.id for v in catalog.voices}) == len(catalog.voices)
    assert all(v.engine in catalog.engines for v in catalog.voices)


def test_languages_are_named_in_their_own_script_and_in_english():
    names = {lang.id: (lang.name, lang.english) for lang in load_catalog().languages}
    assert names["hi"] == ("हिन्दी", "Hindi") and names["fr"] == ("Français", "French")
    assert names["bn"] == ("বাংলা", "Bengali")
    assert names["pt-BR"][1] == "Portuguese (Brazil)"


def test_a_language_and_gender_resolve_to_that_languages_default_voice():
    catalog = load_catalog()
    v = catalog.resolve("es", "male")
    assert (v.language, v.gender, v.engine) == ("es", "male", "kokoro")
    assert v.engine_voice.startswith("e") and v.id == f"kokoro:{v.engine_voice}"
    other = [x for x in catalog.voices_for("en-US", "female") if not x.default][0]
    assert catalog.resolve("en-US", "female", other.id) == other


def test_a_missing_voice_is_a_plain_reason_not_a_silent_change():
    catalog = load_catalog()
    with pytest.raises(NoVoice, match="no male voice for French yet"):
        catalog.resolve("fr", "male")
    with pytest.raises(NoVoice, match="Please choose one of the languages"):
        catalog.resolve("xx", "female")
    with pytest.raises(NoVoice, match="male or a female"):
        catalog.resolve("es", "robot")
    with pytest.raises(NoVoice, match="not available for this language"):
        catalog.resolve("es", "male", catalog.resolve("hi", "male").id)  # another language's voice


def test_the_form_gets_languages_with_their_voices_and_empty_lists_for_gaps():
    public = load_catalog().public()
    french = next(x for x in public["languages"] if x["id"] == "fr")
    assert len(french["genders"]["female"]) == 1 and french["genders"]["male"] == []
    us = next(x for x in public["languages"] if x["id"] == "en-US")
    assert (
        sum(v["default"] for v in us["genders"]["female"]) == 1 and len(us["genders"]["male"]) >= 5
    )
    assert all({"id", "label", "default", "quality"} == set(v) for v in us["genders"]["female"])


def raw(**changes):
    base = {
        "engines": {"e": {"model": "m", "max_chars": 100}},
        "languages": [{"id": "xx", "name": "X", "english": "X", "whisper": "xx"}],
        "voices": [
            {"id": "e:a", "language": "xx", "gender": "female", "label": "A", "engine": "e",
             "engine_voice": "a", "default": True},
        ],
    }  # fmt: skip
    return {**base, **changes}


def voice(**over):
    base = {"id": "e:a", "language": "xx", "gender": "female", "label": "A", "engine": "e",
            "engine_voice": "a", "default": True}  # fmt: skip
    return {**base, **over}


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"voices": [voice(language="yy")]}, "unknown language"),
        ({"voices": [voice(gender="other")]}, "gender"),
        ({"voices": [voice(engine="z")]}, "unknown engine"),
        ({"voices": [voice(default=False)]}, "exactly one default"),
    ],
)
def test_a_broken_catalog_is_refused_at_load(changes, message):
    with pytest.raises(ValueError, match=message):
        Catalog(raw(**changes))
    assert Catalog(raw()).voices  # the unbroken one loads
    yaml.safe_dump(raw())  # (keeps the helper honest)


def test_voice_quality_follows_the_model_cards_grade_and_is_honest_about_weak_languages():
    catalog = load_catalog()
    quality = {
        lang: catalog.resolve(lang, "female").quality for lang in ("en-US", "fr", "hi", "es")
    }
    assert quality == {
        "en-US": "good",
        "fr": "good",
        "hi": "fair",
        "es": "limited",
    }
    assert catalog.resolve("en-US", "female").engine_voice == "af_bella"  # the best graded voice


def test_bengali_voices_were_reviewed_by_a_native_listener_and_are_not_limited():
    catalog = load_catalog()
    for gender in GENDERS:
        assert catalog.resolve("bn", gender).quality == "good"
