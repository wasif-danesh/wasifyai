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


async def test_a_3d_engine_without_an_installer_is_asked_whether_it_is_ready():
    # the web's 3D engine is a cloud one with no installer: app.status failed (test E, 2026-11-21)
    from types import SimpleNamespace

    from wasifyai_platform_sdk.actions import need_runtime

    class Cloud3d:
        def __init__(self, ready: bool):
            self._ready = ready

        def ready(self) -> bool:
            return self._ready

        def problem(self) -> str | None:
            return None if self._ready else "The worker is not ready."

    for ready, state in [(True, "ready"), (False, "needs_setup")]:
        host = ApiToolHost(
            runs=lambda: None, index=lambda: None,
            state=lambda r=ready: SimpleNamespace(model3d=Cloud3d(r), video_builder=Cloud3d(r)),
        )  # fmt: skip
        assert (await host.readiness(need_runtime("model3d"))).state == state
        # Motion graphics' engine on the web has no installer either
        assert (await host.readiness(need_runtime("video-builder"))).state != "unavailable"


def test_a_nul_in_a_run_input_is_taken_out():
    from wasifyai_api.routes import without_nul

    got = without_nul({"text": "hi\x00 there", "list": ["a\x00", 1, None], "k\x00": {"x": "\x00"}})
    assert got == {"text": "hi there", "list": ["a", 1, None], "k": {"x": ""}}
