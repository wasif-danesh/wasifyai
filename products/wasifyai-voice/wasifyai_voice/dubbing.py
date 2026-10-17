# SPDX-License-Identifier: Apache-2.0
"""The parts of dubbing that are not a model (ADR-0066, stage V6): which languages a model speaks,
the script (segments with times), the prompt that translates it and the reading of the answer, how
long a spoken line may be, and the mixing of the lines over the background with ffmpeg.

A dub is made in two steps so a person can read and change the translation before anything is
spoken: the script (separate the voice from the background, write down what is said with times,
translate it) and the dub (speak each line, fit it to its time, mix)."""

import asyncio
import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk import VoiceModel
from wasifyai_platform_sdk.voice_models import MAX_SPEAK_CHARS

from wasifyai_voice.audio_input import find_converter

MAX_SEGMENTS = 400
MAX_TEMPO = 1.3  # a line is spoken at most this much faster to fit; more would sound hurried
TAIL_S = 2.0  # time after the last line before the end

LANGUAGES = {
    "bg": "Bulgarian", "cs": "Czech", "da": "Danish", "de": "German", "el": "Greek",
    "en": "English", "es": "Spanish", "et": "Estonian", "fi": "Finnish", "fr": "French",
    "hr": "Croatian", "hu": "Hungarian", "it": "Italian", "ja": "Japanese", "ko": "Korean",
    "lt": "Lithuanian", "lv": "Latvian", "mt": "Maltese", "nl": "Dutch", "pl": "Polish",
    "pt": "Portuguese", "ro": "Romanian", "ru": "Russian", "sk": "Slovak", "sl": "Slovenian",
    "sv": "Swedish", "uk": "Ukrainian", "zh": "Chinese",
}  # fmt: skip
# how many characters a language speaks in a second, roughly: how long a line may be, for the
# translator
CHARS_PER_SECOND = {"zh": 5.0, "ja": 7.0, "ko": 7.0, "de": 14.0, "ru": 13.0, "fi": 13.0}
DEFAULT_CPS = 15.0


def base(code: str) -> str:
    """`en-us` and `EN` are both `en`."""
    return str(code).lower().replace("_", "-").split("-")[0]


def language_name(code: str) -> str:
    return LANGUAGES.get(base(code), str(code))


def supports(model: VoiceModel, language: str) -> bool:
    """Whether a model speaks (or writes down) a language; `multi` means it is not limited."""
    langs = {base(x) for x in model.languages}
    return "multi" in langs or base(language) in langs


class DubError(Exception):
    """`str(e)` is a sentence safe to show; `code` is stable."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    source: str  # what was said
    text: str  # what it becomes

    def public(self) -> dict[str, Any]:
        return {
            "start": round(self.start, 2), "end": round(self.end, 2),
            "source": self.source, "text": self.text,
        }  # fmt: skip


def clean_segments(raw: list[dict[str, Any]] | None, total: float) -> list[Segment]:
    """The script a person sent, checked: lines in order, each inside the recording, none empty."""
    if not raw:
        raise DubError("script_required", "There is no script to speak. Write the script first.")
    if len(raw) > MAX_SEGMENTS:
        raise DubError("too_many_lines", f"A script has at most {MAX_SEGMENTS} lines.")
    out: list[Segment] = []
    last_end = 0.0
    for i, item in enumerate(raw, 1):
        try:
            start, end = float(item["start"]), float(item["end"])
        except (KeyError, TypeError, ValueError):
            raise DubError("bad_line", f"Line {i} has no start and end time.") from None
        text = " ".join(str(item.get("text", "")).split())
        source = " ".join(str(item.get("source", "")).split())
        if not text:
            raise DubError("empty_line", f"Line {i} has no words. Write them or take the line out.")
        if len(text) > MAX_SPEAK_CHARS:
            raise DubError(
                "line_too_long", f"Line {i} is longer than {MAX_SPEAK_CHARS} characters."
            )
        if not 0 <= start < end <= total + 0.5:
            raise DubError("bad_time", f"Line {i} is outside the recording.")
        if start < last_end - 0.25:
            raise DubError("lines_overlap", f"Line {i} starts before the line before it ends.")
        out.append(Segment(start, min(end, total), source, text))
        last_end = end
    return out


def slots(segments: list[Segment], total: float) -> list[float]:
    """The time each line may take: until the next line starts (the last may run on a little)."""
    out = []
    for i, s in enumerate(segments):
        nxt = segments[i + 1].start if i + 1 < len(segments) else total + TAIL_S
        out.append(max(0.3, nxt - s.start))
    return out


def tempo_for(duration: float, slot: float) -> tuple[float, float]:
    """(how much faster to play a spoken line, how long it still runs over its slot). A line that
    fits is left as it is; one that does not is sped up to fit, never by more than MAX_TEMPO."""
    if duration <= slot or duration <= 0:
        return 1.0, 0.0
    tempo = min(MAX_TEMPO, duration / slot)
    return tempo, max(0.0, duration / tempo - slot)


def pick_reference(segments: list[Segment], low: float, high: float) -> Segment | None:
    """The line to copy the speaker's voice from: the longest that is between `low` and `high`
    seconds, which is the most voice and the fewest cut words."""
    fit = [s for s in segments if low <= s.end - s.start <= high and len(s.source.split()) >= 3]
    return max(fit, key=lambda s: s.end - s.start) if fit else None


# ---- translating ------------------------------------------------------------------------------

TRANSLATE_SYSTEM = (
    "You translate the lines of a recording so they can be spoken aloud in {language}. Keep the "
    "meaning and the tone, write the way a person speaks, and keep each line about as long as the "
    "original: it has to fit the same time. Names stay as they are. Answer with a JSON array of "
    "strings, one for each line, in the same order, and nothing else."
)


def translation_messages(segments: list[Segment], language: str) -> list[dict[str, str]]:
    cps = CHARS_PER_SECOND.get(base(language), DEFAULT_CPS)
    lines = [
        {
            "n": i, "seconds": round(s.end - s.start, 1),
            "about_characters": max(8, round((s.end - s.start) * cps)), "text": s.source,
        }
        for i, s in enumerate(segments, 1)
    ]  # fmt: skip
    return [
        {"role": "system", "content": TRANSLATE_SYSTEM.format(language=language_name(language))},
        {"role": "user", "content": json.dumps(lines, ensure_ascii=False)},
    ]


def parse_translation(text: str, count: int) -> list[str] | None:
    """The lines of an answer, or None when it is not `count` lines (the caller asks again, line by
    line)."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    text = re.sub(r"^```[a-z]*\n|\n```$", "", text)
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return None
    try:
        items = json.loads(text[start : end + 1])
    except ValueError:
        return None
    if not isinstance(items, list) or len(items) != count:
        return None
    out = []
    for item in items:
        line = item.get("text") if isinstance(item, dict) else item
        if not isinstance(line, str) or not line.strip():
            return None
        out.append(" ".join(line.split()))
    return out


