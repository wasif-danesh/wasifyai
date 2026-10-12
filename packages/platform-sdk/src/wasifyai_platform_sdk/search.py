"""What a product gives the platform so that its creations can be found by search (ADR-0041).

Every kind of thing a user can make and keep must be indexed: when it is saved
(`Capabilities.index_creation`), when it is deleted (`RouteDeps.unindex`), and through an
`IndexSource` the platform uses to backfill and to clean up. A new product or a new kind of creation
is not finished until it does all three, and has a card in My creations."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Protocol

log = logging.getLogger(__name__)

CreationKind = Literal["song", "image", "video", "speech", "transcript", "lipsync"]
KINDS: tuple[str, ...] = ("song", "image", "video", "speech", "transcript", "lipsync")
MAX_TEXT_CHARS = 6000  # what is embedded: more adds cost, not meaning


@dataclass(frozen=True)
class IndexItem:
    """One creation's searchable words, as a product lists them for the index."""

    tenant_id: str
    product_id: str
    user_id: str
    kind: str
    item_id: str
    text: str


class IndexSource(Protocol):
    """A product's way to list what should be in the index. The platform pages through it to fill
    gaps (items made before search existed, or while the embedder was down) and to find rows whose
    item is gone. `page` returns items with `item_id` greater than `after`, in ascending order."""

    product_id: str
    kind: str

    async def page(self, after: str | None, limit: int) -> list[IndexItem]: ...

    async def present(self, item_ids: list[str]) -> set[str]:
        """Which of these ids still exist (and are finished, if a creation can be unfinished)."""
        ...


# factory(engine) -> source: registered by the product, built by the API once the database exists.
IndexSourceFactory = Callable[..., IndexSource]


class CreationIndexer(Protocol):
    """What a product's graph uses, through `Capabilities.index_creation`. It reads the tenant,
    product and user from the run context."""

    async def index(self, kind: str, item_id: str, text: str) -> None: ...


def search_text(*parts: str | None, limit: int = MAX_TEXT_CHARS) -> str:
    """The words to index, from a creation's parts (title, style, lyrics, prompt): blank parts
    dropped, cut at `limit` characters. Parts run together as sentences and line breaks become
    spaces: measured on bge-m3, text split by line breaks scored about 0.04 lower against the same
    query than the same words as running text, enough to fall under the similarity floor."""
    cleaned = (" ".join(p.split()) for p in parts if p and p.strip())
    joined = ". ".join(c.rstrip(".") for c in cleaned if c.strip("."))
    return joined[:limit]


IndexCall = Callable[[str, str, str], Awaitable[None]]
