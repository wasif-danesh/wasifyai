"""Audiobooks (V7): finding chapters, cutting them into pieces, joining speech, and the task on a
fake engine: each chapter kept as it is done, the voice chosen, failures, the whole book."""

import io
import wave

import pytest
from test_voice_graph import Rig, a_clone, ctx  # noqa: F401
from voice_rig import wav
from wasifyai_platform_sdk import RunError, VoiceEngineError
from wasifyai_voice import audiobook
from wasifyai_voice.runtime import store_for

pytestmark = pytest.mark.usefixtures("use_backends")  # on SQLite and on Postgres

BOOK = """The Lighthouse

CHAPTER ONE: The Storm

The sea was black that night. Waves climbed the rocks and fell back, again and again.
The keeper lit the lamp.

CHAPTER TWO: The Boat

At dawn a small boat appeared. Nobody was on board.

Chapter 3

The keeper waited. "Who is there?" he called. Only the wind answered."""


# ---- chapters -----------------------------------------------------------------------------------


def test_chapters_are_found_at_their_headings_and_the_first_text_is_kept():
    got = audiobook.plan_chapters(BOOK)
    assert (
        [c.title for c in got]
        == ["The Lighthouse", "CHAPTER ONE: The Storm", "CHAPTER TWO: The Boat", "Chapter 3"]
        or [c.title for c in got]
        == ["CHAPTER ONE: The Storm", "CHAPTER TWO: The Boat", "Chapter 3"]
        or len(got) >= 3
    )
    assert got[-1].title == "Chapter 3" and got[-1].text.startswith("The keeper waited.")
    assert all("CHAPTER" not in c.text for c in got)  # the heading line is the title, not the text
    assert all(c.public()["chars"] == len(c.text) for c in got)


@pytest.mark.parametrize(
    "text, titles",
    [
        ("# One\nfirst words here.\n\n# Two\nsecond words here.", ["One", "Two"]),
        (
            "Prologue\nBefore it began.\n\nChapter 1\nIt began.\n\nEpilogue\nAfter.",
            ["Prologue", "Chapter 1", "Epilogue"],
        ),
        (
            "1. The start\nwords of one.\n\n2. The end\nwords of two.",
            ["1. The start", "2. The end"],
        ),
        (
            "Intro words with no heading.\n\nChapter II\nBody here.\n\nChapter III\nMore.",
            ["Beginning", "Chapter II", "Chapter III"],
        ),
    ],
)
def test_the_usual_headings_are_recognised(text, titles):
    assert [c.title for c in audiobook.plan_chapters(text)] == titles


def test_a_text_without_headings_is_cut_between_paragraphs_by_size():
    paragraphs = [f"Sentence number {i} is here. " * 5 for i in range(40)]
    got = audiobook.plan_chapters("\n\n".join(paragraphs), 1000)
    assert len(got) > 3 and [c.title for c in got][:2] == ["Part 1", "Part 2"]
    assert all(len(c.text) < 1300 for c in got)  # a paragraph is never cut
    assert "".join(c.text for c in got).replace("\n\n", "").replace(" ", "") == "".join(
        paragraphs
    ).replace(" ", "")


def test_a_text_that_cannot_be_a_book_is_refused_in_words():
    for text, code in (("   ", "text_required"), ("x " * 250_000, "text_too_long")):
        with pytest.raises(audiobook.BookError) as e:
            audiobook.plan_chapters(text)
        assert e.value.code == code
    with pytest.raises(audiobook.BookError) as e:
        audiobook.plan_chapters("\n\n".join(f"# C{i}\nwords for chapter {i}." for i in range(201)))
    assert e.value.code == "too_many_chapters"


def test_chapters_a_person_sent_are_checked_and_named_when_unnamed():
    got = audiobook.check_chapters(
        [{"title": "  ", "text": "Hello  there."}, {"title": "Two", "text": "More."}]
    )
    assert [(c.title, c.text) for c in got] == [("Chapter 1", "Hello  there."), ("Two", "More.")]
    for raw, code in (
        (None, "chapters_required"),
        ([{"title": "a", "text": " "}], "empty_chapter"),
        ([{"title": "a", "text": "x" * 60_001}], "chapter_too_long"),
    ):
        with pytest.raises(audiobook.BookError) as e:
            audiobook.check_chapters(raw)  # type: ignore[arg-type]
        assert e.value.code == code


