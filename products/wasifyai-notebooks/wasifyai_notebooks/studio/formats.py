# SPDX-License-Identifier: Apache-2.0
# The structure of each format (schemas, the outline, the ceilings, what is kept when a reply is
# loose) follows SurfSense's `worker/studio/content/*` (Apache-2.0, commit 622c1ded8). See
# ../../PROVENANCE.md.
"""The formats a notebook can make from its sources, and how a model's reply becomes each of them
(ADR-0010's rule, ADR-0065 decision 11): the model writes Markdown or validated JSON and a
committed builder renders it. Nothing a model writes is ever run.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Any

PROMPTS = Path(__file__).with_name("prompts")

CARDS = 20
QUESTIONS = 10
OPTIONS = 4
BRANCHES = 10
MAX_TITLE = 200


@dataclass(frozen=True)
class Format:
    key: str
    label: str
    #: the folder of prompts
    prompt: str
    #: JSON the model is held to (a grammar on the local engine), or None for Markdown
    schema: dict[str, Any] | None = None
    #: what the person gets besides the body, if anything
    file: str | None = None  # "md" | "json" | "docx" | "pdf"
    #: a steer when the person gave none
    default_focus: str = ""
    max_tokens: int = 3000


SCHEMA_CARDS = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"front": {"type": "string"}, "back": {"type": "string"}},
                "required": ["front", "back"],
            },
        },
    },
    "required": ["title", "cards"],
}

SCHEMA_QUIZ = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": OPTIONS,
                        "maxItems": OPTIONS,
                    },
                    "answer": {"type": "string"},
                    "explanation": {"type": "string"},
                },
                "required": ["question", "options", "answer", "explanation"],
            },
        },
    },
    "required": ["title", "questions"],
}

# a mind map's depth is the prompt's to ask for; a recursive schema is not asked of the grammar
SCHEMA_MINDMAP = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "children": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "children": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {"label": {"type": "string"}},
                                        "required": ["label"],
                                    },
                                },
                            },
                            "required": ["label"],
                        },
                    },
                },
                "required": ["label"],
            },
        },
    },
    "required": ["title", "nodes"],
}

SLIDES = 12
TABLE_ROWS = 40
TABLE_COLUMNS = 8
TURNS = 40
SECTIONS = 8
TOPICS = 8
QUESTIONS_ASKED = 5
HOSTS = ("Alex", "Sam")

SCHEMA_SLIDES = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "slides": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                    "notes": {"type": "string"},
                },
                "required": ["title", "bullets", "notes"],
            },
        },
    },
    "required": ["title", "slides"],
}

SCHEMA_TABLE = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "columns": {"type": "array", "items": {"type": "string"}},
        "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
    },
    "required": ["title", "columns", "rows"],
}

SCHEMA_AUDIO = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "turns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"speaker": {"type": "integer"}, "text": {"type": "string"}},
                "required": ["speaker", "text"],
            },
        },
    },
    "required": ["title", "turns"],
}

SCHEMA_INFOGRAPHIC = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "value": {"type": "string"},
                    "detail": {"type": "string"},
                },
                "required": ["label", "value", "detail"],
            },
        },
    },
    "required": ["title", "summary", "sections"],
}

SCHEMA_GUIDE = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "topics": {"type": "array", "items": {"type": "string"}},
        "questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "topics", "questions"],
}

FORMATS: dict[str, Format] = {
    f.key: f
    for f in (
        Format("report", "Report", "report", file="md"),
        Format(
            "study_guide",
            "Study guide",
            "report",
            file="md",
            default_focus=(
                "a study guide: the key terms with their definitions, the main ideas, and what "
                "to remember, with a short list of questions to check understanding at the end"
            ),
        ),
        Format("flashcards", "Flashcards", "flashcards", SCHEMA_CARDS, file="json"),
        Format("quiz", "Quiz", "quiz", SCHEMA_QUIZ, file="json"),
        Format("mindmap", "Mind map", "mindmap", SCHEMA_MINDMAP, max_tokens=2000),
        Format("word", "Word document", "report", file="docx"),
        Format("pdf", "PDF", "report", file="pdf"),
        Format("slides", "Slide deck", "slides", SCHEMA_SLIDES, file="pptx", max_tokens=3500),
        Format("datatable", "Data table", "datatable", SCHEMA_TABLE, file="xlsx"),
        Format("audio", "Audio overview", "audio", SCHEMA_AUDIO, file="md", max_tokens=4000),
        Format("infographic", "Infographic", "infographic", SCHEMA_INFOGRAPHIC, max_tokens=1500),
        # the guide to a notebook is kept with the notebook, not listed as an output
        Format("guide", "Source guide", "guide", SCHEMA_GUIDE, max_tokens=1200),
    )
}


class BadReply(ValueError):
    """The model's reply could not be used; `str(e)` says what was wrong, for a second attempt."""


