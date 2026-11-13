# ruff: noqa: E501  (the sentences shown to people are easier to read on one line)
"""The examples of a language model, and what is checked before a run (ADR-0074 decision 5).

A person gives questions with the answers they would write; this module turns them into what the
trainer reads and says in words what is wrong with them. Nothing here trains and nothing here needs
a model: the same functions run in the screens' checks, the engine and the tests.

Chat records are `{"messages": [{"role": "user", ...}, {"role": "assistant", ...}]}`, the format of
`mlx-lm` and of Unsloth, so the trainer applies the base model's own chat template (and the app serves
with thinking switched off: the served prompt only equals the trained prompt that way, ADR-0074)."""

import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MIN_EXAMPLES = 10  # fewer cannot be split into something to learn from and something to check on
GOOD_EXAMPLES = 50  # the warning of ADR-0074: under this the result mostly copies what it saw
MAX_ASK = 2000  # characters a person can type for one question
MAX_ANSWER = 4000
LONG_ANSWER = 1500  # a warning, not a refusal
MAX_EXAMPLES = 2000
SEED = 3407  # the seed of the spike and of the split: the same set splits the same way

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d ().-]{8,}\d)(?!\d)")
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


@dataclass(frozen=True)
class Example:
    ask: str
    answer: str


def tidy(text: str) -> str:
    """A question or an answer as typed, with the ends and runs of blank lines tidied."""
    return re.sub(r"\n{3,}", "\n\n", (text or "").replace("\r\n", "\n")).strip()


def clean(rows: list[dict[str, str]]) -> tuple[list[Example], list[str]]:
    """The usable examples (empty ones dropped, repeats dropped, order kept) and what was dropped, in words."""
    out: list[Example] = []
    seen: set[tuple[str, str]] = set()
    empty = repeats = 0
    for row in rows:
        ask, answer = tidy(row.get("ask", "")), tidy(row.get("answer", ""))
        if not ask or not answer:
            empty += 1
            continue
        key = (ask.lower(), answer.lower())
        if key in seen:
            repeats += 1
            continue
        seen.add(key)
        out.append(Example(ask[:MAX_ASK], answer[:MAX_ANSWER]))
    said = []
    if empty:
        said.append(
            f"{empty} {'row has' if empty == 1 else 'rows have'} a question or an answer missing and will be left out."
        )
    if repeats:
        said.append(f"{repeats} repeated {'row' if repeats == 1 else 'rows'} will be left out.")
    return out[:MAX_EXAMPLES], said


def personal_data(text: str) -> bool:
    """Whether the text looks like it holds an email address, a phone number or a card number."""
    return bool(_EMAIL.search(text) or _PHONE.search(text) or _CARD.search(text))


def checks(examples: list[Example]) -> list[dict[str, str]]:
    """What to know about the set, in words: `level` is `error` (cannot start), `warn` or `ok`."""
    n = len(examples)
    out: list[dict[str, str]] = []
    if n < MIN_EXAMPLES:
        out.append(
            {
                "level": "error",
                "code": "too_few",
                "message": f"Add at least {MIN_EXAMPLES} examples. You have {n}. 50 or more is better.",
            }
        )
        return out
    if n < GOOD_EXAMPLES:
        out.append(
            {
                "level": "warn",
                "code": "few",
                "message": f"Only {n} examples: the result will mostly copy them. 50 or more is better.",
            }
        )
    long = sum(len(e.answer) > LONG_ANSWER for e in examples)
    if long:
        out.append(
            {
                "level": "warn",
                "code": "long",
                "message": f"{long} {'answer is' if long == 1 else 'answers are'} very long. Short answers teach a style faster.",
            }
        )
    private = sum(personal_data(e.ask) or personal_data(e.answer) for e in examples)
    if private:
        out.append(
            {
                "level": "warn",
                "code": "personal",
                "message": f"{private} {'example looks' if private == 1 else 'examples look'} like they hold personal data: an email address or a number. Check before you keep going.",
            }
        )
    if not out:
        out.append({"level": "ok", "code": "ok", "message": f"{n} examples, ready."})
    return out


def blocker(examples: list[Example]) -> str | None:
    """The sentence that says why a run cannot start, or None."""
    for c in checks(examples):
        if c["level"] == "error":
            return c["message"]
    return None


def split(examples: list[Example], seed: int = SEED) -> tuple[list[Example], list[Example]]:
    """(to learn from, to check on): a tenth, at least 2 and at most 20 of them, chosen with a fixed seed."""
    order = list(range(len(examples)))
    random.Random(seed).shuffle(order)
    held = min(20, max(2, round(len(examples) * 0.1)))
    valid = {i for i in order[:held]}
    return (
        [e for i, e in enumerate(examples) if i not in valid],
        [e for i, e in enumerate(examples) if i in valid],
    )


def record(e: Example) -> dict[str, Any]:
    return {
        "messages": [{"role": "user", "content": e.ask}, {"role": "assistant", "content": e.answer}]
    }


def jsonl(examples: list[Example]) -> str:
    return "".join(json.dumps(record(e), ensure_ascii=False) + "\n" for e in examples)


# the steps: a few passes over the examples, never fewer than the least that learns a style in
# the spike (30 steps of 2 on 40 rows, 12 of 12 held-out replies in the style) and never so many
# that a small set is copied word for word
PASSES = {"quick": 3, "better": 6}
BATCH = 2
MIN_STEPS = 30
MAX_STEPS = 600


def steps_for(train_rows: int, quality: str = "quick") -> int:
    per_pass = max(1, -(-train_rows // BATCH))
    return min(MAX_STEPS, max(MIN_STEPS, per_pass * PASSES.get(quality, PASSES["quick"])))


def test_questions(examples: list[Example], valid: list[Example], count: int = 3) -> list[str]:
    """The questions the model is asked before and after (held-out ones first): how it answers now."""
    pool = [e.ask for e in valid] + [e.ask for e in examples]
    out: list[str] = []
    for q in pool:
        if q not in out:
            out.append(q)
        if len(out) == count:
            break
    return out


# ---- what the product and the engine hand each other (the engine imports these) ---------------


@dataclass
class LanguageJob:
    train: list[dict[str, Any]]  # chat records
    valid: list[dict[str, Any]]
    steps: int
    questions: list[str]
    batch: int = 2
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass
class LanguageResult:
    adapter: Path  # the folder with `adapters.safetensors` and `adapter_config.json`
    seconds: float
    engine: str
    first_val: float | None = None  # the loss on the held-out examples before it learned
    last_val: float | None = None  # and after
    last_train: float | None = None
    peak_bytes: int = 0
    note: str = ""


class Stopped(Exception):
    """The run was stopped on request and nothing was kept."""
