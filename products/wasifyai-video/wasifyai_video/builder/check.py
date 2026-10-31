"""The exact-text check (ADR-0079 decision 7): is what is drawn what the person typed?

The template says which words must be on the screen and when. The component opens the page in the
sandbox, seeks to those moments and reports what is really drawn for each element. Here that
report is compared with the typed words, in plain sentences. A failed check is shown, never fixed
quietly: the words are never retyped by a model, and a render does not start on a page that does
not say them."""

import logging
import unicodedata
from typing import Any

from wasifyai_video.builder import templates

log = logging.getLogger(__name__)

MIN_OPACITY = 0.75  # the templates dim a second line to 0.8; a word still fading in is below this
MIN_INK = 20  # pixels that change when the element is hidden: fewer means nothing is drawn
MAX_CUT = 80  # pixels that change when every clip is removed: more means something is cut off
# (a clip layer redraws the headline rule of Bengali letters a little differently: 40 pixels)
MAX_CUT_SHARE = 0.015  # for big letters, this share of what is drawn: redrawing their edges changes
# up to 0.9% of them (85 pixels of 13,877, a serif title), and the tail of one "y" is about 3%


def _norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def _quote(text: str, limit: int = 40) -> str:
    text = _norm(text)
    return f"“{text if len(text) <= limit else text[: limit - 1].rstrip() + '…'}”"


def spec_for(template: str, slots: dict[str, Any]) -> dict[str, Any]:
    width, height = templates.SHAPES[slots["shape"]]
    return {
        "width": width, "height": height, "safe": templates.SAFE,
        "transparent": templates.is_transparent(template, slots),
        "items": [{"slot": e.slot, "at": e.at} for e in templates.expected(template, slots)],
    }  # fmt: skip


def compare(
    template: str, slots: dict[str, Any], seen: list[dict[str, Any]]
) -> list[dict[str, str]]:
    """What is wrong, one sentence each; empty means the screen says exactly what was typed."""
    wanted = templates.expected(template, slots)
    by_slot = {(i.get("slot"), i.get("at")): i for i in seen}
    problems: list[dict[str, str]] = []
    for e in wanted:
        got = by_slot.get((e.slot, e.at))
        if got is None or not got.get("found"):
            problems.append(
                {"slot": e.slot, "code": "missing",
                 "message": f"{_quote(e.text)} is not on the screen."}
            )  # fmt: skip
            continue
        if _norm(got.get("text", "")) != _norm(e.text):
            problems.append(
                {"slot": e.slot, "code": "text_mismatch", "message": (
                    f"The screen says {_quote(got.get('text', ''))} "
                    f"but you wrote {_quote(e.text)}.")}
            )  # fmt: skip
        elif not got.get("shown") or float(got.get("opacity", 0)) < MIN_OPACITY:
            problems.append(
                {"slot": e.slot, "code": "hidden",
                 "message": f"{_quote(e.text)} is not fully visible when it should be."}
            )  # fmt: skip
        elif int(got.get("inked", 0)) < MIN_INK:
            problems.append(
                {"slot": e.slot, "code": "not_drawn",
                 "message": f"{_quote(e.text)} is in the page but nothing is drawn for it."}
            )  # fmt: skip
        elif int(got.get("clipped", 0)) > max(MAX_CUT, int(got.get("inked", 0)) * MAX_CUT_SHARE):
            problems.append(
                {"slot": e.slot, "code": "clipped",
                 "message": f"Part of {_quote(e.text)} is cut off."}
            )  # fmt: skip
        elif not got.get("inside", True):
            problems.append(
                {"slot": e.slot, "code": "outside_safe_area",
                 "message": f"{_quote(e.text)} is too close to the edge of the picture."}
            )  # fmt: skip
    return problems


def describe(problems: list[dict[str, str]]) -> str:
    first = "; ".join(p["message"] for p in problems[:3])
    more = f" (and {len(problems) - 3} more)" if len(problems) > 3 else ""
    return f"The words on the screen are not exactly what you wrote: {first}{more}"


async def run_check(
    engine: Any, folder: Any, template: str, slots: dict[str, Any]
) -> dict[str, Any]:
    """The check of one composition: `{ok, checked, problems, message}`. `ok` is false when the page
    says something else, and also when the check itself could not be run (it is not skipped)."""
    report = await engine.inspect(folder, spec_for(template, slots))
    if not report["ok"]:  # the browser did not start or died (seen once under load): once more
        log.warning("the check could not be run, trying again: %s", report.get("log") or report)
        report = await engine.inspect(folder, spec_for(template, slots))
    expected = len(templates.expected(template, slots))
    if not report["ok"]:
        return {"ok": False, "checked": 0, "problems": [], "message": (
            f"The check could not be run: {report['message']}")}  # fmt: skip
    problems = compare(template, slots, report["items"])
    if problems:
        return {
            "ok": False,
            "checked": expected,
            "problems": problems,
            "message": describe(problems),
        }
    return {
        "ok": True, "checked": expected, "problems": [],
        "message": "Checked: the words on the screen are exactly what you wrote.",
    }  # fmt: skip
