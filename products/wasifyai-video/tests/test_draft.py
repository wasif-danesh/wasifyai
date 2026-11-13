"""Plain words to template fields (the prompt box): what is asked of the model, how an attached
CSV is read, and how a model's mistakes are caught. The model is a stand-in that answers with
whatever JSON a test gives it."""

import json
from typing import Any

import pytest
from wasifyai_video.builder import draft, templates


class FakeLLM:
    """Answers the two steps: which template, then its fields. `fields` are what the model
    "says"; anything it does not say is empty, as strict mode gives it."""

    def __init__(self, template: str | None = "title", fields: dict[str, Any] | None = None,
                 raw: str | None = None):  # fmt: skip
        self.template, self.fields, self.raw = template, fields or {}, raw
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def complete(
        self, system: str, prompt: str, schema: dict[str, Any], max_tokens: int = 800
    ) -> str:
        self.calls.append((system, prompt, schema))
        if self.raw is not None:
            return self.raw
        props = schema["properties"]
        if set(props) == {"template"}:
            return json.dumps({"template": self.template})
        empty = {k: (0 if v["type"] == "integer" else "") for k, v in props.items()}
        return json.dumps({**empty, **self.fields})


# ---- what the model is asked ------------------------------------------------------------------


def test_the_first_question_is_only_which_template_and_the_second_only_that_templates_fields():
    one = draft.choose_schema()
    assert list(one["properties"]) == ["template"]
    assert one["properties"]["template"]["enum"] == list(templates.TEMPLATES)
    for template, t in templates.TEMPLATES.items():
        two = draft.fields_schema(template)
        assert list(two["properties"]) == [f.id for f in t.fields]
        words = {f.id for f in t.fields if f.kind in ("text", "longtext", "lines", "rows")}
        assert set(two["required"]) == words and two["additionalProperties"] is False
    theme = draft.fields_schema("title")["properties"]["theme"]
    assert "" not in theme["enum"] and "forest" in theme["enum"]
    assert draft.fields_schema("title")["properties"]["seconds"] == {"type": "integer"}


def test_the_instructions_name_each_template_and_demand_the_words_exactly():
    text = draft.choose_prompt()
    for t in templates.TEMPLATES:
        assert f"- {t}:" in text
    fill = draft.fill_prompt("lower_third", False)
    assert "character for character" in fill and "Never correct, translate" in fill
    assert "name = name, required" in fill and "role = role, optional" in fill
    assert "CSV" not in fill and "app takes the rows" in draft.fill_prompt("chart", True)
    assert "one bar per line" in draft.fill_prompt("chart", False)


# ---- the attached file ---------------------------------------------------------------------------


def test_a_csv_becomes_chart_lines_with_the_numbers_exactly_as_written():
    lines, warnings = draft.csv_rows("Region,Sales\nNorth,$120\nSouth,95\nEast,45%\n")
    assert warnings == []
    assert lines.splitlines() == ["North, $120", "South, 95", "East, 45%"]


def test_quoted_numbers_with_commas_survive():
    lines, _ = draft.csv_rows('Region,Sales\nNorth,"1,200.5"\nSouth,"$95"\n')
    assert lines.splitlines() == ["North, 1,200.5", "South, $95"]


def test_numbers_with_thousands_commas_that_were_not_quoted_are_put_back_together():
    lines, _ = draft.csv_rows("Region,Sales\nNorth,$1,200.5\nSouth,95\nEast,1,000\n")
    assert lines.splitlines() == ["North, $1,200.5", "South, 95", "East, 1,000"]


def test_a_file_with_several_value_columns_is_not_rejoined():
    lines, _ = draft.csv_rows("City,2025,2026\nLyon,120,130\nBonn,95,99")
    assert lines == "Lyon, 120\nBonn, 95"  # the first number column, as written


def test_a_header_is_skipped_other_separators_are_understood_and_a_bom_is_ignored():
    lines, _ = draft.csv_rows("﻿Name;Score\nAna;12\nBo;7\n")
    assert lines == "Ana, 12\nBo, 7"
    lines, _ = draft.csv_rows("a\t1\nb\t2")
    assert lines == "a, 1\nb, 2"


