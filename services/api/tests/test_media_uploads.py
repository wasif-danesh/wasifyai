"""The recording upload endpoint (ADR-0043): sniffing, decoding, limits, who may take one back."""

import asyncio
import io
import struct
import wave

import pytest
from fastapi.testclient import TestClient
from wasifyai_platform_sdk import (
    InMemoryUploadLimiter,
    InMemoryUploadStore,
    InMemoryUsageRecorder,
    ScopedStorage,
    memory_storage,
    object_key,
)

from tests.test_runs import hello_registry, mem_app


def tone(seconds=1.0, rate=22050, channels=2) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<" + "h" * channels, *([2000] * channels)) * int(rate * seconds))
    return out.getvalue()


@pytest.fixture
def parts(tmp_path):
    (tmp_path / "hello").mkdir()
    (tmp_path / "hello" / "product.yaml").write_text(
        "id: hello\ncapabilities:\n  text.chat: { provider: fake, defaults: { reply: hi } }\n"
        "uploads:\n  audio: { max_bytes: 400000, max_seconds: 10 }\n"
    )
    (tmp_path / "plain").mkdir()
    (tmp_path / "plain" / "product.yaml").write_text(
        "id: plain\ncapabilities:\n  text.chat: { provider: fake, defaults: { reply: hi } }\n"
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


def post(c, data: bytes, product="hello"):
    return c.post(f"/products/{product}/uploads/media", content=data)


def test_a_recording_is_stored_as_a_clean_16k_mono_wav_under_the_users_prefix(parts):
    with client_for(parts) as c:
        r = post(c, tone(2.0))
    assert r.status_code == 201
    body = r.json()
    assert body["key"] == f"uploads/{body['upload_id']}.wav" and 1.9 < body["seconds"] < 2.1
    stored = asyncio.run(
        parts["storage"]._storage.get(object_key("dev-tenant", "hello", "dev-user", body["key"]))
    )
    with wave.open(io.BytesIO(stored)) as w:
        assert (w.getnchannels(), w.getframerate()) == (1, 16000)
    (row,) = parts["store"].rows.values()
    assert row.kind == "audio" and 1.9 < (row.seconds or 0) < 2.1
    (event,) = [e for e in parts["usage"].events if e.kind == "upload.created"]
    assert event.meta["kind"] == "audio" and event.meta["container"] == "wav"


def test_a_product_that_takes_no_recordings_says_so(parts):
    with client_for(parts) as c:
        assert post(c, tone(), product="plain").status_code == 404
        assert post(c, tone(), product="nobody").status_code == 404


@pytest.mark.parametrize(
    ("data", "status"),
    [
        (b"", 422),
        (b"definitely not audio, though it may be called song.mp3" * 20, 415),
        (b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\xff" * 200, 422),  # claims to be a WAV, is not
        (b"<html><script>alert(1)</script></html>", 415),
        (b"\x89PNG\r\n\x1a\n" + b"\0" * 100, 415),  # a picture is not a recording
    ],
)
def test_files_that_are_not_recordings_are_refused_and_nothing_is_kept(parts, data, status):
    with client_for(parts) as c:
        assert post(c, data).status_code == status
    assert not parts["store"].rows


def test_a_recording_over_the_length_limit_is_refused(parts):
    with client_for(parts) as c:
        r = post(c, tone(12.0, rate=8000, channels=1))  # the product allows 10 seconds
    assert r.status_code == 422 and "longer than" in r.json()["detail"]
    assert not parts["store"].rows


def test_a_body_over_the_size_limit_is_refused_while_it_streams(parts):
    with client_for(parts) as c:
        r = post(c, b"RIFF" + b"\0" * 500_000)  # the product allows 400 000 bytes
    assert r.status_code == 413
    assert not parts["store"].rows


def test_the_hourly_limit_applies_to_recordings_too(parts):
    with client_for(parts, per_hour=2) as c:
        codes = [post(c, tone(0.5)).status_code for _ in range(3)]
    assert codes == [201, 201, 429]


def test_a_recording_can_be_taken_back_only_by_its_owner(parts):
    with client_for(parts) as c:
        body = post(c, tone()).json()
        path = f"/products/hello/uploads/media/{body['upload_id']}"
        assert c.delete(f"/products/other/uploads/media/{body['upload_id']}").status_code == 404
        assert c.delete("/products/hello/uploads/media/not-a-uuid").status_code == 404
        assert parts["store"].rows
        assert c.delete(path).status_code == 204
        assert not parts["store"].rows
        key = object_key("dev-tenant", "hello", "dev-user", body["key"])
        with pytest.raises(FileNotFoundError):
            asyncio.run(parts["storage"]._storage.get(key))
        assert c.delete(path).status_code == 404