@dataclass
class Built:
    """What a format makes: the body that is searched and shown, a file to keep, and the data a
    viewer reads."""

    title: str
    markdown: str
    data: dict[str, Any] | None = None
    file: bytes | None = None
    file_ext: str | None = None
    file_mime: str | None = None


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_json(raw: str) -> dict[str, Any]:
    """The JSON object in a reply, tolerating a fence or a sentence around it."""
    text = raw.strip()
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise BadReply(f"the reply was not valid JSON ({e.msg})") from e
    if not isinstance(data, dict):
        raise BadReply("the reply was not a JSON object")
    return data


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def slug(title: str, fallback: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return cleaned[:60] or fallback


def prompt_for(fmt: Format, tier: str, focus: str | None) -> str:
    """The system prompt of a format for a model tier, with the person's steer in it."""
    path = PROMPTS / fmt.prompt / f"{tier}.md"
    text = (focus or "").strip() or fmt.default_focus
    steer = f"Focus on: {text}" if text else ""
    return Template(path.read_text()).safe_substitute(
        focus=steer,
        options=OPTIONS,
        ceiling={"flashcards": CARDS, "quiz": QUESTIONS}.get(fmt.key, BRANCHES),
    )


def _title_of(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip()[:MAX_TITLE] or fallback
    return fallback


def build(fmt: Format, raw: str, notebook_title: str = "") -> Built:
    """Turn a reply into the format. Raises `BadReply` when nothing usable came back."""
    if fmt.key in ("report", "study_guide", "word", "pdf"):
        return _document(fmt, raw)
    if fmt.key == "flashcards":
        return _cards(raw)
    if fmt.key == "quiz":
        return _quiz(raw)
    if fmt.key == "mindmap":
        return _mindmap(raw)
    if fmt.key == "slides":
        return _slides(raw)
    if fmt.key == "datatable":
        return _table(raw)
    if fmt.key == "audio":
        return _audio(raw)
    if fmt.key == "infographic":
        return _infographic(raw)
    if fmt.key == "guide":
        return _guide(raw)
    raise BadReply(f"unknown format {fmt.key}")


def _document(fmt: Format, raw: str) -> Built:
    markdown = raw.strip()
    # a model sometimes wraps the whole document in a fence
    fenced = re.fullmatch(r"```(?:markdown|md)?\s*\n(.*)\n```", markdown, re.DOTALL)
    if fenced:
        markdown = fenced.group(1).strip()
    if len(markdown) < 40:
        raise BadReply("the document was empty or far too short")
    title = _title_of(markdown, fmt.label)
    if fmt.file == "docx":
        from wasifyai_notebooks.studio.word import markdown_to_word

        return Built(
            title, markdown, file=markdown_to_word(markdown), file_ext="docx",
            file_mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )  # fmt: skip
    if fmt.file == "pdf":
        from wasifyai_notebooks.studio.pdf import markdown_to_pdf

        return Built(title, markdown, file=markdown_to_pdf(markdown), file_ext="pdf",
                     file_mime="application/pdf")  # fmt: skip
    return Built(title, markdown, file=markdown.encode(), file_ext="md", file_mime="text/markdown")


def _cards(raw: str) -> Built:
    spec = parse_json(raw)
    title = _text(spec.get("title")) or "Flashcards"
    cards: list[dict[str, str]] = []
    for card in _list(spec.get("cards")):
        if len(cards) == CARDS:
            break
        if not isinstance(card, dict):
            continue
        front, back = _text(card.get("front")), _text(card.get("back"))
        if front and back:
            cards.append({"front": front, "back": back})
    if not cards:
        raise BadReply("there were no usable flashcards in the reply")
    lines = [f"# {title}", ""]
    for n, c in enumerate(cards, 1):
        lines += [f"**{n}. {c['front']}**", "", c["back"], ""]
    data = {"schema_version": 1, "title": title, "cards": cards}
    return Built(
        title, "\n".join(lines).strip(), data, json.dumps(data).encode(), "json", "application/json"
    )


def _quiz(raw: str) -> Built:
    spec = parse_json(raw)
    title = _text(spec.get("title")) or "Quiz"
    questions: list[dict[str, Any]] = []
    for item in _list(spec.get("questions")):
        if len(questions) == QUESTIONS:
            break
        if not isinstance(item, dict):
            continue
        question = _text(item.get("question"))
        options = [t for t in map(_text, _list(item.get("options"))) if t]
        answer = _text(item.get("answer"))
        # the viewer scores by position: an answer must be one of four distinct options
        if (
            not question
            or len(options) != OPTIONS
            or len(set(options)) != OPTIONS
            or answer not in options
        ):
            continue
        questions.append(
            {
                "question": question,
                "options": options,
                "answer_index": options.index(answer),
                "explanation": _text(item.get("explanation")),
            }
        )
    if not questions:
        raise BadReply("there were no usable questions in the reply (each needs four options)")
    lines = [f"# {title}", ""]
    for n, q in enumerate(questions, 1):
        lines += [f"**{n}. {q['question']}**", ""]
        lines += [f"- {o}" for o in q["options"]]
        lines += ["", f"_Answer: {q['options'][q['answer_index']]}_", ""]
    data = {"schema_version": 1, "title": title, "questions": questions}
    return Built(
        title, "\n".join(lines).strip(), data, json.dumps(data).encode(), "json", "application/json"
    )


def _mindmap(raw: str) -> Built:
    spec = parse_json(raw)
    title = _text(spec.get("title")) or "Mind map"
    lines = [f"# {title}"]

    def walk(nodes: list[Any], depth: int) -> None:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            label = _text(node.get("label"))
            if not label:
                continue
            lines.append(f"{'  ' * depth}- {label}")
            if depth < 3:
                walk(_list(node.get("children")), depth + 1)

    walk(_list(spec.get("nodes"))[:BRANCHES], 0)
    if len(lines) < 3:
        raise BadReply("the mind map had no branches")
    return Built(title, "\n".join(lines), None, None, None, None)


def _slides(raw: str) -> Built:
    from wasifyai_notebooks.studio.slides import build_deck

    spec = parse_json(raw)
    title = _text(spec.get("title")) or "Slides"
    slides: list[dict[str, Any]] = []
    for item in _list(spec.get("slides")):
        if len(slides) == SLIDES:
            break
        if not isinstance(item, dict):
            continue
        head = _text(item.get("title"))
        bullets = [b for b in map(_text, _list(item.get("bullets"))) if b]
        if head and bullets:
            slides.append({"title": head, "bullets": bullets, "notes": _text(item.get("notes"))})
    if not slides:
        raise BadReply("there were no usable slides in the reply (each needs a title and bullets)")
    lines = [f"# {title}", ""]
    for n, s in enumerate(slides, 1):
        lines += [f"## {n}. {s['title']}", ""] + [f"- {b}" for b in s["bullets"]] + [""]
    data = {"title": title, "slides": slides}
    return Built(
        title, "\n".join(lines).strip(), data, build_deck(title, slides), "pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )  # fmt: skip


def _table(raw: str) -> Built:
    from wasifyai_notebooks.studio.sheet import build_workbook

    spec = parse_json(raw)
    title = _text(spec.get("title")) or "Table"
    columns = [c for c in map(_text, _list(spec.get("columns")))][:TABLE_COLUMNS]
    if not columns or not all(columns):
        raise BadReply("the table had no columns, or a column with no name")
    rows: list[list[str]] = []
    for row in _list(spec.get("rows")):
        if len(rows) == TABLE_ROWS:
            break
        if not isinstance(row, list):
            continue
        cells = [_text(c) for c in row][: len(columns)]
        cells += [""] * (len(columns) - len(cells))
        if any(cells):
            rows.append(cells)
    if not rows:
        raise BadReply("the table had no rows")
    head = "| " + " | ".join(c.replace("|", "\\|") for c in columns) + " |"
    body = ["| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |" for r in rows]
    markdown = "\n".join(
        [f"# {title}", "", head, "|" + "|".join(["---"] * len(columns)) + "|", *body]
    )
    data = {"title": title, "columns": columns, "rows": rows}
    return Built(
        title, markdown, data, build_workbook(title, columns, rows), "xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )  # fmt: skip


def _audio(raw: str) -> Built:
    spec = parse_json(raw)
    title = _text(spec.get("title")) or "Audio overview"
    turns: list[dict[str, Any]] = []
    for item in _list(spec.get("turns")):
        if len(turns) == TURNS:
            break
        if not isinstance(item, dict):
            continue
        text = _text(item.get("text"))
        try:
            speaker = int(item.get("speaker", 0))
        except (TypeError, ValueError):
            continue
        if text and speaker in (1, 2):
            turns.append({"speaker": speaker, "host": HOSTS[speaker - 1], "text": text})
    if len(turns) < 4:
        raise BadReply("the script had too few turns between the two hosts")
    lines = [f"# {title}", ""] + [f"**{t['host']}:** {t['text']}\n" for t in turns]
    data = {"title": title, "hosts": list(HOSTS), "turns": turns, "audio": False}
    markdown = "\n".join(lines).strip()
    return Built(title, markdown, data, markdown.encode(), "md", "text/markdown")


def _infographic(raw: str) -> Built:
    spec = parse_json(raw)
    title = _text(spec.get("title")) or "Infographic"
    summary = _text(spec.get("summary"))
    sections = []
    for item in _list(spec.get("sections"))[:SECTIONS]:
        if not isinstance(item, dict):
            continue
        label, value = _text(item.get("label"))[:60], _text(item.get("value"))[:80]
        if label and value:
            sections.append({"label": label, "value": value, "detail": _text(item.get("detail"))})
    if not sections:
        raise BadReply("the infographic had no sections with a label and a value")
    lines = [f"# {title}"] + ([summary] if summary else [])
    for s in sections:
        lines.append(f"\n## {s['label']}\n\n**{s['value']}**\n\n{s['detail']}")
    data = {"title": title, "summary": summary, "sections": sections}
    return Built(title, "\n".join(lines), data)


def _guide(raw: str) -> Built:
    spec = parse_json(raw)
    summary = _text(spec.get("summary"))
    topics = [t[:80] for t in map(_text, _list(spec.get("topics"))) if t][:TOPICS]
    questions = [q[:300] for q in map(_text, _list(spec.get("questions"))) if q.endswith("?")][
        :QUESTIONS_ASKED
    ]
    if not summary or not questions:
        raise BadReply("the guide needs a summary and at least one question")
    data = {"summary": summary, "topics": topics, "questions": questions}
    return Built("Source guide", summary, data)


IMAGE_PROMPT_CHARS = 500  # the image product's limit on a description
_STYLE = (
    "Hand-drawn sketchnote infographic, black ink on warm white with one accent colour, simple "
    "icons and arrows, large legible hand-lettered headings, no photorealism."
)


def infographic_prompt(data: dict[str, Any]) -> str:
    """A description of the picture for the image model, within its limit: the style, the title and
    as many sections (label and value) as fit. The style follows SurfSense's sketchnote look."""
    head = f'{_STYLE} Title: "{data["title"]}". Panels: '
    parts: list[str] = []
    for section in data["sections"]:
        piece = f"{section['label']}: {section['value']}"
        if len(head) + len("; ".join([*parts, piece])) > IMAGE_PROMPT_CHARS:
            break
        parts.append(piece)
    return (head + "; ".join(parts))[:IMAGE_PROMPT_CHARS]


__all__ = [
    "BadReply",
    "Built",
    "FORMATS",
    "Format",
    "build",
    "parse_json",
    "prompt_for",
    "slug",
    "field",
]
