# ruff: noqa: E501  (test data is easier to read on one line)
"""The Agent Server's events in the place's own words (`events.py`), and how a turn's end is
worked out. The events here have the shapes of `agent_types.py`."""

from wasifyai_code import place as places
from wasifyai_code.events import MAX_ARG, MAX_TEXT, Reader, given, text_of


def state(value, event_id="e-state"):
    return {
        "id": event_id, "kind": "ConversationStateUpdateEvent", "source": "environment",
        "key": "execution_status", "value": value,
    }  # fmt: skip


def action(tool, call="c1", **given_to_it):
    return {
        "id": f"a-{call}", "kind": "ActionEvent", "source": "agent", "tool_name": tool,
        "tool_call_id": call, "action": {"kind": "SomeAction", **given_to_it},
    }  # fmt: skip


def observation(tool, call="c1", text="done", is_error=False):
    return {
        "id": f"o-{call}", "kind": "ObservationEvent", "source": "environment", "tool_name": tool,
        "tool_call_id": call, "action_id": f"a-{call}",
        "observation": {"content": [{"type": "text", "text": text}], "is_error": is_error},
    }  # fmt: skip


def test_a_tool_step_and_what_it_gave_back():
    r = Reader()
    (step,) = r.read(action("grep", pattern="TODO", path="/w", include=None))
    assert step == (places.STEP, {"tool": "grep", "id": "c1", "pattern": "TODO", "path": "/w"})
    (result,) = r.read(observation("grep", text="2 matches"))
    assert result == (places.RESULT, {"id": "c1", "tool": "grep", "ok": True, "text": "2 matches"})
    assert r.steps == 1


def test_a_failed_tool_a_refused_one_and_an_error_told_to_the_agent_are_not_ok():
    r = Reader()
    r.read(action("planning_file_editor", command="create", path="/w/a.txt"))
    (failed,) = r.read(observation("planning_file_editor", text="not allowed", is_error=True))
    assert failed[1]["ok"] is False and failed[1]["text"] == "not allowed"
    (told,) = r.read(
        {"kind": "AgentErrorEvent", "tool_name": "glob", "tool_call_id": "c2", "error": "bad path"}
    )
    assert told == (places.RESULT, {"id": "c2", "tool": "glob", "ok": False, "text": "bad path"})
    (no,) = r.read(
        {"kind": "UserRejectObservation", "tool_call_id": "c1", "rejection_reason": "Not now."}
    )
    # the tool's name is remembered from the step when the event does not carry it
    assert no == (
        places.RESULT, {"id": "c1", "tool": "planning_file_editor", "ok": False, "text": "Not now."}
    )  # fmt: skip


def test_what_a_tool_was_given_is_short_and_never_a_files_content():
    shown = given(
        {
            "kind": "FileEditorAction", "command": "create", "path": "/w/big.py",
            "file_text": "x" * 9000, "old_str": "secret", "new_str": "other",
            "view_range": [1, 40], "insert_line": None, "note": "n" * 2000, "nested": {"a": 1},
        }
    )  # fmt: skip
    assert shown == {
        "command": "create", "path": "/w/big.py", "view_range": [1, 40],
        "note": "n" * MAX_ARG + "…",
    }  # fmt: skip
    r = Reader()
    (result,) = r.read(observation("grep", text="y" * (MAX_TEXT + 500)))
    assert len(result[1]["text"]) == MAX_TEXT + 1


def test_the_agents_last_message_is_what_it_finished_with():
    r = Reader()
    (said,) = r.read(action("finish", message="Here is the map."))
    assert said == (places.TEXT, {"text": "Here is the map."})
    assert r.read(observation("finish", text="Here is the map.")) == []
    assert r.steps == 0  # finishing is not a step
    assert r.read(action("think", thought="hmm")) == [] and r.steps == 0


def test_a_message_of_the_agent_is_text_and_the_persons_own_is_passed_over():
    r = Reader()
    agent = {
        "kind": "MessageEvent", "source": "agent",
        "llm_message": {"role": "assistant", "content": [{"type": "text", "text": "Two parts."}]},
    }  # fmt: skip
    assert r.read(agent) == [(places.TEXT, {"text": "Two parts."})]
    assert r.read({**agent, "source": "user"}) == []
    empty = {**agent, "llm_message": {"role": "assistant", "content": []}}
    assert r.read(empty) == []
    assert text_of([{"type": "text", "text": "a"}, {"type": "image"}, {"text": "b"}]) == "a\nb"


