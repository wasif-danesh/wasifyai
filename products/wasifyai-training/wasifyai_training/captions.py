"""The app writes the description of every picture (ADR-0076 decision 2): the person only
uploads pictures.

The instruction depends on what is being taught. For a character it leaves out what makes the
character itself (so the trainer learns that from the pictures), for a style it leaves out the
style, for an object it describes the surroundings. The magic word goes first. Captions are
English: the text encoders are English-trained, a recorded limit (ADR-0076)."""

import asyncio
import re

from wasifyai_platform_sdk import Capabilities, Image, RunError

from wasifyai_training import vision

MAX_WORDS = 60
KIND_PROMPT = {
    "character": "caption_character",
    "style": "caption_style",
    "object": "caption_object",
}


def tidy(text: str) -> str:
    """One plain sentence: no quotes, no label, no line breaks, at most `MAX_WORDS` words."""
    one = re.sub(r"\s+", " ", text).strip().strip("\"'`")
    one = re.sub(r"^(caption|description)\s*:\s*", "", one, flags=re.IGNORECASE)
    one = re.sub(
        r"^(an?|the)\s+(picture|image|photo|photograph)\s+of\s+", "", one, flags=re.IGNORECASE
    )
    words = one.split(" ")
    if len(words) > MAX_WORDS:
        one = " ".join(words[:MAX_WORDS]).rstrip(",;:") + "."
    return one


def with_word(caption: str, word: str) -> str:
    """The magic word first, once: `marlo, standing on a beach at sunset.`"""
    body = caption.strip()
    if not word:
        return body
    if body.lower().startswith(word.lower()):
        return body
    return f"{word}, {body[:1].lower()}{body[1:]}" if body else word


async def describe(caps: Capabilities, png: bytes, kind: str, word: str) -> str:
    """The caption of one picture, from the chosen vision model. Raises `RunError` with words."""
    small = await asyncio.to_thread(vision.review_copy, png)
    system = vision.prompt(KIND_PROMPT.get(kind, "caption_object"))
    user = [vision.prompt("caption_request"), Image.from_bytes(small, "image/jpeg")]
    try:
        raw = await caps.text.complete("describe_image", system, user)
    except RunError:
        raise
    except Exception:
        raise RunError(
            "caption_failed",
            "The picture could not be described. Choose a vision model, or try again.",
        ) from None
    caption = tidy(raw)
    if len(caption) < 6:
        raise RunError("caption_failed", "The picture could not be described. Try again.")
    return with_word(caption, word)
