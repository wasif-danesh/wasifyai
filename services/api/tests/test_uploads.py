import io
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from wasifyai_api.config import get_settings
from wasifyai_api.uploads import sweep_uploads
from wasifyai_platform_sdk import (
    InMemoryUploadLimiter,
    InMemoryUploadStore,
    InMemoryUsageRecorder,
    ScopedStorage,
    memory_storage,
    new_upload,
    object_key,
)

from tests.test_runs import hello_registry, mem_app


def photo(size=(300, 200), fmt="JPEG", with_exif=True) -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "SecretCameraMaker"
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2] = "N", (48.0, 51.0, 24.0)
    out = io.BytesIO()
    kw = {"exif": exif} if with_exif and fmt == "JPEG" else {}
    Image.new("RGB", size, (200, 30, 30)).save(out, fmt, **kw)
    return out.getvalue()


@pytest.fixture
def parts(tmp_path):
    (tmp_path / "hello").mkdir()
    (tmp_path / "hello" / "product.yaml").write_text(
        "id: hello\ncapabilities:\n  text.chat: { provider: fake, defaults: { reply: hi } }\n"
        "uploads:\n  image: { max_bytes: 20000 }\n"
    )
    return {
        "tmp": tmp_path,
        "storage": ScopedStorage(memory_storage()),
        "store": InMemoryUploadStore(),
        "usage": InMemoryUsageRecorder(),
    }


def client_for(parts, per_hour=60):
    app = mem_app(
        hello_registry(), parts["tmp"], parts["usage"], storage=parts["storage"],
        uploads=parts["store"], upload_limiter=InMemoryUploadLimiter(per_hour),
    )  # fmt: skip
    return TestClient(app)


def post(c, data: bytes, product="hello", headers=None):
    return c.post(f"/products/{product}/uploads/images", content=data, headers=headers or {})


def test_a_photo_is_stored_clean_under_the_users_own_prefix(parts):
    with client_for(parts) as c:
        original = photo()
        assert b"SecretCameraMaker" in original
        r = post(c, original)
    assert r.status_code == 201
    body = r.json()
    assert body["key"] == f"uploads/{body['upload_id']}.png" and (
        body["width"],
        body["height"],
    ) == (300, 200)
    key = object_key("dev-tenant", "hello", "dev-user", body["key"])
    stored = parts["storage"]._storage  # the plain storage behind the scoped one
    import asyncio

    saved = asyncio.run(stored.get(key))
    assert saved[:8] == b"\x89PNG\r\n\x1a\n" and b"SecretCameraMaker" not in saved
    assert body["bytes"] == len(saved)
    (row,) = parts["store"].rows.values()
    assert (row.tenant_id, row.product_id, row.user_id, row.key) == (
        "dev-tenant",
        "hello",
        "dev-user",
        body["key"],
    )
    (event,) = [e for e in parts["usage"].events if e.kind == "upload.created"]
    assert event.quantity == body["bytes"] and event.unit == "bytes" and event.user_id == "dev-user"


def test_the_clients_name_and_type_are_ignored(parts):
    with client_for(parts) as c:
        r = post(
            c,
            photo(fmt="PNG", with_exif=False),
            headers={"content-type": "text/plain", "x-filename": "../../etc/passwd"},
        )
    assert r.status_code == 201 and "passwd" not in r.text and ".." not in r.json()["key"]


def test_a_product_that_takes_no_uploads_or_does_not_exist_is_404(parts):
    with client_for(parts) as c:
        assert post(c, photo(), product="nope").status_code == 404
        assert post(c, photo(), product="..%2Fhello").status_code == 404


def test_too_large_is_413_whether_or_not_the_length_is_declared(parts):
    import os

    out = io.BytesIO()
    Image.frombytes("RGB", (200, 200), os.urandom(200 * 200 * 3)).save(
        out, "PNG"
    )  # noise: no compression
    big = out.getvalue()
    assert len(big) > 20000
    with client_for(parts) as c:
        assert post(c, big).status_code == 413  # Content-Length says so

        # a body with no declared length is cut off while it streams
        def chunks():
            for i in range(0, len(big), 4096):
                yield big[i : i + 4096]

        assert c.post("/products/hello/uploads/images", content=chunks()).status_code == 413
    assert not parts["store"].rows  # nothing was kept


@pytest.mark.parametrize(
    ("data", "status"),
    [
        (b"", 422),
        (b"plain text", 422),
        (b"<svg></svg>", 422),
        (b"GIF89a....", 422),
    ],
)
def test_things_that_are_not_images_are_refused_with_a_plain_message(parts, data, status):
    with client_for(parts) as c:
        r = post(c, data)
    assert r.status_code == status and r.json()["detail"]
    assert not parts["store"].rows


def test_a_gif_is_a_415(parts):
    out = io.BytesIO()
    Image.new("P", (8, 8)).save(out, "GIF")
    with client_for(parts) as c:
        assert post(c, out.getvalue()).status_code == 415


def test_the_hourly_limit_is_429(parts):
    with client_for(parts, per_hour=2) as c:
        codes = [post(c, photo()).status_code for _ in range(3)]
    assert codes == [201, 201, 429]
    assert len(parts["store"].rows) == 2


def test_an_upload_can_be_taken_back_and_only_by_its_owner(parts):
    import asyncio

    with client_for(parts) as c:
        body = post(c, photo()).json()
        path = f"/products/hello/uploads/images/{body['upload_id']}"
        key = object_key("dev-tenant", "hello", "dev-user", body["key"])
        stored = parts["storage"]._storage
        assert asyncio.run(stored.get(key))
        assert c.delete(f"/products/other/uploads/images/{body['upload_id']}").status_code == 404
        assert c.delete("/products/hello/uploads/images/not-a-uuid").status_code == 404
        assert parts["store"].rows  # still there
        assert c.delete(path).status_code == 204
        assert not parts["store"].rows
        with pytest.raises(FileNotFoundError):
            asyncio.run(stored.get(key))
        assert c.delete(path).status_code == 404  # already gone


def test_uploading_needs_a_signed_in_user(parts, monkeypatch):
    from tests.test_auth import SECRET

    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("API_AUTH_SECRET", SECRET)
    get_settings.cache_clear()
    try:
        with client_for(parts) as c:
            r = post(c, photo())
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
    assert r.status_code == 401 and not parts["store"].rows


async def test_the_clean_up_removes_old_unused_uploads_and_keeps_fresh_ones(parts):
    storage, store = parts["storage"], parts["store"]
    now = datetime(2026, 10, 8, 12, tzinfo=UTC)
    made = {}
    for name, age in [("old", timedelta(hours=25)), ("fresh", timedelta(hours=1))]:
        up = new_upload("t", "p", "ann", 5)
        await storage.put_for(up.owner, up.key, b"png", "image/png")
        await store.add(up)
        store.rows[up.id] = up.__class__(**{**up.__dict__, "created_at": now - age})
        made[name] = up
    assert await sweep_uploads(store, storage, now) == 1
    inner = storage._storage
    assert not await inner.exists(object_key("t", "p", "ann", made["old"].key))
    assert await inner.exists(object_key("t", "p", "ann", made["fresh"].key))
    assert list(store.rows) == [made["fresh"].id]
    assert await sweep_uploads(store, storage, now) == 0  # nothing more to do
