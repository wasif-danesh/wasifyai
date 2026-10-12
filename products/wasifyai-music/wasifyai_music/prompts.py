"""Prompt templates live in `prompts/`, not in Python (product rule). `$name` placeholders."""

from pathlib import Path
from string import Template

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def load(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def render(name: str, **values: str) -> str:
    return Template(load(name)).safe_substitute(**values)
