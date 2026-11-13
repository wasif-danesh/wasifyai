"""Saving a copy where the person chose (the desktop's Save As box).

The window cannot write a file by itself, so it asks the system for a place (a Save As box, where
the person also answers "replace?") and gives the engine the path to write. The engine only ever
writes a file at that exact path: never a folder, never a path whose folder does not exist, never
inside the app's own data (its database and keys)."""

import os
import shutil
from pathlib import Path

from pydantic import BaseModel


class SaveTo(BaseModel):
    """The optional body of an export route: where to write. Without it the engine's own export
    folder is used (the assistant has no Save As box to ask)."""

    path: str | None = None


class SaveRefused(ValueError):
    """The path cannot be written. The message is in words for the person."""


def chosen_path(path: str, protect: Path | None = None) -> Path:
    """The path to write, checked. `protect` is a folder nothing may be written into."""
    if not path or "\x00" in path:
        raise SaveRefused("That place cannot be used. Choose another.")
    target = Path(path).expanduser()
    if not target.is_absolute():
        raise SaveRefused("That place cannot be used. Choose another.")
    if target.is_dir():
        raise SaveRefused("That is a folder. Choose a file name.")
    if not target.parent.is_dir():
        raise SaveRefused("That folder does not exist. Choose another.")
    if protect is not None:
        guarded = protect.resolve()
        if guarded in (target.parent.resolve(), *target.parent.resolve().parents):
            raise SaveRefused("That place belongs to the app. Choose another folder.")
    return target


def _part(target: Path) -> Path:
    return target.with_name(f".{target.name}.part")


def write_to_path(path: str, data: bytes, protect: Path | None = None) -> Path:
    """Write `data` at the chosen path, replacing a file there (the Save As box asked)."""
    target = chosen_path(path, protect)
    part = _part(target)
    try:
        part.write_bytes(data)
        os.replace(part, target)
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise SaveRefused("The file could not be saved there. Choose another place.") from exc
    return target


def copy_to_path(path: str, source: Path, protect: Path | None = None) -> Path:
    """Copy a file of the app's to the chosen path."""
    target = chosen_path(path, protect)
    part = _part(target)
    try:
        shutil.copyfile(source, part)
        os.replace(part, target)
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise SaveRefused("The file could not be saved there. Choose another place.") from exc
    return target