def test_the_first_column_with_a_number_is_the_value():
    lines, _ = draft.csv_rows("City,Country,Visitors\nLyon,France,120\nBonn,Germany,95")
    assert lines == "Lyon, 120\nBonn, 95"


def test_more_than_eight_rows_use_the_first_eight_and_say_so():
    rows = "\n".join(f"r{i},{i}" for i in range(1, 12))
    lines, warnings = draft.csv_rows("Label,Value\n" + rows)
    assert len(lines.splitlines()) == 8 and "first 8 of the 11 rows" in warnings[0]


@pytest.mark.parametrize(
    ("text", "words"),
    [
        ("a,1", "at least two rows"),
        ("Label,Value\nnorth,12\nsouth,none", "Row 3 of data.csv has no number"),
        ("", "at least two rows"),
        ("x," + "1" * 50_000, "too big"),
    ],
)
def test_a_file_that_cannot_be_a_chart_is_refused_in_words(text, words):
    with pytest.raises(draft.DraftError, match=words) as e:
        draft.csv_rows(text, "data.csv")
    assert e.value.code == "bad_file"


# ---- what the model said ------------------------------------------------------------------------


async def test_a_lower_third_is_drafted_with_the_name_as_written():
    llm = FakeLLM("lower_third", {"name": "Maya Chen", "role": "Head of Design"})
    prompt = 'A lower third for "Maya Chen", Head of Design'
    out = await draft.draft(llm, prompt)
    assert out["template"] == "lower_third" and out["warnings"] == []
    assert out["fields"] == {"name": "Maya Chen", "role": "Head of Design"}
    assert out["summary"] == "Lower third: name “Maya Chen”, role “Head of Design”"
    assert [c[1] for c in llm.calls] == [prompt, prompt]  # the words reach the model untouched
    assert set(llm.calls[1][2]["properties"]) == {f.id for f in templates.get("lower_third").fields}


async def test_a_name_the_model_changed_is_flagged_and_still_filled_in():
    out = await draft.draft(
        FakeLLM("lower_third", {"name": "Maya Chan"}), 'lower third for "Maya Chen"'
    )
    assert out["fields"]["name"] == "Maya Chan"
    assert out["warnings"] == [
        "“Maya Chen” is not in the form exactly as you wrote it. Check the words before you go on."
    ]


@pytest.mark.parametrize("quote", ['"Maya Chen"', "“Maya Chen”", "«Maya Chen»"])
def test_every_kind_of_quotation_mark_is_noticed(quote):
    assert draft.quoted(f"for {quote}, Head") == ["Maya Chen"]
    assert draft.quoted("it's Maya's day") == []  # an apostrophe is not a quote


async def test_empty_and_unknown_fields_are_dropped():
    llm = FakeLLM("title", {"title": "Launch day", "seconds": 30, "theme": "forest", "x": "no"})
    out = await draft.draft(llm, "Launch day in green, 30 seconds")
    assert out["fields"] == {"title": "Launch day", "seconds": 30, "theme": "forest"}


async def test_a_length_the_templates_cannot_make_is_a_warning_not_a_crash():
    out = await draft.draft(FakeLLM("title", {"title": "Hi", "seconds": 500}), "Hi for 500 seconds")
    assert out["fields"]["seconds"] == 500
    assert any("between 3 and 90" in w for w in out["warnings"])


async def test_a_missing_required_word_is_said_so_the_form_can_ask_for_it():
    out = await draft.draft(FakeLLM("quote"), "a quote")
    assert out["warnings"] == ["Write a quote."]


async def test_the_shape_the_person_chose_wins():
    llm = FakeLLM("title", {"title": "Hi", "shape": "landscape"})
    out = await draft.draft(llm, "Hi", shape="portrait")
    assert out["fields"]["shape"] == "portrait"


