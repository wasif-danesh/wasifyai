"""A project of scenes (ADR-0096): the document, its page, what it must say, and changing one scene.
The real browser is `services/api/tests/test_video_builder_templates.py`."""

import html
import re

import pytest
from wasifyai_video.builder import scenes, templates
from wasifyai_video.builder.templates import SCENES, SlotError

DOC = {
    "name": "Northbean launch",
    "shape": "portrait",
    "scenes": [
        {"kind": "title", "name": "Hook", "fields": {"title": "Mornings are hard.", "seconds": 4}},
        {"kind": "quote", "fields": {"quote": "Smooth, not bitter.", "author": "A customer"}},
        {"kind": "chart", "fields": {"title": "Sales", "data": "North, 120\nSouth, 95"}},
    ],
}


def doc() -> dict:
    return templates.normalize_slots(SCENES, DOC)


def test_a_document_is_completed_and_its_length_comes_from_its_scenes():
    d = doc()
    assert d["seconds"] == 4 + 5 + 5  # no length given: a short scene, not the template's 30
    assert [s["name"] for s in d["scenes"]] == ["Hook", "Quote", "Bar chart"]
    assert d["font"] == "sans" and "shape" not in d["scenes"][0]["fields"]
    assert len({s["id"] for s in d["scenes"]}) == 3
    assert templates.scene_starts(d) == [0, 4, 9]


def test_checking_a_document_again_changes_nothing_and_keeps_the_ids():
    d = doc()
    assert templates.normalize_slots(SCENES, d) == d


@pytest.mark.parametrize(
    ("change", "said"),
    [
        ({"scenes": []}, "at least one scene"),
        ({"scenes": [{"kind": "poster", "fields": {}}]}, "must be one of"),
        ({"scenes": [{"kind": "title", "fields": {}}]}, "Scene 1: Write a title"),
        (
            {"scenes": [{"kind": "title", "fields": {"title": "x", "shape": "square"}}]},
            "whole project",
        ),
        ({"scenes": [{"kind": "title", "fields": {"title": "x"}, "extra": 1}]}, "no setting"),
        ({"shape": "round"}, "shape must be"),
        ({"colour": "red"}, "no setting called colour"),
        (
            {"scenes": [{"kind": "title", "fields": {"title": "x", "seconds": 50}}] * 2},
            "would run 100 seconds",
        ),
        (
            {"scenes": [{"kind": "title", "fields": {"title": "x", "seconds": 3}}] * 31},
            "at most 30",
        ),
    ],
)
def test_a_bad_document_is_refused_in_words(change, said):
    with pytest.raises(SlotError, match=said):
        templates.normalize_slots(SCENES, {**DOC, **change})


def test_an_id_used_twice_or_not_ours_gets_a_new_one():
    one = {"id": "aaaaaaaa", "kind": "title", "fields": {"title": "x", "seconds": 3}}
    bad = {**one, "id": '"><script>'}
    d = templates.normalize_slots(SCENES, {"scenes": [one, one, bad]})
    ids = [s["id"] for s in d["scenes"]]
    assert ids[0] == "aaaaaaaa" and len(set(ids)) == 3
    assert all(re.fullmatch("[0-9a-f]{8}", i) for i in ids)


def test_what_a_film_must_say_is_each_scenes_words_at_film_time():
    d = doc()
    a, b, c = (s["id"] for s in d["scenes"])
    wanted = {(e.slot, e.text, e.at) for e in templates.expected(SCENES, d)}
    assert (f"{a}-title", "Mornings are hard.", 3.9) in wanted
    assert (f"{b}-quote", "Smooth, not bitter.", 8.9) in wanted
    assert (f"{c}-value-1", "95", 13.9) in wanted


def test_the_page_has_every_scene_at_its_own_time_with_nothing_shared():
    d = doc()
    page = templates.render_html(SCENES, d)
    a, b, c = (s["id"] for s in d["scenes"])
    assert f'id="scene-{b}" class="clip scene" data-start="4" data-duration="5"' in page
    assert f'id="s{a}-title"' in page and f'data-slot="{b}-quote"' in page
    assert f"#s{a}-title" in page and f'getElementById("s{b}-quote")' in page
    assert f'"#scene-{c} .fill"' in page  # a class selector reaches only inside its scene
    ids = re.findall(r'\bid="([^"]+)"', page)
    assert len(ids) == len(set(ids))
    for slot in re.findall(r'data-slot="([^"]+)"', page):
        assert slot.split("-")[0] in (a, b, c)
    assert 'data-start="0" data-duration="4" data-track-index="1"' in page
    assert "film.add(tl, 9)" in page and 'window.__timelines["main"] = film' in page


