"""Starters: a new project in a new, empty folder (stage C4; mockup `start`, "Start in a new,
empty folder").

A starter is a folder of plain files under `starters/<id>/`, copied as they are; `{{NAME}}` and
`{{TITLE}}` in a text file become the project's own. A starter of ours needs nothing installed
to run: its preview and its check work on a clean computer, with Node as the only tool.

    list_starters   what can be started, for the screen
    make            write a starter into `<parent>/<name>`, which must not hold anything yet

The folder is the person's: it is made inside a folder they chose, and nothing is written
anywhere else.
"""

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).with_name("starters")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,62}[A-Za-z0-9]$|^[A-Za-z0-9]$")
TEXT = (".html", ".js", ".mjs", ".css", ".json", ".md", ".txt", ".py", ".toml")
# a file a starter cannot carry under its own name (the repository's own tools would read it)
RENAMED = {"gitignore.txt": ".gitignore"}


@dataclass(frozen=True)
class Starter:
    id: str
    title: str
    says: str
    preview: str  # the command that starts it
    check: str  # the command that checks it
    needs: tuple[str, ...]  # the tools it needs, in words


STARTERS = (
    Starter(
        "web",
        "A small web app",
        "One page with its script and its styles, tests, and a preview that loads again when "
        "a file changes. No build step and nothing to install.",
        preview="npm run dev",
        check="npm test",
        needs=("Node",),
    ),
)


class StarterError(Exception):
    """A project could not be started. `message` is safe to show."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def list_starters() -> list[dict[str, Any]]:
    return [
        {"id": s.id, "title": s.title, "says": s.says, "needs": list(s.needs)} for s in STARTERS
    ]


def get(starter_id: str) -> Starter:
    found = next((s for s in STARTERS if s.id == starter_id), None)
    if found is None:
        raise StarterError("no_such_starter", "There is no such starter.")
    return found


def package_name(name: str) -> str:
    """A project's name as a package name: small letters, digits and dashes."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "app"


def make(starter_id: str, parent: Path, name: str) -> Path:
    """Write the starter into `<parent>/<name>` and give that folder. The folder may be there
    already when it is empty; anything in it is a refusal, and nothing is written."""
    starter = get(starter_id)
    name = name.strip()
    if not NAME.match(name):
        raise StarterError(
            "bad_name",
            "Give the project a name of letters, digits, spaces, dots, dashes or underlines.",
        )
    if not parent.is_dir():
        raise StarterError("no_folder", f"There is no folder at {parent}.")
    target = parent / name
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise StarterError("taken", f"{name} is already there and is not a folder.")
    if target.is_dir() and any(target.iterdir()):
        raise StarterError(
            "not_empty", f"The folder {name} already holds files. Choose a new name."
        )
    source = HERE / starter.id
    made = not target.exists()
    try:
        target.mkdir(exist_ok=True)
        for path in sorted(source.rglob("*")):
            rel = path.relative_to(source)
            if "__pycache__" in rel.parts:
                continue
            out = target / rel.parent / RENAMED.get(rel.name, rel.name)
            if path.is_dir():
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix in TEXT:
                text = path.read_text()
                text = text.replace("{{NAME}}", package_name(name)).replace("{{TITLE}}", name)
                out.write_text(text)
            else:
                shutil.copyfile(path, out)
    except OSError:
        if made:
            shutil.rmtree(target, ignore_errors=True)
        raise StarterError("could_not_write", "The project's files could not be written.") from None
    return target
