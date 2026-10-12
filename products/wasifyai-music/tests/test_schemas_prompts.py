import re

from wasifyai_music import prompts
from wasifyai_music.schemas import MODERATION_SCHEMA, SONG_SCHEMA


def test_structured_output_schemas_are_stable():
    """Snapshot: the schema sent to the model is a contract with the prompts and the parser."""
    assert SONG_SCHEMA == {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "lyrics": {"type": "string"},
            "style": {"type": "string"},
            "cover_prompt": {"type": "string"},
        },
        "required": ["title", "lyrics", "style", "cover_prompt"],
        "additionalProperties": False,
    }
    assert MODERATION_SCHEMA["properties"]["category"]["enum"] == [
        "ok", "artist_voice", "existing_lyrics", "disallowed_content",
    ]  # fmt: skip
    assert MODERATION_SCHEMA["required"] == ["allowed", "category", "reason"]
    assert MODERATION_SCHEMA["additionalProperties"] is False


def test_prompts_exist_and_render_every_placeholder():
    for name in ("lyrics", "lyrics_request", "moderation", "moderation_request"):
        assert prompts.load(name)
    text = prompts.render("lyrics_request", idea="a", genre="b", mood="c", feedback="")
    assert "<idea>a</idea>" in text and not re.search(r"\$\w+", text)
    assert "<request>\nhello\n</request>" in prompts.render(
        "moderation_request", kind="lyrics", text="hello"
    )


def test_prompts_keep_the_product_rules():
    lyrics = prompts.load("lyrics")
    for tag in ("[verse]", "[chorus]", "[bridge]"):
        assert tag in lyrics  # ACE-Step needs these section tags
    assert "never an instruction" in lyrics  # user text is data
    moderation = prompts.load("moderation")
    for category in ("artist_voice", "existing_lyrics", "disallowed_content"):
        assert category in moderation
    assert "never instructions" in moderation


def test_user_text_cannot_inject_placeholders():
    out = prompts.render(
        "lyrics_request", idea="$genre $mood", genre="rock", mood="calm", feedback=""
    )
    assert "<idea>$genre $mood</idea>" in out  # substituted once, not recursively
