"""Plain words to the fields of a template (the prompt box of Motion graphics, ADR-0079).

A model reads "lower third for \"Maya Chen\", Head of Design" and chooses a template and fills its
fields. It only fills fields: the page is made by the template, the words stay what the person
typed, and the exact-text check still runs before anything is drawn. What this module adds is
caution about the model:

- a word the person put in quotes must come back exactly as written, or the person is told;
- the rows of an attached CSV file never pass through the model, so a number cannot be retyped;
- what the model got wrong is said in words, and the form is still filled so it can be fixed."""

import csv
import io
import json
import re
from typing import Any, Protocol

from wasifyai_video.builder import templates

MAX_PROMPT = 2000
MAX_CSV_BYTES = 40_000
MAX_ROWS = 8

SETTINGS = ("seconds", "shape", "theme", "font")
TEXT_KEYS = ("title", "subtitle", "quote", "author", "data", "name", "role", "lines")  # in forms


class Engine(Protocol):
    async def complete(
        self, system: str, prompt: str, schema: dict[str, Any], max_tokens: int = 800
    ) -> str: ...


class DraftError(Exception):
    """Something the person can fix, in words."""

    def __init__(self, message: str, code: str = "bad_draft"):
        super().__init__(message)
        self.message = message
        self.code = code


def _choices(field_id: str) -> list[str]:
    for t in templates.TEMPLATES.values():
        for f in t.fields:
            if f.id == field_id:
                return [v for v, _ in f.choices]
    return []


def choose_schema() -> dict[str, Any]:
    """Step one: which template. A small model answers a one-key schema reliably; the long
    union of every template's fields in one answer made it ramble."""
    return {
        "type": "object",
        "properties": {"template": {"type": "string", "enum": list(templates.TEMPLATES)}},
        "required": ["template"], "additionalProperties": False,
    }  # fmt: skip


def fields_schema(template: str) -> dict[str, Any]:
    """Step two: the fields of that template only. The words are required (an empty string means
    "not given"); the length and the looks may be left out, which is what a small model does well:
    asked for every key it wrote the words and then wrote blanks until it ran out of room."""
    props: dict[str, Any] = {}
    required: list[str] = []
    for f in templates.get(template).fields:
        if f.kind == "seconds":
            props[f.id] = {"type": "integer"}
        elif f.kind == "choice":
            props[f.id] = {"type": "string", "enum": [v for v, _ in f.choices]}
        else:
            props[f.id] = {"type": "string"}
            required.append(f.id)
    return {
        "type": "object", "properties": props, "required": required,
        "additionalProperties": False,
    }  # fmt: skip


def _template_lines() -> str:
    return "\n".join(f"- {t.id}: {t.description}" for t in templates.TEMPLATES.values())


CHOOSE_RULES = (
    "You choose the template for a request for a short animated graphic. Answer only with the "
    "JSON the schema asks for.\nTemplates:\n{templates}\n"
    "A name and a job title is a lower_third. Typed captions or subtitles is captions. A saying "
    "with an author is a quote. Numbers to compare, or a file of them, is a chart. Otherwise it "
    "is a title.\n"
)
FILL_RULES = (
    "You fill in the fields of the {title} template ({description}) from a request. Answer only "
    "with the JSON the schema asks for.\n"
    "- Copy the person's own words exactly, character for character: anything in quotes, every "
    "name, every number. Never correct, translate, shorten, reword or reformat them.\n"
    "- Use an empty string for words the request does not give; never invent words for optional "
    "fields. Leave out seconds, shape, theme and font unless the request asks for them.\n"
    "- Fields: {fields}\n"
)


def choose_prompt() -> str:
    return CHOOSE_RULES.format(templates=_template_lines())


def fill_prompt(template: str, has_file: bool) -> str:
    t = templates.get(template)
    fields = "; ".join(f"{f.id} = {_describe(f)}" for f in t.fields)
    file_rule = (
        "A CSV file is attached and the app takes the rows from it: leave data empty, and give "
        "only the title.\n"
        if has_file
        else ""
    )
    return (
        FILL_RULES.format(title=t.title.lower(), description=t.description, fields=fields)
        + file_rule
    )


