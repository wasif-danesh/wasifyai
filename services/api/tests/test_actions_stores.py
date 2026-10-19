"""The audit and approval stores follow one contract on memory and on the desktop's SQLite."""

from uuid import uuid4

import pytest
from wasifyai_platform_sdk.actions import (
    InMemoryApprovalStore,
    InMemoryAuditStore,
    SqlApprovalStore,
    SqlAuditStore,
)
from wasifyai_platform_sdk.sqlite import create_sqlite_engine

from tests.action_store_contract import check_approvals, check_audit


@pytest.fixture
async def engine(tmp_path):
    eng = create_sqlite_engine(tmp_path / "wasifyai.db")
    yield eng
    await eng.dispose()


def tenant() -> str:
    return "t-" + uuid4().hex


async def test_memory_audit_store():
    await check_audit(InMemoryAuditStore(), tenant())


async def test_memory_approval_store():
    await check_approvals(InMemoryApprovalStore(), tenant())


async def test_sqlite_audit_store_creates_its_table_on_first_use(engine):
    await check_audit(SqlAuditStore(engine), tenant())


async def test_sqlite_approval_store_creates_its_table_on_first_use(engine):
    await check_approvals(SqlApprovalStore(engine), tenant())


async def test_the_sqlite_tables_are_additive_and_can_be_made_twice(engine):
    await SqlAuditStore(engine).recent("t", "u")
    other = create_sqlite_engine(engine.url.database)  # a second process opening the same file
    try:
        await SqlAuditStore(other).recent("t", "u")
        await SqlApprovalStore(other).pending("t", "u")
    finally:
        await other.dispose()
