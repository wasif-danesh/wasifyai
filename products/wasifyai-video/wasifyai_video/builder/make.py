"""Making something for a project without leaving it (ADR-0096 MX6): a picture, a clip, speech or
music, by the same actions as the products' own screens, so the same checks and the same choice of
model apply. What comes back is saved to the Library as usual, and a copy becomes a file of the
project, checked as an upload is.

A voiceover's captions keep the words as they were typed. Speech to text is only asked when they
were said, never what they were: a model that hears "North Bean" must not change a brand's name."""

import re
from typing import Any

MAX_CUES = 60
MAX_CUE_WORDS = 6
STOP = re.compile(r"[.;:!?…]$")
PAUSE = re.compile(r",$")

# what = (the action, how its input is made, the key of what it made, the library's kind, a name)
PICTURE, CLIP, SPEECH, MUSIC = "picture", "clip", "speech", "music"
# what the image and video products call the nearest shape (a feed's 4:5 is cropped from portrait)
NEAREST = {"landscape": "landscape", "portrait": "portrait", "square": "square", "feed": "portrait"}


def inner_call(
    what: str, text: str, shape: str, seconds: float, voice: str | None
) -> tuple[str, dict]:
    """The product's own action for this, and what to ask it."""
    if what == PICTURE:
        return "image.generate", {"prompt": text, "size": NEAREST[shape]}
    if what == CLIP:
        return "video.generate", {
            "prompt": text,
            "shape": NEAREST[shape],
            "seconds": 8 if seconds > 6 else 5,
        }
    if what == SPEECH:
        return "speech.speak", {"text": text, **({"saved_voice": voice} if voice else {})}
    return "music.generate", {
        "description": text,
        "instrumental": True,
        "seconds": max(5.0, min(seconds, 240.0)),
    }


def made_item(what: str, output: dict[str, Any]) -> tuple[str, str] | None:
    """(the library's kind, the id) of what an action made."""
    key, kind = {
        PICTURE: ("image_id", "image"),
        CLIP: ("video_id", "video"),
        SPEECH: ("speech_id", "speech"),
        MUSIC: ("track_id", "track"),
    }[what]
    found = output.get(key)
    return (kind, str(found)) if found else None


def file_name(what: str, text: str) -> str:
    short = re.sub(r"\s+", " ", text).strip()[:40].strip() or what
    return short + {PICTURE: ".png", CLIP: ".mp4", SPEECH: ".wav", MUSIC: ".wav"}[what]


def _phrases(text: str) -> list[list[str]]:
    """The words, as short lines to read: a line ends at a stop or after a few words."""
    out: list[list[str]] = []
    line: list[str] = []
    for word in text.split():
        line.append(word)
        if (
            len(line) >= MAX_CUE_WORDS
            or STOP.search(word)
            or (PAUSE.search(word) and len(line) >= 3)
        ):
            out.append(line)
            line = []
    if line:
        out.append(line)
    return out


def _clock(segments: list[dict[str, Any]], seconds: float) -> list[tuple[float, float, int]]:
    """Stretches of speech with how many words were heard in each; one when none is known."""
    heard = [
        (float(s["start"]), float(s["end"]), len(str(s.get("text", "")).split()))
        for s in segments
        if float(s.get("end", 0)) > float(s.get("start", 0))
    ]
    heard = [h for h in heard if h[2] > 0]
    return heard or [(0.0, seconds, 1)]


def _time_at(share: float, clock: list[tuple[float, float, int]]) -> float:
    """When this share of the words has been said."""
    total = sum(n for _, _, n in clock)
    left = share * total
    for start, end, words in clock:
        if left <= words:
            return start + (end - start) * (left / words)
        left -= words
    return clock[-1][1]


def timed_lines(text: str, segments: list[dict[str, Any]], seconds: float) -> list[dict[str, Any]]:
    """The typed words as lines with their times. The words are the person's; the times come from
    what was heard, by how far through the words each line is."""
    lines = _phrases(text)[:MAX_CUES]
    if not lines or seconds <= 0:
        return []
    clock = _clock(segments, seconds)
    total = sum(len(line) for line in lines)
    out = []
    done = 0
    for line in lines:
        start = _time_at(done / total, clock)
        done += len(line)
        end = _time_at(done / total, clock)
        out.append(
            {
                "text": " ".join(line),
                "start": round(start, 2),
                "end": round(max(end, start + 0.2), 2),
            }
        )
    return out
