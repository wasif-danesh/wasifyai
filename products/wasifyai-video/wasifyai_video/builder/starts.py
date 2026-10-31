"""The starting points of a marketing project (ADR-0096 MX7): each is a set of scenes in the usual
document, with words to replace, so all of it can be changed like anything else. They end with an
end card, whose words come from the person's brand when it has them."""

from typing import Any

END_CARD = {"kind": "end_card", "name": "End card", "transition": "fade",
            "fields": {"action": "Your call to action", "address": "", "seconds": 4}}  # fmt: skip


def _title(name: str, title: str, under: str = "", seconds: int = 3) -> dict[str, Any]:
    return {"kind": "title", "name": name, "transition": "fade",
            "fields": {"title": title, "subtitle": under, "seconds": seconds}}  # fmt: skip


def _quote(name: str, quote: str, author: str, seconds: int = 6) -> dict[str, Any]:
    return {"kind": "quote", "name": name, "transition": "fade",
            "fields": {"quote": quote, "author": author, "seconds": seconds}}  # fmt: skip


# id -> (the name on the screen, what it is for, its scenes)
STARTS: dict[str, tuple[str, str, list[dict[str, Any]]]] = {
    "promo": ("Product promo", "A short promo that shows a product and why it matters.", [
        _title("Hook", "The problem your product solves"),
        _title("The product", "Your product's name", "What it does, in one line", 4),
        _title("Why it is different", "The one thing only you do", "", 4),
        END_CARD,
    ]),
    "launch": ("Launch announcement", "An announcement that something new is here.", [
        _title("Tease", "Something new is here"),
        _title("What it is", "Your product's name", "Available from your date", 4),
        _title("Why it matters", "What people can now do", "", 4),
        END_CARD,
    ]),
    "offer": ("Sale or offer", "A short video about an offer, clear about what it is.", [
        _title("The offer", "Your offer, like 20% off"),
        _title("What it covers", "What the offer is on", "Until your end date", 4),
        END_CARD,
    ]),
    "customer": ("Customer words", "A short video built around what a customer said.", [
        _title("Before", "What your customer was facing"),
        _quote("In their words", "What your customer said, in their own words.", "Their name"),
        END_CARD,
    ]),
    "explainer": ("Feature explainer", "A short video that explains one feature, step by step.", [
        _title("The feature", "Your feature's name", "What it is for"),
        _title("Step 1", "First, what to do", "", 4),
        _title("Step 2", "Then, what happens", "", 4),
        _title("The result", "What you end up with", "", 4),
        END_CARD,
    ]),
    "before_after": ("Before and after", "A short video that shows the difference.", [
        _title("Before", "Before: how it was", "", 4),
        _title("After", "After: how it is now", "", 4),
        END_CARD,
    ]),
    "social": ("Social post", "One idea, short and loud, for a social post.", [
        _title("The idea", "Your one idea, short and loud", "", 4),
        END_CARD,
    ]),
}  # fmt: skip


def info() -> list[dict[str, str]]:
    return [{"id": k, "title": v[0], "description": v[1]} for k, v in STARTS.items()]


def document_of(start: str, shape: str, name: str = "") -> dict[str, Any]:
    """The document a starting point begins with. Raises KeyError for one that is not there."""
    title, _, scenes = STARTS[start]
    return {"name": name or title, "shape": shape, "scenes": [dict(s) for s in scenes]}
