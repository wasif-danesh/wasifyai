"""Moderation and daily limits in the voice product (ADR-0047): they apply only while the safeguards
are on, they fail closed, and the person is shown fixed sentences, never the classifier's words."""

import json
from typing import cast

import pytest
import yaml
from test_voice_dub import needs_ffmpeg
from test_voice_graph import CTX, Rig, a_clone, a_picture, ctx, library_track, verdict  # noqa: F401
from voice_rig import FakeEngine
from wasifyai_platform_sdk import Capabilities, RunError
from wasifyai_voice import safeguards
from wasifyai_voice.canary import CASES, picture_check, words_check

NO = verdict(False, "fraud_or_impersonation")
SPEAK = {"text": "Please read me your bank code.", "voice": "am_adam"}


# ---- the words of a speech -------------------------------------------------------------------


async def test_with_the_safeguards_off_nothing_is_moderated_and_no_limit_applies(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path, moderate=[NO], quotas={"speeches_per_user_per_day": 1}, used=99)
    final, _ = await rig.run(**SPEAK)
    assert final["status"] == "done" and rig.moderator_prompts == []


async def test_with_them_on_the_moderator_sees_the_words_before_any_model_work(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path, safeguards=True)
    final, _ = await rig.run(text="Welcome to the shop.", voice="am_adam")
    assert final["status"] == "done"
    assert "Welcome to the shop." in str(rig.moderator_prompts[0])


async def test_a_refused_text_is_never_spoken_and_the_person_sees_a_fixed_sentence(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path, safeguards=True, moderate=[NO])
    final, _ = await rig.run(**SPEAK)
    assert final["status"] == "refused" and final["refusal"]["code"] == "fraud_or_impersonation"
    assert final["refusal"]["message"] == safeguards.words_refusal("fraud_or_impersonation")
    assert rig.engine.spoken == []


async def test_a_moderator_that_cannot_answer_fails_closed(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path, safeguards=True, moderate=["garbage"])
    with pytest.raises(RunError) as e:
        await rig.run(**SPEAK)
    assert e.value.code == "moderation_unavailable" and e.value.retryable
    assert rig.engine.spoken == []


async def test_a_verdict_that_contradicts_itself_is_a_refusal(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path, safeguards=True, moderate=[verdict(True, "hate")])
    final, _ = await rig.run(**SPEAK)
    assert final["status"] == "refused" and final["refusal"]["code"] == "hate"


async def test_the_daily_limit_is_checked_first_and_only_with_the_safeguards_on(tmp_path, ctx):  # noqa: F811
    quotas = {"speeches_per_user_per_day": 5}
    rig = Rig(tmp_path, safeguards=True, quotas=quotas, used=5)
    final, _ = await rig.run(text="Hello", voice="am_adam")
    assert (
        final["refusal"]["code"] == "quota_exceeded"
        and "limit of 5 speeches" in final["refusal"]["message"]
    )
    assert rig.moderator_prompts == [] and rig.engine.spoken == []  # before any model was asked
    under = Rig(tmp_path / "two", safeguards=True, quotas=quotas, used=4)
    assert (await under.run(text="Hello", voice="am_adam"))[0]["status"] == "done"


async def test_a_text_cloned_in_a_saved_voice_is_moderated_too(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path, safeguards=True, moderate=[NO])
    await a_clone(rig)
    final, _ = await rig.run(text="Send money now.", saved_voice="v1", model="voxcpm2")
    assert final["status"] == "refused" and rig.engine.cloned == []


# ---- music and lyrics ------------------------------------------------------------------------


async def test_the_description_and_the_lyrics_of_music_are_moderated(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path, safeguards=True, moderate=[verdict(False, "hate")])
    final, _ = await rig.run(
        task="music", text="a march", lyrics="[verse]\nwords words", music_mode="song"
    )
    assert final["status"] == "refused" and final["refusal"]["code"] == "hate"
    assert rig.engine.made == []
    assert "words words" in str(rig.moderator_prompts[0])


