# SPDX-License-Identifier: Apache-2.0
# Adapted from SurfSense (Apache-2.0), worker/studio/office/markdown/blocks.py (the desktop
# app's backend), commit 622c1ded8. See ../../PROVENANCE.md.
"""The document a Markdown spec describes, as both builders walk it."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    """A run of text with one set of marks."""

    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    strike: bool = False
    href: str | None = None


Spans = tuple[Span, ...]


@dataclass(frozen=True)
class Heading:
    level: int
    spans: Spans


@dataclass(frozen=True)
class Paragraph:
    spans: Spans


@dataclass(frozen=True)
class ListBlock:
    ordered: bool
    # Each item is its own blocks: a paragraph, then any nested list.
    items: tuple[tuple["Block", ...], ...]


@dataclass(frozen=True)
class Table:
    header: tuple[Spans, ...]
    rows: tuple[tuple[Spans, ...], ...]


@dataclass(frozen=True)
class Figure:
    """A source figure; `name` is None when the target is not `image:<name>`."""

    name: str | None
    caption: str


@dataclass(frozen=True)
class Code:
    text: str


@dataclass(frozen=True)
class Quote:
    blocks: tuple["Block", ...]


@dataclass(frozen=True)
class Rule:
    pass


Block = Heading | Paragraph | ListBlock | Table | Figure | Code | Quote | Rule
