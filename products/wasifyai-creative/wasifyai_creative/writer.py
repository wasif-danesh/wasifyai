# ruff: noqa: E501  (prose and test data are easier to read on one line)
"""Writing the plan (ADR-0090 decision 4). The model is small, so the code owns almost everything: the times, the
cast, the order of places, the camera and the motion. The model answers two questions under a schema: the story beats
for the whole song, then one sentence per shot, a part at a time (`docs/spikes/creative-cs0.md`).

Every answer is kept as a checkpoint under its own key, so a run that stopped goes on from the first part it does
not have. A bad sentence is asked for again a bounded number of times, then replaced by a plain row the person can
see is plain. Lyrics and ideas are data: they reach the model inside a prompt, and it can only answer with text."""

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from wasifyai_creative.document import ANIMATED_CAMERA, FRAMINGS
from wasifyai_creative.layout import Slot

GUIDE = (
    "You write one plain sentence per shot for a short video. Concrete: who, doing what, with which "
    "object, in which place. Only what can be seen: no thoughts, no style words, no camera words. "
    "Keep each thing the same from shot to shot. Follow the order of the story: nothing happens "
    "before its beat. Keep every sentence under 20 words. Never quote the song's words."
)
TRIES = 3  # asking for a whole step
REPAIRS = 2  # asking again for one bad sentence
SHOTS_PER_BEAT = 3
MIN_SENTENCE, MAX_SENTENCE = 25, 180
SENTENCE_END = re.compile(r"[.!?…。！？।॥][\"'”’)]*$")  # a sentence the length limit cut has none
# what reads as filler or cannot be shot, seen in the spike's plans
BAD_WORDS = (
    "the camera", "camera shows", "the shot", "the scene", "the frame", "beautiful", "cinematic",
    "thinking about", "while thinking", "dreaming of", "the essence", "a sense of", "symbolizing",
    "representing", "journey of",
)  # fmt: skip

Ask = Callable[[str, str, dict[str, Any]], Awaitable[str]]


class WriterFailed(Exception):
    """The model gave nothing usable for a step the plan cannot go without."""


def _schema_places(most: int) -> dict[str, Any]:
    item = {"type": "string", "minLength": 3, "maxLength": 40}
    return _object("places", {"type": "array", "minItems": 3, "maxItems": most, "items": item})


def _schema_beats(n: int, names: list[str]) -> dict[str, Any]:
    item = {
        "type": "object",
        "properties": {
            "what": {"type": "string", "minLength": 25, "maxLength": 140},
            "who": {"enum": [*names, ""]},
        },
        "required": ["what", "who"],
        "additionalProperties": False,
    }
    return _object("beats", {"type": "array", "minItems": n, "maxItems": n, "items": item})


def _schema_lines(n: int) -> dict[str, Any]:
    item = {"type": "string", "minLength": MIN_SENTENCE, "maxLength": MAX_SENTENCE}
    return _object("shots", {"type": "array", "minItems": n, "maxItems": n, "items": item})


def _object(key: str, value: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {key: value},
        "required": [key],
        "additionalProperties": False,
    }


def _parse(raw: str, key: str) -> Any:
    try:
        return json.loads(re.sub(r"^```(json)?|```$", "", raw.strip()).strip()).get(key)
    except (ValueError, AttributeError):
        return None


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[^\W\d_]{4,}", s.lower()))


def bad_sentence(text: str, seen: list[str]) -> bool:
    """Too short, filler, something that cannot be shot, or a near repeat of a shot already written."""
    low = text.lower()
    if len(text.strip()) < MIN_SENTENCE or any(w in low for w in BAD_WORDS):
        return True
    if len(text.strip()) >= MAX_SENTENCE - 1 and not SENTENCE_END.search(text.strip()):
        return True  # the length limit cut it
    mine = _tokens(text)
    for other in seen:
        theirs = _tokens(other)
        if low == other.lower():
            return True
        if mine | theirs and len(mine & theirs) / len(mine | theirs) > 0.7:
            return True
    return False


def line_at(lines: list[dict[str, Any]], start: float, end: float) -> str:
    """The typed line sung during this shot, when the lines have times."""
    for row in lines:
        if row.get("start") is not None and row["start"] < end and row["end"] > start:
            return str(row["text"])
    return ""


def _marks(person: dict[str, Any]) -> list[str]:
    """What names a person in a sentence: their name, or the end of a phrase of how they look, as a
    writer often says "the green jacket" for someone in one."""
    marks = [person["name"].lower()]
    for phrase in str(person.get("look") or "").lower().split(","):
        words = phrase.split()
        if len(words) >= 2:
            marks.append(" ".join(words[-2:]))
    return marks


