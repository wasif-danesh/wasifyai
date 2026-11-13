"""Prompt templates live in `prompts/`, not in Python (product rule). `$name` placeholders."""

from pathlib import Path
from string import Template

# Inside the package when installed from a wheel (the build copies `prompts/` in), else beside it in
# a source checkout.
_HERE = Path(__file__).resolve().parent
PROMPTS_DIR = _HERE / "prompts" if (_HERE / "prompts").is_dir() else _HERE.parent / "prompts"


def load(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def render(name: str, **values: str) -> str:
    return Template(load(name)).safe_substitute(**values)
