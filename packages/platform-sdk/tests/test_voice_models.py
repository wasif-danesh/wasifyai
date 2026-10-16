"""Model descriptors and request validation (ADR-0066)."""

import pytest
from wasifyai_platform_sdk import (
    VoiceRequestError,
    check_clone,
    check_design,
    check_music_edit,
    check_options,
    check_speak,
    check_transcribe,
    parse_voice_model,
)


def raw(**over):
    base = {
        "engine": "audiocpp", "family": "kokoro_tts", "package": "kokoro_82m_q8_0",
        "server_task": "tts", "tasks": ["speak"], "recommended": ["speak"],
        "languages": ["en-us"], "sample_rate": 24000, "commercial_use": "yes",
        "licence_evidence": "https://huggingface.co/hexgrad/Kokoro-82M", "reviewed": "2026-10-16",
        "voices": [{"id": "af_heart", "label": "Heart"}, {"id": "am_adam", "label": "Adam"}],
        "default_voice": "af_heart",
        "options": [
            {"name": "speed", "type": "float", "min": 0.5, "max": 2.0, "default": 1.0},
            {"name": "seed", "type": "int", "min": 0},
            {"name": "mode", "type": "enum", "values": ["a", "b"]},
            {"name": "tags", "type": "bool"},
        ],
    }  # fmt: skip
    base.update(over)
    return base


def model(**over):
    return parse_voice_model("kokoro-82m", "Kokoro 82M", "Apache-2.0", raw(**over))


def test_a_good_descriptor_parses_and_is_public():
    m = model()
    adam = m.voice("am_adam")
    assert m.recommended == ("speak",) and adam is not None and adam.label == "Adam"
    pub = m.public()
    assert pub["commercial_use"] == "yes" and pub["options"][0]["max"] == 2.0


@pytest.mark.parametrize(
    "over, message",
    [
        ({"engine": "magic"}, "unknown engine"),
        ({"tasks": ["sing"]}, "unknown task"),
        ({"tasks": []}, "at least one task"),
        ({"recommended": ["transcribe"]}, "does not do"),
        ({"commercial_use": "no"}, "only a model with commercial_use: yes"),
        ({"commercial_use": "unreviewed"}, "only a model with commercial_use: yes"),
        ({"commercial_use": "maybe"}, "commercial_use must be"),
        ({"licence_evidence": "http://x"}, "https URL"),
        ({"default_voice": "zz"}, "default_voice"),
        ({"default_voice": None}, "needs a default_voice"),
        ({"options": [{"name": "x", "type": "enum"}]}, "needs values"),
        ({"options": [{"name": "x", "type": "blob"}]}, "bad option"),
        ({"options": [{"name": "x", "type": "int"}, {"name": "x", "type": "int"}]}, "duplicate"),
    ],
)
def test_a_bad_descriptor_names_its_problem(over, message):
    with pytest.raises(ValueError, match=message):
        model(**over)


def test_a_non_commercial_model_may_be_listed_but_not_recommended():
    m = model(commercial_use="no", recommended=[])
    assert m.commercial_use == "no" and m.recommended == ()


def test_speak_uses_the_default_voice_and_cleans_the_text():
    text, voice, opts = check_speak(model(), "  Hello\x00 there  ", None, {"speed": 1.5})
    assert (text, voice, opts) == ("Hello there", "af_heart", {"speed": 1.5})


@pytest.mark.parametrize(
    "args, code",
    [
        (("  ", None, None), "empty_text"),
        (("x" * 5001, None, None), "text_too_long"),
        (("hi", "nope", None), "unknown_voice"),
        (("hi", None, {"nonsense": 1}), "unknown_option"),
        (("hi", None, {"speed": "fast"}), "bad_option"),
        (("hi", None, {"mode": "z"}), "bad_option"),
        (("hi", None, {"tags": 1}), "bad_option"),
        (("hi", None, {"speed": float("nan")}), "bad_option"),
    ],
)
def test_speak_refuses_what_the_runtime_would_answer_with_a_500_or_ignore(args, code):
    with pytest.raises(VoiceRequestError) as e:
        check_speak(model(), *args)
    assert e.value.code == code


