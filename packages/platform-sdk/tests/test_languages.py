# SPDX-License-Identifier: Apache-2.0
"""The shared language list (voice languages plan, stage L1)."""

import re
from pathlib import Path

from wasifyai_platform_sdk import languages
from wasifyai_platform_sdk.voice_models import VoiceInfo, VoiceModel

ROOT = Path(__file__).resolve().parents[3]
TS = ROOT / "packages/ui/src/voice/languages.ts"


def test_the_window_names_the_same_languages_as_the_engine() -> None:
    rows = re.findall(
        r'\{ code: "([a-z]+)", english: "([^"]+)", own: "([^"]+)"(, rtl: true)? \}', TS.read_text()
    )
    window = {c: (e, o, bool(r)) for c, e, o, r in rows}
    engine = {c: (x.english, x.own, x.rtl) for c, x in languages.LANGUAGES.items()}
    assert window == engine


def test_bengali_and_the_chosen_indian_languages_are_named() -> None:
    for code in ("bn", "hi", "mr", "te", "ta", "gu"):
        assert code in languages.LANGUAGES
    assert languages.label("bn") == "Bengali (বাংলা)"
    assert languages.label("en-GB") == "English"
    assert languages.language_name("xx") == "xx"


def test_codes_are_compared_by_their_base() -> None:
    assert languages.base("pt_BR") == "pt" and languages.base(" EN-us ") == "en"
    assert languages.supports(("en-us", "en-gb"), "EN")
    assert not languages.supports(("en-us",), "bn")
    assert languages.supports(("multi",), "bn")
    assert languages.spoken(("multi",)) == set(languages.LANGUAGES)
    assert languages.spoken(("en-us", "en-gb", "hi")) == {"en", "hi"}


def _model(langs: tuple[str, ...], voices: tuple[VoiceInfo, ...]) -> VoiceModel:
    return VoiceModel(
        id="m", title="M", engine="test", family="f", package="", server_task="tts",
        tasks=("speak",), recommended=("speak",), languages=langs, sample_rate=24000,
        voices=voices,
    )  # fmt: skip


def test_a_voice_speaks_its_own_language_or_every_one_of_its_model() -> None:
    model = _model(
        ("en-us", "hi", "bn"),
        (VoiceInfo("af_heart", "Heart", "en-us"), VoiceInfo("hf_alpha", "Alpha", "hi"),
         VoiceInfo("any", "Any")),
    )  # fmt: skip
    assert languages.voice_languages(model) == {
        "af_heart": {"en"}, "hf_alpha": {"hi"}, "any": {"en", "hi", "bn"},
    }  # fmt: skip
    assert languages.voices_for(model, "hi") == ["hf_alpha", "any"]
    assert languages.voices_for(model, "bn") == ["any"]
    assert languages.voices_for(model, "fr") == []


def test_a_text_s_own_script_names_its_language_only_when_it_is_clear() -> None:
    assert languages.script_language("আজ আবহাওয়া খুব সুন্দর।") == "bn"
    assert languages.script_language("आज मौसम बहुत अच्छा है।") == "hi"
    assert languages.script_language("இன்று வானிலை நன்றாக உள்ளது") == "ta"
    assert languages.script_language("Hello, how are you?") is None
    assert languages.script_language("Bengali word: আজ, then many English words here") is None
    assert languages.script_language("12345 !!") is None