def _describe(f: templates.Field) -> str:
    if f.kind == "rows":
        return "one bar per line like 'North, 120' (numbers exactly as written)"
    if f.kind == "lines":
        return "one caption per line"
    if f.kind == "seconds":
        return f"a length in seconds ({f.minimum} to {f.maximum}), only if one was asked for"
    if f.kind == "choice":
        return "only if asked for: " + ", ".join(v for v, _ in f.choices)
    return f.label.lower() + (", required" if f.required else ", optional")


# ---- the attached file -------------------------------------------------------------------------


def _rejoin_thousands(rows: list[list[str]], delimiter: str) -> list[list[str]]:
    """A comma-separated file whose rows are mostly two cells, with a few longer rows, has
    written numbers like 1,200.5 without quotes: join the cells after the label back together
    when that makes one number (the person's own digits, in their own order)."""
    if delimiter != "," or not rows:
        return rows
    counts = [len(r) for r in rows]
    usual = max(set(counts), key=counts.count)
    if usual != 2:
        return rows
    out = []
    for r in rows:
        if len(r) > 2 and templates.parse_number(",".join(r[1:])) is not None:
            r = [r[0], ",".join(r[1:])]
        out.append(r)
    return out


def csv_rows(text: str, name: str = "the file") -> tuple[str, list[str]]:
    """The chart lines ("label, value") of a CSV file, and what was left out. The first column is
    the label and the first column after it that holds a number is the value; a header row is
    skipped; the values are kept exactly as written."""
    if len(text.encode("utf-8", "ignore")) > MAX_CSV_BYTES:
        raise DraftError(f"{name} is too big for a chart: use a file under 40 KB.", "bad_file")
    text = text.lstrip("﻿")
    try:
        dialect = csv.Sniffer().sniff(text[:2000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), dialect) if any(r)]
    rows = _rejoin_thousands(rows, dialect.delimiter)
    lines: list[str] = []
    if rows and len(rows[0]) >= 3 and all(_YEAR.match(c) for c in rows[0][1:]):
        rows = rows[1:]  # a header of years ("City,2025,2026")
    for i, row in enumerate(rows):
        if len(row) < 2 or not row[0]:
            continue
        value = next((c for c in row[1:] if templates.parse_number(c) is not None), None)
        if value is None:
            if i == 0:
                continue  # a header
            raise DraftError(
                f"Row {i + 1} of {name} has no number in it. A chart needs a label and a number "
                "on each row.",
                "bad_file",
            )
        lines.append(f"{row[0]}, {value}")
    if len(lines) < 2:
        raise DraftError(
            f"{name} needs at least two rows, each with a label and a number.", "bad_file"
        )
    warnings = []
    if len(lines) > MAX_ROWS:
        warnings.append(
            f"A chart shows {MAX_ROWS} bars: the first {MAX_ROWS} of the {len(lines)} rows "
            "of the file are used."
        )
        lines = lines[:MAX_ROWS]
    return "\n".join(lines), warnings


# ---- checking what the model said ----------------------------------------------------------------

_YEAR = re.compile(r"^(19|20)\d\d$")
_QUOTED = re.compile(r"[\"“„«]([^\"”“»]{2,200})[\"”»]")


def quoted(prompt: str) -> list[str]:
    """What the person put in quotation marks."""
    return [m.group(1).strip() for m in _QUOTED.finditer(prompt) if m.group(1).strip()]


def _text_values(fields: dict[str, Any]) -> str:
    return "\n".join(str(v) for k, v in fields.items() if k in TEXT_KEYS)


def verbatim_warnings(prompt: str, fields: dict[str, Any]) -> list[str]:
    seen = _text_values(fields)
    return [
        f"“{q}” is not in the form exactly as you wrote it. Check the words before you go on."
        for q in quoted(prompt)
        if q not in seen
    ]


def summary(template: str, fields: dict[str, Any]) -> str:
    t = templates.get(template)
    shown = []
    for f in t.fields:
        value = fields.get(f.id)
        if value in (None, "") or f.kind not in ("text", "longtext", "lines", "rows"):
            continue
        text = str(value).replace("\n", " / ")
        shown.append(f"{f.label.lower()} “{text if len(text) <= 60 else text[:57] + '...'}”")
    return f"{t.title}: " + (", ".join(shown) if shown else "no words yet")


def _close(raw: str) -> Any:
    """An answer that stopped before its closing brace (a model that ran out of things to say and
    wrote blanks): close it, and give up if that does not make an object."""
    text = raw.rstrip()
    if not text.startswith("{") or text.endswith("}"):
        return None
    try:
        return json.loads(text.rstrip(",") + "}")
    except ValueError:
        return None


