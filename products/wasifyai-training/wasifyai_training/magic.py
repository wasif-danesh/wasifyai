"""Magic words (ADR-0076 decision 3): a made-up word that stands for the person's character or
style in a prompt. A good one is rare (the model has no meaning for it), short, in lower case
letters, and does not look like a word the model knows. The app suggests three; the first is
chosen.

The check against the real tokenizer (a good word splits into two or three pieces and each piece is
uncommon) comes with the real trainer; here the words are made from sounds that are not English
words and are checked against a list of common words and against each other."""

import hashlib
import re

ONSETS = [
    "b",
    "d",
    "f",
    "g",
    "k",
    "l",
    "m",
    "n",
    "p",
    "r",
    "s",
    "t",
    "v",
    "z",
    "br",
    "dr",
    "kr",
    "pl",
    "tr",
    "zh",
]
VOWELS = ["a", "e", "i", "o", "u", "ai", "oa", "ee"]
CODAS = ["", "n", "r", "l", "x", "k", "m"]
COMMON = {
    "the",
    "and",
    "man",
    "woman",
    "boy",
    "girl",
    "dog",
    "cat",
    "bird",
    "tree",
    "car",
    "house",
    "love",
    "star",
    "moon",
    "sun",
    "blue",
    "red",
    "green",
    "gold",
    "king",
    "queen",
    "baby",
    "hero",
    "magic",
}  # a word the model knows well is a poor magic word


def _clean(word: str) -> str:
    return re.sub(r"[^a-z]", "", word.lower())


def valid(word: str) -> bool:
    w = _clean(word)
    return 4 <= len(w) <= 12 and w == word and w not in COMMON


def suggest(name: str, kind: str, taken: set[str] | None = None, n: int = 3) -> list[str]:
    """Up to `n` words, the same for the same name and kind. The person's own name (when it is not
    a common word) is a candidate: "marlo" is fine, "dog" is not."""
    taken = {_clean(t) for t in (taken or set())}
    out: list[str] = []

    def add(word: str) -> None:
        if valid(word) and word not in taken and word not in out:
            out.append(word)

    own = _clean(name)
    if own and valid(own):
        add(own)
    seed = hashlib.sha256(f"{own}:{kind}".encode()).digest()
    i = 0
    while len(out) < n and i < 200:
        a, b, c, d, e = (seed[(i * 5 + k) % len(seed)] for k in range(5))
        add(
            ONSETS[a % len(ONSETS)]
            + VOWELS[b % len(VOWELS)]
            + ONSETS[c % len(ONSETS)]
            + VOWELS[d % len(VOWELS)]
            + CODAS[e % len(CODAS)]
        )
        i += 1
        seed = hashlib.sha256(seed).digest() if i % 4 == 0 else seed
    return out[:n]
