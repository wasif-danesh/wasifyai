"""The help file of an action (ADR-0068 decision 1, ADR-0071 decision 1): `docs/help/<id>.md`.

    ---
    action: speech.speak
    screen: voice.speak
    synonyms: [read aloud, voice over, tts]
    ---
    # Text to speech
    ...steps with the exact labels, written **Voice › Text to speech** ...

The front matter ties the file to its action and screen; the synonyms are the words people use.
A menu path is written in bold with ` › ` between the group and the item, so a test can check it
against the shipped menu."""

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

HELP_DIR = "docs/help"
FRONT = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.S)
MENU_PATH = re.compile(r"\*\*([^*\n]+?) › ([^*\n]+?)\*\*")


class HelpError(ValueError):
    pass


@dataclass
class Help:
    action: str
    screen: str | None
    synonyms: list[str]
    body: str
    path: Path
    menu_paths: list[tuple[str, str]] = field(default_factory=list)  # (group label, item label)


def help_path(root: Path, action_id: str) -> Path:
    return root / HELP_DIR / f"{action_id}.md"


def parse_help(text: str, path: Path) -> Help:
    m = FRONT.match(text)
    if not m:
        raise HelpError(f"{path.name}: the file must start with a front matter block")
    meta = yaml.safe_load(m.group(1)) or {}
    if not isinstance(meta, dict) or not isinstance(meta.get("action"), str):
        raise HelpError(f"{path.name}: front matter needs 'action'")
    synonyms = meta.get("synonyms") or []
    if not isinstance(synonyms, list) or not all(isinstance(s, str) for s in synonyms):
        raise HelpError(f"{path.name}: 'synonyms' must be a list of words")
    body = m.group(2).strip()
    return Help(
        action=meta["action"],
        screen=meta.get("screen"),
        synonyms=synonyms,
        body=body,
        path=path,
        menu_paths=[(g.strip(), i.strip()) for g, i in MENU_PATH.findall(body)],
    )


def load_help(root: Path, action_id: str) -> Help:
    path = help_path(root, action_id)
    if not path.is_file():
        raise HelpError(f"{action_id} has no help file: write {HELP_DIR}/{action_id}.md")
    return parse_help(path.read_text(encoding="utf-8"), path)