async def _ask(engine: Engine, system: str, request: str, schema: dict[str, Any]) -> Any:
    raw = await engine.complete(system, request, schema)
    try:
        answer = json.loads(raw)
    except ValueError:
        answer = _close(raw)
    if not isinstance(answer, dict):
        raise DraftError(
            "The model's answer could not be read. Try again, or fill in the form yourself.",
            "bad_answer",
        )
    return answer


async def _choose(engine: Engine, request: str) -> str:
    answer = await _ask(engine, choose_prompt(), request, choose_schema())
    if answer.get("template") not in templates.TEMPLATES:
        raise DraftError(
            "The model's answer could not be read. Try again, or fill in the form yourself.",
            "bad_answer",
        )
    return str(answer["template"])


async def _fill(engine: Engine, template: str, request: str, has_file: bool) -> dict[str, Any]:
    return await _ask(engine, fill_prompt(template, has_file), request, fields_schema(template))


# ---- settings the person did not ask for ---------------------------------------------------------

# A small model fills a look it was never asked for ("square", "paper"). A setting is kept only when
# the request has a word that asks for it; the rest stay at the template's own defaults.
ASKED = {
    ("shape", "portrait"): ("portrait", "vertical", "tiktok", "reel", "stories", "story", "9:16"),
    ("shape", "square"): ("square", "1:1", "instagram post"),
    ("shape", "landscape"): ("landscape", "horizontal", "widescreen", "wide", "16:9", "youtube"),
    ("theme", "midnight"): ("midnight", "dark", "night", "navy", "blue"),
    ("theme", "sunrise"): ("sunrise", "sunset", "warm", "orange", "pink", "purple"),
    ("theme", "forest"): ("forest", "green"),
    ("theme", "paper"): ("paper", "light", "cream", "white", "beige"),
    ("font", "sans"): ("sans", "modern", "clean"),
    ("font", "serif"): ("serif", "elegant", "classic", "editorial"),
}
_LENGTH = re.compile(r"(\d+(?:\.\d+)?)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes)\b")


def asked_for(prompt: str, key: str, value: Any) -> bool:
    """Whether the request asks for this setting (`key` = `value`)."""
    text = prompt.lower()
    if key == "seconds":
        for number, unit in _LENGTH.findall(text):
            seconds = float(number) * (60 if unit.startswith("m") else 1)
            if round(seconds) == value:
                return True
        return False
    return any(word in text for word in ASKED.get((key, str(value)), ()))


# ---- the draft -------------------------------------------------------------------------------


async def draft(
    engine: Engine,
    prompt: str,
    attachment: dict[str, str] | None = None,
    shape: str | None = None,
) -> dict[str, Any]:
    """`{template, fields, warnings, summary}`: the template and the form text to start from."""
    prompt = prompt.strip()
    if len(prompt) > MAX_PROMPT:
        raise DraftError(f"Describe it in {MAX_PROMPT} characters or fewer.")
    warnings: list[str] = []
    rows = ""
    if attachment and attachment.get("text", "").strip():
        rows, warnings = csv_rows(attachment["text"], attachment.get("name") or "The file")
    elif not prompt:
        raise DraftError("Describe what to make, or attach a CSV file.")
    request = prompt or "A chart of the attached file."
    template = "chart" if rows else await _choose(engine, request)
    answer = await _fill(engine, template, request, bool(rows))
    allowed = {f.id for f in templates.get(template).fields}
    fields: dict[str, Any] = {}
    for key, value in answer.items():
        if key not in allowed or value in (None, "", 0):
            continue
        if key in SETTINGS and not asked_for(prompt, key, value):
            continue
        fields[key] = value if isinstance(value, int) else str(value)
    if rows:
        fields["data"] = rows
        if not fields.get("title"):  # the file's own name, when no title was given
            stem = (attachment or {}).get("name", "").rsplit(".", 1)[0].strip()
            fields["title"] = stem[:80] or "Chart"
    if shape in _choices("shape"):
        fields["shape"] = shape
    warnings += verbatim_warnings(prompt, fields)
    try:
        templates.normalize_slots(template, fields)
    except templates.SlotError as e:
        warnings.append(str(e))
    return {
        "template": template, "fields": fields, "warnings": warnings,
        "summary": summary(template, fields),
    }  # fmt: skip
