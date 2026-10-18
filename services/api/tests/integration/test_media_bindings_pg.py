"""The media binding store against real Postgres (needs `make migrate`)."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from wasifyai_platform_sdk import MediaBinding, PostgresMediaBindingStore


@pytest.fixture
async def store(engine):
    try:
        async with engine.connect() as c:
            await c.execute(text("select 1 from media_bindings limit 1"))
    except Exception:
        pytest.skip("media_bindings table missing (make migrate)")
    return PostgresMediaBindingStore(engine)


async def test_save_replace_list_and_delete(store):
    tenant = "it-" + uuid4().hex
    assert await store.get(tenant, "p", "image.generate") is None

    first = MediaBinding(
        "p", "image.generate", "comfy-api", {"base_url": "https://c.example"}, "enc-1", "a1"
    )
    await store.put(tenant, first)
    got = await store.get(tenant, "p", "image.generate")
    assert got and (got.backend, got.config, got.secret_enc, got.updated_by) == (
        "comfy-api",
        {"base_url": "https://c.example"},
        "enc-1",
        "a1",
    )
    assert got.key_set and got.updated_at is not None

    await store.put(
        tenant, MediaBinding("p", "image.generate", "openai-images", {"model": "m"}, None, "a2")
    )
    again = await store.get(tenant, "p", "image.generate")
    assert again and (again.backend, again.secret_enc, again.updated_by) == (
        "openai-images",
        None,
        "a2",
    )
    assert not again.key_set

    await store.put(tenant, MediaBinding("p", "video.generate", "comfyui-local", {}, None, "a2"))
    listed = await store.list(tenant)
    assert [b.capability for b in listed] == ["image.generate", "video.generate"]
    assert await store.list("another-" + tenant) == []  # tenants are separate

    await store.delete(tenant, "p", "image.generate")
    assert await store.get(tenant, "p", "image.generate") is None
    assert [b.capability for b in await store.list(tenant)] == ["video.generate"]