async def test_an_attached_csv_makes_a_chart_whatever_the_model_says():
    llm = FakeLLM("title", {"title": "Sales", "data": "North, 999"})
    attachment = {"name": "sales-2026.csv", "text": "Region,Sales\nNorth,$120\nSouth,95"}
    out = await draft.draft(llm, "make a chart", attachment)
    assert out["template"] == "chart"
    assert out["fields"]["data"] == "North, $120\nSouth, 95"  # the file, not the model
    assert out["fields"]["title"] == "Sales" and out["warnings"] == []
    assert len(llm.calls) == 1 and "app takes the rows" in llm.calls[0][0]  # no choosing needed


async def test_a_csv_with_no_request_and_no_title_is_named_by_its_file():
    llm = FakeLLM("title")
    out = await draft.draft(llm, "", {"name": "sales-2026.csv", "text": "a,1\nb,2"})
    assert out["fields"]["title"] == "sales-2026" and out["template"] == "chart"
    assert llm.calls[0][1] == "A chart of the attached file."


async def test_a_bad_file_stops_before_the_model_is_asked():
    llm = FakeLLM("chart")
    with pytest.raises(draft.DraftError):
        await draft.draft(llm, "chart", {"name": "x.csv", "text": "a,1"})
    assert llm.calls == []


@pytest.mark.parametrize("raw", ["not json", "[1]", "{}", json.dumps({"template": "poster"})])
async def test_an_answer_that_cannot_be_read_is_said_in_words(raw):
    with pytest.raises(draft.DraftError, match="could not be read") as e:
        await draft.draft(FakeLLM(raw=raw), "something")
    assert e.value.code == "bad_answer"


async def test_a_fields_answer_that_is_not_an_object_is_said_in_words_too():
    class Half(FakeLLM):
        async def complete(self, system, prompt, schema, max_tokens=800):
            if set(schema["properties"]) == {"template"}:
                return '{"template": "title"}'
            return "I cannot do that."

    with pytest.raises(draft.DraftError, match="could not be read"):
        await draft.draft(Half(), "a title")


async def test_nothing_to_go_on_and_too_much_are_refused():
    with pytest.raises(draft.DraftError, match="Describe what to make"):
        await draft.draft(FakeLLM(), "   ")
    with pytest.raises(draft.DraftError, match="2000 characters"):
        await draft.draft(FakeLLM(), "x" * 2001)


@pytest.mark.parametrize(
    ("prompt", "key", "value", "asked"),
    [
        ("a vertical title", "shape", "portrait", True),
        ("title for TikTok", "shape", "portrait", True),
        ("a title", "shape", "square", False),
        ("make it green", "theme", "forest", True),
        ("a title", "theme", "paper", False),
        ("in a serif font", "font", "serif", True),
        ("a title", "font", "sans", False),
        ("a 30 second title", "seconds", 30, True),
        ("for 1 minute", "seconds", 60, True),
        ("1.5 minutes", "seconds", 90, True),
        ("Annual Report 2026", "seconds", 60, False),
        ("a 30 second title", "seconds", 60, False),
    ],
)
def test_a_setting_is_kept_only_when_the_request_asks_for_it(prompt, key, value, asked):
    assert draft.asked_for(prompt, key, value) is asked


async def test_a_look_the_model_made_up_is_dropped():
    llm = FakeLLM("quote", {"quote": "Still I rise.", "shape": "square", "theme": "paper",
                            "font": "sans", "seconds": 7})  # fmt: skip
    out = await draft.draft(llm, 'Quote: "Still I rise."')
    assert out["fields"] == {"quote": "Still I rise."}


async def test_an_answer_that_trails_off_without_its_closing_brace_is_closed():
    raw = '{"title": "Hi",\n  \n  \n  '
    llm = FakeLLM("title", raw=None)

    async def complete(system, prompt, schema, max_tokens=800):
        return '{"template": "title"}' if set(schema["properties"]) == {"template"} else raw

    llm.complete = complete  # type: ignore[method-assign]
    out = await draft.draft(llm, "Hi")
    assert out["fields"] == {"title": "Hi"}
