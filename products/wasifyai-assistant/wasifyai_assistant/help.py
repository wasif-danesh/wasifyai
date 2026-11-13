"""What the assistant knows about the app's features (ADR-0071 decisions 1 and 2): the help
corpus, searched by words and synonyms.

`help.json` is written from `docs/help/*.md` by `wasifyai_api.assistant_features --write` (one
entry per action offered to the assistant), never typed by hand, and ships inside this package.
The search is small and local: a question is split into words, and each guide scores by the
synonyms it lists (the words people use), its title, its action id and the words of its body. No
model, no network. Real embeddings (the notebooks' search model) are a later, measured step."""

import json
import re
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

FILE = Path(__file__).with_name("help.json")
MAX_PASSAGE = 1800  # characters of a guide the model is given
WORD = re.compile(r"[a-z0-9]+")
STOP = frozenset(
    "a an the to of in on for and or is are it i my me do does can how what with this that "
    "from into as at be by make get use want need own app one some here there you your just "
    "version out up have has had will would could should if then than so very really please".split()
)
BODY_CAP = 2.5  # the body's words say less than the title and the synonyms


def words(text: str) -> list[str]:
    return [w for w in WORD.findall(text.lower()) if w not in STOP]


def _stem(word: str) -> str:
    """Enough stemming to match 'pictures' with 'picture' and 'speaking' with 'speak'."""
    for end in ("ing", "ies", "es", "s"):
        if word.endswith(end) and len(word) - len(end) >= 3:
            return word[: -len(end)] + ("y" if end == "ies" else "")
    return word


@dataclass(frozen=True)
class Guide:
    action: str
    title: str
    screen: str | None
    synonyms: tuple[str, ...]
    body: str

    @property
    def passage(self) -> str:
        text = self.body if len(self.body) <= MAX_PASSAGE else self.body[:MAX_PASSAGE] + "…"
        return f"# {self.title} (action {self.action})\n{text}"


@cache
def _guides() -> tuple[Guide, ...]:
    try:
        rows = json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    out = []
    for r in rows:
        if isinstance(r, dict) and isinstance(r.get("action"), str):
            out.append(
                Guide(
                    action=r["action"],
                    title=str(r.get("title") or r["action"]),
                    screen=r.get("screen") if isinstance(r.get("screen"), str) else None,
                    synonyms=tuple(str(s) for s in r.get("synonyms") or ()),
                    body=str(r.get("body") or ""),
                )
            )
    return tuple(out)


def guides(served: Collection[str] | None = None) -> list[Guide]:
    """The guides of the actions this engine serves (all of them when `served` is None)."""
    return [g for g in _guides() if served is None or g.action in served]


def _score(guide: Guide, question: str, qwords: list[str]) -> float:
    stems = {_stem(w) for w in qwords}
    if not stems:
        return 0.0
    score = 0.0
    q = question.lower()
    if guide.action in q or guide.action.replace(".", " ") in q:
        score += 6
    credited: set[str] = set()  # a stem counts once, however many synonyms hold it
    for s in guide.synonyms:
        s_l = s.lower()
        s_words = {_stem(w) for w in words(s_l)}
        new = s_words - credited
        if s_l and s_l in q:
            score += 8 if new else 2
        elif s_words and s_words <= stems and new:
            score += 5 if len(s_words) > 1 else 3  # all its words, in another order
        elif new & stems:
            score += 1.5 * len(new & stems) / len(s_words)
        credited |= s_words & stems
    title = {_stem(w) for w in words(guide.title)}
    score += 3 * len(title & stems)
    body = {_stem(w) for w in words(guide.body)}
    score += min(BODY_CAP, 0.5 * len(body & stems))
    return score


def search(question: str, served: Collection[str] | None = None, limit: int = 3) -> list[Guide]:
    """The best guides for a question, best first; none when nothing matches at all."""
    qwords = words(question)
    scored = [(_score(g, question, qwords), g) for g in guides(served)]
    best = sorted((p for p in scored if p[0] > 0), key=lambda p: (-p[0], p[1].action))
    return [g for _, g in best[:limit]]


def titles(served: Iterable[str]) -> dict[str, str]:
    """Action id -> its guide's title, for the list of actions in the system prompt."""
    return {g.action: g.title for g in guides(set(served))}


def screens(served: Collection[str] | None = None) -> dict[str, str]:
    """Screen id -> the title of a guide that opens there (for `open_screen`)."""
    out: dict[str, str] = {}
    for g in guides(served):
        if g.screen and g.screen not in out:
            out[g.screen] = g.title
    return out


def as_rows(found: list[Guide]) -> list[dict[str, Any]]:
    return [
        {"action": g.action, "title": g.title, "screen": g.screen, "text": g.passage} for g in found
    ]
