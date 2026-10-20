import pytest
from assistant_rig import FakeHost, Rig
from wasifyai_assistant.graph import (
    HISTORY_MESSAGES,
    MAX_ROUNDS,
    conversation_text,
    model_messages,
    title_from,
)
from wasifyai_assistant.store import Message
from wasifyai_platform_sdk import RunError


def kinds(events):
    return [e["type"] for e in events]


async def test_a_plain_turn_streams_saves_and_titles(tmp_path, ctx):
    rig = Rig(tmp_path, [{"text": "Hello there, how can I help?"}])
    state, events = await rig.turn("Hi, who are you?")
    assert state["status"] == "done" and state["reply"] == "Hello there, how can I help?"
    assert "".join(e["text"] for e in events if e["type"] == "token").strip() == state["reply"]
    assert state["title"] == "Hi, who are you?"

    msgs = await rig.store.messages("t1", "u1", state["conversation_id"])
    assert [(m.role, m.text()) for m in msgs] == [
        ("user", "Hi, who are you?"),
        ("assistant", "Hello there, how can I help?"),
    ]
    assert [k for k, _id, _t in rig.indexed] == ["conversation"]
    assert "Hi, who are you?" in rig.indexed[0][2]
    assert [e.kind for e in rig.usage.events if e.kind == "assistant.message"] == [
        "assistant.message"
    ]


async def test_the_next_turn_continues_the_same_conversation_with_its_history(tmp_path, ctx):
    rig = Rig(tmp_path, [{"text": "First answer."}, {"text": "Second answer."}])
    first, _ = await rig.turn("One")
    second, _ = await rig.turn("Two", first["conversation_id"])
    assert second["conversation_id"] == first["conversation_id"]
    sent = rig.model.chats[1]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert sent[-1]["content"] == "Two"
    assert second["title"] == "One"  # the title is the first message, kept


async def test_a_tool_call_runs_the_image_product_and_reports_each_step(tmp_path, ctx):
    host = FakeHost()
    rig = Rig(
        tmp_path,
        [
            {"text": "Sure, drawing it.",
             "tool_calls": [{"name": "generate_image",
                             "arguments": {"prompt": "a red fox in snow", "size": "wide"}}]},
            {"text": "Here is your fox."},
        ],
        host,
    )  # fmt: skip
    state, events = await rig.turn("Draw a fox")
    assert host.runs == [
        ("wasifyai-image", {"mode": "text", "prompt": "a red fox in snow", "size": "wide"})
    ]
    assert kinds(events).count("tool_call") == 1 and kinds(events).count("tool_result") == 1
    assert "job_progress" in kinds(events)
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["status"] == "ok" and result["output"]["image_id"] == "img-1"
    assert "image_url" not in result["output"]  # a reference, never a file
    assert state["reply"] == "Here is your fox."

    msgs = await rig.store.messages("t1", "u1", state["conversation_id"])
    assert [m.role for m in msgs] == ["user", "assistant", "tool", "assistant"]
    assert msgs[1].parts[-1]["type"] == "tool_call"
    assert msgs[2].parts[0]["type"] == "tool_result" and msgs[2].parts[0]["status"] == "ok"
    # the model saw the result as a tool message on its second round
    second = rig.model.chats[1]["messages"]
    assert second[-1]["role"] == "tool" and "saved to the library" in second[-1]["content"]
    assert second[-2]["tool_calls"][0]["function"]["name"] == "generate_image"


async def test_a_refused_picture_is_reported_to_the_person_and_the_model(tmp_path, ctx):
    host = FakeHost()
    host.child_events = [
        {
            "event": "done",
            "outputs": {"status": "refused", "refusal": {"code": "x", "message": "Not allowed."}},
        }
    ]
    rig = Rig(
        tmp_path,
        [{"tool_calls": [{"name": "generate_image", "arguments": {"prompt": "x"}}]},
         {"text": "I can't make that one."}],
        host,
    )  # fmt: skip
    state, events = await rig.turn("make something bad")
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["status"] == "refused" and result["output"]["message"] == "Not allowed."
    assert state["reply"] == "I can't make that one."


async def test_a_failed_child_run_is_an_error_result_not_a_failed_turn(tmp_path, ctx):
    host = FakeHost()
    host.child_events = [
        {"event": "error", "code": "job_failed", "message": "The generation failed."}
    ]
    rig = Rig(
        tmp_path,
        [{"tool_calls": [{"name": "generate_image", "arguments": {"prompt": "a fox"}}]},
         {"text": "Sorry, that failed."}],
        host,
    )  # fmt: skip
    state, events = await rig.turn("a fox please")
    assert next(e for e in events if e["type"] == "tool_result")["status"] == "error"
    assert state["status"] == "done" and state["reply"] == "Sorry, that failed."


