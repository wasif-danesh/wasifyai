"""Who said what: each stretch of the transcript goes to the speaker who spoke most during it."""

from dataclasses import dataclass

from wasifyai_meetings.merge import merge, plain_text
from wasifyai_meetings.sortformer import Turn


@dataclass
class Seg:
    start: float
    end: float
    text: str


def test_speakers_are_numbered_in_the_order_they_first_speak():
    turns = [Turn(0.0, 5.0, 2), Turn(5.0, 9.0, 0), Turn(9.0, 12.0, 2)]
    segs = [Seg(0.2, 4.8, "Hello all."), Seg(5.1, 8.9, "Hi."), Seg(9.2, 11.5, "Let's start.")]
    speakers, lines = merge(segs, turns)
    assert [s["key"] for s in speakers] == ["S1", "S2"]
    assert [x["speaker"] for x in lines] == ["S1", "S2", "S1"]
    assert speakers[0]["name"] == "Speaker 1" and speakers[0]["seconds"] == 8.0
    assert plain_text(lines, speakers).splitlines()[1] == "Speaker 2: Hi."


def test_a_stretch_goes_to_whoever_spoke_most_of_it_and_neighbours_are_joined():
    turns = [Turn(0.0, 3.0, 0), Turn(3.0, 10.0, 1)]
    segs = [Seg(2.0, 6.0, "mostly the second"), Seg(6.5, 8.0, "still them")]
    speakers, lines = merge(segs, turns)
    assert len(lines) == 1 and lines[0]["speaker"] == "S1"
    assert lines[0]["text"] == "mostly the second still them" and lines[0]["end"] == 8.0
    assert [s["key"] for s in speakers] == ["S1"]  # speaker 0 never got a stretch


def test_a_stretch_no_turn_covers_goes_to_the_nearest_speaker():
    turns = [Turn(0.0, 2.0, 0), Turn(10.0, 12.0, 1)]
    _, lines = merge([Seg(8.0, 9.0, "near the second")], turns)
    assert lines[0]["speaker"] == "S1"  # the only speaker of a line is numbered first
    speakers, lines = merge([Seg(0.5, 1.0, "a"), Seg(8.0, 9.0, "b")], turns)
    assert [x["speaker"] for x in lines] == ["S1", "S2"]


def test_with_no_turns_everything_is_speaker_1_and_empty_stretches_are_left_out():
    speakers, lines = merge([Seg(0.0, 2.0, "one"), Seg(2.1, 3.0, "  "), Seg(10.0, 11.0, "two")], [])
    assert [x["text"] for x in lines] == ["one", "two"]
    assert speakers == [{"key": "S1", "default": "Speaker 1", "name": "Speaker 1", "seconds": 3.0}]


def test_a_short_recording_is_one_piece_and_a_long_one_is_cut_in_its_longest_pause():
    from wasifyai_meetings.merge import pieces

    assert pieces([], 200.0) == [(0.0, 200.0)]
    turns = [
        Turn(0.0, 190.0, 0),
        Turn(191.0, 210.0, 1),
        Turn(215.0, 239.0, 0),
        Turn(239.5, 500.0, 1),
    ]
    cuts = pieces(turns, 500.0)
    assert cuts[0] == (0.0, 212.5)  # the 5 s pause, not the 1 s or 0.5 s one
    assert all(b - a <= 240.0 for a, b in cuts) and cuts[-1][1] == 500.0
    assert all(cuts[i][1] == cuts[i + 1][0] for i in range(len(cuts) - 1))
    assert pieces([Turn(0.0, 600.0, 0)], 600.0)[0] == (0.0, 240.0)  # no pause: cut at the limit


def test_with_word_times_a_sentence_is_split_where_the_speaker_changes():
    turns = [Turn(0.0, 2.0, 0), Turn(2.0, 4.0, 1)]
    segs = [Seg(0.0, 4.0, "Shall we start? Yes please.")]
    words = [Seg(0.1, 0.5, "Shall"), Seg(0.6, 0.9, "we"), Seg(1.0, 1.6, "start?"),
             Seg(2.2, 2.6, "Yes"), Seg(2.7, 3.4, "please.")]  # fmt: skip
    speakers, lines = merge(segs, turns, words)
    assert [(x["speaker"], x["text"]) for x in lines] == [
        ("S1", "Shall we start?"),
        ("S2", "Yes please."),
    ]
    assert [s["key"] for s in speakers] == ["S1", "S2"]


def test_with_word_times_a_long_turn_is_broken_after_a_sentence():
    turns = [Turn(0.0, 70.0, 0)]
    words = [Seg(float(t), t + 0.5, "word." if t % 10 == 9 else "word") for t in range(60)]
    _, lines = merge([], turns, words)
    assert len(lines) == 2 and lines[0]["text"].endswith(".") and lines[1]["start"] >= 30.0
