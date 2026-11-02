# ruff: noqa: E501  (prose and test data are easier to read on one line)
"""What a shot's still is asked for (ADR-0090 decision 10): pure functions from a shot and the brief. A person's look and
the fixed words of objects and places are repeated in every prompt, because they do not carry over by themselves (CS0).
Someone seen only in photos is never drawn as present. What the image product is asked for fits its limit of 500 characters,
so the words that matter most are kept when there are too many."""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

MAX_PROMPT = 500  # the image product's limit
SIZES = {"landscape": "wide", "portrait": "tall", "square": "square"}
PLAIN, REFERENCE = "plain", "reference"
FRAMING = {
    "wide": "Wide shot.",
    "medium": "Medium shot.",
    "close": "Close up.",
    "overhead": "Seen from above.",
}
# what CS0 measured on this Mac, seconds a still
SECONDS = {PLAIN: (14.0, 20.0), REFERENCE: (34.0, 42.0)}
STILL_BYTES = 3 * 1024 * 1024
PREVIEW_BYTES_A_SECOND = 500 * 1024
PORTRAITS = 2


@dataclass(frozen=True)
class Still:
    action: str
    params: dict[str, Any]
    prompt: str
    mode: str


def _named(name: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE) is not None


def _person(name: str, text: str) -> bool:
    """A person named in a sentence, also as Mira's or as the model's Miras."""
    return re.search(rf"\b{re.escape(name)}(?:['’]?s)?\b", text) is not None


def _cast(shot: dict[str, Any], brief: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Who is there in person in this shot, and who is seen only in photos."""
    cast = brief.get("cast") or []
    # the sentence counts too: a shot that says "Miras face" with nobody in `who` drew a stranger
    present = [
        p for p in cast
        if not p.get("photos_only") and (p["name"] in shot["who"] or _person(p["name"], shot["shows"]))
    ]  # fmt: skip
    return present, [p["name"] for p in cast if p.get("photos_only")]


def _fixed(shot: dict[str, Any], brief: dict[str, Any]) -> list[dict[str, str]]:
    """The fixed words of the things this shot names."""
    text = f"{shot['shows']} {shot['place']}"
    return [f for f in brief.get("fixed") or [] if _named(f["name"], text)]


def inputs_of(shot: dict[str, Any], brief: dict[str, Any]) -> str:
    """A mark of everything a still depends on: when it changes, a still made before is out of date."""
    present, _ = _cast(shot, brief)
    body = [
        shot["shows"], shot["place"], shot["camera"], brief.get("style", ""), brief.get("shape", ""),
        [[p["name"], p.get("look", ""), p.get("pictures") or []] for p in present],
        [[f["name"], f["words"]] for f in _fixed(shot, brief)],
    ]  # fmt: skip
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


def _fit(shows: str, pieces: list[str]) -> str:
    """What a shot shows, then as many of the other pieces as fit, in the order of their importance."""
    out = shows.strip()[:MAX_PROMPT]
    for piece in pieces:
        if piece and len(out) + 1 + len(piece) <= MAX_PROMPT:
            out = f"{out} {piece}"
    return out


def still_for(shot: dict[str, Any], brief: dict[str, Any], mode: str) -> Still:
    """The action and what to ask it. A shot with no person, or with nobody who has pictures, is plain."""
    present, photos = _cast(shot, brief)
    shows = shot["shows"]
    in_a_photo = re.search(r"\b(photo|photos|photograph|picture|album)\b", shows, re.IGNORECASE)
    for name in photos:
        shows = re.sub(
            rf"\b{re.escape(name)}\b", "someone" if in_a_photo else "someone in a photograph", shows
        )
    people = [f"{p['name']}: {p['look'][:160]}." for p in present if p.get("look")]
    place = f"Place: {shot['place']}." if shot.get("place") else ""
    frame = FRAMING.get(str(shot.get("camera", "")).split(" ")[0], "")
    fixed = [f"{f['name']}: {f['words'][:120]}." for f in _fixed(shot, brief)]
    style = f"{brief['style']}." if brief.get("style") else ""
    size = SIZES[brief.get("shape", "landscape")]
    pictured = [p for p in present if p.get("pictures")]
    if mode == REFERENCE and pictured:
        if len(pictured) == 1:
            found = pictured[0]["pictures"]
            ids = [found[0], found[1] if len(found) > 1 else found[0]]
            who = f"{pictured[0]['name']} is the person from the pictures, alone."
        else:
            ids = [pictured[0]["pictures"][0], pictured[1]["pictures"][0]]
            who = f"{pictured[0]['name']} is the person in picture 1 and {pictured[1]['name']} the person in picture 2."
        prompt = _fit(shows, [who, *people, place, frame, style, *fixed])
        return Still(
            "image.reference", {"image_ids": ids, "prompt": prompt, "size": size}, prompt, REFERENCE
        )
    prompt = _fit(shows, [*people, place, frame, style, *fixed])
    return Still("image.generate", {"prompt": prompt, "size": size}, prompt, PLAIN)


def portrait_prompts(person: dict[str, Any], style: str) -> list[str]:
    """Two pictures of a person, made first so that every shot starts from the same face."""
    end = f" {style}." if style else ""
    look = person["look"][:240]
    return [
        f"Portrait photo of {look}, looking at the camera, plain soft background.{end}"[
            :MAX_PROMPT
        ],
        f"Photo of {look}, head and shoulders, three quarter view, plain soft background.{end}"[
            :MAX_PROMPT
        ],
    ]


def needs_portraits(plan: dict[str, Any], brief: dict[str, Any]) -> list[dict[str, Any]]:
    """The people the plan shows in person who have words for how they look but no pictures yet."""
    seen = {name for s in plan["shots"] for name in s["who"]}
    return [
        p for p in brief.get("cast") or []
        if p["name"] in seen and not p.get("photos_only") and not p.get("pictures") and p.get("look")
    ]  # fmt: skip


def estimate(
    count: int, portraits: int, mode: str, measured: float | None, seconds: float, free: int
) -> dict[str, Any]:
    """What making these stills will take, in a range, and whether it fits on the disk."""
    low, high = SECONDS[mode]
    if measured:  # corrected after the first still
        low, high = measured * 0.85, measured * 1.15
    plain_low, plain_high = SECONDS[PLAIN]
    extra = portraits * PORTRAITS
    need = (count + extra) * STILL_BYTES + int(seconds * PREVIEW_BYTES_A_SECOND)
    fit = "fits" if free >= need + 5 * 2**30 else "tight" if free >= need + 2**30 else "too_big"
    return {
        "seconds_low": round(count * low + extra * plain_low),
        "seconds_high": round(count * high + extra * plain_high),
        "bytes": need,
        "free_bytes": free,
        "fit": fit,
        "measured": bool(measured),
    }
