"""The assistant's tool host: it acts for the user of the run, and says when a tool is not here."""

import pytest
from wasifyai_api.tool_host import ApiToolHost
from wasifyai_platform_sdk import RunContext, ToolUnavailable, reset_context, set_context


@pytest.fixture
def ctx():
    token = set_context(RunContext("t9", "wasifyai-assistant", "u9", run_id="r", thread_id="th"))
    yield
    reset_context(token)


async def test_notebook_search_is_asked_for_the_runs_user_with_a_bounded_query(ctx):
    seen: list[tuple] = []

    async def search(tenant, user, query, limit):
        seen.append((tenant, user, query, limit))
        return [
            {"notebook_id": "n", "notebook": "N", "document_id": "d", "title": "t", "text": "x"}
        ]

    host = ApiToolHost(lambda: None, lambda: None, notebook_search=search)
    out = await host.search_notebooks("  " + "q" * 900 + " ", 50)

    assert out[0]["notebook_id"] == "n"
    assert seen == [("t9", "u9", "q" * 300, 8)]
    await host.search_notebooks("x", 0)
    assert seen[-1][3] == 1


async def test_without_notebooks_the_tool_says_so(ctx):
    host = ApiToolHost(lambda: None, lambda: None)
    with pytest.raises(ToolUnavailable, match="not available"):
        await host.search_notebooks("anything")