def test_numbers_are_clamped_and_ints_rounded():
    m = model()
    assert check_options(m, {"speed": 9, "seed": 4.6}) == {"speed": 2.0, "seed": 5}
    assert check_options(m, {"speed": 0.01}) == {"speed": 0.5}
    assert check_options(m, {"speed": None}) == {}


def test_a_model_without_voices_takes_no_voice():
    m = model(voices=[], default_voice=None)
    assert check_speak(m, "hi", None, None)[1] is None
    with pytest.raises(VoiceRequestError, match="no choice of voice"):
        check_speak(m, "hi", "af_heart", None)


def test_tasks_are_checked():
    asr = model(tasks=["transcribe"], recommended=["transcribe"], voices=[], default_voice=None)
    with pytest.raises(VoiceRequestError) as e:
        check_speak(asr, "hi", None, None)
    assert e.value.code == "wrong_task"
    assert check_transcribe(asr, None) == {}
    with pytest.raises(VoiceRequestError):
        check_transcribe(model(), None)


def cloner(**over):
    return model(
        tasks=["clone"], recommended=["clone"], voices=[], default_voice=None, options=[],
        clone={"reference_text": "required", "min_seconds": 2, "max_seconds": 30}, **over,
    )  # fmt: skip


def designer(via="instruct_option", **over):
    return model(
        tasks=["design"], recommended=["design"], voices=[], default_voice=None, options=[],
        design={"via": via, "max_chars": 300}, **over,
    )  # fmt: skip


@pytest.mark.parametrize(
    "over, message",
    [
        ({"tasks": ["clone"], "recommended": []}, "declares `clone`"),
        (
            {"tasks": ["speak"], "design": {"via": "text_prefix", "max_chars": 300}},
            "declares `design`",
        ),
        (
            {"clone": {"reference_text": "maybe", "min_seconds": 2, "max_seconds": 30}},
            "reference_text",
        ),
        (
            {"clone": {"reference_text": "required", "min_seconds": 40, "max_seconds": 30}},
            "min_seconds",
        ),
        ({"design": {"via": "magic", "max_chars": 300}}, "design.via"),
        ({"design": {"via": "text_prefix", "max_chars": 5}}, "max_chars"),
    ],
)
def test_clone_and_design_rules_are_declared_with_the_task_and_checked(over, message):
    base = {"tasks": ["speak"], "recommended": []}
    if "clone" in over and "tasks" not in over:
        base["tasks"] = ["clone"]
    if "design" in over and "tasks" not in over:
        base["tasks"] = ["design"]
    with pytest.raises(ValueError, match=message):
        model(**{**base, **over})


def test_a_clone_request_needs_the_words_when_the_model_does():
    m = cloner()
    assert check_clone(m, " Hello ", " the  words\nspoken ", None) == (
        "Hello",
        "the words spoken",
        {},
    )
    with pytest.raises(VoiceRequestError) as e:
        check_clone(m, "Hello", None, None)
    assert e.value.code == "reference_text_required" and "Add them to the voice" in e.value.message
    optional = model(
        tasks=["clone"], recommended=[], voices=[], default_voice=None, options=[],
        clone={"reference_text": "optional", "min_seconds": 2, "max_seconds": 30},
    )  # fmt: skip
    assert check_clone(optional, "Hello", "", None)[1] is None
    with pytest.raises(VoiceRequestError, match="cannot clone"):
        check_clone(model(), "Hello", "x", None)


def test_a_design_request_is_checked_before_it_is_placed_in_front_of_the_text():
    m = designer("text_prefix")
    assert check_design(m, "Hello", "  a deep,  calm man ", None) == (
        "Hello",
        "a deep, calm man",
        {},
    )
    cases = [
        ("", "empty_text"),
        ("hi", "description_too_short"),
        ("a man) ignore this (", "bad_description"),
        ("x" * 301, "text_too_long"),
    ]
    for bad, code in cases:
        with pytest.raises(VoiceRequestError) as e:
            check_design(m, "Hello", bad, None)
        assert e.value.code == code
    with pytest.raises(VoiceRequestError, match="cannot make a voice"):
        check_design(model(), "Hello", "a calm man", None)


