"""What can be taught, and how: the base models and the methods the person may choose (ADR-0073,
amendment 2026-10-24).

An engine is a descriptor, not a screen. Each descriptor names a family of models, the base models
it can teach, the engine that does it and which methods that engine supports; a method it does not
support is listed with the reason, never hidden. A model on this computer that has no descriptor is
shown as "cannot be taught yet", never offered. The app still recommends (the first base, LoRA) and
the choice is optional: a run that names neither uses the recommendation."""

from dataclasses import dataclass, field
from typing import Any

from wasifyai_training import trainer

FAMILY_FOR_KIND = {"character": "image", "style": "image", "object": "image"}

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
    licence: str
    methods_not: dict[str, str] = field(
        default_factory=dict
    )  # method -> why it cannot be used here


DESCRIPTORS = (
    Descriptor(
        id=trainer.BASE,
        title=trainer.BASE_TITLE,
        family="image",
        engine="mflux",
        licence=trainer.BASE_LICENCE,
        methods_not={
            "qlora": "Pictures are taught as a small adapter. The less-memory version is for "
            "writing models, which the app cannot teach yet.",
            "full": "Teaching all of a picture model needs far more memory than a Mac has, and the "
            "picture trainer does not do it.",
        },
    ),
)


class Unavailable(ValueError):
    """The base or the method asked for cannot be used; `str(e)` says why, in words."""


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
    kind: str, fit: dict[str, Any] | None, ready: bool, installed: list[dict[str, Any]]
) -> dict[str, Any]:
    """The rows of the "Choose the model and method" panel for a kind of teaching.

    `fit` is the engine's verdict for this computer, `ready` whether the engine is set up, and
    `installed` the models found on this computer (`kind`, `name`, `format` at least)."""
    family = FAMILY_FOR_KIND.get(kind, "image")
    rows: list[dict[str, Any]] = []
    for d in descriptors(family):
        can, reason = True, ""
        if not ready:
            can, reason = (
                False,
                "Set up training first: this model is taught by a tool that is not installed yet.",
            )
        elif fit and fit.get("verdict") == "too_big":
            can, reason = False, str(fit.get("reason", ""))
        rows.append(
            {
                "id": d.id, "title": d.title, "licence": d.licence, "engine": d.engine,
                "recommended": d is descriptors(family)[0], "can_teach": can, "reason": reason,
                "installed": ready, "methods": method_rows(d),
            }
        )  # fmt: skip
    known = {d.title.lower() for d in DESCRIPTORS}
    for item in installed[:8]:
        name = str(item.get("name", ""))
        if item.get("kind") != "diffusion" or name.lower() in known:
            continue
        rows.append(
            {
                "id": "", "title": name, "licence": str(item.get("licence", "")), "engine": "",
                "recommended": False, "can_teach": False, "installed": True,
                "reason": "This model cannot be taught yet: the app has no way to teach it.",
                "methods": [],
            }
        )  # fmt: skip
    return {
        "family": family,
        "default_base": rows[0]["id"] if rows else "",
        "default_method": DEFAULT_METHOD,
        "bases": rows,
    }


def resolve(kind: str, base: str | None, method: str | None) -> tuple[Descriptor, str]:
    """The descriptor and method a run will use; `Unavailable` says why a choice cannot be used."""
    family = FAMILY_FOR_KIND.get(kind, "image")
    options = descriptors(family)
    chosen = options[0]
    if base:
        found = [d for d in options if d.id == base]
        if not found:
            raise Unavailable("This model cannot be taught yet. Choose another one.")
        chosen = found[0]
    use = method or DEFAULT_METHOD
    if use not in {m[0] for m in METHODS}:
        raise Unavailable("Choose a small adapter or teach all of it.")
    if use in chosen.methods_not:
        raise Unavailable(chosen.methods_not[use])
    return chosen, use
