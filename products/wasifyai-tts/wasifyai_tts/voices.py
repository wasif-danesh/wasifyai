"""The voice catalog (ADR-0042): which languages and voices the product offers, from `voices.yaml`.

The user chooses a language and male or female; the catalog turns that into an engine, a model
and a voice. A choice with no voice is an error with a plain reason, never a silent change to
another voice."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

CATALOG = Path(__file__).resolve().parents[1] / "voices.yaml"
Gender = Literal["female", "male"]
GENDERS: tuple[str, ...] = ("female", "male")


class NoVoice(Exception):
    """The language or gender asked for has no voice; `message` is the plain reason for the user."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Language:
    id: str
    name: str  # in its own script, for example "हिन्दी"
    english: str  # the English name, for people who cannot read the script
    whisper: str  # the language hint for the round-trip check


@dataclass(frozen=True)
class Voice:
    id: str  # "kokoro:af_heart": stable, stored with each result
    language: str
    gender: str
    label: str
    engine: str
    engine_voice: str
    default: bool
    grade: str = ""  # the model card's overall grade for the voice, used to pick the default

    @property
    def quality(self) -> str:
        """ "good", "fair" or "limited", from the model card's grade (A and B, C, D and F): the form
        says so plainly, because a language with little training data sounds clearly worse."""
        letter = self.grade[:1]
        return "good" if letter in ("A", "B") else "fair" if letter == "C" else "limited"


@dataclass(frozen=True)
class Engine:
    model: str
    max_chars: int  # the longest piece the engine says comfortably in one go


class Catalog:
    def __init__(self, raw: dict):
        self.engines = {k: Engine(**v) for k, v in raw["engines"].items()}
        self.languages = [Language(**x) for x in raw["languages"]]
        self.voices = [Voice(**{"default": False, **v}) for v in raw["voices"]]
        self._check()

    def _check(self) -> None:
        ids = {lang.id for lang in self.languages}
        seen: set[str] = set()
        for v in self.voices:
            if v.id in seen:
                raise ValueError(f"voice {v.id!r} is listed twice")
            seen.add(v.id)
            if v.language not in ids:
                raise ValueError(f"voice {v.id!r} has an unknown language {v.language!r}")
            if v.gender not in GENDERS:
                raise ValueError(f"voice {v.id!r} has gender {v.gender!r}")
            if v.engine not in self.engines:
                raise ValueError(f"voice {v.id!r} uses an unknown engine {v.engine!r}")
        for lang in self.languages:
            for g in GENDERS:
                defaults = [v for v in self.voices_for(lang.id, g) if v.default]
                if self.voices_for(lang.id, g) and len(defaults) != 1:
                    raise ValueError(f"{lang.id}/{g} needs exactly one default voice")

    def language(self, language_id: str) -> Language | None:
        return next((x for x in self.languages if x.id == language_id), None)

    def voices_for(self, language_id: str, gender: str) -> list[Voice]:
        return [v for v in self.voices if (v.language, v.gender) == (language_id, gender)]

    def resolve(self, language_id: str, gender: str, voice_id: str | None = None) -> Voice:
        lang = self.language(language_id)
        if lang is None:
            raise NoVoice("Please choose one of the languages in the list.")
        if gender not in GENDERS:
            raise NoVoice("Please choose a male or a female voice.")
        options = self.voices_for(language_id, gender)
        if not options:
            word = "male" if gender == "male" else "female"
            raise NoVoice(f"There is no {word} voice for {lang.english} yet.")
        if voice_id is None:
            return next(v for v in options if v.default)
        match = next((v for v in options if v.id == voice_id), None)
        if match is None:
            raise NoVoice("That voice is not available for this language and choice.")
        return match

    def public(self) -> dict:
        """What the web form needs: languages with the voices that exist for each gender."""
        return {
            "languages": [
                {
                    "id": lang.id,
                    "name": lang.name,
                    "english": lang.english,
                    "genders": {
                        g: [
                            {
                                "id": v.id,
                                "label": v.label,
                                "default": v.default,
                                "quality": v.quality,
                            }
                            for v in self.voices_for(lang.id, g)
                        ]
                        for g in GENDERS
                    },
                }
                for lang in self.languages
            ]
        }


@lru_cache
def load_catalog(path: Path = CATALOG) -> Catalog:
    return Catalog(yaml.safe_load(path.read_text(encoding="utf-8")))
