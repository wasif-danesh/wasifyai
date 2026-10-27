"""Principals and scopes (stage F3; ADR-0092): who is calling and what they may do."""

import pytest
from pydantic import BaseModel
from wasifyai_platform_sdk import ALL_SCOPES, SCOPE_WORDS, SCOPES, USER_SCOPES, Principal
from wasifyai_platform_sdk.actions import (
    Action,
    ActionContext,
    CallBinding,
    Outcome,
    parse_origin,
    scope_of,
)
from wasifyai_platform_sdk.actions.model import Effect
from wasifyai_platform_sdk.principal import parse_origin as parse_origin_here


class In(BaseModel):
    pass


async def _call(p: BaseModel, ctx: ActionContext) -> Outcome:
    return Outcome.ok({}, "")


def act(id: str, effect: Effect = "read") -> Action:
    return Action(
        id=id, title=id, summary="s", description="d", input=In, output=In, effect=effect,
        bind=CallBinding(_call), ui="x",
    )  # fmt: skip


def test_a_person_has_every_scope_their_role_allows():
    user = Principal.person("t1", "u1")
    admin = Principal.person("t1", "u2", "admin")
    assert user.scopes == USER_SCOPES and "admin" not in user.scopes
    assert admin.scopes == ALL_SCOPES
    assert user.identity.user_id == "u1" and user.identity.role == "user"
    assert user.origin == "window" and user.may("make") and not user.may("admin")


def test_a_key_or_connection_is_held_to_what_it_was_given():
    key = Principal("api_key", "t1", "u1", scopes=frozenset({"read", "make"}), origin="api:k1")
    assert key.may("make") and not key.may("library")
    assert key.refusal("library") == (
        "This key may not list, open and delete creations (the library scope)."
    )
    conn = Principal(
        "connection", "t1", "u1", scopes=frozenset({"read"}), origin="mcp:Codex", connection_id="c1"
    )
    assert conn.noun == "connection" and conn.connection_id == "c1"


@pytest.mark.parametrize(
    "bad",
    [
        dict(kind="api_key", scopes=frozenset({"everything"}), origin="api:k1"),
        dict(kind="api_key", scopes=frozenset({"admin"}), origin="api:k1"),  # not an admin
        dict(kind="api_key", origin="window"),  # a key does not come through the window
        dict(kind="person", origin="api:k1"),
        dict(kind="api_key", origin="api:"),
    ],
)
def test_what_is_not_a_principal(bad):
    with pytest.raises(ValueError):
        Principal(tenant_id="t1", user_id="u1", **bad)


def test_every_scope_has_words_and_the_origins_are_shared_with_the_actions():
    assert set(SCOPES) == set(SCOPE_WORDS) == ALL_SCOPES
    assert parse_origin is parse_origin_here
    for ok in ("window", "assistant", "mcp:Claude Code", "api:wsk_live_abc"):
        assert parse_origin(ok) == ok
    for bad in ("", "agent:x", "api:", "mcp:", "window2"):
        with pytest.raises(ValueError):
            parse_origin(bad)


@pytest.mark.parametrize(
    ("action_id", "effect", "scope"),
    [
        ("app.status", "read", "read"),
        ("job.status", "read", "read"),
        ("job.cancel", "change", "make"),
        ("image.generate", "make", "make"),
        ("speech.speak", "make", "make"),
        ("train.start", "make", "make"),
        ("library.list", "read", "library"),
        ("library.delete", "destroy", "library"),
        ("notebook.ask", "read", "notebooks"),
        ("voice.add", "make", "voices"),
        ("models.list", "read", "models"),
        ("models.download", "make", "models"),
    ],
)
def test_the_scope_an_action_needs_is_its_domains_group_or_read_or_make(action_id, effect, scope):
    assert scope_of(act(action_id, effect)) == scope
