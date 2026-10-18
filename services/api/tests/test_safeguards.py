"""The safeguards switch (ADR-0047): the default, the force-on, and the admin routes."""

import pytest
from fastapi.testclient import TestClient
from wasifyai_api.admin import InMemoryAdminStore
from wasifyai_api.config import get_settings
from wasifyai_api.safeguards import KEY, ForcedOn, InMemorySettingsStore, Safeguards
from wasifyai_api.users import InMemoryUserStore
from wasifyai_platform_sdk import Capabilities, InMemoryUsageRecorder

from tests.test_admin import ADMIN_EMAIL, as_admin, as_user
from tests.test_auth import SECRET
from tests.test_runs import hello_registry, mem_app


async def test_off_by_default_and_the_admin_can_turn_it_on_and_off():
    g = Safeguards(InMemorySettingsStore())
    assert await g.enabled() is False
    assert (await g.set(True, "u1")).enabled is True and await g.enabled() is True
    assert (await g.set(False, "u1")).enabled is False


async def test_forced_on_ignores_the_stored_value_and_cannot_be_changed():
    store = InMemorySettingsStore({KEY: False})
    g = Safeguards(store, force_on=True)
    assert await g.enabled() is True and (await g.status()).forced is True
    with pytest.raises(ForcedOn):
        await g.set(False, "u1")


async def test_an_unreadable_setting_fails_closed():
    class Broken:
        async def get(self, key):
            raise RuntimeError("database down")

        async def put(self, key, value, by): ...

    assert await Safeguards(Broken()).enabled() is True


async def test_capabilities_without_a_switch_have_the_safeguards_on():
    caps = Capabilities(text=None, image=None, video=None)  # type: ignore[arg-type]
    assert await caps.safeguards_on() is True

    async def off() -> bool:
        return False

    caps.safeguards = off
    assert await caps.safeguards_on() is False


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
    admin = InMemoryAdminStore()
    app = mem_app(
        hello_registry(), tmp_path, InMemoryUsageRecorder(), users=InMemoryUserStore(),
        admin_store=admin, safeguards=Safeguards(InMemorySettingsStore()),
    )  # fmt: skip
    with TestClient(app) as c:
        c.admin = admin  # type: ignore[attr-defined]
        yield c
    monkeypatch.undo()
    get_settings.cache_clear()


def test_only_an_admin_can_read_or_change_it(client):
    assert client.get("/admin/safeguards").status_code == 401
    assert client.get("/admin/safeguards", headers=as_user()).status_code == 403
    assert (
        client.put("/admin/safeguards", json={"enabled": True}, headers=as_user()).status_code
        == 403
    )


def test_the_admin_switches_it_and_the_change_is_audited(client):
    assert client.get("/admin/safeguards", headers=as_admin()).json() == {
        "enabled": False, "forced": False,
    }  # fmt: skip
    r = client.put("/admin/safeguards", json={"enabled": True}, headers=as_admin())
    assert r.status_code == 200 and r.json()["enabled"] is True
    entry = client.admin.entries[-1]
    assert entry.action == "admin.safeguards.update" and entry.detail == {"from": False, "to": True}


def test_a_forced_deployment_refuses_the_change(monkeypatch, tmp_path):
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
        safeguards=Safeguards(InMemorySettingsStore(), force_on=True),
    )  # fmt: skip
    with TestClient(app) as c:
        assert c.get("/admin/safeguards", headers=as_admin()).json() == {
            "enabled": True, "forced": True,
        }  # fmt: skip
        r = c.put("/admin/safeguards", json={"enabled": False}, headers=as_admin())
        assert r.status_code == 409
    monkeypatch.undo()
    get_settings.cache_clear()
