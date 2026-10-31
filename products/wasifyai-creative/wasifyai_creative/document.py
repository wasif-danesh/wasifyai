# ruff: noqa: E501  (prose and test data are easier to read on one line)
"""The project's document (ADR-0090 decision 3): the brief, what was found in the song, and the plan. The plan holds
nothing about a model. Edits go through `apply_edits`, used by the screen, the assistant and MCP alike, and every
result is checked by `problems`."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Motion = Literal["Hold", "Animate", "Sing"]
SHOT_FIELDS = ("shows", "motion", "place", "camera", "note", "line")
# the framings the code hands out, each with what the writer is asked to look at (docs/spikes/creative-cs0.md)
FRAMINGS: tuple[tuple[str, str], ...] = (
    ("wide slow push in", "the whole place, with the person small in it, or the place alone"),
    ("medium slow pan", "the person doing one clear action"),
    ("close still", "one object or hands, in close up"),
    ("close slow push in", "the person's face and what they feel"),
    ("overhead still", "the place seen from above"),
    ("medium still", "the person together with something from the place"),
)
CAMERAS = tuple(c for c, _ in FRAMINGS)
ANIMATED_CAMERA = (
    "medium slow pan"  # about one shot in six moves; the rest are stills with a camera move
)


class EditRefused(Exception):
    """An edit that cannot be done, with the sentence the person is shown."""


class Person(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=60, description="What the person is called.")
    look: str = Field(
        "", max_length=240, description="How they look, words used again in every picture."
    )
    photos_only: bool = Field(
        False, description="They are only ever seen in photographs, never there in person."
    )


class Brief(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    track_id: str = Field(min_length=1, max_length=64, description="The song, from Your music.")
    idea: str = Field(
        min_length=3, max_length=600, description="What the video is about, in a line."
    )
    style: str = Field("", max_length=120, description="The look: warm film photo, for instance.")
    cast: list[Person] = Field(default_factory=list, max_length=8)
    places: list[str] = Field(
        default_factory=list,
        max_length=12,
        description="Where it happens; left empty, the writer chooses.",
    )
    lyrics: str | None = Field(
        None,
        max_length=20000,
        description="The words of the song; left out, those it was made with.",
    )
    shape: Literal["landscape", "portrait", "square"] = "landscape"
    cut_speed: int = Field(0, ge=-2, le=2, description="-2 few long shots, +2 many short ones.")


def problems(plan: dict[str, Any], cast: list[str], seconds: float) -> list[str]:
    """What is wrong with a plan, in words: the checks every plan and every edit must pass."""
    shots = plan.get("shots") or []
    if not shots:
        return ["The plan has no shots."]
    bad: list[str] = []
    if abs(shots[0]["start"]) > 0.01:
        bad.append("The first shot must start at the beginning of the song.")
    if abs(shots[-1]["end"] - seconds) > 0.1:
        bad.append("The last shot must end with the song.")
    for a, b in zip(shots, shots[1:], strict=False):
        if abs(a["end"] - b["start"]) > 0.01:
            bad.append(f"There is a gap or an overlap after shot {a['id']}.")
    for s in shots:
        if s["end"] <= s["start"]:
            bad.append(f"Shot {s['id']} has no length.")
        if not str(s["shows"]).strip():
            bad.append(f"Shot {s['id']} does not say what is seen.")
        unknown = [w for w in s["who"] if w not in cast]
        if unknown:
            bad.append(f"Shot {s['id']} has {unknown[0]}, who is not in the cast.")
        if s["motion"] == "Sing" and not (s["line"] and s["who"]):
            bad.append(f"Shot {s['id']} can only sing with a person and a line of the song.")
    return bad


def _at(shots: list[dict[str, Any]], shot_id: str) -> int:
    for i, s in enumerate(shots):
        if s["id"] == shot_id:
            return i
    raise EditRefused(f"There is no shot {shot_id} in this plan.")


def _next_id(shots: list[dict[str, Any]]) -> str:
    return f"s{max((int(s['id'][1:]) for s in shots), default=0) + 1}"


def _move_cut(shots: list[dict[str, Any]], i: int, by_beats: int, beats: list[float]) -> None:
    """Move the cut at the end of shot `i` by whole beats. It stays on a beat and inside its neighbours."""
    if i >= len(shots) - 1:
        raise EditRefused("The last shot ends with the song.")
    if not beats:
        raise EditRefused("The beats of this song are not known.")
    now = shots[i]["end"]
    nearest = min(range(len(beats)), key=lambda k: abs(beats[k] - now))
    target = beats[max(0, min(len(beats) - 1, nearest + by_beats))]
    if not shots[i]["start"] < target < shots[i + 1]["end"]:
        raise EditRefused("That would leave a shot with no length.")
    shots[i]["end"] = shots[i + 1]["start"] = target


def apply_edits(
    plan: dict[str, Any], edits: list[dict[str, Any]], beats: list[float]
) -> dict[str, Any]:
    """A new plan with the edits made, in order. Nothing is changed when one is refused."""
    shots = [dict(s) for s in plan["shots"]]
    for e in edits:
        op = e.get("op")
        if op == "set_shot":
            s = shots[_at(shots, str(e.get("shot_id")))]
            for key in SHOT_FIELDS:
                if key in e:
                    s[key] = e[key]
            if "who" in e:
                s["who"] = list(e["who"])
            if "shows" in e or "who" in e:
                s["fallback"] = False
            if s["motion"] not in ("Hold", "Animate", "Sing"):
                raise EditRefused("A shot holds, animates or sings.")
        elif op == "delete_shot":
            if len(shots) == 1:
                raise EditRefused("A plan needs at least one shot.")
            i = _at(shots, str(e.get("shot_id")))
            gone = shots.pop(i)
            if i:  # the shot before grows to cover the time; the first shot's goes to the next
                shots[i - 1]["end"] = gone["end"]
            else:
                shots[0]["start"] = gone["start"]
        elif op == "add_shot":
            i = _at(shots, str(e.get("after")))
            s = shots[i]
            inside = [t for t in beats if s["start"] < t < s["end"]]
            middle = (s["start"] + s["end"]) / 2
            at = min(inside, key=lambda t: abs(t - middle)) if inside else round(middle, 3)
            new = {
                **s, "id": _next_id(shots), "start": at, "end": s["end"], "fallback": False,
                "shows": str(e.get("shows") or s["shows"]), "note": "",
            }  # fmt: skip
            s["end"] = at
            shots.insert(i + 1, new)
        elif op == "move_cut":
            _move_cut(shots, _at(shots, str(e.get("shot_id"))), int(e.get("by_beats", 0)), beats)
        else:
            raise EditRefused(f"Unknown change: {op}.")
    return {**plan, "shots": shots}


def index_words(
    title: str, brief: dict[str, Any], plan: dict[str, Any] | None, lyrics: str
) -> list[str]:
    """What search finds a project by (ADR-0041): its title, idea, cast, places, shots and lyrics."""
    cast = [f"{p['name']} {p.get('look', '')}" for p in brief.get("cast", [])]
    shots = [s["shows"] for s in (plan or {}).get("shots", [])]
    places = (plan or {}).get("places") or brief.get("places", [])
    return [title, brief.get("idea", ""), brief.get("style", ""), *cast, *places, *shots, lyrics]
