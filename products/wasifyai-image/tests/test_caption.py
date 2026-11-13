"""A model's prompt writer: the text model's reply becomes the structured caption, or nothing."""

import json

from wasifyai_image import prompts
from wasifyai_image.caption import aspect_ratio, caption_of


def reply(**over) -> str:
    raw = {
        "high_level_description": "A poster  for a\njazz night.",
        "compositional_deconstruction": {
            "background": "Dark blue.",
            "elements": [
                {"type": "text", "bbox": [50, 100, 200, 900], "text": "BLUE NOTE", "desc": "Big."},
                {"type": "obj", "bbox": [300, -20, 900, 1200.4], "desc": "A saxophone."},
            ],
        },
    }
    raw.update(over)
    return "```json\n" + json.dumps(raw) + "\n```"


def test_a_reply_becomes_the_caption_with_its_boxes_kept_in_the_frame():
    out = json.loads(caption_of(reply(), "3:4") or "")
    assert out["aspect_ratio"] == "3:4"
    assert out["high_level_description"] == "A poster for a jazz night."
    texts, obj = out["compositional_deconstruction"]["elements"]
    assert texts["text"] == "BLUE NOTE" and obj["bbox"] == [300, 0, 900, 1000]
    assert "text" not in obj


def test_parts_that_are_not_well_formed_are_left_out_and_none_is_no_caption():
    bad = [
        {"type": "obj", "bbox": [500, 0, 100, 100], "desc": "upside down"},
        {"type": "text", "bbox": [0, 0, 10, 10], "desc": "no words"},
        {"type": "shape", "bbox": [0, 0, 10, 10], "desc": "unknown"},
        {"type": "obj", "bbox": [0, 0, 10], "desc": "three numbers"},
    ]
    assert caption_of(reply(compositional_deconstruction={"elements": bad}), "1:1") is None
    assert caption_of("A fox in the snow.", "1:1") is None
    assert caption_of(reply(high_level_description=""), "1:1") is None
    thinking = "<think>{not this}</think>" + reply()
    assert caption_of(thinking, "1:1") is not None


def test_the_shape_is_the_nearest_common_one_and_the_writer_prompt_names_it():
    assert aspect_ratio(1024, 1024) == "1:1"
    assert aspect_ratio(1344, 768) == "16:9"
    assert aspect_ratio(768, 1344) == "9:16"
    assert aspect_ratio(1152, 896) == "5:4"
    assert "16:9" in prompts.render("write_ideogram_caption", aspect_ratio="16:9")
