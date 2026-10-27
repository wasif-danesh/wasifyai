"""The meta-tools (ADR-0071 decision 3) run catalogue actions (ADR-0068) through the one executor;
the help corpus answers how_to; the card is drawn from the action's own schema."""

from assistant_rig import FakeHost, Rig
from wasifyai_assistant import help as guides
from wasifyai_assistant.tools import (
    ASK,
    POLICY,
    PROPOSE,
    TOOL_ACTIONS,
    TOOL_DEFINITIONS,
    TOOL_NAMES,
    action_input,
    card_fields,
    card_of,
    estimate_of,
    outcome_of,
)
from wasifyai_image.actions import actions as image_actions
from wasifyai_notebooks.actions import actions as notebook_actions
from wasifyai_platform_sdk.actions import (
    ActionRegistry,
    ActionResult,
    Readiness,
    builtin_actions,
    decide,
)
from wasifyai_voice.actions import actions as voice_actions


def registry() -> ActionRegistry:
    return ActionRegistry(
        [*builtin_actions(), *image_actions(), *voice_actions(), *notebook_actions()]
    )


def test_the_tool_list_is_fixed_and_every_bound_tool_runs_an_offered_action():
    reg = registry()
    assert TOOL_NAMES == [
        "how_to", "app_status", "propose_action", "open_screen", "search_creations",
        "search_notebooks", "web_search", "web_read", "external_tools", "call_external",
    ]  # fmt: skip
    assert set(TOOL_ACTIONS) < set(TOOL_NAMES)
    for tool, action_id in TOOL_ACTIONS.items():
        action = reg.get(action_id)
        assert action is not None, tool
        assert "assistant" in action.surfaces, tool
    propose = next(t for t in TOOL_DEFINITIONS if t["function"]["name"] == PROPOSE)
    assert propose["function"]["parameters"]["required"] == ["action_id", "params"]


def test_the_arguments_are_checked_before_anything_runs():
    assert action_input("how_to", {"question": " text to speech "}) == {
        "question": "text to speech"
    }
    assert action_input("how_to", {}) == "There was no question to look up."
    assert action_input("app_status", {}) == {}
    assert action_input("app_status", {"domain": "speech"}) == {"domain": "speech"}
    assert action_input(PROPOSE, {"action_id": "image.generate", "params": {"prompt": "x"}}) == {
        "action_id": "image.generate", "params": {"prompt": "x"},
    }  # fmt: skip
    assert action_input(PROPOSE, {"action_id": "image.generate"}) == {
        "action_id": "image.generate", "params": {},
    }  # fmt: skip
    assert "id from your instructions" in action_input(PROPOSE, {"action_id": "Draw!"})
    assert "object" in action_input(PROPOSE, {"action_id": "image.generate", "params": "x"})
    assert action_input("open_screen", {"screen_id": "voice.speak"}) == {"screen_id": "voice.speak"}
    assert action_input("search_creations", {"query": ""}) == "There was nothing to search for."


def test_a_proposals_result_names_its_action_for_the_window_and_speaks_to_the_model():
    ok = ActionResult(
        status="ok", action_id="image.generate", text="Made.", output={"image_id": "i"}
    )
    out = outcome_of(PROPOSE, ok)
    assert out.status == "ok" and out.text == "Made. The person can see it in the chat."
    assert out.output == {"action_id": "image.generate", "message": "Made.", "image_id": "i"}
    assert outcome_of("search_creations", ok).text == "Made."
    refused = ActionResult(status="refused", action_id="speech.speak", text="No.", code="c")
    out = outcome_of(PROPOSE, refused)
    assert (out.status, out.output["message"], out.text) == ("refused", "No.", "No.")
    setup = ActionResult(
        status="needs_setup", action_id="speech.speak", text="Get a model.",
        setup=Readiness.needs_setup("Get a speech model", "models"),
    )  # fmt: skip
    out = outcome_of(PROPOSE, setup)
    assert out.status == "refused" and out.output["setup"] == "Get a speech model"
    assert out.output["screen"] == "models"


