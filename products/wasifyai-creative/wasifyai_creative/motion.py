# ruff: noqa: E501  (prose and test data are easier to read on one line)
"""Motion (ADR-0090 decision 6, stage CS4): pure functions for the clips. A clip is the video product's Animate on the shot's
still, at the draft setting (quick and soft, to see the motion) or the final one (sharp, about four times as long). The
draft excerpt is a stretch of about 30 seconds, the song's loudest part unless the person picks another start; Make it
better animates the shots the plan marks Animate. The time is a range from what CS0 measured until clips have been made
on this computer, and from those after the first one."""

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
    """The shots Make it better animates: those the plan marks Animate. Sing waits for lip sync (CS5)."""
    return [s["id"] for s in shots if s["motion"] == "Animate"]


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
    """Whether the shot already has an up-to-date clip at this setting or a better one: going on skips it."""
    wanted = (DRAFT, FINAL) if quality == DRAFT else (FINAL,)
    return any(
        t["shot_id"] == shot
        and t["kind"] == "video"
        and t["mode"] in wanted
        and t["inputs"] == inputs
        for t in takes
    )


def measured(takes: list[dict[str, Any]], quality: str) -> float | None:
    """How long a clip at this setting takes on this computer, once one has been made."""
    made = [
        t["seconds"]
        for t in takes
        if t["kind"] == "video" and t["mode"] == quality and t["seconds"]
    ][-12:]
    return sum(made) / len(made) if made else None


def estimate(count: int, quality: str, seen: float | None, free: int) -> dict[str, Any]:
    """What making these clips will take, in a range, and whether they fit on the disk."""
    low, high = SECONDS[quality]
    if seen:  # corrected after the first clip
        low, high = seen * 0.85, seen * 1.15
    need = count * CLIP_BYTES[quality]
    fit = "fits" if free >= need + 5 * 2**30 else "tight" if free >= need + 2**30 else "too_big"
    return {
        "seconds_low": round(count * low), "seconds_high": round(count * high), "bytes": need,
        "free_bytes": free, "fit": fit, "measured": bool(seen),
    }  # fmt: skip