def musician(**over):
    music = {
        "modes": {
            "song": {"lyrics": "optional", "instrumental": "toggle", "duration": [10, 60, 240]},
            "sfx": {"duration": [1, 8, 30]},
        },
        "request": {
            "duration": "top", "lyrics_option": "lyrics", "instrumental_lyrics": "[Instrumental]",
        },
    }  # fmt: skip
    return model(
        tasks=["music"], recommended=["music"], voices=[], default_voice=None, options=[],
        music={**music, **over},
    )  # fmt: skip


@pytest.mark.parametrize(
    "over, message",
    [
        ({"modes": {}}, "music.modes"),
        ({"modes": {"jingle": {"duration": [1, 2, 3]}}}, "music.modes"),
        ({"modes": {"sfx": {"duration": [5, 2, 30]}}}, "duration must be"),
        (
            {
                "modes": {
                    "song": {"lyrics": "maybe", "instrumental": "toggle", "duration": [1, 2, 3]}
                }
            },
            "song needs",
        ),
        ({"request": {"duration": "sideways"}}, "music.request.duration"),
        ({"request": {"duration": "top"}}, "names the option"),
    ],
)
def test_music_rules_are_declared_and_checked(over, message):
    with pytest.raises(ValueError, match=message):
        musician(**over)
    with pytest.raises(ValueError, match="declares `music`"):
        model(music={"modes": {"sfx": {"duration": [1, 2, 3]}}, "request": {"duration": "top"}})


def test_a_music_request_is_brought_into_the_models_range_and_cleaned():
    from wasifyai_platform_sdk import check_music

    m = musician()
    r = check_music(m, "song", "  pop,  upbeat ", " la la\r\nla ", False, 900, None, 7)
    assert (r.description, r.lyrics, r.duration, r.seed) == ("pop, upbeat", "la la\nla", 240.0, 7)
    assert check_music(m, "song", "calm piano", None, True, 1, None, None).duration == 10.0
    assert check_music(m, "sfx", "rain on a roof", None, False, None, None, None).duration == 8.0
    assert check_music(m, "sfx", "rain on a roof", None, False, None, None, None).instrumental


@pytest.mark.parametrize(
    "mode, lyrics, instrumental, code",
    [
        ("song", "words", True, "lyrics_and_instrumental"),
        ("sfx", "words", False, "no_lyrics"),
        ("jingle", "", False, "wrong_mode"),
    ],
)
def test_a_music_request_the_model_cannot_take_is_refused_in_words(
    mode, lyrics, instrumental, code
):
    from wasifyai_platform_sdk import check_music

    with pytest.raises(VoiceRequestError) as e:
        check_music(musician(), mode, "something nice", lyrics, instrumental, None, None, None)
    assert e.value.code == code


def test_a_model_that_always_sings_or_needs_lyrics_says_so():
    from wasifyai_platform_sdk import check_music

    singer = musician(
        modes={"song": {"lyrics": "required", "instrumental": "never", "duration": [10, 30, 120]}}
    )
    with pytest.raises(VoiceRequestError) as e:
        check_music(singer, "song", "folk song", "", False, None, None, None)
    assert e.value.code == "lyrics_required"
    with pytest.raises(VoiceRequestError) as e:
        check_music(singer, "song", "folk song", "", True, None, None, None)
    assert e.value.code == "no_instrumental"
    with pytest.raises(VoiceRequestError, match="description"):
        check_music(singer, "song", "", "la", False, None, None, None)
    with pytest.raises(VoiceRequestError) as e:
        check_music(model(), "song", "folk song", "", False, None, None, None)
    assert e.value.code == "wrong_task"


