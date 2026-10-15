"""A small embedder that needs no model, for an engine that has no embedding gateway yet.

The desktop profile starts without a model gateway (ADR-0056), but every creation still has to be
searchable (ADR-0041). This turns text into a fixed-size vector of hashed words and word pieces:
two texts that share words are close, in any script that separates words with spaces or
punctuation, and a word and its plural or a near spelling share most of their pieces. It is not
semantic: "dog" and "puppy" are far apart. Rows it makes carry its own model name, so the
background indexer replaces them with real embeddings once a gateway is configured."""

import math
import re
import zlib

MODEL = "local-hash/v1"
DIMENSIONS = 256
_WORD = re.compile(r"\w+", re.UNICODE)


def _pieces(word: str) -> list[str]:
    padded = f"^{word}$"
    grams = [padded[i : i + 3] for i in range(len(padded) - 2)] if len(padded) > 3 else []
    return [word, *grams]


def embed_one(text: str) -> list[float]:
    vector = [0.0] * DIMENSIONS
    for word in _WORD.findall(text.lower()):
        for piece in _pieces(word):
            vector[zlib.crc32(piece.encode()) % DIMENSIONS] += 1.0
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else vector


async def hashing_embed(texts: list[str]) -> list[list[float]]:
    return [embed_one(t) for t in texts]
