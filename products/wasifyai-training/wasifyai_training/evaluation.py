"""Did it learn? (ADR-0073 decision 10, ADR-0076)

After a run the model is drawn with and without what was taught, and the person's vision model
says, picture by picture, whether it looks like the pictures that were uploaded. The result is a
sentence in words and a "did not pass" mark that never blocks keeping the model.

Three pictures are drawn for each scene, with the same seed so the only difference is what is
being tested:

    with_word      the model, and its magic word in the prompt        should look like them
    without_word   the model, and the prompt without the magic word   shown, not judged: a strong
                                                                      model appears anyway
    without_model  the base model alone, with the magic word          must NOT look like them

A model passes when its pictures with the word look like the references at least half the time and
the base model's pictures do not. This is a soft check by a vision model, not a proof; the pictures
are shown next to it."""

import asyncio
import io
import json
from pathlib import Path
from typing import Any

from PIL import Image as PILImage
from wasifyai_platform_sdk import Capabilities, Image, RunError

from wasifyai_training import vision

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"same": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["same", "reason"],
    "additionalProperties": False,
}
PROMPT = {"character": "judge_character", "style": "judge_style", "object": "judge_object"}
REFS = 3  # reference pictures kept with a model, and shown to the judge
REF_PX = 512

# a scene the model did not see, twice; `{w}` is the magic word, placed first as in the captions it
# was taught with (a position the model never saw it in is not a fair test)
SCENES = {
    "character": [
        ("{w}, standing in a sunny park", "someone standing in a sunny park"),
        (
            "{w}, sitting at a cafe table, reading a book",
            "someone sitting at a cafe table, reading a book",
        ),
    ],
    "style": [
        ("{w}, a lighthouse on a cliff at sunrise", "a lighthouse on a cliff at sunrise"),
        ("{w}, a bowl of fruit on a wooden table", "a bowl of fruit on a wooden table"),
    ],
    "object": [
        ("{w} on a wooden table by a window", "an object on a wooden table by a window"),
        (
            "{w} on a kitchen counter, morning light",
            "an object on a kitchen counter, morning light",
        ),
    ],
}
CONDITIONS = ("with_word", "without_word", "without_model")
# what to try when it did not pass, by kind (a style needs many subjects to reach a new scene)
TIP = {
    "character": " It did not pass: try more pictures, or ones that show it more clearly.",
    "object": (
        " It did not pass: try more pictures from other angles, or ones that show it more clearly."
    ),
    "style": (
        " It did not pass: it learnt the scenes it was shown but not a new one. A style carries"
        " over only when it sees many different subjects, so add pictures of different things."
    ),
}


def check_plan(kind: str, word: str) -> list[dict[str, Any]]:
    """The pictures to draw: each scene three ways; `with_model` says whether the model is on."""
    out = []
    for n, (with_w, without_w) in enumerate(SCENES.get(kind, SCENES["character"])):
        prompt = with_w.format(w=word)
        out.append(
            {
                "id": f"s{n}-with_word",
                "scene": n,
                "condition": "with_word",
                "prompt": prompt,
                "with_model": True,
            }
        )
        out.append(
            {
                "id": f"s{n}-without_word",
                "scene": n,
                "condition": "without_word",
                "prompt": without_w,
                "with_model": True,
            }
        )
        out.append(
            {
                "id": f"s{n}-without_model",
                "scene": n,
                "condition": "without_model",
                "prompt": prompt,
                "with_model": False,
            }
        )
    return out


def save_refs(pictures: list[Path], folder: Path) -> int:
    """Keep up to three training pictures, small, with the model: what a check compares with."""
    folder.mkdir(parents=True, exist_ok=True)
    chosen = (
        pictures
        if len(pictures) <= REFS
        else [pictures[round(i * (len(pictures) - 1) / (REFS - 1))] for i in range(REFS)]
    )
    for n, path in enumerate(chosen, start=1):
        with PILImage.open(path) as im:
            rgb = im.convert("RGB")
        rgb.thumbnail((REF_PX, REF_PX))
        rgb.save(folder / f"ref-{n}.jpg", "JPEG", quality=88)
    return len(chosen)


def load_refs(folder: Path) -> list[bytes]:
    return [p.read_bytes() for p in sorted(folder.glob("ref-*.jpg"))]


def small(data: bytes) -> bytes:
    with PILImage.open(io.BytesIO(data)) as im:
        rgb = im.convert("RGB")
    rgb.thumbnail((REF_PX, REF_PX))
    out = io.BytesIO()
    rgb.save(out, "JPEG", quality=85)
    return out.getvalue()


async def judge(
    caps: Capabilities, kind: str, refs: list[bytes], candidate: bytes
) -> dict[str, Any]:
    """`{same, reason}` for one picture. Raises `RunError` with words when it cannot be judged."""
    if not refs:
        raise RunError("no_references", "This model has no pictures to compare with.")
    cand = await asyncio.to_thread(small, candidate)
    user: list[Any] = [vision.prompt("judge_request")]
    user += [Image.from_bytes(r, "image/jpeg") for r in refs]
    user.append(Image.from_bytes(cand, "image/jpeg"))
    try:
        raw = await caps.text.complete(
            "judge_image", vision.prompt(PROMPT.get(kind, "judge_object")), user, schema=SCHEMA
        )
        data = json.loads(raw)
        return {"same": bool(data["same"]), "reason": str(data.get("reason", ""))[:200]}
    except RunError:
        raise
    except (ValueError, KeyError, TypeError):
        raise RunError("judge_failed", "The picture could not be judged. Try again.") from None
    except Exception:
        raise RunError(
            "judge_failed",
            "The picture could not be judged. Choose a model that reads pictures, or try again.",
        ) from None


def _count(items: list[dict[str, Any]], condition: str) -> tuple[int, int]:
    judged = [i for i in items if i["condition"] == condition and i.get("same") is not None]
    return sum(1 for i in judged if i["same"]), len(judged)


def summarize(kind: str, items: list[dict[str, Any]], at: str) -> dict[str, Any]:
    """The evaluation for the model's card, in words; `passed` is None when nothing was judged."""
    yes_w, n_w = _count(items, "with_word")
    yes_b, n_b = _count(items, "without_model")
    yes_o, n_o = _count(items, "without_word")
    what = {"character": "your character", "style": "your style", "object": "your object"}.get(
        kind, "your pictures"
    )
    if n_w == 0:
        return {
            "passed": None,
            "note": "Not judged: a model that reads pictures is needed to say whether it learnt.",
            "counts": {}, "items": items, "at": at,
        }  # fmt: skip
    passed = yes_w * 2 >= n_w and (n_b == 0 or yes_b * 2 < n_b)
    note = f"With its magic word it looked like {what} in {yes_w} of {n_w} pictures"
    if n_b:
        note += f"; the base model without it, in {yes_b} of {n_b}"
    note += "."
    if n_o and yes_o:
        note += f" It also shows up without the magic word ({yes_o} of {n_o}): it is strong."
    if not passed:
        note += TIP.get(kind, TIP["character"])
    return {
        "passed": passed, "note": note, "at": at, "items": items,
        "counts": {
            "with_word": [yes_w, n_w],
            "without_word": [yes_o, n_o],
            "without_model": [yes_b, n_b],
        },
    }  # fmt: skip
