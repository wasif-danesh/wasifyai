"""The admin queries and the audit log against real Postgres (needs `make migrate`)."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from wasifyai_api.admin import AuditEntry, PostgresAdminStore
from wasifyai_api.users import PostgresUserStore

from tests.user_store_contract import NO_ADMINS, claims


@pytest.fixture
async def stores(engine):
    try:
        async with engine.connect() as c:
            await c.execute(text("select 1 from audit_log limit 1"))
            await c.execute(text("select 1 from users limit 1"))
    except Exception:
        pytest.skip("migrations missing (make migrate)")
    return PostgresUserStore(engine), PostgresAdminStore(engine)


async def test_users_usage_and_audit(engine, stores):
    users, admin = stores
    tenant = "it-" + uuid4().hex
    ann = await users.resolve(tenant, claims("google", "a1", "ann@example.com"), NO_ADMINS)
    await users.resolve(tenant, claims("github", "g1", "ann@example.com"), NO_ADMINS)  # linked
    bob = await users.resolve(
        tenant, claims("github", "g2", "bob@example.com", verified=False), NO_ADMINS
    )

    listed = await admin.users(tenant, 10, None)
    assert {u.id for u in listed} == {ann.id, bob.id}
    by_id = {u.id: u for u in listed}
    assert (
        by_id[ann.id].providers == ["github", "google"] and by_id[ann.id].email == "ann@example.com"
    )
    assert by_id[bob.id].email_verified is False
    page = await admin.users(tenant, 1, None)
    assert len(page) == 1
    older = await admin.users(tenant, 10, page[0].created_at)
    assert page[0].id not in {u.id for u in older}

    async with engine.begin() as conn:
        for kind, qty in (("song.created", 1), ("llm.input_tokens", 120), ("llm.input_tokens", 30)):
            await conn.execute(
                text(
                    "INSERT INTO usage_events (id, tenant_id, product_id, user_id, kind, quantity, "
                    "unit) VALUES (:id, :t, 'wasifyai-music', :u, :k, :q, 'x')"
                ),
                {"id": uuid4(), "t": tenant, "u": ann.id, "k": kind, "q": qty},
            )
    report = await admin.usage(tenant, 7)
    totals = {t.kind: (t.events, t.quantity) for t in report.totals}
    assert totals == {"song.created": (1, 1.0), "llm.input_tokens": (2, 150.0)}
    assert {d.kind for d in report.daily} == set(totals)

    await admin.audit(
        tenant, AuditEntry(id="", actor_user_id=ann.id, action="admin.users.list", detail={"n": 2})
    )
    log = await admin.audit_log(tenant, 10)
    assert [(e.action, e.detail) for e in log] == [("admin.users.list", {"n": 2})]
    assert (await admin.users("another-" + tenant, 10, None)) == []  # tenants are separate
