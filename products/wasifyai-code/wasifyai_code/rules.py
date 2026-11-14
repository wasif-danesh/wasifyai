"""What the agent is asked about, and what a person allowed (ADR-0102, decision 6 and the
amendment of 2026-11-14, "Allow for this project").

The coding engine stops before every use of a tool that changes something and waits
(`services/coding-engine/wasify_rules.py`). The decision is made here, outside the sandbox:

    classify   which kind of request a waiting step is, or none
    decide     answer at once, or ask the person

The kinds are a fixed list. A person cannot write a rule of their own in v1; they can allow a
kind for one project, and take that back. An allowance is for one project and one person.

    not_undoable   changing a file Undo cannot put back: one the project ignores (`.env`), or
                   one inside a `.git` folder. Asked from stage C2
    delete         deleting files       } asked once the agent can run commands (stage C3);
    install        installing packages  } listed now so that the screen and the store do not change

In "Work on its own" nothing of this list is asked. What is asked in every mode (deleting
something of the person's outside the project, going on after the cost limit) arrives with the
tools that can do it.
"""

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

NOT_UNDOABLE, DELETE, INSTALL = "not_undoable", "delete", "install"
KINDS = (NOT_UNDOABLE, DELETE, INSTALL)
# kinds a real session can meet at this stage; the others are shown as "from a later version"
ASKED_NOW = (NOT_UNDOABLE,)

YES, ALLOW, NO = "yes", "allow", "no"
ANSWERS = (YES, ALLOW, NO)
ALLOWED = "allowed"  # how a step is marked that ran because its kind is allowed for the project

# the file editor's commands that change a file
EDITS = ("create", "str_replace", "insert", "undo_edit")
WRITE_TOOLS = ("file_editor",)


def path_in(workspace: Path, given: str) -> str | None:
    """A path the agent named, as a path from the workspace's top; None when it is outside."""
    if not given:
        return None
    path = Path(given)
    if not path.is_absolute():
        path = workspace / path
    try:
        # the folder's real place, not the file's: a new file does not exist yet
        real = Path(path.parent).resolve() / path.name
        return real.relative_to(workspace.resolve()).as_posix()
    except (OSError, ValueError):
        return None


def classify(
    step: Mapping[str, Any], workspace: Path, left_out: Callable[[str], bool]
) -> str | None:
    """The kind of request one waiting step is, or None when no rule asks about it. `left_out`
    says whether a path is one a checkpoint does not hold."""
    if step.get("tool") not in WRITE_TOOLS or step.get("command") not in EDITS:
        return None
    inside = path_in(workspace, str(step.get("path") or ""))
    if inside is None:
        return None  # outside the project: the sandbox refuses the write itself
    return NOT_UNDOABLE if left_out(inside) else None


def decide(mode: str, allowed: Sequence[str], kinds: Sequence[str | None]) -> tuple[str, str]:
    """What to do with the steps that wait together: `(YES, "")` to let them run with no
    question, `(ALLOWED, kind)` to let them run because the kind is allowed for the project, or
    `("ask", kind)` to ask the person about the first kind that is not."""
    found = [k for k in kinds if k]
    if not found or mode == "own":
        return YES, ""
    for kind in found:
        if kind not in allowed:
            return "ask", kind
    return ALLOWED, found[0]
