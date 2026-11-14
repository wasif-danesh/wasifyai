"""A project's files for the Files tab: the folders one level at a time, and one file to read.

This is the Wasify engine reading the person's own folder for the person, not the agent: nothing
here goes through the coding engine. It only reads. A path is always inside the session's
workspace, also when a link in the project points elsewhere."""

import os
from pathlib import Path
from typing import Any

MAX_FILE_BYTES = 400_000  # of one file shown; a longer one is cut and says so
MAX_ENTRIES = 2000  # of one folder
HIDDEN = (".git",)  # the project's own git store: thousands of files nobody reads
# folders a search by name does not go into: other programs' files, by the thousand
NOT_SEARCHED = (".git", "node_modules", ".venv", "venv", "__pycache__", "target", ".next")
MAX_FOUND = 50
MAX_LOOKED_AT = 100_000  # entries one search looks at before it gives what it has


class NotThere(Exception):
    """No such file or folder in the project."""


def inside(workspace: Path, relative: str) -> Path:
    """The real path of `relative` in the workspace, or `NotThere` when it is outside it."""
    root = Path(os.path.realpath(workspace))
    if relative.startswith("/") or "\x00" in relative:
        raise NotThere(relative)
    found = Path(os.path.realpath(root / relative))
    if found != root and root not in found.parents:
        raise NotThere(relative)
    return found


def list_folder(workspace: Path, relative: str = "") -> dict[str, Any]:
    """One folder's entries: folders first, then files, each by name."""
    folder = inside(workspace, relative)
    if not folder.is_dir():
        raise NotThere(relative)
    root = Path(os.path.realpath(workspace))
    entries = []
    with os.scandir(folder) as found:
        for entry in found:
            if entry.name in HIDDEN:
                continue
            try:
                is_folder = entry.is_dir()  # a link is what it points at
                size = 0 if is_folder else entry.stat().st_size
                real = Path(os.path.realpath(entry.path))
            except OSError:
                continue
            if real != root and root not in real.parents:
                continue  # a link that leaves the project is not shown
            entries.append(
                {
                    "name": entry.name,
                    "path": str(Path(relative) / entry.name) if relative else entry.name,
                    "kind": "folder" if is_folder else "file",
                    "bytes": size,
                }
            )
    entries.sort(key=lambda e: (e["kind"] != "folder", e["name"].lower()))
    return {"path": relative, "entries": entries[:MAX_ENTRIES], "more": len(entries) > MAX_ENTRIES}


def read_file(workspace: Path, relative: str) -> dict[str, Any]:
    """One file as text to read. A file that is not text says so and gives none."""
    path = inside(workspace, relative)
    if not path.is_file():
        raise NotThere(relative)
    size = path.stat().st_size
    with path.open("rb") as f:
        data = f.read(MAX_FILE_BYTES + 1)
    cut = len(data) > MAX_FILE_BYTES
    data = data[:MAX_FILE_BYTES]
    if b"\x00" in data[:8000]:
        return {
            "path": relative,
            "bytes": size,
            "binary": True,
            "text": "",
            "lines": 0,
            "cut": False,
        }
    text = data.decode("utf-8", errors="replace")
    if cut:  # end at a whole line
        text = text.rsplit("\n", 1)[0]
    return {
        "path": relative,
        "bytes": size,
        "binary": False,
        "text": text,
        "lines": text.count("\n") + (1 if text and not text.endswith("\n") else 0),
        "cut": cut,
    }


def find_files(workspace: Path, query: str) -> dict[str, Any]:
    """Files whose name holds `query` (letters in any case), nearest the top first. Links are not
    followed, so nothing outside the project is found."""
    wanted = query.strip().lower()
    root = Path(os.path.realpath(workspace))
    found: list[dict[str, Any]] = []
    looked = 0
    if not wanted:
        return {"query": query, "entries": [], "more": False}
    for folder, folders, names in os.walk(root, followlinks=False):
        folders[:] = sorted(f for f in folders if f not in NOT_SEARCHED)
        for name in sorted(names):
            looked += 1
            if wanted not in name.lower():
                continue
            path = Path(folder) / name
            if path.is_symlink():
                continue
            found.append(
                {"name": name, "path": str(path.relative_to(root)), "kind": "file", "bytes": 0}
            )
            if len(found) > MAX_FOUND:
                break
        if len(found) > MAX_FOUND or looked > MAX_LOOKED_AT:
            break
    more = len(found) > MAX_FOUND or looked > MAX_LOOKED_AT
    found.sort(key=lambda e: (e["path"].count("/"), e["path"].lower()))
    return {"query": query, "entries": found[:MAX_FOUND], "more": more}