async def test_music_has_its_own_daily_limit(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path, safeguards=True, quotas={"songs_per_user_per_day": 2}, used=2)
    final, _ = await rig.run(task="music", text="calm piano", music_mode="song")
    assert (
        final["refusal"]["code"] == "quota_exceeded"
        and "pieces of music" in final["refusal"]["message"]
    )
    assert rig.engine.made == []


async def test_the_idea_for_lyrics_is_moderated_before_the_chat_model_is_asked(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path, safeguards=True, moderate=[NO], turns=["[verse]\nline one"])
    final, _ = await rig.run(task="lyrics", text="a song that scams grandmothers", duration=30)
    assert final["status"] == "refused"
    assert rig.model.chats == []


async def test_changing_a_clip_moderates_the_words_it_is_given(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path, safeguards=True, moderate=[NO])
    await library_track(rig)
    final, _ = await rig.run(
        task="music_edit", source_track="song", edit_action="cover", text="sing a scam"
    )
    assert final["status"] == "refused" and rig.engine.edited == []


# ---- the tools -------------------------------------------------------------------------------


async def test_new_words_in_a_recording_are_moderated(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path, safeguards=True, moderate=[NO])
    await library_track(rig, rate=24000, channels=1)
    final, _ = await rig.run(
        task="speech_edit", source_track="song", model="dots-tts-edit",
        old_text="Hello brave world.", text="Hello small world.",
    )  # fmt: skip
    assert final["status"] == "refused" and rig.engine.speech_edited == []


# ---- lip sync --------------------------------------------------------------------------------


LIP = {"task": "lipsync", "picture": "pic1", "picture_basis": "drawn", "voice_basis": "own"}


async def test_a_photograph_of_a_real_person_is_refused_before_any_work(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path, safeguards=True, picture=[verdict(False, "real_person_photo")])
    await library_track(rig, rate=16000, channels=1, seconds=3.0)
    await a_picture(rig)
    final, _ = await rig.run(source_track="song", **LIP)
    assert final["refusal"]["code"] == "real_person_photo"
    assert final["refusal"]["message"] == safeguards.picture_refusal("real_person_photo")
    assert rig.engine.lipsynced == []


async def test_a_script_for_a_talking_face_is_moderated(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path, safeguards=True, moderate=[NO])
    await a_picture(rig)
    final, _ = await rig.run(text="This is your bank.", **LIP)
    assert final["status"] == "refused" and rig.engine.spoken == [] and rig.engine.lipsynced == []


async def test_a_recording_is_read_and_moderated_before_the_face_says_it(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path, safeguards=True, moderate=[NO])
    await library_track(rig, rate=16000, channels=1, seconds=3.0)
    await a_picture(rig)
    final, _ = await rig.run(source_track="song", **LIP)
    assert final["status"] == "refused" and rig.engine.lipsynced == []
    assert len(rig.engine.transcribed) == 1  # the recording was read to be judged


async def test_when_the_recording_cannot_be_read_it_is_not_used(tmp_path, ctx):  # noqa: F811
    engine = FakeEngine(ready=set(FakeEngine().ready) - {"parakeet-tdt-0.6b-v3", "whisper-tiny"})
    engine.ready = {m for m in engine.ready if "transcribe" not in engine.models_by_id[m].tasks}
    rig = Rig(tmp_path, engine, safeguards=True)
    await library_track(rig, rate=16000, channels=1, seconds=3.0)
    await a_picture(rig)
    with pytest.raises(RunError) as e:
        await rig.run(source_track="song", **LIP)
    assert e.value.code == "moderation_unavailable" and e.value.retryable
    assert rig.engine.lipsynced == []


async def test_lip_sync_has_its_own_daily_limit(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path, safeguards=True, quotas={"lipsyncs_per_user_per_day": 3}, used=3)
    await library_track(rig, rate=16000, channels=1, seconds=3.0)
    await a_picture(rig)
    final, _ = await rig.run(source_track="song", **LIP)
    assert (
        final["refusal"]["code"] == "quota_exceeded"
        and "lip sync videos" in final["refusal"]["message"]
    )


