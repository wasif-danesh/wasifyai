from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from wasifyai_api.admin import AdminUser, InMemoryAdminStore, UsageReport, UsageTotal
from wasifyai_api.config import get_settings
from wasifyai_api.users import InMemoryUserStore
from wasifyai_platform_sdk import InMemoryUsageRecorder

from tests.test_auth import SECRET, token
from tests.test_runs import hello_registry, mem_app

ADMIN_EMAIL = "boss@example.com"
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


@pytest.fixture
def store():
    s = InMemoryAdminStore()
    s.user_rows = [
        AdminUser(
            id=f"u{i}", email=f"user{i}@example.com", email_verified=True, name=f"User {i}",
            role="user", providers=["google"], created_at=NOW - timedelta(hours=i),
        )
        for i in range(5)
    ]  # fmt: skip
    s.usage_report = UsageReport(
        days=7,
        totals=[UsageTotal(kind="song.created", unit="song", events=3, quantity=3)],
        daily=[],
    )
    return s


@pytest.fixture
def jwt_client(monkeypatch, tmp_path, store):
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
        admin_store=store,
    )  # fmt: skip
    with TestClient(app) as c:
        yield c
    monkeypatch.undo()
    get_settings.cache_clear()


def as_admin():
    return {
        "authorization": "Bearer "
        + token(sub="google:9", email=ADMIN_EMAIL, email_verified=True, name="Boss")
    }


def as_user():
    return {"authorization": "Bearer " + token(sub="google:1", email="ann@example.com")}


ROUTES = ["/admin/users", "/admin/usage", "/admin/audit"]


@pytest.mark.parametrize("path", ROUTES)
def test_no_token_is_401(jwt_client, path):
    assert jwt_client.get(path).status_code == 401


@pytest.mark.parametrize("path", ROUTES)
def test_a_normal_user_is_403(jwt_client, path):
    r = jwt_client.get(path, headers=as_user())
    assert r.status_code == 403 and r.json() == {"detail": "admin only"}


@pytest.mark.parametrize("path", ROUTES)
def test_an_admin_is_allowed(jwt_client, path):
    assert jwt_client.get(path, headers=as_admin()).status_code == 200


def test_an_unverified_email_never_makes_an_admin(jwt_client):
    h = {
        "authorization": "Bearer " + token(sub="github:5", email=ADMIN_EMAIL, email_verified=False)
    }
    assert jwt_client.get("/admin/users", headers=h).status_code == 403


def test_me_reports_the_role(jwt_client):
    assert jwt_client.get("/me").status_code == 401
    user = jwt_client.get("/me", headers=as_user()).json()
    admin = jwt_client.get("/me", headers=as_admin()).json()
    assert (user["role"], admin["role"]) == ("user", "admin")
    assert user["user_id"] != admin["user_id"] and len(admin["user_id"]) == 36


def test_users_are_paged_newest_first(jwt_client):
    first = jwt_client.get("/admin/users?limit=2", headers=as_admin()).json()
    assert [u["id"] for u in first["users"]] == ["u0", "u1"] and first["next_before"]
    second = jwt_client.get(
        "/admin/users", params={"limit": 2, "before": first["next_before"]}, headers=as_admin()
    ).json()
    assert [u["id"] for u in second["users"]] == ["u2", "u3"]
    last = jwt_client.get(
        "/admin/users", params={"limit": 2, "before": second["next_before"]}, headers=as_admin()
    ).json()
    assert [u["id"] for u in last["users"]] == ["u4"] and last["next_before"] is None


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "limit=x"])
def test_bad_limits_are_422(jwt_client, query):
    assert jwt_client.get(f"/admin/users?{query}", headers=as_admin()).status_code == 422


def test_reading_users_is_audited_but_not_logged_with_data(jwt_client, store):
    jwt_client.get("/admin/users?limit=3", headers=as_admin())
    (entry,) = store.entries
    assert entry.action == "admin.users.list" and entry.detail == {"limit": 3, "returned": 3}
    assert "@" not in entry.model_dump_json()
    log = jwt_client.get("/admin/audit", headers=as_admin()).json()["entries"]
    assert log[0]["action"] == "admin.users.list"


def test_usage_has_the_documented_shape(jwt_client):
    usage = jwt_client.get("/admin/usage?days=30", headers=as_admin()).json()
    assert usage["days"] == 30 and usage["totals"][0]["kind"] == "song.created"


def test_stub_mode_is_an_admin(monkeypatch, tmp_path, store):
    monkeypatch.setenv("AUTH_MODE", "stub")
    get_settings.cache_clear()
    (tmp_path / "hello").mkdir()
    (tmp_path / "hello" / "product.yaml").write_text(
        "id: hello\ncapabilities:\n  text.chat: { provider: fake, defaults: { reply: hi } }\n"
    )
    app = mem_app(hello_registry(), tmp_path, InMemoryUsageRecorder(), admin_store=store)
    with TestClient(app) as c:
        assert c.get("/me").json()["role"] == "admin"
        assert c.get("/admin/usage").status_code == 200
    get_settings.cache_clear()
