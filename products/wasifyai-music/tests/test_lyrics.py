import json
import random

import pytest
from conftest import GOOD_LYRICS, draft
from wasifyai_music.lyrics import (
    DraftInvalid,
    LyricsStreamer,
    lyric_problems,
    normalise_lyrics,
    parse_draft,
)


def test_normalise_gives_canonical_lowercase_section_tags():
    raw = (
        "```\n[Verse 1]\nline one  \n\n\n\n[ CHORUS ]\nline two\n[Hook]\nline three\n"
        "[Pre Chorus]\nx\n```"
    )
    out = normalise_lyrics(raw)
    assert out.split("\n") == [
        "[verse]",
        "line one",
        "",
        "[chorus]",
        "line two",
        "[chorus]",
        "line three",
        "[pre-chorus]",
        "x",
    ]


def test_lyric_problems_names_what_is_missing():
    assert lyric_problems(GOOD_LYRICS) == []
    no_chorus = "[verse]\n" + "\n".join(f"line {i}" for i in range(8))
    assert lyric_problems(no_chorus) == [
        "include at least one [chorus] section tag on its own line"
    ]
    assert any("at least 6 lines" in p for p in lyric_problems("[verse]\na\n[chorus]\nb"))
    assert len(lyric_problems("just words")) == 3


def test_parse_draft_accepts_a_good_reply_and_normalises():
    d = parse_draft(draft(lyrics=GOOD_LYRICS.replace("[verse]", "[Verse 1]")))
    assert d.title == "Sing It Out Loud" and d.lyrics.count("[verse]") == 2


@pytest.mark.parametrize(
    "raw, fragment",
    [
        ("not json at all", "not valid JSON"),
        ('{"title": "x"}', "Fix these fields"),
        (draft(title="   "), "Fix these fields: title"),
        (draft(lyrics="[verse]\n" + "\n".join(f"l{i}" for i in range(9))), "[chorus]"),
        (draft(lyrics="[verse]\nonly\n[chorus]\nthree\nlines"), "at least 6 lines"),
        (draft(style="x" * 500), "style"),
    ],
)
def test_parse_draft_rejects_with_feedback_for_the_model(raw, fragment):
    with pytest.raises(DraftInvalid) as e:
        parse_draft(raw)
    assert fragment in e.value.feedback


def stream_in_chunks(text: str, cuts: list[int]) -> str:
    s, out, prev = LyricsStreamer(), [], 0
    for c in [*cuts, len(text)]:
        out.append(s.feed(text[prev:c]))
        prev = c
    return "".join(out)


def test_streamer_emits_only_the_lyrics_value_decoded():
    text = draft()
    assert stream_in_chunks(text, []) == GOOD_LYRICS


def test_streamer_handles_every_possible_chunk_boundary():
    text = json.dumps(
        {
            "title": 'A "quoted" title',
            "lyrics": 'line "one"\nline two \\ back\n[chorus] é世',
            "style": "x",
            "cover_prompt": "y",
        }
    )
    expected = json.loads(text)["lyrics"]
    for cut in range(len(text) + 1):  # every split into two chunks, including inside escapes
        assert stream_in_chunks(text, [cut]) == expected, cut
    rng = random.Random(7)
    for _ in range(300):  # and random splits into many chunks, down to single characters
        cuts = sorted(rng.sample(range(len(text)), rng.randint(1, 20)))
        assert stream_in_chunks(text, cuts) == expected
    assert stream_in_chunks(text, list(range(len(text)))) == expected


def test_streamer_ignores_other_fields_whatever_the_order():
    text = json.dumps(
        {"cover_prompt": "lyrics lyrics", "lyrics": "la la", "title": "lyrics", "style": "s"}
    )
    assert stream_in_chunks(text, []) == "la la"
    assert LyricsStreamer().feed('{"title": "no lyrics here"}') == ""


def test_merge_tags_drops_repeats_but_keeps_order_and_spelling():
    from wasifyai_music.lyrics import merge_tags

    assert (
        merge_tags("Indie Pop", "mellow", "indie pop, mellow, female vocal, 100 bpm")
        == "Indie Pop, mellow, female vocal, 100 bpm"
    )
    assert merge_tags("", None, " a ,, b ") == "a, b" and merge_tags() == ""


def test_a_tag_written_on_the_same_line_as_its_first_lyric_is_split():
    """The real model often writes "[verse]First line" (measured: 6 of 30 first attempts)."""
    raw = (
        "[verse]The big moon hangs so low\nLittle horns begin to glow\n\n"
        "[Chorus 1] Hush now, little dino dear\n[hook]Sleep tight"
    )
    assert normalise_lyrics(raw).split("\n") == [
        "[verse]", "The big moon hangs so low", "Little horns begin to glow", "",
        "[chorus]", "Hush now, little dino dear", "[chorus]", "Sleep tight",
    ]  # fmt: skip


def test_only_real_section_names_are_split_off():
    assert (
        normalise_lyrics("[laughs] hello there\n[Verse]\nx") == "[laughs] hello there\n[verse]\nx"
    )
    assert normalise_lyrics("[verse]\n[chorus] already fine") == "[verse]\n[chorus]\nalready fine"


def test_lyrics_too_long_for_the_song_are_refused_not_silently_cut_off():
    from wasifyai_music.lyrics import MAX_LYRIC_LINES

    long_ = "[verse]\n" + "\n".join(f"line {i}" for i in range(MAX_LYRIC_LINES)) + "\n[chorus]\nx"
    assert any("at most 20 lines" in p for p in lyric_problems(long_))
    ok = (
        "[verse]\n"
        + "\n".join(f"line {i}" for i in range(MAX_LYRIC_LINES - 4))
        + "\n[chorus]\nx\ny\nz"
    )
    assert lyric_problems(ok) == []  # 20 sung lines exactly is fine
    with pytest.raises(DraftInvalid) as e:
        parse_draft(draft(lyrics=long_))
    assert "at most 20 lines" in e.value.feedback  # the model is told how to fix it
