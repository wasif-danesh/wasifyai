# ruff: noqa: E501  (prose in the docstrings is easier to read on one line)
"""When typed lines are sung (ADR-0090): the words stay the person's; what was heard only gives times."""

from wasifyai_voice.lyric_timing import lyric_lines, timed_lines

LYRICS = "[Verse]\nMorning light on the empty street\n\nCoffee cold and a steady beat\n(Chorus)\nI left the city with a borrowed car"
HEARD = [
    {"start": 2.0, "end": 6.0, "text": "morning line on the empty street"},
    {"start": 7.0, "end": 11.0, "text": "coffee cold and a steady beat"},
    {"start": 12.0, "end": 16.0, "text": "I left the city with a bar card"},
]


def test_marks_and_empty_lines_are_not_sung():
    assert lyric_lines(LYRICS)[0] == "Morning light on the empty street"
    assert len(lyric_lines(LYRICS)) == 3


def test_the_words_stay_as_typed_and_the_times_come_from_what_was_heard():
    rows = timed_lines(LYRICS, HEARD)
    assert [r["text"] for r in rows] == lyric_lines(LYRICS)
    assert rows[0]["start"] == 2.0 and rows[0]["end"] <= 6.0
    assert 7.0 <= rows[1]["start"] < rows[1]["end"] <= 11.0
    assert rows[2]["start"] == 12.0


def test_a_line_not_heard_takes_its_place_between_the_lines_around_it():
    heard = [HEARD[0], HEARD[2]]
    rows = timed_lines(LYRICS, heard)
    assert rows[0]["end"] <= rows[1]["start"] < rows[1]["end"] <= rows[2]["start"]


def test_when_too_little_matches_the_lines_have_no_times():
    garbled = [{"start": 0, "end": 40, "text": "ami tomake bhalobashi shono aaj rate gaan"}]
    assert timed_lines(LYRICS, garbled) == []
    assert timed_lines(LYRICS, []) == []
    assert timed_lines("", HEARD) == []
