"""A meeting recorded in two channels: the split, "You" as one speaker, the microphone's echo."""

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
from wasifyai_meetings.channels import loud, split
from wasifyai_meetings.merge import merge_two, without_echo
from wasifyai_meetings.sortformer import SR, BadAudio, Wav


@dataclass(frozen=True)
class W:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class T:
    start: float
    end: float
    speaker: int


def _stereo(path: Path, mine: np.ndarray, theirs: np.ndarray, size_unknown: bool = False) -> None:
    frames = np.stack([mine, theirs], axis=1).astype("<i2").tobytes()
    size = 0xFFFFFFFF if size_unknown else len(frames)
    head = struct.pack(
        "<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(frames), b"WAVE", b"fmt ", 16, 1, 2, SR, SR * 4,
        4, 16, b"data", size,
    )  # fmt: skip
    path.write_bytes(head + frames)


def test_two_channels_become_you_others_and_both(tmp_path: Path):
    t = np.arange(SR * 2) / SR
    mine = (np.sin(2 * np.pi * 220 * t) * 8000).astype(np.int16)
    theirs = np.zeros_like(mine)
    theirs[SR:] = 4000
    src = tmp_path / "rec.wav"
    _stereo(src, mine, theirs, size_unknown=True)  # as the shell leaves it when the app is closed
    you, others, both = tmp_path / "you.wav", tmp_path / "others.wav", tmp_path / "both.wav"
    assert split(src, you, others, both) == pytest.approx(2.0)
    a, b, c = Wav(you), Wav(others), Wav(both)
    try:
        assert np.array_equal(a.samples, mine) and np.array_equal(b.samples, theirs)
        assert c.samples[SR + 5] == np.clip(int(mine[SR + 5]) + 4000, -32768, 32767)
    finally:
        a.close(), b.close(), c.close()  # type: ignore[func-returns-value]
    assert loud(you) and loud(others)
    _stereo(src, mine, np.zeros_like(mine))
    split(src, you, others, both)
    assert not loud(others)  # nothing played, or the Mac did not allow the capture


def test_a_file_that_is_not_the_recording_is_refused(tmp_path: Path):
    bad = tmp_path / "x.wav"
    bad.write_bytes(b"not a wav at all")
    with pytest.raises(BadAudio):
        split(bad, tmp_path / "a.wav", tmp_path / "b.wav", tmp_path / "c.wav")


def test_the_microphone_is_one_speaker_and_the_others_are_numbered_after_it():
    you = (
        [],
        [T(0.0, 2.0, 0), T(6.0, 8.0, 1)],  # the model heard two in the microphone: still "You"
        [W(0.2, 0.6, "Hello"), W(0.7, 1.2, "everyone."), W(6.1, 6.6, "Thanks.")],
    )
    others = (
        [],
        [T(2.5, 4.0, 0), T(4.2, 5.8, 1)],
        [W(2.6, 3.0, "Hi"), W(3.1, 3.6, "there."), W(4.3, 5.0, "Morning.")],
    )
    speakers, lines = merge_two(you, others)
    assert [(s["key"], s["name"]) for s in speakers] == [
        ("S1", "You"),
        ("S2", "Speaker 2"),
        ("S3", "Speaker 3"),
    ]
    assert [(x["speaker"], x["text"]) for x in lines] == [
        ("S1", "Hello everyone."),
        ("S2", "Hi there."),
        ("S3", "Morning."),
        ("S1", "Thanks."),
    ]
    assert speakers[0]["seconds"] == 4.0


def test_the_microphone_hearing_the_computer_is_dropped():
    mine = [W(1.0, 1.3, "Shall"), W(1.4, 1.6, "we"), W(5.0, 5.4, "Yes,"), W(5.5, 5.9, "please.")]
    theirs = [W(0.6, 0.9, "shall"), W(1.0, 1.2, "We"), W(9.0, 9.3, "yes")]
    assert [w.text for w in without_echo(mine, theirs)] == ["Yes,", "please."]


def test_a_recording_with_only_one_side_talking():
    speakers, lines = merge_two(([], [], []), ([], [T(0, 1, 0)], [W(0.1, 0.5, "Hello.")]))
    assert [s["key"] for s in speakers] == ["S2"] and lines[0]["speaker"] == "S2"
    speakers, lines = merge_two(([], [T(0, 1, 0)], [W(0.1, 0.5, "Notes.")]), ([], [], []))
    assert [s["name"] for s in speakers] == ["You"]