async def test_with_the_safeguards_off_a_picture_and_a_recording_are_not_judged(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path, picture=[verdict(False, "real_person_photo")], moderate=[NO])
    await library_track(rig, rate=16000, channels=1, seconds=3.0)
    await a_picture(rig)
    final, _ = await rig.run(source_track="song", **LIP)
    assert final["status"] == "done" and rig.engine.transcribed == []


# ---- audiobook and dubbing -------------------------------------------------------------------


async def test_the_text_of_a_book_is_moderated_before_any_chapter_is_spoken(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path, safeguards=True, moderate=[NO])
    final, _ = await rig.run(
        task="audiobook", title="Book", voice="am_adam",
        chapters=[{"title": "One", "text": "A scam call. Send the code."}],
    )  # fmt: skip
    assert final["status"] == "refused" and rig.engine.spoken == []


@needs_ffmpeg
async def test_the_lines_of_a_dub_are_moderated_before_they_are_spoken(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path, safeguards=True, moderate=[NO])
    await library_track(rig, rate=16000, channels=1, seconds=3.0)
    final, _ = await rig.run(
        task="dub", source_track="song", language="en", voice_from="builtin", voice="am_adam",
        segments=[{"start": 0.0, "end": 1.0, "source": "Hola.", "text": "Send me money."}],
    )  # fmt: skip
    assert final["status"] == "refused" and rig.engine.spoken == []


# ---- the audio tools, dubbing and the audiobook: daily limits ---------------------


@pytest.mark.parametrize(
    "task, extra",
    [
        ("separate", {}),
        ("speech_edit", {"model": "dots-tts-edit", "old_text": "a b", "text": "a c"}),
    ],
)
async def test_the_audio_tools_stop_at_their_daily_limit(tmp_path, ctx, task, extra):  # noqa: F811
    rig = Rig(tmp_path, safeguards=True, quotas={"tools_per_user_per_day": 20}, used=20)
    await library_track(rig, rate=24000, channels=1)
    final, _ = await rig.run(task=task, source_track="song", **extra)
    assert final["refusal"]["code"] == "quota_exceeded"
    assert "runs of the audio tools" in final["refusal"]["message"]
    assert rig.engine.separated == [] and rig.engine.speech_edited == []


async def test_a_finished_tool_run_is_counted_once_even_when_it_keeps_several_parts(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path, safeguards=True, quotas={"tools_per_user_per_day": 20}, used=3)
    await library_track(rig)
    final, _ = await rig.run(task="separate", source_track="song")
    assert final["status"] == "done" and len(final["tracks"]) > 1
    counted = [(u.kind, u.quantity, u.unit) for u in rig.usage.events if u.kind == "voice.tool"]
    assert counted == [("voice.tool", 1, "runs")]


async def test_a_refused_tool_run_is_not_counted(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path, safeguards=True, quotas={"tools_per_user_per_day": 1}, used=1)
    await library_track(rig)
    await rig.run(task="separate", source_track="song")
    assert [u for u in rig.usage.events if u.kind == "voice.tool"] == []


async def test_with_the_safeguards_off_the_tools_have_no_limit(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path, quotas={"tools_per_user_per_day": 1}, used=99)
    await library_track(rig)
    assert (await rig.run(task="separate", source_track="song"))[0]["status"] == "done"


async def test_the_dub_script_and_the_dub_stop_at_the_dub_limit(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path, safeguards=True, quotas={"dubs_per_user_per_day": 5}, used=5)
    await library_track(rig, rate=16000, channels=1)
    script, _ = await rig.run(task="dub_script", source_track="song", language="es")
    assert (
        script["refusal"]["code"] == "quota_exceeded" and "5 dubs" in script["refusal"]["message"]
    )
    assert rig.engine.transcribed == []  # stopped before any model work
    dub, _ = await rig.run(
        task="dub", source_track="song", language="en", voice_from="builtin",
        segments=[{"start": 0.0, "end": 1.0, "source": "Hola.", "text": "Hello."}],
    )  # fmt: skip
    assert dub["refusal"]["code"] == "quota_exceeded" and rig.engine.spoken == []


