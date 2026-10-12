"""The languages the product offers, from `languages.yaml` (ADR-0043)."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

CATALOG = Path(__file__).resolve().parent / "languages.yaml"
QUALITIES = ("good", "fair", "limited", "unrated")


@dataclass(frozen=True)
class Language:
    id: str  # also Whisper's language code
    name: str  # in its own script
    english: str
    quality: str


@dataclass(frozen=True)
class Engine:
    model: str
    detect_model: str


class Languages:
    def __init__(self, raw: dict):
        self.engine = Engine(**raw["engines"]["whisper"])
        self.indic: tuple[str, ...] = tuple(raw["engines"]["indic"]["languages"])
        self.languages = [Language(**x) for x in raw["languages"]]
        ids = [x.id for x in self.languages]
        if len(set(ids)) != len(ids):
            raise ValueError("a language is listed twice")
        missing = [code for code in self.indic if code not in ids]
        if missing:
            raise ValueError(f"the Indic engine lists languages that are not offered: {missing}")
        bad = [x.id for x in self.languages if x.quality not in QUALITIES]
        if bad:
            raise ValueError(f"unknown quality for {bad}")

    def get(self, language_id: str) -> Language | None:
        return next((x for x in self.languages if x.id == language_id), None)

    def public(self) -> dict:
        return {
            "languages": [
                {"id": x.id, "name": x.name, "english": x.english, "quality": x.quality}
                for x in self.languages
            ]
        }


@lru_cache(maxsize=1)
def load_languages(path: Path = CATALOG) -> Languages:
    return Languages(yaml.safe_load(path.read_text(encoding="utf-8")))
