"""What the assistant knows the app can do: the screens of the side menu and what each is for.

`features.json` is made from the action catalogue and the menu (`wasifyai_api.assistant_features`),
never typed by hand. Only the screens whose actions this engine serves are listed, so a person on
an app that does not have one is not sent to it."""

import json
import re
from collections.abc import Collection
from functools import cache
from pathlib import Path

from wasifyai_assistant.help import fields_of, titles

FILE = Path(__file__).with_name("features.json")

FEATURES_PROMPT = (
    " The app has these screens in its side menu (menu path: what it does): {list}. You make "
    "pictures and music yourself with your tools. For anything else, say where it is in the menu "
    "and what to do there, in a step or two; never say you made it yourself, and never say the "
    "app cannot do something that is in this list."
)


@cache
def _rows() -> list[dict[str, list[str] | str]]:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _screen_lines(served: Collection[str]) -> list[str]:
    """One line per screen this engine serves: its menu path, and what it is for."""
    lines = []
    for row in _rows():
        if any(a in served for a in row["actions"]):
            says = row.get("about") or "; ".join(row["does"]).lower()  # type: ignore[arg-type]
            lines.append(f"{row['where']}: {says}")
    return lines


def features_prompt(served: Collection[str]) -> str:
    """The sentence about the app's screens, for the screens this engine serves ("" if none)."""
    lines = _screen_lines(served)
    return FEATURES_PROMPT.format(list=" | ".join(lines)) if lines else ""


SCREENS_PROMPT = (
    " The app has {n} screens in its side menu. Each line is its menu path, then what it is "
    "for:\n{list}\nWhen someone asks what the app can do, or to describe the products, give one "
    "short sentence for each menu heading (the words before the first ›) and one for each screen "
    "that has no heading, in this order, and leave none out. When they ask about one screen, "
    "say everything its line says."
)


def screens_prompt(served: Collection[str]) -> str:
    """What each screen of the app is for, so the assistant can describe the whole app, not only
    the actions it may propose ("" if this engine serves none)."""
    lines = _screen_lines(served)
    if not lines:
        return ""
    numbered = "\n".join(f"{i}. {line}" for i, line in enumerate(lines, 1))
    return SCREENS_PROMPT.format(n=len(lines), list=numbered)


FOCUS_PROMPT = (
    " The person's last message is about {where}. Its line in the list above is the answer: "
    "{says}. Answer from that line and the guides; never from general knowledge."
)


def focus_prompt(text: str, served: Collection[str]) -> str:
    """For a message that names a screen with several jobs (Train, Creative Studio, Motion
    graphics: the rows that have `about`), that screen's line again, last in the prompt, so even
    a small model answers from it and not from what it thinks such a screen is ("" if none)."""
    said = text.lower()
    out = []
    for row in _rows():
        about = row.get("about")
        if not about or not any(a in served for a in row["actions"]):
            continue
        label = str(row["where"]).lower()
        if label in said or re.search(rf"\b{re.escape(str(row['screen']))}\b", said):
            out.append(FOCUS_PROMPT.format(where=row["where"], says=about))
    return "".join(out)


def where_of(action_id: str) -> str:
    """The menu path of an action's screen ("Voice › Text to speech"), or ""."""
    for row in _rows():
        if action_id in row["actions"]:
            return str(row["where"])
    return ""


def where_of_screen(screen_id: str) -> str:
    """The menu path of a screen (a menu item id), or ""."""
    for row in _rows():
        if row.get("screen") == screen_id:
            return str(row["where"])
    return ""


NOT_PROPOSED = frozenset({"web", "app", "job", "external"})  # these have tools of their own
ACTIONS_PROMPT = (
    " Actions you may propose with propose_action (id(the fields it needs): what it does; where it "
    "is in the app): {list}. Give params with exactly those field names; an id field takes the id "
    "of a library item, never its name."
)


def actions_prompt(served: Collection[str]) -> str:
    """The compact map of the actions this engine serves (ADR-0071 decision 3): about 600 tokens,
    made from the guides' titles and the menu, never typed by hand ("" if none)."""
    named = titles(served)
    needs = fields_of(served)
    lines = []
    for action_id in sorted(served):
        # the web, the app's state and jobs have tools of their own; they are not proposed
        if action_id not in named or action_id.split(".", 1)[0] in NOT_PROPOSED:
            continue
        where = where_of(action_id)
        sig = f"{action_id}({', '.join(needs.get(action_id, ()))})"
        lines.append(f"{sig}: {named[action_id]}" + (f"; {where}" if where else ""))
    actions = ACTIONS_PROMPT.format(list=" | ".join(lines)) if lines else ""
    return actions + screens_prompt(served)  # last, so a small model still has it in mind