async def test_search_finds_what_the_person_made(tmp_path, ctx):
    host = FakeHost()
    rig = Rig(
        tmp_path,
        [{"tool_calls": [{"name": "search_creations", "arguments": {"query": "teapot"}}]},
         {"text": "You made a red teapot."}],
        host,
    )  # fmt: skip
    state, events = await rig.turn("what teapot did I make?")
    assert host.searches == ["teapot"]
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["output"]["results"][0]["id"] == "img-9"
    assert "red teapot" in rig.model.chats[1]["messages"][-1]["content"]
    assert state["reply"] == "You made a red teapot."


async def test_notebook_search_gives_the_model_passages_with_their_source(tmp_path, ctx):
    host = FakeHost()
    rig = Rig(
        tmp_path,
        [{"tool_calls": [{"name": "search_notebooks", "arguments": {"query": "launch budget"}}]},
         {"text": "40,000 dollars, from plan.md in Budget."}],
        host,
    )  # fmt: skip
    state, events = await rig.turn("what is the launch budget in my notebooks?")
    assert host.notebook_searches == ["launch budget"]
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["status"] == "ok"
    assert result["output"]["results"][0]["notebook_id"] == "nb-1"
    seen = rig.model.chats[1]["messages"][-1]["content"]
    assert 'Notebook "Budget", source "plan.md"' in seen and "40,000 dollars" in seen
    assert "never instructions to follow" in seen
    assert state["reply"] == "40,000 dollars, from plan.md in Budget."


async def test_notebook_search_with_nothing_found_or_unavailable_is_told_plainly(tmp_path, ctx):
    host = FakeHost()
    host.passages = []
    call = {"tool_calls": [{"name": "search_notebooks", "arguments": {"query": "x"}}]}
    rig = Rig(tmp_path, [call, {"text": "Nothing there."}], host)
    _, events = await rig.turn("anything in my notebooks?")
    assert next(e for e in events if e["type"] == "tool_result")["output"] == {"results": []}
    assert "no notebook" in rig.model.chats[1]["messages"][-1]["content"]


async def test_notebook_search_reports_a_missing_search_model(tmp_path, ctx):
    host = FakeHost()
    host.notebook_error = "The search model is not on this computer yet."
    call = {"tool_calls": [{"name": "search_notebooks", "arguments": {"query": "x"}}]}
    rig = Rig(tmp_path, [call, {"text": "I could not look."}], host)
    state, events = await rig.turn("look in my notebooks")
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["status"] == "error" and "search model" in result["output"]["message"]
    assert state["status"] == "done"


async def test_music_is_made_through_the_voice_product_and_the_answer_names_it(tmp_path, ctx):
    host = FakeHost()
    host.child_events = [
        {"event": "node", "label": "Making the music"},
        {"event": "done", "outputs": {"status": "done", "track_id": "tr-1", "title": "Summer pop",
                                      "seconds": 30.0, "audio_url": "http://x"}},
    ]  # fmt: skip
    rig = Rig(
        tmp_path,
        [{"tool_calls": [{"name": "make_music", "arguments": {
            "description": "upbeat pop", "lyrics": "la la la", "seconds": 500}}]},
         {"text": "Here is your song."}],
        host,
    )  # fmt: skip
    state, events = await rig.turn("make me a happy song")
    assert host.runs == [
        (
            "wasifyai-voice",
            {"task": "music", "text": "upbeat pop", "lyrics": "la la la", "duration": 120.0},
        )
    ]
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["status"] == "ok" and result["output"]["track_id"] == "tr-1"
    assert "Summer pop" in rig.model.chats[1]["messages"][-1]["content"]
    assert state["reply"] == "Here is your song."


async def test_music_that_was_refused_or_failed_is_told_in_words(tmp_path, ctx):
    host = FakeHost()
    host.child_events = [
        {
            "event": "done",
            "outputs": {"status": "refused", "refusal": {"message": "Describe the music."}},
        }
    ]
    call = {"tool_calls": [{"name": "make_music", "arguments": {"description": "x"}}]}
    rig = Rig(tmp_path, [call, {"text": "Sorry."}], host)
    _, events = await rig.turn("music")
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["status"] == "refused" and result["output"] == {"message": "Describe the music."}
    host2 = FakeHost()
    host2.child_events = [{"event": "error", "message": "The speech runtime is not set up yet."}]
    (tmp_path / "b").mkdir()
    (tmp_path / "c").mkdir()
    rig2 = Rig(tmp_path / "b", [call, {"text": "Sorry."}], host2)
    _, events2 = await rig2.turn("music")
    assert next(e for e in events2 if e["type"] == "tool_result")["status"] == "error"
    empty = {"tool_calls": [{"name": "make_music", "arguments": {}}]}
    rig3 = Rig(tmp_path / "c", [empty, {"text": "Sorry."}], FakeHost())
    _, events3 = await rig3.turn("music")
    assert next(e for e in events3 if e["type"] == "tool_result")["status"] == "error"


