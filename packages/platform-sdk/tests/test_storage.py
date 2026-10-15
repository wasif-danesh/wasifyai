import pytest
from wasifyai_platform_sdk import ScopedStorage, memory_storage, object_key


def test_object_key_layout_and_validation():
    assert (
        object_key("t", "wasifyai-music", "u", "s1", "audio.mp3")
        == "t/wasifyai-music/u/s1/audio.mp3"
    )
    for bad in ("../x", "a//b", "/abs", "a/../b", " sp", ""):
        with pytest.raises(ValueError):
            object_key("t", "p", "u", bad)
    with pytest.raises(ValueError):
        object_key("t/../x", "p", "u", "f")


async def test_scoped_storage_round_trip_and_prefix(ctx):
    raw = memory_storage()
    s = ScopedStorage(raw)
    key = await s.put("songs/1/audio.mp3", b"abc", "audio/mpeg")
    assert key == "t1/demo/u1/songs/1/audio.mp3"
    assert await s.get("songs/1/audio.mp3") == b"abc"
    assert await s.exists("songs/1/audio.mp3") and not await s.exists("songs/2/audio.mp3")
    assert await raw.list("t1/demo/") == [key]
    assert (await s.url("songs/1/audio.mp3")).endswith(key)
    await s.delete("songs/1/audio.mp3")
    assert not await s.exists("songs/1/audio.mp3")


async def test_scoped_storage_blocks_traversal_and_other_tenants(ctx):
    s = ScopedStorage(memory_storage())
    with pytest.raises(ValueError):
        await s.put("../other-tenant/x", b"1")


async def test_scoped_storage_needs_context():
    with pytest.raises(RuntimeError):
        await ScopedStorage(memory_storage()).put("a", b"1")


async def test_move_rekeys_a_file_within_the_users_prefix(ctx):
    raw = memory_storage()
    s = ScopedStorage(raw)
    await s.put("jobs/j1/audio.mp3", b"abc", "audio/mpeg")
    assert await s.move("jobs/j1/audio.mp3", "songs/s1/audio.mp3") == "songs/s1/audio.mp3"
    assert await s.get("songs/s1/audio.mp3") == b"abc"
    assert not await s.exists("jobs/j1/audio.mp3")
    with pytest.raises(ValueError):
        await s.move("songs/s1/audio.mp3", "../other-user/audio.mp3")


# ---- local files (the desktop profile) -----------------------------------------------------


async def test_local_storage_round_trip_list_copy_delete(tmp_path):
    from wasifyai_platform_sdk.storage import LocalFileStorage

    s = LocalFileStorage(
        tmp_path / "files", "http://127.0.0.1:9", "secret-secret-secret-secret-32b"
    )
    await s.put("t/p/u/a/image.png", b"png", "image/png")
    assert await s.get("t/p/u/a/image.png") == b"png"
    assert await s.exists("t/p/u/a/image.png") and not await s.exists("t/p/u/a/none.png")
    await s.copy("t/p/u/a/image.png", "t/p/u/b/image.png")
    assert sorted(await s.list("t/p/u/")) == ["t/p/u/a/image.png", "t/p/u/b/image.png"]
    await s.delete("t/p/u/a/image.png")
    assert not await s.exists("t/p/u/a/image.png")
    assert (tmp_path / "files" / "t/p/u/b/image.png").read_bytes() == b"png"


async def test_local_links_are_signed_and_expire(tmp_path):
    from urllib.parse import parse_qs, urlparse

    from wasifyai_platform_sdk.storage import LocalFileStorage

    s = LocalFileStorage(
        tmp_path / "files", "http://127.0.0.1:9", "secret-secret-secret-secret-32b"
    )
    url = await s.url("t/p/u/a/image.png")
    parts = urlparse(url)
    assert parts.path == "/files/t/p/u/a/image.png" and parts.netloc == "127.0.0.1:9"
    q = parse_qs(parts.query)
    expires_at, sig = int(q["e"][0]), q["s"][0]
    assert s.verify("t/p/u/a/image.png", expires_at, sig)
    assert not s.verify("t/p/u/a/other.png", expires_at, sig)  # the link is for one file
    assert not s.verify("t/p/u/a/image.png", expires_at + 1, sig)  # and one expiry
    assert not s.verify("t/p/u/a/image.png", expires_at, "0" * 64)
    assert not s.verify("t/p/u/a/image.png", expires_at, sig, now=expires_at + 1)
    assert not s.verify("t/../image.png", expires_at, sig)
    other = LocalFileStorage(
        tmp_path / "files", "http://127.0.0.1:9", "another-secret-another-secret-3"
    )
    assert not other.verify("t/p/u/a/image.png", expires_at, sig)  # signed by this launch only