def who_in(sentence: str, cast: list[dict[str, Any]]) -> list[str]:
    low = sentence.lower()
    return [
        p["name"] for p in cast if any(re.search(rf"\b{re.escape(m)}\b", low) for m in _marks(p))
    ]


def _head(brief: dict[str, Any]) -> str:
    people = []
    for p in brief.get("cast", []):
        said = f"{p['name']}: {p.get('look') or 'a person'}"
        people.append(
            said
            + (", seen only in photographs, never there in person" if p.get("photos_only") else "")
        )
    return f"Idea: {brief['idea']}\nCast: {'; '.join(people) or 'no people'}\n"


def _route(places: list[str], n: int) -> list[str]:
    """Which place each beat is in: every place gets used, in order."""
    return [places[min(i * len(places) // n, len(places) - 1)] for i in range(n)]


def part_of(slots: list[Slot], n: int) -> list[list[int]]:
    """Which slots belong to which beat, evenly."""
    per = len(slots) / n
    return [[i for i in range(len(slots)) if int(i / per) == b] for b in range(n)]


class PlanWriter:
    """One run of the writer. `saved` is what earlier runs of this plan already have, by step; `keep` saves a
    step as soon as it is done; `log` writes what was asked and what came back, for the planning log."""

    def __init__(
        self, ask: Ask, saved: dict[str, Any],
        keep: Callable[[str, Any], None], log: Callable[[str, str, str], None],
    ) -> None:  # fmt: skip
        self._ask, self._saved, self._keep, self._log = ask, saved, keep, log

    async def _call(self, step: str, prompt: str, schema: dict[str, Any], key: str) -> Any:
        raw = await self._ask(GUIDE, prompt, schema)
        self._log(step, prompt, raw)
        return _parse(raw, key)

    async def _step(
        self, step: str, prompt: str, schema: dict[str, Any], key: str, n: int | None
    ) -> Any:
        """A step's answer: the one kept from an earlier run, or asked now and kept."""
        if step in self._saved:
            return self._saved[step]
        for _ in range(TRIES):
            found = await self._call(step, prompt, schema, key)
            if isinstance(found, list) and found and (n is None or len(found) == n):
                self._keep(step, found)
                self._saved[step] = found
                return found
        return None

    async def places(self, brief: dict[str, Any]) -> list[str]:
        given = [p for p in brief.get("places", []) if p.strip()]
        if given:
            return given
        found = await self._step(
            "places",
            _head(brief) + "\nName 3 to 5 places where this video happens, in the order they appear. "
            "Short and concrete, like 'wet alley' or 'red barn'.",
            _schema_places(5), "places", None,
        )  # fmt: skip
        if not found:
            raise WriterFailed("The model could not suggest places. Name them in the brief.")
        return [str(p) for p in found]

    async def beats(self, brief: dict[str, Any], route: list[str]) -> list[dict[str, Any]]:
        want = "\n".join(f"{i + 1}. in {p}" for i, p in enumerate(route))
        n = len(route)
        found = await self._step(
            "beats",
            _head(brief) + f"\nWrite {n} story beats in order, each a different event that moves "
            f"things on, one in each of these places:\n{want}",
            _schema_beats(n, [p["name"] for p in brief.get("cast", [])]), "beats", n,
        )  # fmt: skip
        if found is None:
            return [
                {"what": brief["idea"], "who": ""} for _ in route
            ]  # the shots still get written
        return found

    async def _sentence_again(
        self, head: str, place: str, beat: str, looks_at: str, seen: list[str], step: str
    ) -> str:
        prompt = (
            head + f"\nThis beat, in {place}: {beat}\nThis shot looks at: {looks_at}. These are "
            f"taken: {json.dumps(seen[-5:], ensure_ascii=False)}. Write one new sentence."
        )
        found = await self._call(step, prompt, _schema_lines(1), "shots")
        return str(found[0]) if isinstance(found, list) and found else ""

    async def part(
        self, brief: dict[str, Any], key: str, place: str, beat: str, rows: list[dict[str, Any]], seen: list[str],
    ) -> list[dict[str, Any]]:  # fmt: skip
        """The sentences of one beat, with the marks of what was repaired or fell back."""
        if key in self._saved:
            return self._saved[key]
        head = _head(brief)
        ask = "\n".join(
            f"{k + 1}. looks at: {r['looks_at']}"
            + (
                f" (the song says here, for the mood only, not to be quoted: {r['line']})"
                if r["line"]
                else ""
            )
            for k, r in enumerate(rows)
        )
        before = "\n".join(f"- {s}" for s in seen[-3:]) or "(none)"
        said = await self._call(
            key,
            head + f"\nThis beat, in {place}: {beat}\nAlready shown, do not repeat:\n{before}\n\n"
            f"Write {len(rows)} different shots of this beat:\n{ask}",
            _schema_lines(len(rows)), "shots",
        )  # fmt: skip
        said = said if isinstance(said, list) else []
        taken = list(seen)
        out: list[dict[str, Any]] = []
        for k, r in enumerate(rows):
            text = str(said[k]) if k < len(said) else ""
            tries = 0
            while bad_sentence(text, taken) and tries < REPAIRS:
                tries += 1
                text = await self._sentence_again(head, place, beat, r["looks_at"], taken, key)
            fallback = bad_sentence(text, taken)
            if fallback:
                text = f"{beat}"[:MAX_SENTENCE]
            taken.append(text)
            out.append(
                {"shows": text, "fallback": fallback, "repaired": bool(tries and not fallback)}
            )
        self._keep(key, out)
        self._saved[key] = out
        return out


async def write_plan(
    writer: PlanWriter,
    brief: dict[str, Any],
    slots: list[Slot],
    lines: list[dict[str, Any]],
    progress: Callable[[str, float], None] = lambda _s, _p: None,
) -> dict[str, Any]:
    """The whole plan: places, beats, then the shots a part at a time."""
    progress("Choosing the places", 0.02)
    places = await writer.places(brief)
    n = max(min(len(places) + 1, len(slots)), round(len(slots) / SHOTS_PER_BEAT), 1)
    n = min(n, len(slots))
    route = _route(places, n)
    progress("Writing the story", 0.08)
    beats = await writer.beats(brief, route)
    cast = brief.get("cast", [])
    shots: list[dict[str, Any]] = []
    seen: list[str] = []
    focus = 0
    parts = part_of(slots, n)
    for b, indexes in enumerate(parts):
        progress(f"Writing part {b + 1} of {n}", 0.1 + 0.9 * b / n)
        rows = []
        for i in indexes:
            camera, looks_at = FRAMINGS[focus % len(FRAMINGS)]
            focus += 1
            rows.append(
                {
                    "i": i, "camera": camera, "looks_at": looks_at,
                    "line": line_at(lines, slots[i].start, slots[i].end),
                }
            )  # fmt: skip
        written = await writer.part(brief, f"part-{b}", route[b], str(beats[b]["what"]), rows, seen)
        for r, w in zip(rows, written, strict=True):
            seen.append(w["shows"])
            slot = slots[r["i"]]
            shots.append(
                {
                    "id": f"s{r['i'] + 1}", "start": slot.start, "end": slot.end, "beat": b,
                    "shows": w["shows"], "who": who_in(w["shows"], cast), "place": route[b],
                    "camera": r["camera"], "line": r["line"], "note": "",
                    "motion": "Animate" if r["camera"] == ANIMATED_CAMERA else "Hold",
                    "fallback": w["fallback"],
                }
            )  # fmt: skip
    return {
        "places": places,
        "beats": [{**x, "place": route[i]} for i, x in enumerate(beats)],
        "shots": shots,
    }


async def rewrite_part(
    writer: PlanWriter, brief: dict[str, Any], plan: dict[str, Any], beat: int, key: str
) -> dict[str, Any]:
    """Try another idea for one part of the plan: only its sentences change."""
    mine = [s for s in plan["shots"] if s["beat"] == beat]
    if not mine:
        raise WriterFailed("That part of the plan is gone.")
    others = [s["shows"] for s in plan["shots"] if s["beat"] != beat]
    looks = dict(FRAMINGS)
    rows = [{"line": s["line"], "looks_at": looks.get(s["camera"], "the person")} for s in mine]
    what = plan["beats"][beat]["what"] if beat < len(plan.get("beats", [])) else brief["idea"]
    written = await writer.part(
        brief, key, mine[0]["place"], str(what), rows, others + [s["shows"] for s in mine]
    )
    cast = brief.get("cast", [])
    new = {s["id"]: w for s, w in zip(mine, written, strict=True)}
    return {
        **plan,
        "shots": [
            {**s, "shows": new[s["id"]]["shows"], "fallback": new[s["id"]]["fallback"],
             "who": who_in(new[s["id"]]["shows"], cast)}
            if s["id"] in new else s
            for s in plan["shots"]
        ],
    }  # fmt: skip
