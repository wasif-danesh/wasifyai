"""People (ADR-0108 decisions 11 and 12, stage MT3): the voices Meetings knows.

When a person names a speaker of a meeting, the speaker becomes that person and their voiceprint is
kept as evidence of the person's voice. In a later meeting a speaker whose voice is close to a
person's is **suggested** as them; a person always confirms. Nothing is named alone: in spike MT0b
even the best voiceprint model named one person in four wrong from a room microphone.

The rules follow StenographAI's `speaker_suggestions.py` (MIT, notice in `NOTICE`), which learnt
them
on real meetings:

- evidence is kept by **how it was recorded** (`in_person`: the microphone of a recording made in
the
  app; `remote`: the computer's sound, the people on a call; `imported`: a file), and a speaker is
  compared with the same kind first, since people sharing a room and a microphone sound alike;
- **"not this person" is remembered**: when a meeting has two named people, each is evidence against
  the other, and "No" to a suggestion is evidence against that person. A suggestion is withheld when
  the speaker is as close to a person's "not them" evidence as to their voice;
- the best person must be clearly better than the next (a margin), or nothing is suggested;
- a suggestion is **likely** only with enough speech (20 s in 3 turns of 1.55 s on average),
evidence
  of the same kind, from two meetings or more; otherwise it is **possible**.

The distances are cosine distances (1 - cosine) between unit voiceprints. ERes2Net in MT0b: the same
person across meetings about 0.30 to 0.34, different people about 0.7 to 0.8 (MT3 measures it again
on
the app's own speakers, `docs/spikes/meetings-mt3.md`)."""

import base64
import wave
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from wasifyai_meetings.store import MeetingStore, NotFound
from wasifyai_meetings.voiceprint import SR, Voiceprints

THRESHOLD = 0.40  # a person's voice must be at least this close
MARGIN = 0.10  # ... and this much closer than the next person's
NOT_THRESHOLD = 0.40  # "not them" evidence this close withholds the suggestion
MIN_SECONDS = 20.0
MIN_TURNS = 3
MIN_AVG_TURN_S = 1.55
MIN_MEETINGS = 2
MIN_TURN_S = 0.8  # a stretch shorter than this is left out of a voiceprint
KINDS = ("in_person", "remote", "imported")


def pack(v: np.ndarray) -> str:
    return base64.b64encode(np.asarray(v, dtype="<f4").tobytes()).decode()


def unpack(s: str) -> np.ndarray | None:
    if not s:
        return None
    return np.frombuffer(base64.b64decode(s), dtype="<f4")


def kind_of(source: str, key: str) -> str:
    """How a speaker was recorded: in the app, the microphone (S1) is in the room and the rest are
    on the call; a file is imported."""
    if source == "recorded":
        return "in_person" if key == "S1" else "remote"
    return "imported"


def solo_spans(lines: Sequence[dict[str, Any]], key: str) -> list[tuple[float, float]]:
    """Where `key` speaks and nobody else does: their lines that no other speaker's line
    overlaps."""
    others = [(x["start"], x["end"]) for x in lines if x["speaker"] != key]
    out = []
    for x in lines:
        if x["speaker"] != key or x["end"] - x["start"] < MIN_TURN_S:
            continue
        if any(a < x["end"] and b > x["start"] for a, b in others):
            continue
        out.append((float(x["start"]), float(x["end"])))
    return out


def _read(path: Path, spans: Sequence[tuple[float, float]]) -> np.ndarray:
    """The stretches of a 16 kHz one-channel WAV, joined, as float -1 to 1 (read where they are,
    not the whole file)."""
    parts = []
    with wave.open(str(path), "rb") as w:
        n = w.getnframes()
        for a, b in spans:
            start = max(0, int(a * SR))
            stop = min(n, int(b * SR))
            if stop <= start:
                continue
            w.setpos(start)
            raw = np.frombuffer(w.readframes(stop - start), dtype="<i2")
            parts.append(raw.astype(np.float32) / 32768.0)
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)


