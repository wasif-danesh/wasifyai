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
