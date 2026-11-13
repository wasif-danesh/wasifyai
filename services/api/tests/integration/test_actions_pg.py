"""The Postgres audit and approval stores follow the same rules as the others (needs `make migrate`,
which applies revision 0020)."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from wasifyai_platform_sdk.actions import SqlApprovalStore, SqlAuditStore, SqlJobStore

from tests.action_store_contract import check_approvals, check_audit, check_jobs


@pytest.fixture
async def pg(engine):
    try:
        async with engine.connect() as c:
            await c.execute(text("select 1 from action_audit limit 1"))
            await c.execute(text("select 1 from action_approvals limit 1"))
    except Exception:
        pytest.skip("action tables missing (make migrate)")
    return engine


async def test_postgres_audit_store(pg):
    await check_audit(SqlAuditStore(pg), "it-" + uuid4().hex)


async def test_postgres_approval_store(pg):
    await check_approvals(SqlApprovalStore(pg), "it-" + uuid4().hex)


async def test_job_store_on_postgres(pg):
    try:
        async with pg.connect() as c:
            await c.execute(text("select 1 from action_jobs limit 1"))
    except Exception:
        pytest.skip("action_jobs missing (make migrate applies revision 0027)")
    await check_jobs(SqlJobStore(pg), "it-" + uuid4().hex)
