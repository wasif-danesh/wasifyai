"""How a product lets the library actions reach what it kept (ADR-0068 decision 7, `library.*`).

Each product that lets a person keep something declares one `LibraryKind` per kind of creation
(next to its other actions), in terms of its own stores. The `library.*` actions are written once
on top of them, so a new kind of creation is searchable by an agent the day it declares one."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# (context) -> ...; the context is `executor.ActionContext`
ListItems = Callable[[Any, int], Awaitable[list["LibraryItem"]]]
GetItem = Callable[[Any, str], Awaitable["LibraryItem | None"]]
RenameItem = Callable[[Any, str, str], Awaitable[bool]]
DeleteItem = Callable[[Any, str], Awaitable[bool]]
ExportItem = Callable[[Any, str, Path], Awaitable[Path | None]]
ReadItem = Callable[[Any, str], Awaitable[bytes | None]]


def creation_uri(kind: str, item_id: str) -> str:
    """A reference to a creation, as an agent sees it (ADR-0068 decision 5)."""
    return f"wasify://creation/{kind}/{item_id}"


class LibraryItem(BaseModel):
    kind: str
    id: str
    title: str  # what a person calls it: a prompt, a name, a title
    created_at: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)  # small facts: width, seconds, model

    @property
    def uri(self) -> str:
        return creation_uri(self.kind, self.id)


@dataclass(frozen=True)
class LibraryKind:
    kind: str  # the search kind: "image", "track", "speech" ...
    product_id: str
    noun: str  # for sentences: "picture", "song"
    list: ListItems
    get: GetItem
    delete: DeleteItem
    rename: RenameItem | None = None  # None: this kind has no name to change
    export: ExportItem | None = None  # (context, id, folder) -> the file written, or None
    read: ReadItem | None = None  # (context, id) -> the item's file, for another action to use
