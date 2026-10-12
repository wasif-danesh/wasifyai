"""Integration tests run against real services (compose stack: Postgres + pgvector, SeaweedFS,
LiteLLM + Ollama). Each test skips itself when its service is not reachable, so `make test`
works on any machine and CI runs the subset it has services for."""

import socket
from pathlib import Path
from urllib.parse import urlparse

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from wasifyai_api.config import get_settings
from wasifyai_platform_sdk import RunContext, reset_context, set_context

PRODUCTS_DIR = Path(__file__).resolve().parents[4] / "products"


def _reachable(url: str, default_port: int) -> bool:
    u = urlparse(url if "://" in url else f"//{url}")
    try:
        socket.create_connection(
            (u.hostname or "localhost", u.port or default_port), timeout=1
        ).close()
        return True
    except OSError:
        return False


@pytest.fixture
async def engine():
    s = get_settings()
    if not _reachable(s.database_url.split("@")[-1].split("/")[0], 5432):
        pytest.skip("Postgres not reachable")
    eng = create_async_engine(s.database_url)
    try:
        async with eng.connect() as c:
            await c.execute(text("select 1 from rag_chunks limit 1"))
    except Exception:
        await eng.dispose()
        pytest.skip("database not migrated (make migrate)")
    yield eng
    await eng.dispose()


@pytest.fixture
def run_ctx():
    ctx = RunContext(
        tenant_id="it-tenant", product_id="it-product", user_id="it-user", run_id="it-run"
    )
    token = set_context(ctx)
    yield ctx
    reset_context(token)


@pytest.fixture
def storage_settings():
    s = get_settings()
    if not s.storage_access_key or not _reachable(s.storage_endpoint, 8333):
        pytest.skip("object storage not reachable or STORAGE_ACCESS_KEY unset")
    return s


@pytest.fixture
def litellm_settings():
    s = get_settings()
    if not s.litellm_api_key or not _reachable(s.litellm_base_url, 4000):
        pytest.skip("LiteLLM not reachable or LITELLM_API_KEY unset")
    return s


@pytest.fixture
async def redis_conn():
    """A real Redis on its own database (15), so tests cannot touch the dev stack's queues."""
    import os

    from redis.asyncio import Redis

    url = os.environ.get("INTEGRATION_REDIS_URL", "redis://localhost:6379/15")
    if not _reachable(url, 6379):
        pytest.skip("Redis not reachable")
    conn = Redis.from_url(url, decode_responses=True)
    await conn.flushdb()
    yield conn
    await conn.flushdb()
    await conn.aclose()