def make_prints(
    voices: Voiceprints, wav_of: dict[str, Path], fallback: Path,
    lines: Sequence[dict[str, Any]], speakers: Sequence[dict[str, Any]], source: str,
) -> list[dict[str, Any]]:  # fmt: skip
    """One voiceprint per speaker, from where they speak alone (longest stretches first, up to 30
    s),
    read from `wav_of[key]` (a recording's own channel) or else `fallback`."""
    out = []
    for s in speakers:
        key = s["key"]
        spans = solo_spans(lines, key)
        if not spans:
            continue
        seconds = sum(b - a for a, b in spans)
        longest = sorted(spans, key=lambda ab: ab[0] - ab[1])
        chosen, total = [], 0.0
        for a, b in longest:
            chosen.append((a, b))
            total += b - a
            if total >= 30.0:
                break
        vec = voices.of(_read(wav_of.get(key, fallback), chosen))
        if vec is None:
            continue
        out.append({
            "speaker": key, "kind": kind_of(source, key), "vector": pack(vec),
            "seconds": round(seconds, 1), "turns": len(spans),
        })  # fmt: skip
    return out


# ---- naming -----------------------------------------------------------------------------------


def name_speaker(
    store: MeetingStore, tenant: str, user: str, item: str, key: str, name: str,
    person_id: str | None = None,
) -> dict[str, Any]:  # fmt: skip
    """Name a speaker of a meeting: they become a person (one with that name, `person_id`, or a new
    one) and the speaker's voice is kept as theirs; the other named people of the meeting are kept
    as evidence that they are not this person, and the other way round. An empty name (and no
    `person_id`) gives the speaker back their "Speaker N" and forgets what naming them added."""
    row = store.get(tenant, user, item)
    speakers = row["speakers"]
    hit = next((s for s in speakers if s["key"] == key), None)
    if hit is None:
        raise NotFound(key)
    old = hit.get("person_id")
    if old:
        store.drop_evidence(tenant, user, item, speaker=key)
        store.drop_evidence(tenant, user, item, person=old, reasons=("confirmed",))
    name = name.strip()
    if not name and person_id is None:
        hit["name"] = hit["default"]
        hit.pop("person_id", None)
        store.set_speakers(tenant, user, item, speakers)
        return store.get(tenant, user, item)

    if person_id is not None:
        person = store.person(tenant, user, person_id)
    else:
        person = store.person_named(tenant, user, name) or store.add_person(tenant, user, name)
    hit["name"] = person["name"]
    hit["person_id"] = person["id"]
    hit["not"] = [p for p in hit.get("not", []) if p != person["id"]]
    prints = store.prints_of(tenant, user, item)
    mine = prints.get(key)
    kind = mine["kind"] if mine else kind_of(row.get("source", "file"), key)
    store.add_evidence(
        tenant, user, person=person["id"], item=item, speaker=key, reason="voice", kind=kind,
        vector=mine["vector"] if mine else "",
    )  # fmt: skip
    for other in speakers:
        theirs = other.get("person_id")
        if other["key"] == key or not theirs or theirs == person["id"]:
            continue
        if mine:  # this voice is not theirs
            store.add_evidence(
                tenant, user, person=theirs, item=item, speaker=key, reason="confirmed",
                kind=mine["kind"], vector=mine["vector"],
            )  # fmt: skip
        their_print = prints.get(other["key"])
        if their_print:  # and theirs is not this person's
            store.add_evidence(
                tenant, user, person=person["id"], item=item, speaker=other["key"],
                reason="confirmed", kind=their_print["kind"], vector=their_print["vector"],
            )  # fmt: skip
    store.set_speakers(tenant, user, item, speakers)
    return store.get(tenant, user, item)


def not_this_person(
    store: MeetingStore, tenant: str, user: str, item: str, key: str, person_id: str
) -> dict[str, Any]:
    """ "No" to a suggestion: the speaker is not `person_id`; it is not suggested again here, and
    the
    voice counts against that person in later meetings."""
    row = store.get(tenant, user, item)
    store.person(tenant, user, person_id)
    speakers = row["speakers"]
    hit = next((s for s in speakers if s["key"] == key), None)
    if hit is None:
        raise NotFound(key)
    if person_id not in hit.get("not", []):
        hit["not"] = [*hit.get("not", []), person_id]
    mine = store.prints_of(tenant, user, item).get(key)
    store.add_evidence(
        tenant, user, person=person_id, item=item, speaker=key, reason="rejected",
        kind=mine["kind"] if mine else kind_of(row.get("source", "file"), key),
        vector=mine["vector"] if mine else "",
    )  # fmt: skip
    store.set_speakers(tenant, user, item, speakers)
    return store.get(tenant, user, item)


def rename_person(store: MeetingStore, tenant: str, user: str, pid: str, name: str) -> list[str]:
    """A new name for a person, in every meeting they were named in; the meetings changed."""
    store.rename_person(tenant, user, pid, name)
    person = store.person(tenant, user, pid)
    changed = []
    for row in store.with_person(tenant, user, pid):
        hits = [s for s in row["speakers"] if s.get("person_id") == pid]
        for s in hits:
            s["name"] = person["name"]
        if hits:
            store.set_speakers(tenant, user, row["id"], row["speakers"])
            changed.append(row["id"])
    return changed