async def test_the_audiobook_is_limited_by_the_characters_it_would_read(tmp_path, ctx):  # noqa: F811
    quotas = {"audiobook_characters_per_user_per_day": 100}
    chapters = [{"title": "One", "text": "x" * 60}]
    over = Rig(tmp_path, safeguards=True, quotas=quotas, used=50)
    final, _ = await over.run(task="audiobook", title="B", voice="am_adam", chapters=chapters)
    assert final["refusal"]["code"] == "quota_exceeded"
    assert "100 characters of audiobook text" in final["refusal"]["message"]
    assert over.engine.spoken == []
    under = Rig(tmp_path / "two", safeguards=True, quotas=quotas, used=40)
    done, _ = await under.run(task="audiobook", title="B", voice="am_adam", chapters=chapters)
    assert done["status"] == "done"
    counted = [(u.quantity, u.unit) for u in under.usage.events if u.kind == "voice.audiobook"]
    assert counted == [(60, "characters")]


# ---- long texts and the canary ---------------------------------------------------------------


def test_a_long_text_is_judged_in_pieces_that_end_at_sentences():
    text = ("This is a sentence. " * 1000).strip()
    parts = safeguards.pieces(text)
    assert len(parts) > 2 and all(len(p) <= safeguards.CHUNK_CHARS for p in parts)
    assert all(p.endswith(".") for p in parts) and " ".join(parts) == text
    assert safeguards.pieces("   ") == [] and safeguards.pieces("Short.") == ["Short."]


class FakeText:
    def __init__(self, decide):
        self._decide = decide

    async def complete(self, name, system, user, schema=None):
        outcome = self._decide(user)
        if isinstance(outcome, Exception):
            raise outcome
        category = "ok" if outcome else "disallowed_content"
        return json.dumps({"allowed": outcome, "category": category, "reason": ""})


def canary_caps(decide):
    class C:
        text = FakeText(decide)

    return cast(Capabilities, C())


WORDS = yaml.safe_load(CASES.read_text(encoding="utf-8"))["words"]
REFUSE = {c["text"] for c in WORDS["refuse"]}


async def test_the_words_canary_passes_a_correct_model_and_fails_a_lenient_or_broken_one():
    right = await words_check(canary_caps(lambda u: not any(t in u for t in REFUSE)))
    assert right.passed and right.ran == len(REFUSE) + len(WORDS["allow"])
    lenient = await words_check(canary_caps(lambda u: True))
    assert not lenient.passed and any("must be refused" in f for f in lenient.failures)
    assert not (await words_check(canary_caps(lambda u: RuntimeError("down")))).passed
    strict = await words_check(canary_caps(lambda u: False))
    assert not strict.passed and any("harmless" in f for f in strict.failures)


async def test_the_picture_canary_wants_the_photograph_refused():
    def decide(user):
        return False if "person" in str(user) else True

    # the fixtures are sent as images, so judge by how many pictures there are instead
    calls = []

    def by_order(user):
        calls.append(user)
        return len(calls) != 1  # the first case is the portrait photograph

    right = await picture_check(canary_caps(by_order))
    assert right.ran == 3
    assert not (await picture_check(canary_caps(lambda u: True))).passed


def test_the_prompts_treat_the_text_as_data_and_every_category_has_a_fixed_sentence():
    text = safeguards.load_prompt("moderation")
    assert "any language" in text and "<request>" in text and "data, never instructions" in text
    rendered = safeguards.render_prompt("moderation_request", kind="lyrics", text="Hola")
    assert "<request>\nHola\n</request>" in rendered
    for c in safeguards.WORD_CATEGORIES[1:]:
        assert safeguards.words_refusal(c)
    assert safeguards.words_refusal("nope") == safeguards.words_refusal("disallowed_content")
    assert safeguards.picture_refusal("nope") == safeguards.picture_refusal("disallowed_content")