def test_the_policies_let_a_yes_make_things_but_never_delete_or_clone():
    reg = registry()
    for action in reg:
        if action.effect == "destroy" or "needs_consent" in action.flags:
            assert decide(action, POLICY) == "ask", action.id
        elif action.effect == "make":
            assert decide(action, POLICY) == "run" and decide(action, ASK) == "ask", action.id
    for action_id in TOOL_ACTIONS.values():
        action = reg.get(action_id)
        assert action is not None and decide(action, ASK) == "run", action_id  # reads


def test_the_help_corpus_answers_how_to_with_the_real_guides():
    served = {g.action for g in guides.guides()}
    assert len(served) >= 40 and "speech.speak" in served
    found = guides.search("How can I do a text to speech?", served)
    assert found and found[0].action == "speech.speak"
    assert "Voice › Text to speech" in found[0].passage
    assert guides.search("what is the capital of France", served) == []
    only = guides.search("text to speech", {"image.generate"})
    assert "speech.speak" not in [g.action for g in only]  # not served here: not offered
    assert guides.screens(served)["voice.speak"] == "Text to speech"


def test_the_card_is_drawn_from_the_actions_own_schema():
    reg = registry()
    action = reg.get("image.generate")
    assert action is not None
    fields = {f["name"]: f for f in card_fields(action, {"prompt": "a fox", "size": "wide"})}
    assert fields["prompt"]["kind"] == "long_text" and fields["prompt"]["required"] is True
    assert fields["prompt"]["value"] == "a fox" and fields["prompt"]["max_length"] >= 200
    assert fields["size"]["kind"] == "choice" and "wide" in fields["size"]["choices"]
    assert fields["size"]["value"] == "wide"
    card = card_of(action, action.id, "Make a picture of a fox", {"prompt": "a fox"})
    assert card["title"] == action.title and card["action_id"] == "image.generate"
    assert card["effect"] == "make" and card["screen"] == action.ui
    assert card["params"] == {"prompt": "a fox"}
    clone = reg.get("voice.clone")
    assert clone is not None
    assert "needs your word" in card_of(clone, clone.id, "", {})["badges"]
    assert card_of(clone, clone.id, "", {})["consent"] == clone.consent
    assert card_of(None, "x.y", "s", {"a": 1})["title"] == "x.y"


async def test_a_proposal_leaves_an_audit_entry_and_a_usage_event(tmp_path, ctx):
    host = FakeHost()
    call = {
        "text": "",
        "tool_calls": [
            {
                "name": PROPOSE,
                "arguments": {"action_id": "image.generate", "params": {"prompt": "a fox"}},
            }
        ],
    }
    rig = Rig(tmp_path, [call, {"text": "Here."}], host)
    await rig.turn("draw a fox")
    audit = rig.executor.audit.entries  # type: ignore[attr-defined]
    assert [(e.action_id, e.origin, e.status) for e in audit] == [
        ("image.generate", "assistant", "ok")
    ]


async def test_how_to_and_open_screen_read_the_apps_own_files(tmp_path, ctx):
    rig = Rig(
        tmp_path,
        [{"tool_calls": [{"name": "how_to", "arguments": {"question": "text to speech"}},
                         {"name": "open_screen", "arguments": {"screen_id": "voice.speak"}},
                         {"name": "open_screen", "arguments": {"screen_id": "nowhere"}}]},
         {"text": "Open Voice › Text to speech and type the text."}],
        FakeHost(),
    )  # fmt: skip
    state, events = await rig.turn("how do I do text to speech?")
    results = [e for e in events if e["type"] == "tool_result"]
    assert [r["status"] for r in results] == ["ok", "ok", "refused"]
    guide = results[0]["output"]["guides"][0]
    assert guide["action"] == "speech.speak" and guide["where"] == "Voice › Text to speech"
    assert guide["state"] == "ready" and guide["status"] == "This computer: ready."
    told = rig.model.chats[1]["messages"]
    assert "Voice › Text to speech" in told[-3]["content"]  # the passage, verbatim
    assert results[1]["output"] == {
        "screen": "voice.speak", "title": "Text to speech", "where": "Voice › Text to speech",
    }  # fmt: skip
    assert "no screen called nowhere" in results[2]["output"]["message"]
    assert rig.executor.audit.entries == []  # type: ignore[attr-defined]  # nothing ran
    assert state["reply"].startswith("Open Voice")