def forget_person(store: MeetingStore, tenant: str, user: str, pid: str) -> list[str]:
    """Delete a person and every voiceprint and piece of evidence about them. The meetings keep the
    name as words (a transcript is not changed); the speakers are no longer that person. The
    meetings changed."""
    store.person(tenant, user, pid)
    changed = []
    for row in store.with_person(tenant, user, pid):
        touched = False
        for s in row["speakers"]:
            if s.get("person_id") == pid:
                s.pop("person_id")
                touched = True
            if pid in s.get("not", []):
                s["not"] = [p for p in s["not"] if p != pid]
                touched = True
        if touched:
            store.set_speakers(tenant, user, row["id"], row["speakers"])
            changed.append(row["id"])
    store.delete_person(tenant, user, pid)
    return changed


# ---- suggesting -------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Ev:
    person: str
    meeting: str
    reason: str
    kind: str
    vector: np.ndarray | None


def _stable(p: dict[str, Any]) -> bool:
    turns = int(p["turns"])
    return (
        p["seconds"] >= MIN_SECONDS
        and turns >= MIN_TURNS
        and p["seconds"] / turns >= MIN_AVG_TURN_S
    )


def suggest(
    item: str, speakers: Sequence[dict[str, Any]], prints: dict[str, dict[str, Any]],
    people: dict[str, str], evidence: Sequence[dict[str, Any]],
) -> dict[str, dict[str, Any]]:  # fmt: skip
    """Who each unnamed speaker of meeting `item` may be: `{key: {person_id, name, status,
    distance}}` (`status` "likely" or "possible"). Only speakers with a voiceprint; never a person
    already named in this meeting or said not to be this speaker."""
    ev = [
        _Ev(e["person_id"], e["meeting_id"], e["reason"], e["kind"], unpack(e["vector"]))
        for e in evidence
    ]
    taken = {s["person_id"] for s in speakers if s.get("person_id")}
    out: dict[str, dict[str, Any]] = {}
    for s in speakers:
        p = prints.get(s["key"])
        if s.get("person_id") or p is None:
            continue
        mine = unpack(p["vector"])
        if mine is None:
            continue
        refused = set(s.get("not", []))
        found = []
        for pid in people:
            if pid in taken or pid in refused:
                continue
            voice = [
                e for e in ev
                if e.person == pid and e.reason == "voice" and e.vector is not None
                and e.meeting != item
            ]  # fmt: skip
            if not voice:
                continue
            same = [e for e in voice if e.kind == p["kind"]]
            near = min(
                float(1 - (e.vector @ mine)) for e in (same or voice) if e.vector is not None
            )
            against = [
                float(1 - (e.vector @ mine))
                for e in ev
                if e.person == pid and e.reason != "voice" and e.vector is not None
            ]
            if against and min(against) < NOT_THRESHOLD and min(against) <= near + MARGIN:
                continue
            if near < THRESHOLD:
                found.append((near, pid, bool(same), len({e.meeting for e in voice})))
        if not found:
            continue
        found.sort()
        best = found[0]
        if len(found) > 1 and found[1][0] - best[0] < MARGIN:
            continue
        likely = best[2] and best[3] >= MIN_MEETINGS and _stable(p)
        out[s["key"]] = {
            "person_id": best[1], "name": people[best[1]],
            "status": "likely" if likely else "possible", "distance": round(best[0], 3),
        }  # fmt: skip
    return out


def with_suggestions(
    store: MeetingStore, tenant: str, user: str, row: dict[str, Any]
) -> dict[str, Any]:
    """The meeting with each speaker's `suggestion` (None when there is none)."""
    people = {p["id"]: p["name"] for p in store.people(tenant, user)}
    found: dict[str, dict[str, Any]] = {}
    if people and row.get("status") == "done":
        prints = store.prints_of(tenant, user, row["id"])
        if prints:
            found = suggest(
                row["id"], row["speakers"], prints, people, store.evidence(tenant, user)
            )
    for s in row["speakers"]:
        s["suggestion"] = found.get(s["key"])
    return row


__all__ = [
    "THRESHOLD", "forget_person", "kind_of", "make_prints", "name_speaker", "not_this_person",
    "pack", "rename_person", "solo_spans", "suggest", "unpack", "with_suggestions",
]  # fmt: skip