def test_every_selector_in_the_page_is_a_valid_one_even_for_a_part_a_scene_left_out():
    one = {"id": "28653889", "kind": "title", "fields": {"title": "No line under it"}}
    page = templates.render_html(SCENES, templates.normalize_slots(SCENES, {"scenes": [one]}))
    assert '"#s28653889-sub"' in page and '"#sub"' not in page
    assert not re.search(r"#\d[\w-]*-", page), "a selector cannot start with a digit"


@pytest.mark.parametrize(
    "words", ['id="x" data-start="0"', "<script>alert(1)</script>", '".title', "#stage & 'quotes'"]
)
def test_words_stay_words_when_a_template_is_made_into_a_scene(words):
    d = templates.normalize_slots(
        SCENES, {"scenes": [{"kind": "title", "fields": {"title": words}}]}
    )
    page = templates.render_html(SCENES, d)
    assert "<script>alert" not in page and 'id="x"' not in page
    assert html.escape(words, quote=True) in page  # exactly as typed, not rewritten


def test_each_scene_has_its_own_look_and_a_film_is_transparent_only_if_every_scene_is():
    two = {"scenes": [
        {"kind": "title", "fields": {"title": "a", "theme": "forest"}},
        {"kind": "lower_third", "fields": {"name": "b", "theme": "paper"}},
    ]}  # fmt: skip
    d = templates.normalize_slots(SCENES, two)
    page = templates.render_html(SCENES, d)
    assert templates.THEMES["forest"][0] in page and templates.THEMES["paper"][0] in page
    assert not templates.is_transparent(SCENES, d) and templates.formats_of(SCENES, d) == ("mp4",)
    only = templates.normalize_slots(SCENES, {"scenes": [two["scenes"][1]]})
    assert templates.is_transparent(SCENES, only) and "webm" in templates.formats_of(SCENES, only)
    assert "background: transparent" in templates.render_html(SCENES, only)


def test_a_film_is_found_by_every_word_and_named_by_its_name():
    d = doc()
    words = templates.describe(SCENES, d)
    for said in ("Northbean launch", "Mornings are hard", "A customer", "South 95"):
        assert said in words
    assert templates.title_of(SCENES, d) == "Northbean launch"
    unnamed = templates.normalize_slots(SCENES, {**DOC, "name": ""})
    assert templates.title_of(SCENES, unnamed) == "Mornings are hard"


def test_the_preview_shows_each_of_the_first_scenes_when_everything_is_on_it():
    assert templates.preview_times(SCENES, doc()) == [3.9, 8.9, 13.9]
    one = templates.normalize_slots(SCENES, {"scenes": [DOC["scenes"][0]]})
    assert templates.preview_times(SCENES, one) == templates.preview_times(
        "title", templates.normalize_slots("title", {"title": "x", "seconds": 4})
    )


@pytest.mark.parametrize(
    ("template", "slots"),
    [
        ("title", {"title": "Launch", "subtitle": "Soon", "theme": "paper", "font": "serif"}),
        ("captions", {"lines": ["One", "Two"], "per_line": "2", "shape": "square"}),
        ("chart", {"title": "T", "data": "A, 1\nB, 2"}),
    ],
)
def test_a_project_made_from_a_template_reads_as_one_scene_with_the_same_words(template, slots):
    made = templates.normalize_slots(template, slots)
    d = templates.as_scenes(template, made)
    assert [s["kind"] for s in d["scenes"]] == [template]
    assert d["shape"] == made["shape"] and d["font"] == made["font"]
    assert d["seconds"] == made["seconds"]
    assert templates.scene_slots(d, d["scenes"][0]) == made
    assert templates.describe(SCENES, d) == templates.describe(template, made)


