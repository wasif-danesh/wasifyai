"""Putting who spoke when (the speaker model's turns) together with what was said (the transcript's
segments): each segment goes to the speaker who spoke most during it, and the speakers are numbered
in the order they first speak (Speaker 1, Speaker 2, ...).

A segment that no turn covers goes to the speaker of the nearest turn. When the model found nobody
(a recording of silence, music, or one too short) every segment is Speaker 1. A segment where two
people speak goes whole to the one who spoke more of it; splitting it needs word times, which not
every transcription model gives (a later stage)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol


class _Turn(Protocol):
    @property
    def start(self) -> float: ...
    @property
    def end(self) -> float: ...
    @property
    def speaker(self) -> int: ...


class _Segment(Protocol):
    @property
    def start(self) -> float: ...
    @property
    def end(self) -> float: ...
    @property
    def text(self) -> str: ...


@dataclass(frozen=True)
class _Said:
    start: float
    end: float
    speaker: int


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def speaker_of(seg: _Segment, turns: Sequence[_Turn]) -> int | None:
    """The model's speaker index who spoke most during `seg`, else the nearest turn's."""
    if not turns:
        return None
    talk: dict[int, float] = {}
    for t in turns:
        if t.end > seg.start and t.start < seg.end:
            talk[t.speaker] = talk.get(t.speaker, 0.0) + _overlap(
                seg.start, seg.end, t.start, t.end
            )
    if talk:
        return max(talk.items(), key=lambda kv: (kv[1], -kv[0]))[0]
    mid = (seg.start + seg.end) / 2
    nearest = min(turns, key=lambda t: (0.0 if t.start <= mid <= t.end else min(
        abs(mid - t.start), abs(mid - t.end)), t.start))  # fmt: skip
    return nearest.speaker


LONG_LINE_S = 30.0  # with word times, a long turn is broken at the end of a sentence after this
_SENTENCE_END = (".", "?", "!", "।", "॥", "。", "？", "！")


def merge(
    segments: Sequence[_Segment], turns: Sequence[_Turn], words: Sequence[_Segment] = ()
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(speakers, lines). A speaker is `{key, default, name, seconds}`; a line is `{start, end,
    speaker, text}`. With the words' times (`words`) each word goes to whoever spoke at that moment
    and a line ends where the speaker changes; without them each segment goes whole. The next piece
    of the same speaker is joined to a line when it follows on."""
    by_word = bool(words)
    order: dict[int | None, str] = {}
    lines: list[dict[str, Any]] = []
    for seg in sorted(words or segments, key=lambda s: (s.start, s.end)):
        text = seg.text.strip()
        if not text:
            continue
        idx = speaker_of(seg, turns)
        if idx not in order:
            order[idx] = f"S{len(order) + 1}"
        key = order[idx]
        last = lines[-1] if lines else None
        follows = last is not None and last["speaker"] == key and seg.start - last["end"] < 2.0
        if follows and by_word and last is not None:  # break a long turn after a sentence
            ended = last["text"].endswith(_SENTENCE_END)
            follows = not (ended and last["end"] - last["start"] >= LONG_LINE_S)
        if follows and last is not None:
            last["end"] = round(max(last["end"], seg.end), 2)
            last["text"] = f"{last['text']} {text}"
        else:
            lines.append(
                {"start": round(seg.start, 2), "end": round(seg.end, 2), "speaker": key,
                 "text": text}
            )  # fmt: skip
    # how long each speaker spoke, from the model's turns (the transcript's times are coarser)
    seconds: dict[str, float] = {}
    for t in turns:
        key = order.get(t.speaker)
        if key is not None:
            seconds[key] = seconds.get(key, 0.0) + (t.end - t.start)
    if not turns:
        for line in lines:
            seconds[line["speaker"]] = (
                seconds.get(line["speaker"], 0.0) + line["end"] - line["start"]
            )
    speakers = [
        {"key": key, "default": f"Speaker {key[1:]}", "name": f"Speaker {key[1:]}",
         "seconds": round(seconds.get(key, 0.0), 1)}
        for key in sorted(order.values(), key=lambda k: int(k[1:]))
    ]  # fmt: skip
    return speakers, lines


ECHO_S = 1.5  # a word the microphone heard this close to the computer's same word is its echo


