"""The four tools are catalogue actions (ADR-0068): the move changes nothing the person sees."""

from assistant_rig import FakeHost, Rig
from wasifyai_assistant.tools import (
    POLICY,
    TOOL_ACTIONS,
    TOOL_DEFINITIONS,
    action_input,
    outcome_of,
)
from wasifyai_image.actions import actions as image_actions
from wasifyai_notebooks.actions import actions as notebook_actions
from wasifyai_platform_sdk.actions import (
    ActionRegistry,
    ActionResult,
    builtin_actions,
    decide,
)
from wasifyai_voice.actions import actions as voice_actions


def registry() -> ActionRegistry:
    return ActionRegistry(
        [*builtin_actions(), *image_actions(), *voice_actions(), *notebook_actions()]
    )


def test_every_tool_runs_an_action_that_is_offered_to_the_assistant():
    reg = registry()
    assert set(TOOL_ACTIONS) == {t["function"]["name"] for t in TOOL_DEFINITIONS}
    for tool, action_id in TOOL_ACTIONS.items():
        action = reg.get(action_id)
        assert action is not None, tool
        assert "assistant" in action.surfaces, tool


def test_what_a_tool_takes_the_action_takes():
    reg = registry()
    for tool in TOOL_DEFINITIONS:
        fn = tool["function"]
        action = reg.get(TOOL_ACTIONS[fn["name"]])
        assert action is not None
        wanted = action.input.model_json_schema()["properties"]
        # the tool names the arguments the action's own schema names (the tool may have fewer)
        mapped = {"description", "lyrics", "instrumental", "seconds", "prompt", "size", "query"}
        assert set(fn["parameters"]["properties"]) <= set(wanted) | mapped


def test_the_arguments_are_mended_as_they_always_were():
    assert action_input("generate_image", {"prompt": " a fox ", "size": "huge"}) == {
        "prompt": "a fox", "size": "square",
    }  # fmt: skip
    assert len(action_input("generate_image", {"prompt": "x" * 900})["prompt"]) == 500  # type: ignore[index]
    assert (
        action_input("generate_image", {"prompt": " "})
        == "The prompt was empty, so no image was made."
    )
    music = action_input("make_music", {"description": "pop", "lyrics": "la", "seconds": 999})
    assert music == {"description": "pop", "lyrics": "la", "seconds": 120.0}
    assert action_input("make_music", {"description": "pop", "seconds": 1})["seconds"] == 5.0  # type: ignore[index]
    quiet = action_input("make_music", {"description": "x", "instrumental": True})
    assert isinstance(quiet, dict) and quiet["instrumental"] is True
    assert action_input("search_creations", {"query": ""}) == "There was nothing to search for."


def test_the_result_keeps_its_old_shape():
    ok = ActionResult(
        status="ok", action_id="image.generate", text="Made.", output={"image_id": "i"}
    )
    assert outcome_of("generate_image", ok).text == "Made. The person can see it in the chat."
    assert outcome_of("search_creations", ok).text == "Made."
    refused = ActionResult(status="refused", action_id="x", text="No.", code="c")
    out = outcome_of("generate_image", refused)
    assert (out.status, out.output, out.text) == ("refused", {"message": "No."}, "No.")
    setup = ActionResult(status="needs_setup", action_id="x", text="Get a model.")
    assert outcome_of("make_music", setup).status == "error"


def test_the_assistants_setting_lets_it_make_things_but_never_delete_or_clone():
    reg = registry()
    for action in reg:
        if action.effect == "destroy" or "needs_consent" in action.flags:
            assert decide(action, POLICY) == "ask", action.id
    for action_id in TOOL_ACTIONS.values():
        action = reg.get(action_id)
        assert action is not None and decide(action, POLICY) == "run"


async def test_a_tool_call_leaves_an_audit_entry_and_a_usage_event(tmp_path, ctx):
    host = FakeHost()
    call = {
        "text": "",
        "tool_calls": [{"name": "generate_image", "arguments": {"prompt": "a fox"}}],
    }
    rig = Rig(tmp_path, [call, {"text": "Here."}], host)
    await rig.turn("draw a fox")
    audit = rig.executor.audit.entries  # type: ignore[attr-defined]
    assert [(e.action_id, e.origin, e.status) for e in audit] == [
        ("image.generate", "assistant", "ok")
    ]
    assert [e.meta["action"] for e in rig.usage.events if e.kind == "action.run"] == [
        "image.generate"
    ]
