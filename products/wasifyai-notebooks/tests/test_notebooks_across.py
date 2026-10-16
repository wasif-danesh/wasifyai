"""Searching all of one person's notebooks at once (the assistant's `search_notebooks` tool)."""

import pytest
from notebooks_rig import FakeComponents
from test_notebooks_chat import BUDGET, PEOPLE, Rig
from wasifyai_notebooks.across import PASSAGE_CHARS, search_across
from wasifyai_notebooks.ingest import ingest_one, original_path
from wasifyai_platform_sdk import RunContext, ToolUnavailable, reset_context, set_context

CTX = RunContext("t1", "wasifyai-notebooks", "u1", run_id="r1", thread_id="th1")


@pytest.fixture
def ctx():
    token = set_context(CTX)
    yield CTX
    reset_context(token)


async def test_the_best_passage_across_notebooks_comes_first_with_where_it_is(tmp_path, ctx):
    rig = Rig(tmp_path, [])
    await rig.add("budget.md", BUDGET)
    other = rig.store.create_notebook("t1", "u1", "Hiring")
    rig.nb = other  # the next source goes into the second notebook
    await rig.add("people.md", PEOPLE)

    hits = await search_across(rig.runtime, "t1", "u1", "marketing budget for the launch", 5)

    assert hits[0]["notebook"] == "Notebook" and hits[0]["title"] == "budget.md"
    assert "$350,000" in hits[0]["text"]
    assert {h["notebook"] for h in hits} == {"Notebook", "Hiring"}
    assert set(hits[0]) == {"notebook_id", "notebook", "document_id", "title", "text"}


async def test_only_the_persons_own_ready_notebooks_are_searched(tmp_path, ctx):
    rig = Rig(tmp_path, [])
    await rig.add("budget.md", BUDGET)
    rig.store.create_notebook("t1", "u1", "Empty")  # nothing in it
    theirs = rig.store.create_notebook("t1", "someone-else", "Theirs")
    doc, _ = rig.store.add_file(
        "t1", "someone-else", theirs["id"], title="secret.md", suffix=".txt", mime="text/plain",
        size_bytes=40, sha256="secret",
    )  # fmt: skip
    path = original_path(rig.files, theirs["id"], doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Secret\n\nThe launch budget is hidden here.\n")
    await ingest_one(
        rig.store, rig.components, rig.reader, rig.files, doc, tokenizer_factory=lambda: "word"
    )

    hits = await search_across(rig.runtime, "t1", "u1", "launch budget", 8)

    assert {h["notebook"] for h in hits} == {"Notebook"}
    assert not await search_across(rig.runtime, "t1", "nobody", "launch budget", 8)


async def test_the_limit_and_the_passage_length_hold(tmp_path, ctx):
    rig = Rig(tmp_path, [])
    await rig.add("long.md", "# Long\n\n" + ("launch budget " * 400))
    await rig.add("budget.md", BUDGET)
    await rig.add("people.md", PEOPLE)

    hits = await search_across(rig.runtime, "t1", "u1", "launch budget", 2)

    assert len(hits) == 2
    assert all(len(h["text"]) <= PASSAGE_CHARS for h in hits)


async def test_one_source_does_not_fill_every_slot(tmp_path, ctx):
    rig = Rig(tmp_path, [])
    many = "".join(f"# Part {i}\n\nThe launch budget item {i} is large.\n\n" for i in range(12))
    await rig.add("long.md", many)
    await rig.add("budget.md", BUDGET)

    hits = await search_across(rig.runtime, "t1", "u1", "launch budget", 5)

    per_doc = [h["title"] for h in hits]
    assert per_doc.count("long.md") <= 2 and "budget.md" in per_doc


async def test_an_empty_question_finds_nothing(tmp_path, ctx):
    rig = Rig(tmp_path, [])
    await rig.add("budget.md", BUDGET)
    assert await search_across(rig.runtime, "t1", "u1", "   ", 5) == []


async def test_a_missing_search_model_is_a_tool_problem_not_a_crash(tmp_path, ctx):
    rig = Rig(tmp_path, [], embedder_ready=False)
    assert isinstance(rig.components, FakeComponents)
    with pytest.raises(ToolUnavailable, match="search model"):
        await search_across(rig.runtime, "t1", "u1", "anything", 5)


@pytest.mark.parametrize(
    "query",
    [
        '"unbalanced',
        "NEAR(",
        "budget OR",
        "*",
        "a AND NOT",
        "col:budget",
        "\x00 budget",
        "'; DROP TABLE x;--",
    ],
)
async def test_hostile_or_odd_queries_never_break_the_search(tmp_path, ctx, query):
    rig = Rig(tmp_path, [])
    await rig.add("budget.md", BUDGET)
    hits = await search_across(rig.runtime, "t1", "u1", query, 5)
    assert isinstance(hits, list)
