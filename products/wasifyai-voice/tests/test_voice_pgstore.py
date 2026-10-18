"""The voice store on both databases: what a person keeps is theirs alone."""

import pytest
from wasifyai_voice.store import NotFound

T, U = "t1", "u1"
OTHERS = (("t1", "u2"), ("t2", "u1"))


def speech(s, **kw):
    return s.add_speech(
        T, U, text="Hello there", model_id="m", voice="af", options={"speed": 1.2}, seconds=1.5,
        sample_rate=24000, audio_key="speech/a.wav", load_s=0.1, elapsed_s=0.2, **kw,
    )  # fmt: skip


def test_a_speech_is_kept_listed_and_removed_for_its_owner_only(new_store):
    s = new_store()
    made = speech(s, speech_id="s1")
    assert made["options"] == {"speed": 1.2} and made["seconds"] == 1.5 and made["mode"] == "speak"
    assert s.get_speech(T, U, "s1")["audio_key"] == "speech/a.wav"
    assert [x["id"] for x in s.list_speeches(T, U)] == ["s1"]
    assert [x["id"] for x in s.list_speeches(T, U, ids=["nope"])] == []
    for tenant, user in OTHERS:
        with pytest.raises(NotFound):
            s.get_speech(tenant, user, "s1")
        assert s.list_speeches(tenant, user) == []
        with pytest.raises(NotFound):
            s.delete_speech(tenant, user, "s1")
    assert s.delete_speech(T, U, "s1")["id"] == "s1"
    with pytest.raises(NotFound):
        s.get_speech(T, U, "s1")


def test_a_transcript_keeps_its_segments_and_can_be_renamed(new_store):
    s = new_store()
    segs = [
        {"start": 0.0, "end": 1.0, "text": "hello"},
        {"start": 1.0, "end": 2.5, "text": "world"},
    ]
    t = s.add_transcript(
        T, U, title="Meeting", source_name="m.wav", model_id="w", text="hello world",
        segments=segs, seconds=2.5, elapsed_s=0.4, transcript_id="t9",
    )  # fmt: skip
    assert s.get_transcript(T, U, "t9")["segments"] == segs
    assert s.rename_transcript(T, U, "t9", "Standup")["title"] == "Standup"
    listed = s.list_transcripts(T, U)
    assert [x["id"] for x in listed] == ["t9"]
    for tenant, user in OTHERS:
        with pytest.raises(NotFound):
            s.get_transcript(tenant, user, "t9")
    s.delete_transcript(T, U, "t9")
    assert s.list_transcripts(T, U) == []
    assert t["seconds"] == 2.5


def test_voices_are_filtered_by_kind_and_updated_with_their_rules(new_store):
    s = new_store()
    s.add_voice(T, U, kind="design", name="Calm", description="a deep man", voice_id="v1")
    s.add_voice(T, U, kind="clone", name="Me", reference_key="k", voice_id="v2")
    assert {v["id"] for v in s.list_voices(T, U)} == {"v1", "v2"}
    assert [v["id"] for v in s.list_voices(T, U, kind="clone")] == ["v2"]
    assert s.update_voice(T, U, "v1", name="Calmer", description="deeper")["name"] == "Calmer"
    with pytest.raises(NotFound):
        s.update_voice(T, U, "v2", description="a clone has none")
    for tenant, user in OTHERS:
        with pytest.raises(NotFound):
            s.get_voice(tenant, user, "v1")
    assert s.delete_voice(T, U, "v1")["id"] == "v1"


def test_a_track_keeps_its_numbers_flags_and_edit_history(new_store):
    s = new_store()
    t = s.add_track(
        T, U, title="Summer", mode="song", description="pop", lyrics="la la", instrumental=False,
        model_id="m", options={"a": 1}, seed=2**40, seconds=61.25, sample_rate=44100,
        audio_key="k", load_s=0, elapsed_s=1, track_id="tr1", edit={"action": "repaint"},
    )  # fmt: skip
    assert (t["seed"], t["seconds"], t["instrumental"], t["favourite"]) == (
        2**40,
        61.25,
        False,
        False,
    )
    assert t["edit"] == {"action": "repaint"} and t["options"] == {"a": 1}
    assert s.update_track(T, U, "tr1", favourite=True)["favourite"] is True
    assert [x["id"] for x in s.list_tracks(T, U, favourites=True)] == ["tr1"]
    assert s.rename_track(T, U, "tr1", "Winter")["title"] == "Winter"
    for tenant, user in OTHERS:
        with pytest.raises(NotFound):
            s.get_track(tenant, user, "tr1")
    s.delete_track(T, U, "tr1")
    assert s.list_tracks(T, U) == []


def test_pictures_and_clips_belong_to_their_owner(new_store):
    s = new_store()
    s.add_picture(T, U, key="pic/a.png", width=512, height=512, picture_id="p1")
    clip = s.add_clip(
        T, U, title="Hello", model_id="m", picture_key="pic/a.png", video_key="clip/a.mp4",
        voice={"kind": "speech"}, script="hi", seconds=3.25, fps=25, width=512, height=512,
        consent={"picture": "own"}, load_s=0, elapsed_s=2, clip_id="c1",
    )  # fmt: skip
    assert clip["voice"] == {"kind": "speech"} and clip["consent"] == {"picture": "own"}
    assert s.update_clip(T, U, "c1", title="Renamed", favourite=True)["favourite"]
    for tenant, user in OTHERS:
        with pytest.raises(NotFound):
            s.get_clip(tenant, user, "c1")
        with pytest.raises(NotFound):
            s.get_picture(tenant, user, "p1")
    assert s.stale_pictures("9999-01-01")[0]["id"] == "p1"  # added and never made into a clip
    s.delete_clip(T, U, "c1")
    s.delete_picture(T, U, "p1")
    assert s.list_clips(T, U) == []


async def test_postgres_voice_things_are_listed_for_search(new_store):
    if new_store.backend != "postgres":
        pytest.skip("the SQLite file is covered in test_voice_parts")
    from sqlalchemy.ext.asyncio import create_async_engine
    from voice_rig import pg_dsn
    from wasifyai_voice.index import PgVoiceIndexSource

    s = new_store()
    engine = create_async_engine(pg_dsn().replace("postgresql://", "postgresql+asyncpg://", 1))
    try:
        src = PgVoiceIndexSource(engine, s.schema)
        assert await src.page(None, 10) == []
        speech(s, speech_id="a")
        s.add_transcript(
            T, U, title="Meeting", source_name="", model_id="m", text="we met", segments=[],
            seconds=1, elapsed_s=0, transcript_id="b",
        )  # fmt: skip
        s.add_voice(T, U, kind="design", name="Calm", description="a deep man", voice_id="c")
        s.add_track(
            T, U, title="Summer", mode="song", description="pop", lyrics="la la",
            instrumental=False, model_id="m", options={}, seed=1, seconds=1, sample_rate=1,
            audio_key="k", load_s=0, elapsed_s=0, track_id="d",
        )  # fmt: skip
        items = await src.page(None, 10)
        assert [(i.item_id, i.kind) for i in items] == [
            ("a", "speech"), ("b", "transcript"), ("c", "voice"), ("d", "track"),
        ]  # fmt: skip
        assert items[0].text == "Hello there" and items[2].text == "Calm. a deep man"
        assert [i.item_id for i in await src.page("b", 10)] == ["c", "d"]
        assert await src.present(["a", "d", "zz"]) == {"a", "d"}
        assert await PgVoiceIndexSource(engine, "vt_missing").page(None, 5) == []
    finally:
        await engine.dispose()