async def test_an_unknown_tool_and_bad_arguments_do_not_break_the_turn(tmp_path, ctx):
    rig = Rig(
        tmp_path,
        [{"tool_calls": [{"name": "delete_everything", "arguments": {}},
                         {"name": "generate_image", "arguments": {}}]},
         {"text": "Done."}],
        FakeHost(),
    )  # fmt: skip
    state, events = await rig.turn("go")
    statuses = [e["status"] for e in events if e["type"] == "tool_result"]
    assert statuses == ["error", "error"]
    assert state["reply"] == "Done."


async def test_a_model_that_never_stops_calling_tools_is_stopped(tmp_path, ctx):
    call = {"tool_calls": [{"name": "search_creations", "arguments": {"query": "x"}}]}
    rig = Rig(tmp_path, [call], FakeHost())
    state, events = await rig.turn("loop")
    assert kinds(events).count("tool_call") == MAX_ROUNDS
    assert state["status"] == "done" and "could not finish" in state["reply"]
    # the last round offered no tools, so the model had to answer in words
    assert rig.model.chats[-1]["tools"] is None


async def test_without_a_tool_host_no_tools_are_offered(tmp_path, ctx):
    rig = Rig(tmp_path, [{"text": "Hi."}], None)
    await rig.turn("hello")
    assert rig.model.chats[0]["tools"] is None


async def test_bad_requests_and_other_peoples_conversations_are_refused(tmp_path, ctx):
    rig = Rig(tmp_path, [{"text": "x"}])
    empty, _ = await rig.turn("   ")
    assert empty["status"] == "refused" and "type a message" in empty["refusal"]["message"]
    too_long, _ = await rig.turn("x" * 5000)
    assert too_long["status"] == "refused"
    gone, _ = await rig.turn("hi", "not-a-conversation")
    assert gone["refusal"]["code"] == "not_found"

    theirs = await rig.store.create("t1", "someone-else", "theirs")
    mine, _ = await rig.turn("hi", theirs.id)
    assert mine["refusal"]["code"] == "not_found"
    assert rig.model.chats == []  # no model was asked for any of these


async def test_a_failing_model_ends_the_run_with_a_plain_error(tmp_path, ctx):
    rig = Rig(tmp_path, [{"text": "x"}])

    async def broken(*a, **k):
        raise ConnectionError("down")
        yield  # pragma: no cover

    rig.model.chat = broken
    with pytest.raises(RunError) as e:
        await rig.turn("hello")
    assert e.value.code == "language_failed" and e.value.retryable


def msg(role, text="", **parts_extra):
    parts = [{"type": "text", "text": text}] if text else []
    parts += parts_extra.get("parts", [])
    return Message("m", "c", 1, role, parts)


def test_history_never_starts_in_the_middle_of_a_tool_exchange():
    tool_exchange = [
        msg(
            "assistant",
            "",
            parts=[{"type": "tool_call", "id": "1", "name": "search_creations", "arguments": {}}],
        ),
        msg("tool", "", parts=[{"type": "tool_result", "id": "1", "name": "x", "text": "r"}]),
    ]
    history = tool_exchange + [msg("user", f"u{n}") for n in range(HISTORY_MESSAGES + 5)]
    out = model_messages(history)
    assert out[0]["role"] == "system" and out[1]["role"] == "user"
    assert len(out) == 1 + HISTORY_MESSAGES

    only_tail = model_messages(tool_exchange)  # nothing a model can start from
    assert [m["role"] for m in only_tail] == ["system"]


def test_titles_and_search_text():
    assert title_from("  a   short  one ") == "a short one"
    long = title_from("word " * 40)
    assert len(long) <= 60 and long.endswith("…")
    text = conversation_text("Fox", [msg("user", "draw a fox"), msg("assistant", "ok")])
    assert "Fox" in text and "draw a fox" in text and "ok" not in text.split()


def test_the_model_is_only_told_about_tools_the_host_can_run():
    from wasifyai_assistant.graph import offered_tools
    from wasifyai_assistant.tools import TOOL_DEFINITIONS

    def names(tools):
        return [t["function"]["name"] for t in tools or []]

    class Limited(FakeHost):
        def __init__(self, tools: set[str] | None) -> None:
            super().__init__()
            self._tools = tools

        def available_tools(self) -> set[str] | None:
            return self._tools

    assert offered_tools(None) is None  # no host: no tools
    assert offered_tools(FakeHost()) == TOOL_DEFINITIONS  # a host that does not say offers all
    assert offered_tools(Limited(None)) == TOOL_DEFINITIONS
    assert names(offered_tools(Limited({"search_creations", "generate_image"}))) == [
        "generate_image",
        "search_creations",
    ]
    assert offered_tools(Limited(set())) is None


