# ruff: noqa: E501  (the sentences shown to people, and made-up media in a test, are easier to read on one line)
"""What can be taught, and how: the base models and the methods the person may choose (ADR-0073,
amendment 2026-10-24).

An engine is a descriptor, not a screen. Each descriptor names a family of models, the base models
it can teach, the engine that does it and which methods that engine supports; a method it does not
support is listed with the reason, never hidden. A model on this computer that has no descriptor is
shown as "cannot be taught yet", never offered. The app still recommends (the first base, LoRA) and
the choice is optional: a run that names neither uses the recommendation."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from wasifyai_training import trainer

FAMILY_FOR_KIND = {
    "character": "image",
    "style": "image",
    "object": "image",
    "writing": "language",
    "decision": "decision",
}
VIDEO = "video"  # the family of a set made for the video model (its kinds are the picture kinds)

# id, the words, the technical name, Advanced only
METHODS = (
    ("lora", "Small adapter", "LoRA", False),
    ("qlora", "Small adapter, less memory", "QLoRA", False),
    ("full", "Teach all of it", "full fine-tuning", True),
)
DEFAULT_METHOD = "lora"


@dataclass(frozen=True)
class Descriptor:
    id: str
    title: str
    family: str
    engine: str
    methods_not: dict[str, str] = field(
        default_factory=dict
    )  # method -> why it cannot be used here
    default_method: str = "lora"
    seconds_per_step: float = 1.0  # measured: training only, a step of batch 2
    overhead_s: float = 10.0  # measured: the rest of a run (loading, asking before and after)
    architecture: str = ""  # what llama.cpp calls it, for serving an adapter on top of it
    need_gb: float = 0.0  # the memory a run held when measured, rounded up; 0 = see the engine
    note: str = ""  # one sentence on what it is good for, shown beside it
    measured: str = ""  # what a real run measured, for the card; empty = not measured


DESCRIPTORS = (
    Descriptor(
        id=trainer.BASE,
        title=trainer.BASE_TITLE,
        family="image",
        engine="mflux",
        methods_not={
            "qlora": "Pictures are taught as a small adapter. The less-memory version is for "
            "writing models.",
            "full": "Teaching all of a picture model needs far more memory than a Mac has, and the "
            "picture trainer does not do it.",
        },
    ),
    Descriptor(
        id="qwen3-0.6b-4bit",
        title="Qwen3 0.6B",
        family="language",
        engine="mlx-lm",
        default_method="qlora",
        need_gb=1.5,
        architecture="qwen3",
        seconds_per_step=0.113,
        overhead_s=6.3,
        note="Small and quick: it picks up a style or a format, not new facts.",
        measured="69 steps in 8 s, 1.3 GB, the whole run 14 s, on a 64 GB Mac (2026-10-26)",
        methods_not={
            "lora": "This model is kept in 4-bit form, so it is taught the less-memory way "
            "(QLoRA).",
            "full": "Teaching all of a writing model needs an NVIDIA graphics card for now.",
        },
    ),
    Descriptor(
        id="qwen3-1.7b-4bit",
        title="Qwen3 1.7B",
        family="language",
        engine="mlx-lm",
        default_method="qlora",
        note="A step up: better at keeping to a style, still not for facts.",
        measured="69 steps in 13 s, 2.0 GB, the whole run 21 s, on a 64 GB Mac (2026-10-26)",
        need_gb=2.0,
        seconds_per_step=0.184,
        overhead_s=8.0,
        architecture="qwen3",
        methods_not={
            "lora": "This model is kept in 4-bit form, so it is taught the less-memory way "
            "(QLoRA).",
            "full": "Teaching all of a writing model needs an NVIDIA graphics card for now.",
        },
    ),
    Descriptor(
        id="qwen3-4b-4bit",
        title="Qwen3 4B",
        family="language",
        engine="mlx-lm",
        default_method="qlora",
        note="The best of these at following a style and a format; slower to teach.",
        measured="69 steps in 19 s, 3.8 GB, the whole run 30 s, on a 64 GB Mac (2026-10-26)",
        need_gb=4.0,
        seconds_per_step=0.281,
        overhead_s=10.3,
        architecture="qwen3",
        methods_not={
            "lora": "This model is kept in 4-bit form, so it is taught the less-memory way "
            "(QLoRA).",
            "full": "Teaching all of a writing model needs an NVIDIA graphics card for now.",
        },
    ),
)

_WHOLE = {
    "lora": "This model is small, so all of it is taught. It is not taught as a small adapter.",
    "qlora": "This model is small, so all of it is taught. It is not taught as a small adapter.",
}
DESCRIPTORS += (
    Descriptor(
        id="ltx-video-2b",
        title="LTX-Video 2B (0.9.5)",
        family="video",
        engine="diffusers",
        default_method="lora",
        need_gb=12.0,
        note="The model Video makes clips with. It learns a look, a motion or a subject from pictures and short clips.",
        measured="pictures: 0.5 s a step and 7.4 GB; clips of 25 frames at 768x512: 7.7 s a step and 9.8 GB, on a 64 GB Mac (2026-10-26)",
        methods_not={
            "qlora": "This model is taught as a small adapter. The less-memory version is for writing models.",
            "full": "Teaching all of a video model needs far more memory than a Mac has, and the video trainer does not do it.",
        },
    ),
    Descriptor(
        id="laya-english",
        title="Laya",
        family="decision",
        engine="laya",
        default_method="full",
        need_gb=12.0,
        seconds_per_step=0.85,
        overhead_s=10.0,
        note="Reads English texts and answers with how sure it is. Small and quick.",
        measured="36 steps in 33 s, 11 GB, the whole run 41 s, on a 64 GB Mac (2026-10-26)",
        methods_not=_WHOLE,
    ),
    Descriptor(
        id="laya-multilingual",
        title="Laya (many languages)",
        family="decision",
        engine="laya",
        default_method="full",
        need_gb=10.0,
        seconds_per_step=0.7,
        overhead_s=6.0,
        note="For texts in more than 100 languages. A little slower to read long texts.",
        measured="24 steps in 18 s, 9.3 GB, the whole run 22 s, on a 64 GB Mac (2026-10-26)",
        methods_not=_WHOLE,
    ),
)


class Unavailable(ValueError):
    """The base or the method asked for cannot be used; `str(e)` says why, in words."""


def descriptor(base: str) -> Descriptor | None:
    return next((d for d in DESCRIPTORS if d.id == base), None)


def descriptors(family: str) -> list[Descriptor]:
    return [d for d in DESCRIPTORS if d.family == family]


def method_rows(d: Descriptor) -> list[dict[str, Any]]:
    return [
        {
            "id": m, "title": title, "technical": tech, "advanced": advanced,
            "can": m not in d.methods_not, "reason": d.methods_not.get(m, ""),
        }
        for m, title, tech, advanced in METHODS
    ]  # fmt: skip


def choices(
    kind: str,
    fit: dict[str, Any] | Callable[[Descriptor], dict[str, Any] | None] | None,
    ready: bool,
    installed: list[dict[str, Any]],
    have: Callable[[Descriptor], bool] | None = None,
    family: str | None = None,
) -> dict[str, Any]:
    """The rows of the "Choose the model and method" panel for a kind of teaching.

    `fit` is the engine's verdict for this computer (or a function that gives it for a base),
    `ready` whether the engine is set up, `have` whether a base is on this computer (a row that is
    not can still be chosen: the screen offers to get it) and `installed` the models found on this
    computer (`kind`, `name`, `format` at least)."""
    family = family or FAMILY_FOR_KIND.get(kind, "image")
    rows: list[dict[str, Any]] = []
    for d in descriptors(family):
        can, reason = True, ""
        verdict = fit(d) if callable(fit) else fit
        if not ready:
            can, reason = (
                False,
                "Set up training first: this model is taught by a tool that is not installed yet.",
            )
        elif verdict and verdict.get("verdict") == "too_big":
            can, reason = False, str(verdict.get("reason", ""))
        rows.append(
            {
                "id": d.id, "title": d.title, "engine": d.engine,
                "note": d.note, "measured": d.measured,
                "recommended": d is descriptors(family)[0], "can_teach": can, "reason": reason,
                "installed": ready and (have(d) if have else True), "methods": method_rows(d),
            }
        )  # fmt: skip
    known = {d.title.lower() for d in DESCRIPTORS}
    for item in installed[:8] if family == "image" else []:
        name = str(item.get("name", ""))
        if item.get("kind") != "diffusion" or name.lower() in known:
            continue
        rows.append(
            {
                "id": "", "title": name, "engine": "",
                "recommended": False, "can_teach": False, "installed": True,
                "reason": "This model cannot be taught yet: the app has no way to teach it.",
                "methods": [],
            }
        )  # fmt: skip
    return {
        "family": family,
        "default_base": rows[0]["id"] if rows else "",
        "default_method": descriptors(family)[0].default_method,
        "bases": rows,
    }


def resolve(
    kind: str, base: str | None, method: str | None, family: str | None = None
) -> tuple[Descriptor, str]:
    """The descriptor and method a run will use; `Unavailable` says why a choice cannot be used."""
    family = family or FAMILY_FOR_KIND.get(kind, "image")
    options = descriptors(family)
    chosen = options[0]
    if base:
        found = [d for d in options if d.id == base]
        if not found:
            raise Unavailable("This model cannot be taught yet. Choose another one.")
        chosen = found[0]
    use = method or chosen.default_method
    if use not in {m[0] for m in METHODS}:
        raise Unavailable("Choose a small adapter or teach all of it.")
    if use in chosen.methods_not:
        raise Unavailable(chosen.methods_not[use])
    return chosen, use