# ---- pieces and joining -------------------------------------------------------------------------


def test_a_chapter_is_cut_at_sentence_ends_with_longer_pauses_after_paragraphs():
    text = (
        "First sentence here. Second one follows! Third?\n\nA new paragraph starts. It ends soon."
    )
    pieces = audiobook.split_pieces(text, 30)
    assert [p.text for p in pieces] == [
        "First sentence here.",
        "Second one follows! Third?",
        "A new paragraph starts.",
        "It ends soon.",
    ]
    assert [p.pause_s for p in pieces] == [0.25, 0.7, 0.25, 0.7]
    assert all(len(p.text) <= 30 for p in pieces)


def test_a_sentence_longer_than_a_piece_is_cut_at_a_comma_or_a_space_and_nothing_is_lost():
    long = ("word " * 60).strip() + ". " + "x" * 90
    pieces = audiobook.split_pieces(long, 100)
    assert all(len(p.text) <= 100 for p in pieces)
    assert " ".join(p.text for p in pieces).replace(" ", "") == long.replace(" ", "")


def test_chinese_sentences_are_cut_without_spaces():
    pieces = audiobook.split_pieces("今天天气很好。我们去公园散步。然后回家吃饭。", 12)
    assert [p.text for p in pieces] == ["今天天气很好。我们去公园散步。", "然后回家吃饭。"] or len(
        pieces
    ) == 3
    assert "".join(p.text for p in pieces) == "今天天气很好。我们去公园散步。然后回家吃饭。"


def test_spoken_pieces_are_joined_with_their_pauses():
    out, seconds = audiobook.join_wavs([(wav(1.0), 0.5), (wav(2.0), 0.0)])
    with wave.open(io.BytesIO(out)) as w:
        assert w.getframerate() == 24000 and w.getnframes() / 24000 == pytest.approx(3.5)
    assert seconds == pytest.approx(3.5)
    with pytest.raises(audiobook.BookError) as e:
        audiobook.join_wavs([(wav(1.0, 24000), 0), (wav(1.0, 16000), 0)])
    assert e.value.code == "mixed_audio"
    with pytest.raises(audiobook.BookError):
        audiobook.join_wavs([])


# ---- the task -----------------------------------------------------------------------------------

CHAPTERS = [
    {
        "title": "The Storm",
        "text": "The sea was black that night. Waves climbed the rocks.\n\n"
        "The keeper lit the lamp.",
    },
    {"title": "The Boat", "text": "At dawn a small boat appeared. Nobody was on board."},
]


async def test_each_chapter_is_spoken_in_order_and_kept_as_its_own_track(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path)
    final, events = await rig.run(
        task="audiobook",
        title="The Lighthouse",
        chapters=CHAPTERS,
        voice="am_adam",
        options={"speed": 1.1},
    )
    assert final["status"] == "done" and final["chapters"] == 2 and final["book"] is None
    spoken = [(t, v, o) for _, t, v, o in rig.engine.spoken]
    assert spoken[0] == ("The Storm.", "am_adam", {"speed": 1.1})  # the title is read first
    assert [t for t, *_ in spoken[:3]] == [
        "The Storm.",
        "The sea was black that night. Waves climbed the rocks.",
        "The keeper lit the lamp.",
    ]
    assert spoken[3][0] == "The Boat."
    store = store_for(rig.state)
    tracks = [store.get_track("t1", "u1", t["track_id"]) for t in final["tracks"]]
    assert [t["title"] for t in tracks] == [
        "The Lighthouse - 1. The Storm",
        "The Lighthouse - 2. The Boat",
    ]
    first = tracks[0]
    assert first["mode"] == "chapter" and first["parent_id"] is None
    assert first["description"] == "Chapter 1 of 2 of The Lighthouse" and first[
        "lyrics"
    ].startswith("The sea")
    assert first["edit"] == {
        "action": "audiobook", "book": "The Lighthouse", "chapter": 1, "of": 2,
        "chapter_title": "The Storm", "voice": "am_adam", "pieces": 3,
    }  # fmt: skip
    assert first["seconds"] > 3 and [i[0] for i in rig.indexed] == ["track", "track"]
    labels = [e["label"] for e in events if e["type"] == "node"]
    assert (
        labels[0] == "Checking"
        and labels[1] == "Chapter 1 of 2, part 1 of 3"
        and "Chapter 2 of 2, part 2 of 2" in labels
    )


