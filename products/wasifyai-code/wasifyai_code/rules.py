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
    delete         a command that deletes files or throws work away (`rm`, `git clean`,
                   `git reset --hard`). Asked from stage C3
    install        a command that installs packages (`pip install`, `npm install`, `cargo add`).
                   Asked from stage C3. Letting one through is also what opens the install
                   proxy to the agent's commands for a while (`coding_proxy.py`)

In "Work on its own" nothing of this list is asked. A command is judged by its words, which is a
help to the person and not a wall: a script can delete a file without the word `rm` in it. The
wall is the sandbox, which keeps every command inside the project, and Undo, which puts a
deleted file back unless the project ignores it.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

NOT_UNDOABLE, DELETE, INSTALL = "not_undoable", "delete", "install"
KINDS = (NOT_UNDOABLE, DELETE, INSTALL)
# kinds a real session can meet at this stage; the others are shown as "from a later version"
ASKED_NOW = (NOT_UNDOABLE, DELETE, INSTALL)

YES, ALLOW, NO = "yes", "allow", "no"
ANSWERS = (YES, ALLOW, NO)
ALLOWED = "allowed"  # how a step is marked that ran because its kind is allowed for the project

# the file editor's commands that change a file
EDITS = ("create", "str_replace", "insert", "undo_edit")
WRITE_TOOLS = ("file_editor",)
RUN_TOOLS = ("terminal",)

# A command is cut into its parts at `;`, `&&`, `||`, `|` and new lines; each part is judged by
# its first words, after `sudo`, `env X=1`, `command` and the like.
_PARTS = re.compile(r"\|\||&&|[;|\n&]|\$\(|`")
_LEAD = re.compile(r"^(?:\s*(?:sudo|command|exec|nohup|time|env|xargs(?:\s+-\S+)*|\w+=\S*)\s+)*")
_DELETE = re.compile(
    r"^(?:rm|rmdir|unlink|shred|trash)\b"
    r"|^git\s+(?:clean\b|rm\b|reset\s+.*--hard\b|checkout\s+(?:--\s|\.)|restore\b|stash\s+(?:drop|clear)\b)"
    r"|^find\b.*\s-(?:delete|exec\s+rm)\b"
)
_INSTALL = re.compile(
    r"^(?:pip3?|python3?\s+-m\s+pip|uv\s+pip)\s+(?:install|download|wheel)\b"
    r"|^uv\s+(?:add|sync|lock|tool\s+install|venv\b.*--seed)\b"
    r"|^(?:poetry|pdm|pipenv)\s+(?:add|install|update|lock|sync)\b"
    r"|^(?:npm|pnpm|bun)\s+(?:i|install|add|ci|update|upgrade|create|dlx|exec|x)\b"
    r"|^yarn(?:\s+(?:add|install|up|upgrade|create|dlx))?\s*$|^yarn\s+(?:add|install|up|upgrade|create|dlx)\b"
    r"|^(?:npx|pnpx|bunx|uvx|pipx)\b"
    r"|^cargo\s+(?:add|install|fetch|update)\b"
    r"|^go\s+(?:get|install|mod\s+(?:download|tidy))\b"
    r"|^(?:gem|bundle)\s+(?:install|add|update)\b"
    r"|^(?:brew|apt|apt-get|port|conda|mamba)\s+(?:install|add|upgrade|update)\b"
)


def command_kind(command: str) -> str | None:
    """Whether a shell command installs packages or deletes files, by its words; None for
    neither. Deleting is looked for first: it is the one that loses something."""
    found: str | None = None
    for part in _PARTS.split(command):
        words = _LEAD.sub("", part.strip())
        if not words:
            continue
        if _DELETE.search(words):
            return DELETE
        if found is None and _INSTALL.search(words):
            found = INSTALL
    return found


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
    if step.get("tool") in RUN_TOOLS:
        return command_kind(str(step.get("command") or ""))
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