def single_message(segment: Segment, language: str) -> list[dict[str, str]]:
    """Ask for one line, when the whole script did not come back as lines."""
    cps = CHARS_PER_SECOND.get(base(language), DEFAULT_CPS)
    return [
        {
            "role": "system",
            "content": f"Translate the text into {language_name(language)} so it can be spoken "
            f"aloud in about {max(8, round((segment.end - segment.start) * cps))} characters. "
            "Answer with the translation only.",
        },
        {"role": "user", "content": segment.source},
    ]


def clean_line(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    return " ".join(text.strip().strip('"').split())[:MAX_SPEAK_CHARS]


# ---- ffmpeg -----------------------------------------------------------------------------------


def ffmpeg_path() -> str:
    tool = find_converter()
    if tool is None or tool[0] != "ffmpeg":
        raise DubError(
            "needs_ffmpeg", "Dubbing needs ffmpeg on this computer, to fit and mix the voices."
        )
    return tool[1]


async def _ffmpeg(args: list[str]) -> None:
    proc = await asyncio.create_subprocess_exec(
        ffmpeg_path(), "-nostdin", "-loglevel", "error", "-y", *args,
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )  # fmt: skip
    try:
        _, err = await asyncio.wait_for(proc.communicate(), 900)
    except TimeoutError:
        proc.kill()
        raise DubError("mix_failed", "The voices could not be mixed in time.") from None
    if proc.returncode != 0:
        raise DubError("mix_failed", "The voices could not be mixed. Try again.")


async def cut(source: Path, start: float, end: float, out: Path, rate: int = 24000) -> None:
    """A piece of a recording as mono WAV, for the model to copy a voice from."""
    await _ffmpeg(["-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(source), "-ac", "1",
                   "-ar", str(rate), "-c:a", "pcm_s16le", str(out)])  # fmt: skip


@dataclass(frozen=True)
class Placement:
    path: Path  # a spoken line, WAV
    start: float  # when it starts, in the recording
    tempo: float  # how much faster to play it


def mix_script(count: int, has_background: bool, placements: list[Placement], total: float) -> str:
    """The ffmpeg filter graph that puts each line at its time and mixes them over the background
    (or over silence). Input 0 is the background (or silence), the lines are inputs 1 to `count`."""
    parts = []
    names = ["[0:a]"]
    for i, p in enumerate(placements, 1):
        delay = max(0, round(p.start * 1000))
        tempo = f"atempo={p.tempo:.4f}," if p.tempo > 1.0001 else ""
        parts.append(
            f"[{i}:a]{tempo}aresample=44100,pan=stereo|c0=c0|c1=c0,adelay={delay}|{delay}[s{i}]"
        )
        names.append(f"[s{i}]")
    base_in = "[0:a]aresample=44100,aformat=channel_layouts=stereo[b]"
    parts.insert(0, base_in)
    names[0] = "[b]"
    parts.append(
        f"{''.join(names)}amix=inputs={count + 1}:normalize=0:duration=longest:"
        "dropout_transition=0,alimiter=limit=0.95[out]"
    )
    return ";\n".join(parts)


async def mix(
    background: Path | None, placements: list[Placement], total: float, out: Path
) -> bytes:
    """The dub as a 44.1 kHz stereo WAV: every line at its time over the background."""
    if not placements:
        raise DubError("script_required", "There is no line to mix.")
    with tempfile.TemporaryDirectory(prefix="dub-mix-") as tmp:
        script = Path(tmp) / "graph.txt"
        await asyncio.to_thread(
            script.write_text,
            mix_script(len(placements), background is not None, placements, total),
        )
        silence = ["-f", "lavfi", "-t", f"{total + TAIL_S:.3f}", "-i", "anullsrc=r=44100:cl=stereo"]
        first = ["-i", str(background)] if background is not None else silence
        args = [*first]
        for p in placements:
            args += ["-i", str(p.path)]
        args += ["-filter_complex_script", str(script), "-map", "[out]", "-ar", "44100",
                 "-c:a", "pcm_s16le", str(out)]  # fmt: skip
        await _ffmpeg(args)
    return await asyncio.to_thread(out.read_bytes)