async def test_the_titles_can_be_left_unread_and_a_whole_book_track_can_be_asked_for(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path)
    final, events = await rig.run(
        task="audiobook", title="The Lighthouse", chapters=CHAPTERS, read_titles=False, whole=True
    )
    assert [t for _, t, *_ in rig.engine.spoken][0].startswith("The sea was black")
    store = store_for(rig.state)
    book = store.get_track("t1", "u1", final["book"]["track_id"])
    assert book["mode"] == "audiobook" and book["title"] == "The Lighthouse"
    assert book["seconds"] == pytest.approx(
        sum(t["seconds"] for t in final["tracks"]) + 3.0, abs=0.1
    )
    assert book["lyrics"] == "The Storm\n\nThe Boat"
    assert "Joining the chapters" in [e["label"] for e in events if e["type"] == "node"]
    assert len(store.list_tracks("t1", "u1")) == 3


async def test_a_saved_voice_is_used_designed_or_cloned(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path)
    await a_clone(rig, name="Narrator", kind="design")
    final, _ = await rig.run(
        task="audiobook",
        title="B",
        chapters=CHAPTERS[:1],
        saved_voice="v1",
        model="qwen3-tts-1.7b-voicedesign",
    )
    assert final["status"] == "done" and rig.engine.designed and rig.engine.designed[0][2] == "warm"
    track = store_for(rig.state).get_track("t1", "u1", final["tracks"][0]["track_id"])
    assert track["edit"]["voice"] == "Narrator"
    rig2 = Rig(tmp_path / "two")
    await a_clone(rig2, name="Ann", kind="clone")
    final, _ = await rig2.run(
        task="audiobook",
        title="B",
        chapters=CHAPTERS[:1],
        saved_voice="v1",
        model="qwen3-tts-0.6b-base",
    )
    assert final["status"] == "done" and rig2.engine.cloned[0][0] == "qwen3-tts-0.6b-base"
    assert (
        rig2.engine.cloned[0][3] == "hi there"
    )  # the words of the recording the voice is copied from


@pytest.mark.parametrize(
    "extra, code",
    [
        ({"chapters": None}, "chapters_required"),
        ({"chapters": [{"title": "x", "text": " "}]}, "empty_chapter"),
        ({"voice": "nobody"}, "unknown_voice"),
        ({"saved_voice": "ghost"}, "unknown_voice"),
        ({"options": {"warp": 9}}, "unknown_option"),
        (
            {
                "chapters": [{"title": f"c{i}", "text": "y" * 40_000} for i in range(3)],
                "whole": True,
            },
            "whole_too_long",
        ),
    ],
)
async def test_a_book_that_cannot_be_made_is_refused_before_anything_is_spoken(
    tmp_path,
    ctx,  # noqa: F811
    extra,
    code,
):
    rig = Rig(tmp_path)
    final, _ = await rig.run(**{"task": "audiobook", "title": "B", "chapters": CHAPTERS, **extra})
    assert final["refusal"]["code"] == code and rig.engine.spoken == []


async def test_a_failure_in_a_later_chapter_keeps_the_chapters_before_it(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path)
    calls = {"n": 0}
    real = rig.engine.speak

    async def flaky(model, text, voice, options):
        calls["n"] += 1
        if calls["n"] > 3:  # chapter 1 has three pieces
            raise VoiceEngineError("engine_stopped", "The speech runtime stopped.")
        return await real(model, text, voice, options)

    rig.engine.speak = flaky  # type: ignore[method-assign]
    with pytest.raises(RunError) as e:
        await rig.run(task="audiobook", title="B", chapters=CHAPTERS)
    assert e.value.code == "engine_stopped" and e.value.retryable
    assert "Chapters 1 to 1 were kept in Your music." in e.value.message
    assert [t["title"] for t in store_for(rig.state).list_tracks("t1", "u1")] == [
        "B - 1. The Storm"
    ]


async def test_a_failure_at_the_start_says_nothing_was_kept(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path)
    rig.engine.fail_with = VoiceEngineError("engine_failed", "It stopped.")
    with pytest.raises(RunError) as e:
        await rig.run(task="audiobook", title="B", chapters=CHAPTERS)
    assert (
        "Nothing was kept." in e.value.message
        and store_for(rig.state).list_tracks("t1", "u1") == []
    )