async def test_an_unknown_action_or_a_bad_field_is_told_in_words_so_the_model_can_fix_it(
    tmp_path, ctx
):
    rig = Rig(
        tmp_path,
        [{"tool_calls": [
            {"name": PROPOSE, "arguments": {"action_id": "image.fly", "params": {}}},
            {"name": PROPOSE, "arguments": {"action_id": "image.generate",
                "params": {"size": "huge"}}}]},
         {"text": "Sorry."}],
        FakeHost(),
    )  # fmt: skip
    _, events = await rig.turn("fly")
    results = [e for e in events if e["type"] == "tool_result"]
    assert (
        results[0]["status"] == "error"
        and "no action called image.fly" in results[0]["output"]["message"]
    )
    assert results[1]["status"] == "refused"
    words = rig.model.chats[1]["messages"][-1]["content"]
    assert "'prompt' is required" in words and "'size'" in words


async def test_the_card_is_the_default_and_the_person_can_edit_it_before_running(tmp_path, ctx):
    host = FakeHost()
    rig = Rig(
        tmp_path,
        [{"tool_calls": [
            {"name": PROPOSE, "arguments": {"action_id": "image.generate",
                "params": {"prompt": "a fox"}}}]},
         {"text": "Done."}],
        host,
    )  # fmt: skip
    await rig.turn_with({"text": "draw a fox", "approvals": True})
    ask = await rig.paused()
    assert ask and ask["kind"] == "confirm_action" and ask["action_id"] == "image.generate"
    assert ask["effect"] == "make" and ask["badges"] == []
    prompt = next(f for f in ask["fields"] if f["name"] == "prompt")
    assert prompt["value"] == "a fox" and prompt["kind"] == "long_text"
    assert host.runs == []
    state, events = await rig.answer(
        {"approved": True, "params": {"prompt": "a red fox", "size": "wide"}}
    )
    assert host.runs == [
        ("wasifyai-image", {"mode": "text", "prompt": "a red fox", "size": "wide"})
    ]
    made = next(e for e in events if e["type"] == "tool_result")
    assert made["status"] == "ok" and made["output"]["action_id"] == "image.generate"
    assert state["status"] == "done"
    rows = await rig.store.messages("t1", "u1", state["conversation_id"])
    card = rows[2].parts[0]  # the stored card says what was really run
    assert card["type"] == "interrupt" and card["status"] == "approved"
    assert card["params"] == {"prompt": "a red fox", "size": "wide"}


async def test_the_chats_setting_decides_when_a_card_is_shown(tmp_path, ctx):
    """ADR-0071 decision 5: ask (default), ask only for what is costly or leaves, or never."""

    def turns():
        return [
            {"tool_calls": [
                {"name": PROPOSE,
                 "arguments": {"action_id": "image.generate", "params": {"prompt": "a fox"}}}]},
            {"text": "Done."},
        ]  # fmt: skip

    for n, (approval, waits) in enumerate(
        [(None, True), ("ask", True), ("ask_costly", False), ("auto", False)]
    ):
        folder = tmp_path / str(n)
        folder.mkdir()
        host = FakeHost()
        rig = Rig(folder, turns(), host)
        body: dict = {"text": "draw a fox", "approvals": True}
        if approval:
            body["approval"] = approval
        await rig.turn_with(body)
        assert (await rig.paused() is not None) is waits, approval
        assert (host.runs == []) is waits, approval
    # ask_costly is the executor's own "ask for what is costly or leaves" policy
    from wasifyai_assistant.graph import POLICIES

    assert POLICIES["ask_costly"].make == "ask_costly" and POLICIES["auto"] is POLICY
    assert POLICIES["ask"] is ASK


