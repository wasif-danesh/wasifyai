import time
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from wasifyai_api.auth import AuthError, verify_token
from wasifyai_api.config import get_settings
from wasifyai_api.main import create_app
from wasifyai_api.users import CachedUsers, InMemoryUserStore
from wasifyai_platform_sdk import (
    InMemoryEventLog,
    InMemoryRunStore,
    InMemoryUsageRecorder,
)

from tests.test_runs import hello_registry, mem_app, parse
from tests.user_store_contract import check_contract

SECRET = "s" * 40


@pytest.fixture
def products(tmp_path):
    d = tmp_path / "hello"
    d.mkdir()
    (d / "product.yaml").write_text(
        "id: hello\ncapabilities:\n"
        '  text.chat: { provider: fake, defaults: { reply: "Hello there friend" } }\n'
    )
    return tmp_path


def token(secret=SECRET, **over) -> str:
    now = int(time.time())
    data = {
        "iss": "wasifyai-web",
        "aud": "wasifyai-api",
        "iat": now,
        "exp": now + 300,
        "sub": "google:1001",
        "email": "ann@example.com",
        "email_verified": True,
        "name": "Ann",
    }
    data.update(over)
    return jwt.encode({k: v for k, v in data.items() if v is not None}, secret, algorithm="HS256")


def test_a_good_token_yields_claims():
    c = verify_token(token(), SECRET)
    assert (c.provider, c.account_id, c.email, c.email_verified) == (
        "google",
        "1001",
        "ann@example.com",
        True,
    )


@pytest.mark.parametrize(
    "bad",
    [
        token(exp=int(time.time()) - 60),  # expired
        token(secret="x" * 40),  # wrong signature
        token(aud="someone-else"),
        token(iss="evil"),
        token(sub="myspace:1"),  # unknown provider
        token(sub="google:"),  # no account id
        token(sub=None),
        token(exp=None),
        "not-a-token",
        jwt.encode(
            {"iss": "wasifyai-web", "aud": "wasifyai-api", "sub": "google:1"}, "", algorithm="none"
        ),
    ],
)
def test_bad_tokens_are_rejected(bad):
    with pytest.raises(AuthError):
        verify_token(bad, SECRET)


def test_a_weak_secret_is_refused():
    with pytest.raises(AuthError, match="32 bytes"):
        verify_token(token(), "short")


def test_email_is_not_verified_unless_exactly_true():
    assert verify_token(token(email_verified="true"), SECRET).email_verified is False


async def test_in_memory_store_follows_the_rules():
    await check_contract(InMemoryUserStore(), "t-" + uuid4().hex)


async def test_cache_returns_the_same_user_without_asking_the_store_again():
    class Counting(InMemoryUserStore):
        calls = 0

        async def resolve(self, tenant_id, claims, admin_emails):
            Counting.calls += 1
            return await super().resolve(tenant_id, claims, admin_emails)

    users = CachedUsers(Counting())
    c = verify_token(token(), SECRET)
    one = await users.resolve("t", c, frozenset())
    two = await users.resolve("t", c, frozenset())
    assert one == two and Counting.calls == 1


@pytest.fixture
def jwt_mode(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("API_AUTH_SECRET", SECRET)
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture
def jwt_client(jwt_mode, products):
    app = mem_app(hello_registry(), products, InMemoryUsageRecorder(), users=InMemoryUserStore())
    with TestClient(app) as c:
        yield c


def bearer(**over) -> dict[str, str]:
    return {"authorization": f"Bearer {token(**over)}"}


def test_no_token_is_401(jwt_client):
    r = jwt_client.post("/products/hello/runs", json={"input": {"message": "hi"}})
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


def test_a_bad_token_is_401_without_detail(jwt_client):
    r = jwt_client.post(
        "/products/hello/runs",
        json={"input": {"message": "hi"}},
        headers=bearer(exp=int(time.time()) - 60),
    )
    assert r.status_code == 401 and "expired" not in r.text.lower().replace(
        "invalid or expired", ""
    )


def test_health_needs_no_token(jwt_client):
    assert jwt_client.get("/health").status_code == 200


def test_a_signed_in_user_runs_with_their_own_id_and_others_cannot_see_the_run(
    jwt_client,
):
    ann = bearer(sub="google:1001")
    r = jwt_client.post("/products/hello/runs", json={"input": {"message": "hi"}}, headers=ann)
    assert r.status_code == 200
    run_id = parse(r.text)[0][1]["run_id"]
    assert jwt_client.get(f"/runs/{run_id}/events", headers=ann).status_code == 200
    bob = bearer(sub="github:77", email="bob@example.com", email_verified=False)
    assert jwt_client.get(f"/runs/{run_id}/events", headers=bob).status_code == 404


def test_usage_carries_the_users_uuid_not_the_dev_user(jwt_mode, products):
    usage = InMemoryUsageRecorder()
    app = mem_app(hello_registry(), products, usage, users=InMemoryUserStore())
    with TestClient(app) as c:
        c.post("/products/hello/runs", json={"input": {"message": "hi"}}, headers=bearer())
    user_id = usage.events[0].user_id
    assert user_id is not None and user_id not in ("dev-user", "google:1001") and len(user_id) == 36


def test_jwt_mode_without_a_secret_refuses_to_start(monkeypatch, products):
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("API_AUTH_SECRET", "")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="API_AUTH_SECRET"):
            create_app(
                hello_registry(),
                products,
                event_log=InMemoryEventLog(),
                run_store=InMemoryRunStore(),
            )
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