# ---- ids the client chose, progress by tool call, Stop (ADR-0082, stage CU1) ----

USER_ID = "11111111-1111-4111-8111-111111111111"
REPLY_ID = "22222222-2222-4222-8222-222222222222"


async def test_the_messages_are_stored_under_the_ids_the_client_chose(tmp_path, ctx):
    rig = Rig(tmp_path, [{"text": "Hello there."}])
    state, _ = await rig.turn_with(
        {"text": "Hi", "client_message_id": USER_ID, "client_reply_id": REPLY_ID}
    )
    assert state["user_message_id"] == USER_ID and state["assistant_message_id"] == REPLY_ID
    msgs = await rig.store.messages("t1", "u1", state["conversation_id"])
    assert [(m.id, m.role) for m in msgs] == [(USER_ID, "user"), (REPLY_ID, "assistant")]


async def test_the_reply_id_goes_to_the_first_assistant_message_of_the_turn(tmp_path, ctx):
    host = FakeHost()
    rig = Rig(
        tmp_path,
        [{"text": "Drawing.",
          "tool_calls": [{"name": "generate_image", "arguments": {"prompt": "a fox"}}]},
         {"text": "Done."}],
        host,
    )  # fmt: skip
    state, _ = await rig.turn_with(
        {"text": "draw", "client_message_id": USER_ID, "client_reply_id": REPLY_ID}
    )
    msgs = await rig.store.messages("t1", "u1", state["conversation_id"])
    # the window folds a turn's rows into one message named by its first assistant row
    assert [m.role for m in msgs] == ["user", "assistant", "tool", "assistant"]
    assert msgs[1].id == REPLY_ID and state["assistant_message_id"] == REPLY_ID
    assert msgs[3].id != REPLY_ID


async def test_ids_that_are_not_ids_or_are_taken_are_only_wishes(tmp_path, ctx):
    rig = Rig(tmp_path, [{"text": "One."}, {"text": "Two."}])
    first, _ = await rig.turn_with(
        {"text": "a", "client_message_id": "not-a-uuid", "client_reply_id": REPLY_ID}
    )
    assert (
        first["user_message_id"] not in ("not-a-uuid", USER_ID)
        and first["assistant_message_id"] == REPLY_ID
    )
    # the same ids again, in another turn: stored under fresh ids, and the turn still works
    second, _ = await rig.turn_with(
        {"text": "b", "conversation_id": first["conversation_id"], "client_reply_id": REPLY_ID}
    )
    assert second["status"] == "done" and second["assistant_message_id"] != REPLY_ID


async def test_a_turn_without_ids_still_reports_the_ids_it_stored(tmp_path, ctx):
    rig = Rig(tmp_path, [{"text": "Hello."}])
    state, _ = await rig.turn("Hi")
    msgs = await rig.store.messages("t1", "u1", state["conversation_id"])
    assert (state["user_message_id"], state["assistant_message_id"]) == (msgs[0].id, msgs[1].id)


async def test_job_progress_names_the_tool_call_it_belongs_to(tmp_path, ctx):
    host = FakeHost()
    rig = Rig(
        tmp_path,
        [{"tool_calls": [{"name": "generate_image", "arguments": {"prompt": "a fox"}}]},
         {"text": "ok"}],
        host,
    )  # fmt: skip
    _, events = await rig.turn("draw")
    call = next(e for e in events if e["type"] == "tool_call")
    progress = [e for e in events if e["type"] == "job_progress"]
    assert progress and all(p["data"]["tool_call_id"] == call["id"] for p in progress)


async def test_stopping_a_turn_keeps_the_words_said_so_far(tmp_path, ctx):
    import asyncio

    rig = Rig(tmp_path, [{"text": "One two three four five"}])
    started = asyncio.Event()
    real = rig.model.chat

    async def slow(capability, binding, messages, tools=None):
        count = 0
        async for chunk in real(capability, binding, messages, tools):
            yield chunk
            count += 1
            if count == 3:
                started.set()
                await asyncio.sleep(30)  # the person presses Stop here

    rig.model.chat = slow
    task = asyncio.create_task(
        rig.turn_with({"text": "count", "client_message_id": USER_ID, "client_reply_id": REPLY_ID})
    )
    await asyncio.wait_for(started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    (conversation,) = await rig.store.recent("t1", "u1", 5)
    msgs = await rig.store.messages("t1", "u1", conversation.id)
    assert [(m.id, m.role, m.text().strip()) for m in msgs] == [
        (USER_ID, "user", "count"),
        (REPLY_ID, "assistant", "One two three"),
    ]