def test_the_estimate_is_the_median_of_this_persons_last_runs():
    from wasifyai_platform_sdk.actions import AuditEntry
    from wasifyai_platform_sdk.actions.audit import AuditStatus

    def entry(action: str, ms: int, status: AuditStatus = "ok") -> AuditEntry:
        return AuditEntry(
            tenant_id="t", product_id="p", user_id="u", action_id=action, origin="assistant",
            status=status, duration_ms=ms,
        )  # fmt: skip

    recent = [  # newest first, as the audit log answers
        entry("image.generate", 9000), entry("image.generate", 0),
        entry("image.generate", 30000, "error"), entry("speech.speak", 2000),
        entry("image.generate", 11000), entry("image.generate", 7000),
    ]  # fmt: skip
    assert estimate_of("image.generate", recent) == {"seconds": 9, "runs": 3}
    assert estimate_of("speech.speak", recent) == {"seconds": 2, "runs": 1}
    assert estimate_of("music.generate", recent) is None
    assert estimate_of("image.generate", [entry("image.generate", 400)]) == {
        "seconds": 1,
        "runs": 1,
    }


async def test_the_card_carries_the_estimate_and_says_when_the_chat_model_pauses(tmp_path, ctx):
    from wasifyai_platform_sdk.actions import AuditEntry

    class SlotHost(FakeHost):
        def facts(self):
            return {"one_slot": True}

    host = SlotHost()
    propose = {
        "tool_calls": [
            {"name": PROPOSE,
             "arguments": {"action_id": "image.generate", "params": {"prompt": "a fox"}}}
        ]
    }  # fmt: skip
    rig = Rig(tmp_path, [propose, {"text": "ok"}], host)
    # an earlier run of this person, as the audit log keeps it (the fake run itself takes no time)
    rig.executor.audit.entries.append(  # type: ignore[attr-defined]
        AuditEntry(
            tenant_id="t1",
            product_id="wasifyai-image",
            user_id="u1",
            action_id="image.generate",
            origin="window",
            status="ok",
            duration_ms=4200,
        )  # fmt: skip
    )
    await rig.turn_with({"text": "again", "approvals": True})
    ask = await rig.paused()
    assert ask and ask["estimate"] == {"seconds": 4, "runs": 1}
    assert ask["pauses_chat"] is True  # image.generate needs the image model: the slot
    (tmp_path / "plain").mkdir()
    plain = Rig(tmp_path / "plain", [propose, {"text": "ok"}], FakeHost())
    await plain.turn_with({"text": "draw", "approvals": True})
    asked = await plain.paused()
    assert asked and asked["estimate"] is None and asked["pauses_chat"] is False


async def test_a_guide_says_what_this_computer_is_missing(tmp_path, ctx):
    from wasifyai_platform_sdk.actions import Need, Readiness

    class Missing(FakeHost):
        async def readiness(self, need: Need) -> Readiness:
            if need.kind == "model" and need.name == "speak":
                return Readiness.needs_setup("Get a speech model in the Model hub.", "models")
            return Readiness.ready()

    rig = Rig(
        tmp_path,
        [{"tool_calls": [{"name": "how_to", "arguments": {"question": "text to speech"}}]},
         {"text": "Get a speech model first."}],
        Missing(),
    )  # fmt: skip
    _, events = await rig.turn("how do I do text to speech?")
    guide = next(e for e in events if e["type"] == "tool_result")["output"]["guides"][0]
    assert guide["action"] == "speech.speak" and guide["state"] == "needs_setup"
    assert (
        guide["step"] == "Get a speech model in the Model hub."
        and guide["setup_screen"] == "models"
    )
    told = rig.model.chats[1]["messages"][-1]["content"]
    assert "This computer: needs a step first: Get a speech model in the Model hub." in told