def test_words_as_they_are_written_and_thinking_apart():
    r = Reader()
    assert r.read({"kind": "StreamingDeltaEvent", "content": "Hel"}) == [
        (places.PIECE, {"text": "Hel"})
    ]
    assert r.read({"kind": "StreamingDeltaEvent", "reasoning_content": "let me see"}) == [
        (places.PIECE, {"text": "let me see", "thinking": True})
    ]
    assert r.read({"kind": "StreamingDeltaEvent", "content": None}) == []


def test_kinds_the_product_does_not_read_are_passed_over():
    r = Reader()
    for kind in ("SystemPromptEvent", "TokenEvent", "Condensation", "PauseEvent", "Whatever"):
        assert r.read({"kind": kind, "id": "x"}) == []
    assert r.read({"id": "no-kind"}) == []
    whole = {
        "kind": "ConversationStateUpdateEvent",
        "key": "full_state",
        "value": {"execution_status": "idle"},
    }  # noqa: E501
    assert r.read(whole) == [] and r.status == "idle" and not r.over


def test_a_turn_is_over_when_a_running_conversation_comes_to_rest():
    r = Reader()
    assert r.read(state("idle")) == [(places.STATE, {"state": "idle", "engine": "idle"})]
    assert not r.over  # it was never running: nothing ended
    assert r.read(state("running")) == [(places.STATE, {"state": "running"})]
    r.read(action("glob", pattern="*"))
    assert not r.over
    r.read(state("waiting_for_confirmation"))
    assert not r.over  # waiting for a yes or no is not the end
    r.read(state("finished", "e-rest"))
    assert r.over and r.rest_id == "e-rest"
    assert r.end() == {"why": places.FINISHED, "detail": "", "steps": 1}


def test_the_steps_are_counted_per_turn():
    r = Reader()
    r.read(state("running"))
    r.read(action("glob", "c1"))
    r.read(action("grep", "c2"))
    r.read(state("finished"))
    assert r.end()["steps"] == 2
    r.over = False
    r.read(state("running"))
    r.read(action("grep", "c3"))
    r.read(state("finished"))
    assert r.end()["steps"] == 1


def test_why_a_turn_ended():
    def rested(status, *before):
        r = Reader()
        r.read(state("running"))
        for event in before:
            r.read(event)
        r.read(state(status))
        return r

    error = {"kind": "ConversationErrorEvent", "code": "LLMError", "detail": "The model is down."}
    limit = {"kind": "ConversationErrorEvent", "code": "MaxIterationsReached", "detail": "40"}
    assert rested("finished").end()["why"] == places.FINISHED
    assert rested("paused").end()["why"] == places.STOPPED
    assert rested("error", limit).end()["why"] == places.STEP_LIMIT
    failed = rested("error", error).end()
    assert failed["why"] == places.ERROR and failed["detail"] == "The model is down."
    assert rested("error").end()["detail"] == "The coding engine reported an error."
    assert "round in circles" in rested("stuck").end()["detail"]
    # what only the gateway saw: a refusal by the model, whatever the engine made of it
    refusal = {"refusal": {"message": "The model declined this request.", "category": "cyber"}}
    for status in ("finished", "stuck", "error"):
        ended = rested(status).end(refusal)
        assert ended["why"] == places.REFUSED
        assert ended["detail"] == "The model declined this request."
    # a call refused at the cost limit reaches the engine as an error: it is said as the limit
    over = rested("error", error).end({"over_limit": "This session reached its cost limit."})
    assert over["why"] == places.ERROR and over["detail"] == "This session reached its cost limit."
    # an error that came after the conversation rested still explains it
    late = rested("error")
    late.read(error)
    assert late.end()["detail"] == "The model is down."


# ---- the generated shapes ----------------------------------------------------------------------------


def test_the_generated_types_are_what_the_excerpt_gives_for_the_pinned_version():
    """`agent_types.py` is made from `services/coding-engine/api-excerpt.json`, which is cut from
    the pinned Agent Server's own API description. Neither is edited by hand, and both are for
    the version in `services/coding-engine/VERSION`."""
    import importlib.util
    from pathlib import Path

    from wasifyai_code import agent_types

    script = Path(__file__).resolve().parents[3] / "scripts" / "coding-engine-types.py"
    spec = importlib.util.spec_from_file_location("coding_engine_types", script)
    assert spec is not None and spec.loader is not None
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    assert generator.check() == []
    assert set(agent_types.EVENT_KINDS) == set(generator.EVENTS)
    pinned = (generator.PINS / "VERSION").read_text().strip()
    assert agent_types.AGENT_SERVER_VERSION == pinned
