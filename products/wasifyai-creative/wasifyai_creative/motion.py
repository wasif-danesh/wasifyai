# ruff: noqa: E501  (prose and test data are easier to read on one line)
"""Motion (ADR-0090 decision 6, stage CS4): pure functions for the clips. A clip is the video product's Animate on the shot's
still, at the draft setting (quick and soft, to see the motion) or the final one (sharp, about four times as long). The
draft excerpt is a stretch of about 30 seconds, the song's loudest part unless the person picks another start; Make it
better animates the shots the plan marks Animate. The time is a range from what CS0 measured until clips have been made
on this computer, and from those after the first one.

A shot marked Sing (CS5) is lip sync instead: the voice product makes the face of its still sing the part of the song the
shot covers, so the mouth matches the song when the cut lays the song over it. Lip sync has one setting, used in a draft
and in Make it better alike; its time goes with the length sung."""

from typing import Any

from wasifyai_creative import stills

DRAFT, FINAL = "draft", "final"
QUALITIES = (DRAFT, FINAL)
EXCERPT_S = 30.0
CLIP_S = 5  # the video product's shortest clip; a shorter shot uses the start of it (docs/spikes/creative-cs0.md)
MAX_PROMPT = 500  # the video product's limit
# what CS0 measured on this Mac for a 5 s clip, seconds: draft 48 to 50, final 142 to 192
SECONDS = {DRAFT: (45.0, 60.0), FINAL: (140.0, 200.0)}
CLIP_BYTES = {DRAFT: 2 * 1024 * 1024, FINAL: 4 * 1024 * 1024}
SING = "sing"
# CS0: 20 s sung on the full mix took 134 s on this Mac, so about 7 s of work a second sung, and the model loads first
SING_RATE = (6.0, 8.0)
SING_LOAD_S = 15.0
SING_BYTES_A_SECOND = 400 * 1024
MOVES = {
    "push": "The camera slowly pushes in.",
    "pan": "The camera pans slowly.",
    "still": "The camera stays still.",
}


def loudest_start(sections: list[dict[str, Any]]) -> float:
    """Where the song's loudest part starts: the place to see the motion first."""
    if not sections:
        return 0.0
    rank = {"high": 2, "mid": 1, "low": 0}
    best = max(
        sections, key=lambda s: (float(s.get("energy") or 0), rank.get(str(s.get("label")), 0))
    )
    return float(best["start"])


def excerpt(shots: list[dict[str, Any]], start: float, length: float = EXCERPT_S) -> list[str]:
    """The whole shots of a stretch: from the shot playing at `start`, until the stretch is at least `length` long. Near the
    end of the song it reaches back, so it is as long as it can be."""
    if not shots:
        return []
    first = next((n for n, s in enumerate(shots) if s["end"] > start), len(shots) - 1)
    last = first
    while last + 1 < len(shots) and shots[last]["end"] - shots[first]["start"] < length:
        last += 1
    while first > 0 and shots[last]["end"] - shots[first]["start"] < length:
        first -= 1
    return [s["id"] for s in shots[first : last + 1]]


def better(shots: list[dict[str, Any]]) -> list[str]:
    """The shots Make it better makes move: those the plan marks Animate, and those it marks Sing."""
    return [s["id"] for s in shots if s["motion"] in ("Animate", "Sing")]


def sings(shot: dict[str, Any]) -> bool:
    """A shot that is lip sync: marked Sing, with a person and a line of the song."""
    return shot.get("motion") == "Sing" and bool(shot.get("who")) and bool(shot.get("line"))


def sing_mark(shot: dict[str, Any], inputs: str) -> str:
    """What a sung clip depends on: the still's inputs and the part of the song."""
    return f"{inputs}|{shot['start']:.3f}-{shot['end']:.3f}"


def clip_prompt(shot: dict[str, Any], brief: dict[str, Any]) -> str:
    """What the clip is asked for: the picture in words, then how it moves. The model must be told what the picture shows,
    or it draws something else (the video product's own note)."""
    words = str(shot.get("camera", "")).split()
    move = next((MOVES[w] for w in words if w in MOVES), MOVES["still"])
    action = "Natural, gentle movement." if shot["motion"] != "Hold" else "Small, gentle movement."
    picture = stills.still_for(shot, brief, stills.PLAIN).prompt
    tail = f" {action} {move}"
    return f"{picture[: MAX_PROMPT - len(tail)].rstrip()}{tail}"


def source_of(
    takes: list[dict[str, Any]], chosen: dict[str, str], shot: str
) -> dict[str, Any] | None:
    """The still a clip starts from: the chosen one, or when a clip is chosen, the newest still of the shot."""
    mine = [t for t in takes if t["shot_id"] == shot]
    picked = next((t for t in mine if t["id"] == chosen.get(shot)), None)
    if picked and picked["kind"] == "image":
        return picked
    found = [t for t in mine if t["kind"] == "image"]
    return found[-1] if found else None


def has_clip(takes: list[dict[str, Any]], shot: str, quality: str, inputs: str) -> bool:
    """Whether the shot already has an up-to-date clip at this setting or a better one: going on skips it. A sung clip
    (its `inputs` from `sing_mark`) counts at every setting."""
    wanted = (DRAFT, FINAL) if quality == DRAFT else (FINAL,)
    return any(
        t["shot_id"] == shot
        and t["inputs"] == inputs
        and ((t["kind"] == "video" and t["mode"] in wanted) or t["kind"] == "lipsync")
        for t in takes
    )


def measured_sing(takes: list[dict[str, Any]], shots: dict[str, dict[str, Any]]) -> float | None:
    """Seconds of work a second sung, on this computer, once a shot has been sung."""
    rates = [
        t["seconds"] / (shots[t["shot_id"]]["end"] - shots[t["shot_id"]]["start"])
        for t in takes
        if t["kind"] == "lipsync" and t["seconds"] and t["shot_id"] in shots
    ][-12:]
    return sum(rates) / len(rates) if rates else None


def measured(takes: list[dict[str, Any]], quality: str) -> float | None:
    """How long a clip at this setting takes on this computer, once one has been made."""
    made = [
        t["seconds"]
        for t in takes
        if t["kind"] == "video" and t["mode"] == quality and t["seconds"]
    ][-12:]
    return sum(made) / len(made) if made else None


def estimate(
    count: int, quality: str, seen: float | None, free: int,
    sung: int = 0, sung_s: float = 0.0, sing_seen: float | None = None,
) -> dict[str, Any]:  # fmt: skip
    """What making these clips will take, in a range, and whether they fit on the disk. `sung` shots of `sung_s`
    seconds in all are lip sync."""
    low, high = SECONDS[quality]
    if seen:  # corrected after the first clip
        low, high = seen * 0.85, seen * 1.15
    rate_low, rate_high = (sing_seen * 0.85, sing_seen * 1.15) if sing_seen else SING_RATE
    load = SING_LOAD_S if sung and not sing_seen else 0.0
    need = count * CLIP_BYTES[quality] + int(sung_s * SING_BYTES_A_SECOND)
    fit = "fits" if free >= need + 5 * 2**30 else "tight" if free >= need + 2**30 else "too_big"
    return {
        "seconds_low": round(count * low + sung_s * rate_low + load),
        "seconds_high": round(count * high + sung_s * rate_high + load), "bytes": need,
        "free_bytes": free, "fit": fit, "measured": bool(seen or sing_seen), "sung": sung,
    }  # fmt: skip
