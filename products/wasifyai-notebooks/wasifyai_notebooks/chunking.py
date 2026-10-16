# SPDX-License-Identifier: Apache-2.0
# Adapted from SurfSense (Apache-2.0), surfsense_local/backend/worker/ingestion/chunking.py, commit
# 622c1ded8. See ../PROVENANCE.md.
"""Cut a document's Markdown into passages the embedder can take whole."""

from functools import lru_cache
from pathlib import Path
from typing import Any, NamedTuple

from chonkie import RecursiveChunker, RecursiveLevel, RecursiveRules

# Under bge-small's 512-token limit, with room for the two it adds per input.
CHUNK_TOKENS = 480


class Passage(NamedTuple):
    """A stretch of the document, and where it was found in it (1-based lines of the Markdown)."""

    text: str
    start_line: int
    end_line: int


def chunk(markdown: str, *, tokenizer: Any, chunk_size: int = CHUNK_TOKENS) -> list[Passage]:
    """Split Markdown into passages of at most `chunk_size` tokens of `tokenizer`.

    `tokenizer` is a `tokenizers.Tokenizer`, or the string "word" (a whitespace count, for tests).
    """
    if not markdown.strip():
        return []

    chunker = RecursiveChunker(
        tokenizer=tokenizer,
        chunk_size=chunk_size,
        rules=_rules(),
        min_characters_per_chunk=24,
    )
    passages = (_passage(markdown, piece) for piece in chunker.chunk(markdown))
    return [p for p in passages if p.text]


def load_tokenizer(path: Path) -> Any:
    """The embedder's own tokenizer file. The boundaries are pinned to it rather than taken from
    whichever embedder is active: changing the embedder must not re-cut every document."""
    from tokenizers import Tokenizer

    return Tokenizer.from_file(str(path))


@lru_cache(maxsize=1)
def _rules() -> RecursiveRules:
    # Coarsest boundary first: heading, paragraph, line, sentence, word, then a bare split so an
    # over-budget line still terminates.
    return RecursiveRules(
        levels=[
            RecursiveLevel(delimiters=["\n#"], include_delim="next"),
            RecursiveLevel(delimiters=["\n\n"], include_delim="prev"),
            RecursiveLevel(delimiters=["\n"], include_delim="prev"),
            RecursiveLevel(delimiters=[". ", "! ", "? "], include_delim="prev"),
            RecursiveLevel(whitespace=True),
            RecursiveLevel(),
        ]
    )


def _passage(markdown: str, piece: Any) -> Passage:
    """Trim the separators Chonkie carries, and place the text by line."""
    lead = len(piece.text) - len(piece.text.lstrip())
    trail = len(piece.text) - len(piece.text.rstrip())
    start = piece.start_index + lead
    end = piece.end_index - trail
    return Passage(
        piece.text.strip(),
        markdown.count("\n", 0, start) + 1,
        markdown.count("\n", 0, max(start, end - 1)) + 1,
    )
