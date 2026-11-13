# SPDX-License-Identifier: Apache-2.0
"""The languages the voice screens can name, and which of them a model and each of its voices speak
(docs/voice-languages-plan.md, stage L1). Every screen and the engine read the same answer from
here. The window's copy is `packages/ui/src/voice/languages.ts`; a test keeps the two equal.

A model lists its languages in `models.yaml` or the cloud catalogue, as codes such as `en-us`,
`pt-br` or `bn`; `multi` means it is not limited. Only the base code (`en`, `pt`) is compared."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

MULTI = "multi"


@dataclass(frozen=True)
class Language:
    code: str  # ISO 639-1
    english: str
    own: str  # the language's name for itself
    rtl: bool = False


def _table(*rows: tuple[str, str, str]) -> dict[str, Language]:
    return {c: Language(c, e, o, rtl=c in {"ar"}) for c, e, o in rows}


LANGUAGES: dict[str, Language] = _table(
    ("ar", "Arabic", "العربية"),
    ("bg", "Bulgarian", "Български"),
    ("bn", "Bengali", "বাংলা"),
    ("cs", "Czech", "Čeština"),
    ("da", "Danish", "Dansk"),
    ("de", "German", "Deutsch"),
    ("el", "Greek", "Ελληνικά"),
    ("en", "English", "English"),
    ("es", "Spanish", "Español"),
    ("et", "Estonian", "Eesti"),
    ("fi", "Finnish", "Suomi"),
    ("fr", "French", "Français"),
    ("gu", "Gujarati", "ગુજરાતી"),
    ("hi", "Hindi", "हिन्दी"),
    ("hr", "Croatian", "Hrvatski"),
    ("hu", "Hungarian", "Magyar"),
    ("it", "Italian", "Italiano"),
    ("ja", "Japanese", "日本語"),
    ("ko", "Korean", "한국어"),
    ("lt", "Lithuanian", "Lietuvių"),
    ("lv", "Latvian", "Latviešu"),
    ("mr", "Marathi", "मराठी"),
    ("mt", "Maltese", "Malti"),
    ("nl", "Dutch", "Nederlands"),
    ("pl", "Polish", "Polski"),
    ("pt", "Portuguese", "Português"),
    ("ro", "Romanian", "Română"),
    ("ru", "Russian", "Русский"),
    ("sk", "Slovak", "Slovenčina"),
    ("sl", "Slovenian", "Slovenščina"),
    ("sv", "Swedish", "Svenska"),
    ("ta", "Tamil", "தமிழ்"),
    ("te", "Telugu", "తెలుగు"),
    ("uk", "Ukrainian", "Українська"),
    ("zh", "Chinese", "中文"),
)


def base(code: str) -> str:
    """`en-us`, `EN` and `pt_BR` are `en`, `en` and `pt`."""
    return str(code).strip().lower().replace("_", "-").split("-")[0]


def language_name(code: str) -> str:
    """The English name, or the code itself when the app cannot name it."""
    found = LANGUAGES.get(base(code))
    return found.english if found else str(code)


def label(code: str) -> str:
    """What a list shows: `Bengali (বাংলা)`, or `English` where the two names are the same."""
    found = LANGUAGES.get(base(code))
    if found is None:
        return str(code)
    return found.english if found.own == found.english else f"{found.english} ({found.own})"


def spoken(languages: Iterable[str]) -> set[str]:
    """The base codes a model's `languages` stand for; `multi` is every language the app names."""
    codes = {base(x) for x in languages}
    return set(LANGUAGES) if MULTI in codes else codes


def supports(languages: Iterable[str], language: str) -> bool:
    """Whether a model with these `languages` speaks (or writes down) `language`."""
    codes = {base(x) for x in languages}
    return MULTI in codes or base(language) in codes


class _Voice(Protocol):
    @property
    def id(self) -> str: ...
    @property
    def language(self) -> str: ...


class _Model(Protocol):
    @property
    def languages(self) -> tuple[str, ...]: ...
    @property
    def voices(self) -> tuple[Any, ...]: ...


def voice_languages(model: _Model) -> dict[str, set[str]]:
    """Each voice of a model and the base codes it speaks: its own `language` when it names one (a
    Kokoro voice speaks the language of its accent), otherwise every language of the model."""
    every = spoken(model.languages)
    return {v.id: ({base(v.language)} if v.language else set(every)) for v in model.voices}


def voices_for(model: _Model, language: str) -> list[str]:
    """The ids of a model's voices that speak `language`, in the model's order."""
    want = base(language)
    return [vid for vid, codes in voice_languages(model).items() if want in codes]
