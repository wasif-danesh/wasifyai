# ruff: noqa: E501  (the sentences shown to people are easier to read on one line)
"""Teach it to decide: the questions, the examples and the report of a decision model (ADR-0075).

A decision model reads a text and answers one question about it, with how sure it is: yes or no, one
of several categories, or a score. A person gives texts with the right answers; this module cleans
them, says in words what is wrong with them, splits off the texts to check on, and turns what the
trained model said into the report. Nothing here trains and nothing here needs a model: the same
functions run in the screens' checks, the engine and the tests. The model is Laya (Apache-2.0), run
by `desktop_decision_training` in an environment of its own; it is asked in its own question format
(`Question.laya`) and its answers are read by `Question.read`."""

import math
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from wasifyai_training.language import personal_data, tidy

KINDS = ("yes_no", "category", "score")
MIN_EXAMPLES = 20  # fewer cannot be split into something to learn from and something to check on
GOOD_EXAMPLES = 60
PER_ANSWER = 5  # fewer of one answer than this is said, not refused (ADR-0075 open question 4)
MAX_TEXT = 6000  # characters kept of one text
LONG_TEXT = 2000  # roughly what the model reads (512 tokens): more is cut, and said
MAX_EXAMPLES = 5000
MAX_OPTIONS = 12  # the model gets weak with many categories (its card says over 20)
MIN_LEVELS, MAX_LEVELS, DEFAULT_LEVELS = 3, 10, 5
SEED = 3407
HELD_SHARE = 0.18
MAX_HELD = 200
YES, NO = "yes", "no"
_YES = {"yes", "y", "true", "1", "t", "positive"}
_NO = {"no", "n", "false", "0", "f", "negative"}
_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class Option:
    label: str
    about: str = ""


@dataclass(frozen=True)
class Question:
    """What the model is asked about every text, in the person's words."""

    kind: str
    text: str
    options: tuple[Option, ...] = ()  # category: the answers, each with what it means
    levels: int = DEFAULT_LEVELS  # score: 1 to this
    low: str = ""  # score: what 1 means
    high: str = ""  # and what the top level means

    def answers(self) -> list[str]:
        """Every answer it can give, in the order shown."""
        if self.kind == "yes_no":
            return [YES, NO]
        if self.kind == "score":
            return [str(n) for n in range(1, self.levels + 1)]
        return [o.label for o in self.options]

    def problem(self) -> str | None:
        """What is wrong with the question itself, in a sentence, or None."""
        if self.kind not in KINDS:
            return "Choose yes or no, a category or a score."
        if not self.text.strip():
            return "Write the question it should answer about every text."
        if len(self.text) > 300:
            return "Keep the question short: under 300 characters."
        if self.kind == "category":
            labels = [o.label.strip().lower() for o in self.options]
            if len(labels) < 2 or any(not x for x in labels):
                return "Give at least two categories, each with a name."
            if len(set(labels)) != len(labels):
                return "Two categories have the same name."
            if len(labels) > MAX_OPTIONS:
                return f"Use {MAX_OPTIONS} categories or fewer: it gets less sure with many."
        if self.kind == "score" and not MIN_LEVELS <= self.levels <= MAX_LEVELS:
            return f"A score goes from 1 to a number between {MIN_LEVELS} and {MAX_LEVELS}."
        return None

    def canon(self, raw: Any) -> str | None:
        """A typed answer as one of this question's answers, or None when it is not one of them."""
        text = tidy(str(raw if raw is not None else ""))
        low = text.lower()
        if self.kind == "yes_no":
            return YES if low in _YES else NO if low in _NO else None
        if self.kind == "score":
            try:
                n = float(low)
            except ValueError:
                return None
            return str(int(n)) if n == int(n) and 1 <= n <= self.levels else None
        for o in self.options:
            if o.label.strip().lower() == low:
                return o.label
        return None

    def laya(self) -> dict[str, Any]:
        """The question in the model's own format (its three types are `noul`, `choice`, `score`)."""
        if self.kind == "yes_no":
            return {"type": "noul", "instructions": self.text.strip()}
        if self.kind == "score":
            n = self.levels
            mid = {i: f"{i + 1} out of {n}" for i in range(1, n - 1)}
            crit = [
                self.low.strip() or "the lowest",
                *[mid[i] for i in range(1, n - 1)],
                self.high.strip() or "the highest",
            ]
            return {"type": "score", "instructions": self.text.strip(), "criteria": crit}
        return {
            "type": "choice", "instructions": self.text.strip(),
            "criteria": {o.label: o.about.strip() for o in self.options},
        }  # fmt: skip

    def expected(self, answer: str) -> Any:
        """The right answer as the trainer wants it: a truth value, a category, a level (from 0)."""
        if self.kind == "yes_no":
            return answer == YES
        if self.kind == "score":
            return int(answer) - 1
        return answer

    def read(self, raw: dict[str, Any]) -> "Said":
        """What the model said (its answer for this question, as it prints it) as an answer and how
        sure it is, with a share for every answer."""
        if self.kind == "yes_no":
            yes = float(raw.get("noul", 0.5))
            shares = {YES: yes, NO: 1 - yes}
        elif self.kind == "score":
            probs = raw.get("probabilities", {})
            shares = {str(int(k) + 1): float(v) for k, v in probs.items()}
        else:
            shares = {str(k): float(v) for k, v in raw.get("probabilities", {}).items()}
        top = max(shares, key=lambda k: shares[k]) if shares else ""
        return Said(
            top, round(shares.get(top, 0.0), 4), {k: round(v, 4) for k, v in shares.items()}
        )

    def public(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "text": self.text, "levels": self.levels, "low": self.low,
            "high": self.high, "options": [{"label": o.label, "about": o.about} for o in self.options],
        }  # fmt: skip


