"""Principals at the request edge (stage F3; ADR-0092): a person's token as before, a credential
another verifier knows by its prefix, scopes on routes, and 401 or 403 in a sentence."""

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from wasifyai_api.admin import InMemoryAdminStore
from wasifyai_api.auth import AuthError
from wasifyai_api.config import get_settings
from wasifyai_api.identity import Principal, get_identity, get_principal, require_scope
from wasifyai_api.users import InMemoryUserStore
from wasifyai_platform_sdk import USER_SCOPES, Identity, InMemoryUsageRecorder

from tests.test_admin import ADMIN_EMAIL, as_admin, as_user
from tests.test_auth import SECRET
from tests.test_runs import hello_registry, mem_app

KEYS = {
    "wsk_test_reader_1": Principal(
        "api_key",
        "default",
        "u-key",
        scopes=frozenset({"read"}),
        origin="api:reader",
        connection_id="reader",
    ),  # fmt: skip
    "wsk_test_maker_2": Principal(
        "api_key", "default", "u-key", scopes=frozenset({"read", "make"}), origin="api:maker"
    ),
    "wsk_test_boss_3": Principal(
        "api_key",
        "default",
        "u-boss",
        role="admin",
        scopes=frozenset({"read", "admin"}),
        origin="api:boss",
    ),  # fmt: skip
}


NEEDS_MAKE = require_scope("make")


class FakeKeys:
    """What stage K1 will register for `wsk_`: here a table of known keys."""

    async def verify(self, credential: str, request) -> Principal:
        try:
            return KEYS[credential]
        except KeyError:
            raise AuthError("unknown key") from None


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("API_AUTH_SECRET", SECRET)
    monkeypatch.setenv("ADMIN_EMAILS", ADMIN_EMAIL)
    get_settings.cache_clear()
    (tmp_path / "hello").mkdir()
    (tmp_path / "hello" / "product.yaml").write_text(
        "id: hello\ncapabilities:\n  text.chat: { provider: fake, defaults: { reply: hi } }\n"
    )
    app = mem_app(
        hello_registry(), tmp_path, InMemoryUsageRecorder(), users=InMemoryUserStore(),
        admin_store=InMemoryAdminStore(),
    )  # fmt: skip

    @app.get("/test/who")
    async def who(p: Principal = Depends(get_principal), i: Identity = Depends(get_identity)):
        return {"kind": p.kind, "origin": p.origin, "scopes": sorted(p.scopes), "user": i.user_id}

    @app.get("/test/make")
    async def make(p: Principal = Depends(NEEDS_MAKE)):
        return {"ok": p.origin}

    with TestClient(app) as c:
        c.app.state.credential_verifiers["wsk_"] = FakeKeys()  # type: ignore[attr-defined]
        yield c
    monkeypatch.undo()
    get_settings.cache_clear()


def key(name: str) -> dict[str, str]:
    return {"authorization": f"Bearer {name}"}


def test_a_person_is_a_principal_with_every_scope_of_their_role(client):
    me = client.get("/test/who", headers=as_user()).json()
    assert me["kind"] == "person" and me["origin"] == "window"
    assert set(me["scopes"]) == USER_SCOPES and "admin" not in me["scopes"]
    boss = client.get("/test/who", headers=as_admin()).json()
    assert "admin" in boss["scopes"]
    assert client.get("/test/make", headers=as_user()).json() == {"ok": "window"}


def test_a_credential_is_verified_by_its_prefix_and_acts_as_the_person_behind_it(client):
    r = client.get("/test/who", headers=key("wsk_test_reader_1")).json()
    assert r == {"kind": "api_key", "origin": "api:reader", "scopes": ["read"], "user": "u-key"}
    assert client.get("/me", headers=key("wsk_test_reader_1")).json()["user_id"] == "u-key"


def test_a_route_outside_the_scopes_is_403_in_a_sentence(client):
    no = client.get("/test/make", headers=key("wsk_test_reader_1"))
    assert no.status_code == 403
    assert no.json()["detail"] == (
        "This key may not make pictures, videos, speech and music, and start training "
        "(the make scope)."
    )
    assert client.get("/test/make", headers=key("wsk_test_maker_2")).json() == {"ok": "api:maker"}


def test_the_admin_area_needs_the_admin_scope_as_well_as_the_role(client):
    assert client.get("/admin/users", headers=key("wsk_test_maker_2")).status_code == 403
    assert client.get("/admin/users", headers=key("wsk_test_boss_3")).status_code == 200
    assert client.get("/admin/users", headers=as_admin()).status_code == 200  # unchanged


def test_an_unknown_credential_is_401_without_a_hint(client):
    unknown = client.get("/test/who", headers=key("wsk_test_nobody_9"))
    assert unknown.status_code == 401
    assert unknown.json() == {"detail": "this key or connection is not accepted"}
    assert client.get("/test/who", headers=key("not-a-token")).status_code == 401  # the old path
    assert client.get("/test/who").status_code == 401
