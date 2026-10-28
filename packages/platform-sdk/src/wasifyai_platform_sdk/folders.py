"""Allowed folders: how a program outside the app hands it a file or gets one back without an
arbitrary-path hole (ADR-0069 decision 6; spike S2, `docs/spikes/mcp-s2.md`).

A connection (an MCP client) names the folders it may read from and write to.
Every path it sends is checked here before anything touches the disk:

- it must be absolute, with no `..` segment, no NUL, no backslash and no newline; `~` is not
  expanded (the app does not guess whose home);
- symbolic links are followed, and the place a path really points at must be inside one of the
  connection's folders (which are resolved the same way, so a folder that is itself a link is
  fine, and a link inside a folder that points outside is not);
- a prefix is not a folder: `/Users/me/Documents2` is not inside `/Users/me/Documents`;
- a read needs a regular file that exists; a write needs a parent folder that exists inside a
  write folder and a target that is not a link, a folder or a device.

The checks are strict on purpose: a refused path answers with a sentence that says which rule,
and a client fixes the path. Case-insensitive file systems are not special-cased: a path spelt
in another case than the folder is refused rather than guessed."""

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Mode = Literal["read", "write"]
MAX_PATH = 4096


class PathRefused(ValueError):
    """The path cannot be used. `code` is stable for a client; `message` is a sentence."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _resolved(folder: Path) -> Path:
    return Path(folder).expanduser().resolve(strict=False)


def _inside(path: Path, folder: Path) -> bool:
    try:
        path.relative_to(folder)
    except ValueError:
        return False
    return True


def _well_formed(raw: object) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise PathRefused("no_path", "Give the full path of the file.")
    if len(raw) > MAX_PATH:
        raise PathRefused("too_long", "That path is too long.")
    if "\0" in raw or "\n" in raw or "\r" in raw:
        raise PathRefused("bad_characters", "A path cannot hold a line break or a NUL byte.")
    if "\\" in raw:
        raise PathRefused("bad_characters", "Write the path with forward slashes, no backslashes.")
    if raw.startswith("file:"):
        raise PathRefused("not_absolute", "Give a plain absolute path, not a file: address.")
    p = Path(raw)
    if not p.is_absolute():
        raise PathRefused(
            "not_absolute", "Give the full path, starting from the root (not ~ or a relative path)."
        )
    if ".." in p.parts:
        raise PathRefused("dotdot", "A path cannot hold '..'. Write the full path instead.")
    return p


@dataclass(frozen=True)
class AllowedFolders:
    """The folders a connection may read from and write to (absolute; resolved when checked)."""

    read: tuple[Path, ...] = ()
    write: tuple[Path, ...] = ()

    @classmethod
    def of(cls, read: list[str] | tuple[str, ...] = (), write: list[str] | tuple[str, ...] = ()):
        return cls(tuple(Path(p) for p in read), tuple(Path(p) for p in write))

    def _folder_for(self, resolved: Path, mode: Mode) -> Path | None:
        for folder in self.write if mode == "write" else (*self.read, *self.write):
            root = _resolved(folder)
            if _inside(resolved, root):
                return root
        return None

    def resolve_folder(self, raw: object) -> Path:
        """A folder the connection may write into: inside (or exactly) one of its write folders,
        existing, a directory, not reached through a link out; else `PathRefused`."""
        p = _well_formed(raw)
        resolved = p.resolve(strict=False)
        if self._folder_for(resolved, "write") is None:
            raise PathRefused(
                "outside", "That folder is outside the folders this connection may write to."
            )
        if not resolved.is_dir():
            raise PathRefused("no_folder", "That folder does not exist.")
        return resolved

    def resolve(self, raw: object, mode: Mode) -> Path:
        """The real place `raw` points at, when the connection may use it for `mode`; else a
        `PathRefused` with the rule that failed."""
        p = _well_formed(raw)
        resolved = p.resolve(strict=False)
        if mode == "read":
            if self._folder_for(resolved, "read") is None:
                raise PathRefused(
                    "outside", "That file is outside the folders this connection may read."
                )
            try:
                st = os.stat(resolved)
            except OSError:
                raise PathRefused("missing", "There is no file at that path.") from None
            if not stat.S_ISREG(st.st_mode):
                raise PathRefused("not_a_file", "That path is not a regular file.")
            return resolved
        # a write: never through a link, and the parent must really be inside a write folder;
        # the file may not exist yet
        if p.is_symlink():
            raise PathRefused("link", "That path is a link; write to a real file instead.")
        parent = resolved.parent
        if self._folder_for(parent, "write") is None:
            raise PathRefused(
                "outside", "That place is outside the folders this connection may write to."
            )
        if not parent.is_dir():
            raise PathRefused("no_folder", "The folder for that file does not exist.")
        if not resolved.name:
            raise PathRefused("no_name", "Give the file a name.")
        if p.is_symlink() or resolved.is_symlink():
            raise PathRefused("link", "That path is a link; write to a real file instead.")
        if resolved.exists() and not resolved.is_file():
            raise PathRefused("not_a_file", "That path is a folder or a device, not a file.")
        return resolved