@dataclass(frozen=True)
class Said:
    answer: str
    confidence: float
    shares: dict[str, float]


@dataclass(frozen=True)
class Row:
    text: str
    answer: str  # one of the question's answers, as `Question.canon` gives it


def question_from(row: dict[str, Any]) -> Question:
    """The question of a stored set."""
    return Question(
        kind=row["kind"], text=row["question"],
        options=tuple(Option(str(o.get("label", "")), str(o.get("about", ""))) for o in row["options"]),
        levels=int(row["levels"]), low=row["low"], high=row["high"],
    )  # fmt: skip


def clean(q: Question, rows: list[dict[str, str]]) -> tuple[list[Row], list[str]]:
    """The usable examples (empty ones, answers that are not options and repeats dropped; case and
    spaces of an answer made the same) and what was dropped, in words."""
    out: list[Row] = []
    seen: set[tuple[str, str]] = set()
    empty = repeats = 0
    odd: list[str] = []
    for row in rows:
        text, raw = tidy(row.get("text", "")), tidy(row.get("answer", ""))
        if not text or not raw:
            empty += 1
            continue
        answer = q.canon(raw)
        if answer is None:
            odd.append(raw)
            continue
        key = (text.lower(), answer)
        if key in seen:
            repeats += 1
            continue
        seen.add(key)
        out.append(Row(text[:MAX_TEXT], answer))
    said = []
    if empty:
        said.append(
            f"{empty} {'row has' if empty == 1 else 'rows have'} a text or an answer missing and will be left out."
        )
    if odd:
        names = ", ".join(f"“{x[:30]}”" for x in dict.fromkeys(odd).keys())
        said.append(
            f"{len(odd)} {'row has' if len(odd) == 1 else 'rows have'} an answer that is not one of the options ({names[:120]}) and will be left out."
        )
    if repeats:
        said.append(f"{repeats} repeated {'row' if repeats == 1 else 'rows'} will be left out.")
    return out[:MAX_EXAMPLES], said


