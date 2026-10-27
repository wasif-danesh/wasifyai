"""What the assistant knows the app can do: the screens of the side menu and what each is for.

`features.json` is made from the action catalogue and the menu (`wasifyai_api.assistant_features`),
never typed by hand. Only the screens whose actions this engine serves are listed, so a person on
an app that does not have one is not sent to it."""

import json
from collections.abc import Collection
from functools import cache
from pathlib import Path

from wasifyai_assistant.help import titles

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


def features_prompt(served: Collection[str]) -> str:
    """The sentence about the app's screens, for the screens this engine serves ("" if none)."""
    lines = []
    for row in _rows():
        if any(a in served for a in row["actions"]):
            lines.append(f"{row['where']}: {'; '.join(row['does']).lower()}")
    return FEATURES_PROMPT.format(list=" | ".join(lines)) if lines else ""


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


NOT_PROPOSED = frozenset({"web", "app", "job"})
ACTIONS_PROMPT = (
    " Actions you may propose with propose_action (id: what it does; where it is in the app): "
    "{list}."
)


def actions_prompt(served: Collection[str]) -> str:
    """The compact map of the actions this engine serves (ADR-0071 decision 3): about 600 tokens,
    made from the guides' titles and the menu, never typed by hand ("" if none)."""
    named = titles(served)
    lines = []
    for action_id in sorted(served):
        # the web, the app's state and jobs have tools of their own; they are not proposed
        if action_id not in named or action_id.split(".", 1)[0] in NOT_PROPOSED:
            continue
        where = where_of(action_id)
        lines.append(f"{action_id}: {named[action_id]}" + (f"; {where}" if where else ""))
    return ACTIONS_PROMPT.format(list=" | ".join(lines)) if lines else ""
