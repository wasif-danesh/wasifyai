"""The action model, the approval policy and the registry (ADR-0068 decisions 1, 4, 6)."""

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError
from wasifyai_platform_sdk.actions import (
    WINDOW_POLICY,
    Action,
    ActionRegistry,
    ApprovalPolicy,
    CallBinding,
    Outcome,
    PolicyError,
    decide,
    need_model,
    on_the_floor,
    parse_origin,
    surface_of,
)


class In(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str


class Out(BaseModel):
    n: int = 0


async def noop(p, ctx):
    return Outcome.ok({"n": 1}, "done")


def make(id="demo.run", **kw) -> Action:
    base = dict(
        id=id, title="Demo", summary="s", description="d", input=In, output=Out,
        effect="make", bind=CallBinding(noop), ui="chat",
    )  # fmt: skip
    return Action(**{**base, **kw})


def test_an_id_must_look_like_domain_verb():
    for bad in ("run", "Demo.run", "demo.Run", "demo.run.now", "demo-x.run", "1demo.run"):
        with pytest.raises(ValidationError):
            make(bad)
    assert make("speech.speak").domain == "speech"


def test_consent_is_stated_exactly_when_the_flag_is_there():
    with pytest.raises(ValidationError, match="consent statement"):
        make(flags=("needs_consent",))
    with pytest.raises(ValidationError, match="only a needs_consent"):
        make(consent="I agree")
    ok = make(flags=("needs_consent",), consent="I have the right to use this voice.")
    assert ok.consent
    with pytest.raises(ValidationError, match="read cannot need consent"):
        make(effect="read", flags=("needs_consent",), consent="x")


def test_every_action_names_its_screen_or_says_why_it_has_none():
    with pytest.raises(ValidationError, match="menu item"):
        make(ui=None)
    with pytest.raises(ValidationError, match="needs no exemption"):
        make(ui="chat", ui_exempt="because")
    assert make(ui=None, ui_exempt="A job is shown where it was started.").ui is None


def test_an_example_that_does_not_validate_is_a_bug():
    with pytest.raises(ValidationError):
        make(examples=({"text": "ok"}, {"nope": 1}))


def test_origins():
    assert parse_origin("window") == "window"
    assert parse_origin("mcp:Codex on my laptop") == "mcp:Codex on my laptop"
    for bad in ("", "mcp:", "mcp", "agent", "MCP:x", "mcp:" + "x" * 65):
        with pytest.raises(ValueError):
            parse_origin(bad)
    assert surface_of("assistant") == "assistant"
    assert surface_of("mcp:x") == "mcp"
    assert surface_of("window") is None


# ---- approvals --------------------------------------------------------------------------------


def actions_of_every_kind() -> dict[str, Action]:
    return {
        "read": make("a.read", effect="read"),
        "make": make("a.make"),
        "costly": make("a.costly", flags=("costly",)),
        "leaves": make("a.leaves", flags=("leaves_device",)),
        "change": make("a.change", effect="change"),
        "destroy": make("a.destroy", effect="destroy"),
        "consent": make("a.consent", flags=("needs_consent",), consent="I agree."),
    }


def test_the_default_rule():
    a, p = actions_of_every_kind(), ApprovalPolicy()
    assert decide(a["read"], p) == "run"
    assert decide(a["make"], p) == "ask"
    assert decide(a["change"], p) == "ask"
    assert decide(a["destroy"], p) == "ask"
    assert decide(a["consent"], p) == "ask"


def test_make_follows_the_setting_the_person_chose():
    a = actions_of_every_kind()
    costly = ApprovalPolicy(make="ask_costly")
    assert decide(a["make"], costly) == "run"
    assert decide(a["costly"], costly) == "ask"
    assert decide(a["leaves"], costly) == "ask"
    assert decide(a["make"], ApprovalPolicy(make="auto")) == "run"
    assert decide(a["change"], ApprovalPolicy(change="auto")) == "run"


def test_destroy_and_needs_consent_cannot_be_set_to_run_without_a_person():
    a = actions_of_every_kind()
    most_open = [
        ApprovalPolicy(make="auto", change="auto"),
        WINDOW_POLICY,
    ]
    for policy in most_open:
        assert decide(a["destroy"], policy) == "ask"
        assert decide(a["consent"], policy) == "ask"
    assert on_the_floor(a["destroy"]) and on_the_floor(a["consent"])
    assert not on_the_floor(a["make"])


@pytest.mark.parametrize("key", ["destroy", "needs_consent", "consent", "read"])
def test_the_floor_is_not_a_setting(key):
    with pytest.raises(ValidationError):
        ApprovalPolicy(**{key: "auto"})  # type: ignore[arg-type]
    with pytest.raises(PolicyError, match="always ask"):
        ApprovalPolicy.from_settings({key: "auto"})


def test_stored_settings_are_read_back():
    assert ApprovalPolicy.from_settings({"make": "auto"}).make == "auto"
    with pytest.raises(ValidationError):
        ApprovalPolicy.from_settings({"make": "sometimes"})


# ---- registry ---------------------------------------------------------------------------------


def test_the_registry_finds_lists_and_refuses_duplicates():
    reg = ActionRegistry([make("b.two"), make("a.one", surfaces=("assistant",))])
    assert [a.id for a in reg] == ["a.one", "b.two"]
    assert reg.get("a.one") and reg.get("zzz.none") is None
    assert "a.one" in reg and len(reg) == 2
    assert [a.id for a in reg.for_surface("mcp")] == ["b.two"]
    assert [a.id for a in reg.for_surface("assistant")] == ["a.one", "b.two"]
    with pytest.raises(ValueError, match="already registered"):
        reg.add(make("a.one"))


def test_requires_are_plain_data():
    a = make(requires=(need_model("speak"),))
    assert a.requires[0].model_dump() == {"kind": "model", "name": "speak"}