def checks(q: Question, rows: list[Row]) -> list[dict[str, str]]:
    """What to know about the set, in words: `level` is `error` (cannot start), `warn` or `ok`."""
    out: list[dict[str, str]] = []
    if why := q.problem():
        return [{"level": "error", "code": "question", "message": why}]
    n = len(rows)
    if n < MIN_EXAMPLES:
        return [
            {
                "level": "error",
                "code": "too_few",
                "message": f"Add at least {MIN_EXAMPLES} examples. You have {n}. {GOOD_EXAMPLES} or more is better.",
            }
        ]
    count = Counter(r.answer for r in rows)
    if len(count) < 2:
        return [
            {
                "level": "error",
                "code": "one_answer",
                "message": f"Every example has the same answer ({next(iter(count))}). Add examples with the other answers too.",
            }
        ]
    if n < GOOD_EXAMPLES:
        out.append(
            {
                "level": "warn",
                "code": "few",
                "message": f"Only {n} examples: it will be less sure. {GOOD_EXAMPLES} or more is better.",
            }
        )
    for a in q.answers():
        k = count.get(a, 0)
        if k < PER_ANSWER and q.kind != "yes_no":
            what = f"level {a}" if q.kind == "score" else f"“{a}”"
            out.append(
                {
                    "level": "warn",
                    "code": "thin",
                    "message": f"{what} has {'only ' if k else ''}{k} {'example' if k == 1 else 'examples'}. Try to give at least {PER_ANSWER}.",
                }
            )
        elif k < PER_ANSWER and q.kind == "yes_no":
            out.append(
                {
                    "level": "warn",
                    "code": "thin",
                    "message": f"“{a}” has {'only ' if k else ''}{k} {'example' if k == 1 else 'examples'}. Try to give at least {PER_ANSWER}.",
                }
            )
    top, share = count.most_common(1)[0][0], count.most_common(1)[0][1] / n
    if share >= 0.9 and len(count) >= 2:
        out.append(
            {
                "level": "warn",
                "code": "lopsided",
                "message": f"{round(share * 100)} percent of the examples answer “{top}”. It may just learn to say that. Add more of the others.",
            }
        )
    by_text: dict[str, set[str]] = {}
    for r in rows:
        by_text.setdefault(r.text.lower(), set()).add(r.answer)
    clash = sum(len(v) > 1 for v in by_text.values())
    if clash:
        out.append(
            {
                "level": "warn",
                "code": "clash",
                "message": f"{clash} {'text appears' if clash == 1 else 'texts appear'} more than once with different answers. Check which is right.",
            }
        )
    long = sum(len(r.text) > LONG_TEXT for r in rows)
    if long:
        out.append(
            {
                "level": "warn",
                "code": "long",
                "message": f"{long} {'text is' if long == 1 else 'texts are'} very long. Only the first part is read.",
            }
        )
    private = sum(personal_data(r.text) for r in rows)
    if private:
        out.append(
            {
                "level": "warn",
                "code": "personal",
                "message": f"{private} {'text looks' if private == 1 else 'texts look'} like {'it holds' if private == 1 else 'they hold'} personal data: an email address or a number. Check before you keep going.",
            }
        )
    if not out:
        out.append({"level": "ok", "code": "ok", "message": f"{n} examples, ready."})
    return out


def blocker(q: Question, rows: list[Row]) -> str | None:
    """The sentence that says why a run cannot start, or None."""
    for c in checks(q, rows):
        if c["level"] == "error":
            return c["message"]
    return None


def split(rows: list[Row], seed: int = SEED) -> tuple[list[Row], list[Row]]:
    """(to learn from, to check on): about a fifth of every answer is kept back, at least one of each
    answer that has two or more, at most 200 in all, chosen with a fixed seed."""
    rng = random.Random(seed)
    by_answer: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        by_answer.setdefault(r.answer, []).append(i)
    held: set[int] = set()
    for idx in by_answer.values():
        rng.shuffle(idx)
        if len(idx) >= 2:
            held.update(idx[: max(1, round(len(idx) * HELD_SHARE))])
    if len(held) > MAX_HELD:
        held = set(rng.sample(sorted(held), MAX_HELD))
    return (
        [r for i, r in enumerate(rows) if i not in held],
        [r for i, r in enumerate(rows) if i in held],
    )


QUALITY_EPOCHS = {"quick": 3, "better": 6}
MICRO_BATCH = 8
MIN_STEPS = 20
MAX_STEPS = 800