def test_changing_one_scene_leaves_the_others():
    d = doc()
    _, b, _ = (s["id"] for s in d["scenes"])
    changed = scenes.change(d, b, {"quote": "New words."}, name="Proof")
    assert changed["scenes"][1]["fields"]["quote"] == "New words."
    assert changed["scenes"][1]["fields"]["author"] == "A customer"
    assert changed["scenes"][1]["name"] == "Proof" and changed["scenes"][1]["id"] == b
    assert changed["scenes"][0] == d["scenes"][0] and changed["scenes"][2] == d["scenes"][2]
    with pytest.raises(SlotError, match="not in this project"):
        scenes.change(d, "00000000", {})


def test_adding_moving_duplicating_and_removing_a_scene():
    d = doc()
    a, b, c = (s["id"] for s in d["scenes"])
    added, new = scenes.add(d, "title", {"title": "Try it", "seconds": 3}, "End card")
    assert [s["id"] for s in added["scenes"]] == [a, b, c, new] and added["seconds"] == 17
    first, other = scenes.add(d, "title", {"title": "x"}, at=0)
    assert first["scenes"][0]["id"] == other
    assert [s["id"] for s in scenes.move(d, c, 0)["scenes"]] == [c, a, b]
    assert [s["id"] for s in scenes.move(d, a, 99)["scenes"]] == [b, c, a]
    copied, copy = scenes.duplicate(d, a)
    assert [s["id"] for s in copied["scenes"]] == [a, copy, b, c]
    assert copied["scenes"][1]["fields"] == d["scenes"][0]["fields"]
    assert [s["id"] for s in scenes.remove(d, b)["scenes"]] == [a, c]
    only = templates.as_scenes("title", templates.normalize_slots("title", {"title": "x"}))
    with pytest.raises(SlotError, match="at least one scene"):
        scenes.remove(only, only["scenes"][0]["id"])


def test_a_scene_has_its_own_captions_and_they_must_be_on_the_screen():
    one = {"kind": "title", "fields": {"title": "Hi", "seconds": 4}, "caption": 'Say "hi" <now>'}
    d = templates.normalize_slots(SCENES, {"scenes": [one]})
    sid = d["scenes"][0]["id"]
    assert (f"{sid}-caption", 'Say "hi" <now>', 3.9) in {
        (e.slot, e.text, e.at) for e in templates.expected(SCENES, d)
    }
    page = templates.render_html(SCENES, d)
    assert f'data-slot="{sid}-caption">Say &quot;hi&quot; &lt;now&gt;<' in page
    assert 'Say "hi" <now>' in templates.describe(SCENES, d)
    with pytest.raises(SlotError, match="too long"):
        templates.normalize_slots(SCENES, {"scenes": [{**one, "caption": "x" * 141}]})


@pytest.mark.parametrize(
    ("kind", "said"), [("none", None), ("fade", "opacity: 0"), ("slide", " y: ")]
)
def test_a_scene_starts_the_way_it_says(kind, said):
    one = {"kind": "lower_third", "fields": {"name": "Hi"}, "transition": kind}
    page = templates.render_html(SCENES, templates.normalize_slots(SCENES, {"scenes": [one]}))
    root = 'tl.from("#scene-'
    assert (root in page and said in page) if said else root not in page
    with pytest.raises(SlotError, match="start with"):
        templates.normalize_slots(SCENES, {"scenes": [{**one, "transition": "spin"}]})


def test_a_copy_keeps_the_captions_and_how_it_starts():
    d = templates.normalize_slots(
        SCENES,
        {
            "scenes": [
                {"kind": "title", "fields": {"title": "x"}, "caption": "c", "transition": "fade"}
            ]
        },
    )
    copied, copy = scenes.duplicate(d, d["scenes"][0]["id"])
    assert copied["scenes"][1]["caption"] == "c" and copied["scenes"][1]["transition"] == "fade"
    changed = scenes.change(d, d["scenes"][0]["id"], {}, caption="new", transition="slide")
    assert (
        changed["scenes"][0]["caption"] == "new" and changed["scenes"][0]["transition"] == "slide"
    )
    assert scenes.change(changed, d["scenes"][0]["id"], {})["scenes"][0]["caption"] == "new"
