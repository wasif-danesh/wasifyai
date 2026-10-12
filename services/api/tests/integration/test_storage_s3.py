import pytest
from wasifyai_platform_sdk import ScopedStorage, s3_storage


async def test_s3_round_trip_with_presigned_url(storage_settings, run_ctx):
    import urllib.request
    from uuid import uuid4

    s = storage_settings
    storage = ScopedStorage(
        s3_storage(
            bucket=s.storage_bucket,
            endpoint=s.storage_endpoint,
            access_key=s.storage_access_key,
            secret_key=s.storage_secret_key,
            region=s.storage_region,
        )
    )
    rel = f"it/{uuid4()}/audio.mp3"
    key = await storage.put(rel, b"mp3-bytes", "audio/mpeg")
    assert key == f"it-tenant/it-product/it-user/{rel}"
    assert await storage.get(rel) == b"mp3-bytes" and await storage.exists(rel)
    url = await storage.url(rel)
    assert url.startswith("http") and "X-Amz-Signature" in url
    # the URL works without credentials
    assert urllib.request.urlopen(url).read() == b"mp3-bytes"  # noqa: ASYNC210
    await storage.delete(rel)
    assert not await storage.exists(rel)
    with pytest.raises(FileNotFoundError):
        await storage.get(rel)
