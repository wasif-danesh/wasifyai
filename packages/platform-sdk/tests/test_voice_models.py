"""Model descriptors and request validation (ADR-0066)."""

import pytest
from wasifyai_platform_sdk import (
    VoiceRequestError,
    check_clone,
    check_convert,
    check_design,
    check_lipsync,
    check_music_edit,
    check_options,
    check_separate,
    check_speak,
    check_speech_edit,
    check_transcribe,
    edit_markup,
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


# ---- audio tools (V4) -----------------------------------------------------------------------


def tool(kind: str, **over):
    """A descriptor of one of the audio tools."""
    rules = {
        "separate": {"separate": {"stems": ["vocals", "other"], "input_rate": 44100,
                                  "max_source_s": 600}},
        "convert": {"convert": {"target": "reference", "input_rate": 22050,
                                "reference_seconds": [3, 30], "max_source_s": 300,
                                "request": {"source": "audio", "reference": "voice_ref"}}},
        "edit": {"speech_edit": {"style": "markup", "input_rate": 24000, "max_changes": 3,
                                 "max_source_s": 30}},
    }[kind]  # fmt: skip
    base = {"tasks": [kind], "recommended": [], "server_task": "sep", "voices": [],
            "default_voice": None, "options": [], **rules}  # fmt: skip
    return parse_voice_model(f"{kind}-model", "A model", "MIT", raw(**{**base, **over}))


@pytest.mark.parametrize(
    "kind, over, message",
    [
        ("separate", {"separate": {}}, "declares `separate` rules"),
        ("separate", {"separate": {"stems": [], "input_rate": 44100, "max_source_s": 60}},
         "distinct names"),
        ("separate", {"separate": {"stems": ["a", "a"], "input_rate": 44100, "max_source_s": 60}},
         "distinct names"),
        ("separate", {"separate": {"stems": ["a"], "input_rate": 5, "max_source_s": 60}},
         "sample rate"),
        ("separate", {"separate": {"stems": ["a"], "input_rate": 44100, "max_source_s": 0}},
         "max_source_s"),
        ("convert", {"convert": {}}, "declares `convert` rules"),
        ("convert", {"convert": {"target": "builtin"}}, "convert.target"),
        ("edit", {"speech_edit": {"style": "magic"}}, "speech_edit.style"),
        ("edit", {"speech_edit": {"style": "markup", "input_rate": 24000, "max_changes": 99,
                                  "max_source_s": 30}}, "max_changes"),
        ("edit", {"tasks": ["edit"], "speech_edit": {}}, "declares `speech_edit` rules"),
    ],
)  # fmt: skip
def test_a_tool_declares_what_it_needs(kind, over, message):
    with pytest.raises(ValueError, match=message):
        tool(kind, **over)


def test_only_a_tool_model_declares_tool_rules():
    with pytest.raises(ValueError, match="declares `separate` rules"):
        model(separate={"stems": ["a"], "input_rate": 44100, "max_source_s": 60})
    assert tool("separate").public()["separate"]["stems"] == ["vocals", "other"]


def test_a_recording_for_a_tool_must_be_a_length_the_model_takes():
    sep = tool("separate")
    assert check_separate(sep, 30, None).source_seconds == 30
    for seconds, code in ((0.2, "too_short"), (601, "too_long"), (float("nan"), "too_short")):
        with pytest.raises(VoiceRequestError) as e:
            check_separate(sep, seconds, None)
        assert e.value.code == code
    conv = tool("convert")
    assert check_convert(conv, 20, 10, None, seed=3).seed == 3
    for ref in (1.0, 40.0):
        with pytest.raises(VoiceRequestError) as e:
            check_convert(conv, 20, ref, None)
        assert e.value.code == "reference_length" and "3 to 30" in e.value.message
    with pytest.raises(VoiceRequestError) as e:
        check_convert(conv, 400, 10, None)
    assert e.value.code == "too_long"
    with pytest.raises(VoiceRequestError) as e:
        check_convert(conv, 20, 10, {"pitch": 3})  # an option the model does not declare
    assert e.value.code == "unknown_option"


@pytest.mark.parametrize(
    "old, new, want",
    [
        ("Hello brave world.", "Hello small world.", 'Hello <sub targ="small">brave</sub> world.'),
        ("I like red apples", "I like apples", "I like <del>red </del>apples"),
        ("walk the river and talk", "walk the river slowly and talk",
         "walk the river <ins>slowly </ins>and talk"),
        ("Hello world", "Hello world again", "Hello world<ins> again</ins>"),
        ("one two three four five", "one 2 three 4 five",
         'one <sub targ="2 three 4">two three four</sub> five'),
        ("你好世界", "你好朋友", '你好<sub targ="朋友">世界</sub>'),
        ("It is Cold today", "it is warm today", 'It is <sub targ="warm">Cold</sub> today'),
    ],
)  # fmt: skip
def test_changed_words_are_tagged_the_way_the_editor_reads(old, new, want):
    # the case of a word is not a change; the text is the original with the changes marked
    assert edit_markup(old, new, 5) == want


def test_too_many_or_no_changes_are_refused_in_words():
    with pytest.raises(VoiceRequestError) as e:
        edit_markup("1 a b c 2 d e f 3 g h i 4", "z a b c y d e f x g h i w", 3)
    assert e.value.code == "too_many_changes" and "fewer" in e.value.message
    with pytest.raises(VoiceRequestError) as e:
        edit_markup("Same words.", "same words", 3)
    assert e.value.code == "no_change"


def test_an_edit_request_is_checked_before_it_is_tagged():
    ed = tool("edit")
    req = check_speech_edit(ed, 10, "Hello  brave world.", "Hello small world.", None, seed=2)
    assert req.instruction == 'Hello <sub targ="small">brave</sub> world.' and req.seed == 2
    for old, new, code in (("", "Hello", "empty_text"), ("Hello <b>", "Hello", "bad_text"),
                           ('Say "hi"', "Say hello", "bad_text")):  # fmt: skip
        with pytest.raises(VoiceRequestError) as e:
            check_speech_edit(ed, 10, old, new, None)
        assert e.value.code == code
    with pytest.raises(VoiceRequestError) as e:
        check_speech_edit(ed, 31, "Hello there", "Hello you", None)
    assert e.value.code == "too_long"
    with pytest.raises(VoiceRequestError) as e:
        check_speech_edit(model(), 10, "Hello there", "Hello you", None)
    assert e.value.code == "wrong_task"


# ---- lip sync (V5) ----------------------------------------------------------------------------


def lipsync_rules(**over):
    return {"max_voice_s": 300, "max_side": 768, "fps": 25, "mark": "required", **over}


def talker(**over):
    base = {
        "engine": "sidecar", "tasks": ["lipsync"], "recommended": ["lipsync"],
        "server_task": "lipsync", "voices": [], "default_voice": None, "options": [],
        "lipsync": lipsync_rules(),
    }  # fmt: skip
    return parse_voice_model("musetalk", "MuseTalk", "MIT", raw(**{**base, **over}))


@pytest.mark.parametrize(
    "over, message",
    [
        ({"lipsync": {}}, "declares `lipsync` rules"),
        ({"engine": "audiocpp"}, "runs as a sidecar"),
        ({"lipsync": lipsync_rules(max_voice_s=1)}, "max_voice_s"),
        ({"lipsync": lipsync_rules(max_side=64)}, "max_side"),
        ({"lipsync": lipsync_rules(fps=1)}, "fps"),
        ({"lipsync": lipsync_rules(mark="optional")}, "cannot be left off"),
        ({"lipsync": {"max_voice_s": 60, "max_side": 768, "fps": 25}}, "cannot be left off"),
    ],
)
def test_a_lip_sync_model_declares_its_limits_and_that_the_mark_is_not_optional(over, message):
    with pytest.raises(ValueError, match=message):
        talker(**over)


def test_only_a_lip_sync_model_declares_lip_sync_rules():
    with pytest.raises(ValueError, match="declares `lipsync` rules"):
        model(lipsync=lipsync_rules())
    assert talker().public()["lipsync"]["fps"] == 25


def test_a_lip_sync_request_needs_the_persons_word_and_a_voice_the_model_takes():
    m = talker()
    ok = check_lipsync(m, 12.5, "drawn", "own")
    assert ok.consent == {"picture": "drawn", "voice": "own"} and ok.mark == "AI-generated"
    assert ok.fps == 25 and ok.voice_seconds == 12.5
    for picture, voice in ((None, "own"), ("drawn", None), ("real", "own"), ("own", "mine")):
        with pytest.raises(VoiceRequestError) as e:
            check_lipsync(m, 10, picture, voice)
        assert e.value.code == "consent_required"
    for seconds, code in ((0.3, "too_short"), (301, "too_long"), (float("nan"), "too_short")):
        with pytest.raises(VoiceRequestError) as e:
            check_lipsync(m, seconds, "own", "own")
        assert e.value.code == code
    with pytest.raises(VoiceRequestError) as e:
        check_lipsync(model(), 10, "own", "own")
    assert e.value.code == "wrong_task"