def _plain(word: str) -> str:
    return "".join(ch for ch in word.casefold() if ch.isalnum())


def without_echo(
    mine: Sequence[_Segment], theirs: Sequence[_Segment], within: float = ECHO_S
) -> list[_Segment]:
    """The microphone's words less those it heard from the computer's speakers: a word that the
    computer's channel has too, at nearly the same moment. (With headphones there are none.)"""
    heard: dict[str, list[float]] = {}
    for w in theirs:
        key = _plain(w.text)
        if key:
            heard.setdefault(key, []).append(w.start)
    return [
        w for w in mine
        if not any(abs(w.start - t) <= within for t in heard.get(_plain(w.text), ()))
    ]  # fmt: skip


def merge_two(
    you: tuple[Sequence[_Segment], Sequence[_Turn], Sequence[_Segment]],
    others: tuple[Sequence[_Segment], Sequence[_Turn], Sequence[_Segment]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(speakers, lines) of a meeting recorded in two channels (ADR-0108 decision 10): the
    microphone is one speaker, "You" (S1); the computer's sound is split by the speaker model into
    Speaker 2, 3… Each channel is `(segments, turns, words)`; the microphone's echo of the
    computer is dropped where word times show it."""
    mine_segments, mine_turns, mine_words = you
    their_segments, their_turns, their_words = others
    if mine_words and their_words:
        mine_words = without_echo(mine_words, their_words)
    # the microphone is one person whatever the speaker model heard in it
    one = [_Said(t.start, t.end, 0) for t in mine_turns]
    a_speakers, a_lines = merge(mine_segments, one, mine_words)
    b_speakers, b_lines = merge(their_segments, their_turns, their_words)
    shift = {s["key"]: f"S{int(s['key'][1:]) + 1}" for s in b_speakers}
    speakers = [
        {**s, "key": "S1", "default": "You", "name": "You"} for s in a_speakers[:1]
    ] + [
        {**s, "key": shift[s["key"]], "default": f"Speaker {shift[s['key']][1:]}",
         "name": f"Speaker {shift[s['key']][1:]}"}
        for s in b_speakers
    ]  # fmt: skip
    lines = [{**x, "speaker": "S1"} for x in a_lines] + [
        {**x, "speaker": shift[x["speaker"]]} for x in b_lines
    ]
    lines.sort(key=lambda x: (x["start"], x["end"]))
    return speakers, lines


def plain_text(lines: Sequence[dict[str, Any]], speakers: Sequence[dict[str, Any]]) -> str:
    """The transcript as text, one line per turn with its speaker's name (for search and export)."""
    names = {s["key"]: s["name"] for s in speakers}
    return "\n".join(f"{names.get(x['speaker'], x['speaker'])}: {x['text']}" for x in lines)


PIECE_S = 240.0  # what is written down at once: audio.cpp's Parakeet refuses much more (MT1 run)
LOOK_BACK_S = 60.0  # how far before the end of a piece a pause is looked for


def pieces(
    turns: Sequence[_Turn], seconds: float, most: float = PIECE_S
) -> list[tuple[float, float]]:
    """The recording cut into pieces of at most `most` seconds, each cut in the longest pause in
    the last minute before it (from the speaker model's turns), so a sentence is not cut in two.
    Without a pause there the cut is at the limit."""
    if seconds <= most:
        return [(0.0, seconds)]
    spans = sorted((t.start, t.end) for t in turns)
    speech: list[tuple[float, float]] = []
    for a, b in spans:  # who spoke when, joined: the gaps between are pauses
        if speech and a <= speech[-1][1]:
            speech[-1] = (speech[-1][0], max(speech[-1][1], b))
        else:
            speech.append((a, b))
    gaps = [(speech[i][1], speech[i + 1][0]) for i in range(len(speech) - 1)]
    out: list[tuple[float, float]] = []
    start = 0.0
    while seconds - start > most:
        limit = start + most
        near = [
            (b - a, (a + b) / 2)
            for a, b in gaps
            if start + most - LOOK_BACK_S <= (a + b) / 2 < limit
        ]
        cut = max(near)[1] if near else limit
        out.append((start, cut))
        start = cut
    out.append((start, seconds))
    return out


__all__ = [
    "PIECE_S", "merge", "merge_two", "pieces", "plain_text", "speaker_of", "without_echo",
]  # fmt: skip