def plan_steps(train_rows: int, quality: str = "quick") -> tuple[int, int]:
    """(passes over the examples, steps): a step is one batch of 8. Never fewer than 20 steps (a
    small set gets more passes) and never so many that a big set takes an hour."""
    learn = train_rows - min(
        400, int(train_rows * 0.1)
    )  # the trainer keeps a tenth back to fit its confidence
    per_pass = max(1, math.ceil(learn / MICRO_BATCH))
    epochs = QUALITY_EPOCHS.get(quality, QUALITY_EPOCHS["quick"])
    epochs = max(epochs, math.ceil(MIN_STEPS / per_pass))
    epochs = max(1, min(epochs, MAX_STEPS // per_pass or 1))
    return epochs, per_pass * epochs


# ---- the plain word counter the sorter is compared with (ADR-0075 decision 6) -----------------


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


class WordCounter:
    """Multinomial Naive Bayes on the words of the text: trained in milliseconds, with no model. It
    is what a person could do without this feature, so a sorter that does worse has not helped."""

    def __init__(self, rows: list[Row]):
        self.prior = Counter(r.answer for r in rows)
        self.counts: dict[str, Counter[str]] = {a: Counter() for a in self.prior}
        vocab: set[str] = set()
        for r in rows:
            ws = _words(r.text)
            self.counts[r.answer].update(ws)
            vocab.update(ws)
        self.total = {a: sum(c.values()) for a, c in self.counts.items()}
        self.vocab = max(1, len(vocab))
        self.n = max(1, len(rows))

    def predict(self, text: str) -> str:
        ws = _words(text)
        best, best_score = "", -math.inf
        for a in sorted(self.prior):
            s = math.log(self.prior[a] / self.n)
            for w in ws:
                s += math.log((self.counts[a][w] + 1) / (self.total[a] + self.vocab))
            if s > best_score:
                best, best_score = a, s
        return best


# ---- the report (ADR-0075 decision 6) ----------------------------------------------------------

SURE = 0.8


def _off_by(q: Question, said: str, right: str) -> int:
    try:
        return abs(int(said) - int(right)) if q.kind == "score" else int(said != right) * 99
    except ValueError:
        return 99


def hits(q: Question, said: list[str], right: list[str]) -> int:
    """How many are right: exactly, or for a score right or one level off (the mark counts those)."""
    near = 1 if q.kind == "score" else 0
    return sum(_off_by(q, s, r) <= near for s, r in zip(said, right, strict=True))


def percent(k: int, n: int) -> int:
    return round(100 * k / n) if n else 0


def report(
    q: Question, held: list[Row], before: list[Said], after: list[Said], baseline: list[str]
) -> dict[str, Any]:
    """The honest report of a run on the texts kept back: how often it was right before and after
    the teaching and for a plain word counter, where it went wrong, whether its confidence can be
    trusted, and the mark."""
    n = len(held)
    right = [r.answer for r in held]
    exact_after = sum(s.answer == r for s, r in zip(after, right, strict=True))
    k_before = hits(q, [s.answer for s in before], right)
    k_after = hits(q, [s.answer for s in after], right)
    k_base = hits(q, baseline, right)
    per = []
    for a in q.answers():
        of = [i for i, r in enumerate(right) if r == a]
        per.append({"answer": a, "of": len(of), "right": sum(after[i].answer == a for i in of)})
    mix = Counter((r, s.answer) for r, s in zip(right, after, strict=True) if r != s.answer)
    mixups = [{"right": r, "said": s, "times": t} for (r, s), t in mix.most_common(3)]
    sure = [(s, s.answer == r) for s, r in zip(after, right, strict=True) if s.confidence >= SURE]
    sure_right = sum(ok for _, ok in sure)
    wrong = [
        {"text": h.text[:300], "right": h.answer, "said": s.answer, "confidence": round(s.confidence, 2)}
        for h, s in zip(held, after, strict=True) if s.answer != h.answer
    ][:10]  # fmt: skip
    near_note = " (right, or one level off)" if q.kind == "score" else ""
    passed = k_after >= k_base and k_after >= k_before and k_after > 0
    if n == 0:
        note, passed = "It could not be checked: no texts were kept back.", None
    elif passed:
        note = f"On {n} texts it had not seen, it was right {k_after} times ({percent(k_after, n)} percent){near_note}. Counting words alone was right {k_base} times ({percent(k_base, n)} percent)."
    else:
        why = (
            "a plain word counter did better"
            if k_base > k_after
            else "it did no better than before it was taught"
        )
        note = f"On {n} texts it had not seen, it was right {k_after} times ({percent(k_after, n)} percent){near_note}, but {why} ({k_base if k_base > k_after else k_before} times). It did not pass: add more examples, or clearer ones."
    if not sure:
        trust = "It was rarely very sure, so there is little to say about its confidence."
    else:
        trust = f"When it said it was at least {round(SURE * 100)} percent sure, it was right {sure_right} of {len(sure)} times."
    return {
        "texts": n,
        "right": {"before": k_before, "after": k_after, "word_counter": k_base, "exactly": exact_after},
        "percent": {"before": percent(k_before, n), "after": percent(k_after, n), "word_counter": percent(k_base, n)},
        "per_answer": per, "mix_ups": mixups, "confidence": {"note": trust, "sure": len(sure), "sure_right": sure_right},
        "wrong": wrong, "passed": passed, "note": note,
    }  # fmt: skip


def test_texts(rows: list[Row], held: list[Row], count: int = 3) -> list[str]:
    """Some texts to show the answers of, before and after: held-out ones first."""
    out: list[str] = []
    for r in [*held, *rows]:
        if r.text not in out:
            out.append(r.text)
        if len(out) == count:
            break
    return out


def rows_for_trainer(q: Question, rows: list[Row]) -> list[dict[str, Any]]:
    return [{"text": r.text, "expected": q.expected(r.answer)} for r in rows]


# ---- what the product and the engine hand each other ------------------------------------------


@dataclass
class DecisionJob:
    question: Question
    train: list[Row]
    held: list[Row]
    epochs: int
    steps: int
    peek: list[str]  # texts to show the answers of, before and after
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass
class DecisionResult:
    folder: Any  # the finished model's folder
    seconds: float
    engine: str
    before: list[Said]  # on the texts kept back
    after: list[Said]
    peek_before: list[Said]
    peek_after: list[Said]
    loss: list[float] = field(default_factory=list)  # the mean loss of each pass
    peak_bytes: int = 0
    bytes: int = 0
    note: str = ""