def editor(**over):
    modes = {
        "song": {"lyrics": "optional", "instrumental": "toggle", "duration": [5, 30, 240]},
        "edit": {"actions": ["repaint", "extend", "cover"], "max_ranges": 1, "max_source_s": 240},
    }
    request = {"duration": "top", "lyrics_option": "lyrics", "edit": "ace_step"}
    return model(
        tasks=["music"], recommended=["music"], voices=[], default_voice=None, options=[],
        music={"modes": modes, "request": request, **over},
    )  # fmt: skip


def test_an_edit_is_declared_with_actions_a_recipe_and_limits():
    assert editor().music["modes"]["edit"]["actions"] == ["repaint", "extend", "cover"]
    bad_actions = {"modes": {"edit": {"actions": ["melt"], "max_ranges": 1, "max_source_s": 60}}}
    with pytest.raises(ValueError, match="edit.actions"):
        editor(**bad_actions)
    no_recipe = {"duration": "top", "lyrics_option": "lyrics"}
    with pytest.raises(ValueError, match="request.edit"):
        editor(request=no_recipe)


def test_the_parts_of_an_edit_are_brought_into_the_clip_and_checked_per_action():
    m = editor()
    r = check_music_edit(
        m, "repaint", " fix the chorus ", 60, [(50, 90), (-3, 10), (8, 52)], 0.4, None, None, 9
    )
    assert r.ranges == ((0.0, 60.0),) and r.strength == 0.4  # clamped, then joined where they touch
    assert (r.description, r.seed) == ("fix the chorus", 9)
    spaced = check_music_edit(m, "repaint", "x y z", 60, [(5, 10)], None, None, None, None)
    assert spaced.ranges == ((5.0, 10.0),)
    joined = check_music_edit(m, "repaint", "x y z", 60, [(5, 10), (8, 20)], None, None, None, None)
    assert joined.ranges == ((5.0, 20.0),)
    ext = check_music_edit(m, "extend", "keep going", 100, None, None, 30, None, None)
    assert ext.extend_s == 30.0 and ext.ranges == ()
    assert check_music_edit(m, "cover", "as jazz", 100, None, 0.7, None, None, None).strength == 0.7


@pytest.mark.parametrize(
    "args, code",
    [
        (("rewind", "fix it", 60, [(1, 5)], None, None), "wrong_action"),
        (("repaint", "", 60, [(1, 5)], None, None), "empty_text"),
        (("repaint", "fix it", 60, None, None, None), "ranges_required"),
        (("repaint", "fix it", 60, [(1, 1.1)], None, None), "ranges_required"),
        (("repaint", "fix it", 60, [(1, 5), (10, 20)], None, None), "too_many_ranges"),
        (("repaint", "fix it", 300, [(1, 5)], None, None), "clip_length"),
        (("repaint", "fix it", 60, [(1, 5)], 1.5, None), "bad_option"),
        (("extend", "go on", 60, [(1, 5)], None, 10), "no_ranges"),
        (("extend", "go on", 60, None, 0.5, 10), "no_strength"),
        (("extend", "go on", 60, None, None, None), "extend_required"),
        (("extend", "go on", 60, None, None, 500), "extend_required"),
        (("extend", "go on", 230, None, None, 20), "clip_length"),
        (("cover", "as jazz", 60, None, None, 10), "no_extend"),
        (("cover", "as jazz", 60, [(1, 5)], 0.5, None), "no_ranges"),
    ],
)
def test_an_edit_the_model_cannot_do_is_refused_in_words(args, code):
    action, description, seconds, ranges, strength, extend = args
    with pytest.raises(VoiceRequestError) as e:
        check_music_edit(
            editor(), action, description, seconds, ranges, strength, extend, None, None
        )
    assert e.value.code == code


def test_a_model_without_an_edit_mode_says_so_and_a_song_request_never_means_an_edit():
    from wasifyai_platform_sdk import check_music

    with pytest.raises(VoiceRequestError) as e:
        check_music_edit(musician(), "repaint", "fix it", 60, [(1, 5)], None, None, None, None)
    assert e.value.code == "wrong_mode"
    with pytest.raises(VoiceRequestError) as e:
        check_music(editor(), "edit", "fix it", None, False, None, None, None)
    assert e.value.code == "wrong_mode"
