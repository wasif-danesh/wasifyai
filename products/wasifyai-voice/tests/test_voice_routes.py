"""The voice product's routes on a fake engine: speeches, transcripts, exports, ownership."""

import asyncio
import io
import shutil

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from voice_rig import FakeEngine, app_state, wav
from wasifyai_platform_sdk import (
    Identity,
    LocalFileStorage,
    RouteDeps,
    RunContext,
    ScopedStorage,
    VoiceEngineError,
    reset_context,
    set_context,
)
from wasifyai_voice import audio_input
from wasifyai_voice.routes import build_routes
from wasifyai_voice.runtime import store_for


class Indexed:
    def __init__(self):
        self.items: dict[str, tuple[str, str]] = {}

    async def index(self, tenant, product, user, kind, item_id, text):
        self.items[item_id] = (kind, text)

    async def remove(self, tenant, product, item_id):
        self.items.pop(item_id, None)


@pytest.fixture
def api(tmp_path, new_store):
    engine = FakeEngine()
    state = app_state(tmp_path, engine, new_store() if new_store.backend == "postgres" else None)
    files = LocalFileStorage(tmp_path / "files", "http://127.0.0.1:1", "s" * 20)
    state.storage = ScopedStorage(files)
    state.creation_index = Indexed()

    async def identity(x_user: str = Header("u1"), x_tenant: str = Header("t1")) -> Identity:
        return Identity(x_tenant, x_user)

    app = FastAPI()
    app.include_router(build_routes(RouteDeps(state, identity)), prefix="/products/wasifyai-voice")
    with TestClient(app) as c:
        c.base_url = c.base_url.join("/products/wasifyai-voice/")
        yield c, engine, state


def seed_speech(state, text="Hello there"):
    token = set_context(RunContext("t1", "wasifyai-voice", "u1"))
    try:
        asyncio.run(state.storage.put("speech/abc.wav", wav(0.5), "audio/wav"))
    finally:
        reset_context(token)
    return store_for(state).add_speech(
        "t1", "u1", text=text, model_id="kokoro-82m", voice="af_heart", options={},
        seconds=0.5, sample_rate=24000, audio_key="speech/abc.wav", load_s=0.0, elapsed_s=0.3,
        speech_id="abc",
    )  # fmt: skip


def upload(c, name="talk.wav", data=None, **form):
    return c.post(
        "transcripts", files={"file": (name, io.BytesIO(data or wav(1.0)), "audio/wav")}, data=form
    )


def test_speeches_are_listed_fetched_downloaded_and_deleted(api):
    c, _, state = api
    seed_speech(state)
    listed = c.get("speeches").json()["items"]
    assert [s["id"] for s in listed] == ["abc"] and listed[0]["audio_url"].startswith("http://")
    assert "audio_key" not in listed[0] and "user_id" not in listed[0]
    assert c.get("speeches", params={"ids": "zzz"}).json()["items"] == []
    got = c.get("speeches/abc").json()
    assert got["text"] == "Hello there" and got["voice"] == "af_heart"
    d = c.get("speeches/abc/download")
    assert d.status_code == 200 and d.content[:4] == b"RIFF"
    assert "attachment" in d.headers["content-disposition"]
    assert c.delete("speeches/abc").status_code == 204
    assert c.get("speeches/abc").status_code == 404 and c.delete("speeches/abc").status_code == 404


def test_another_person_sees_nothing(api):
    c, _, state = api
    seed_speech(state)
    other = {"x-user": "u2"}
    assert c.get("speeches", headers=other).json()["items"] == []
    for path in ("speeches/abc", "speeches/abc/download"):
        assert c.get(path, headers=other).status_code == 404
    assert c.delete("speeches/abc", headers=other).status_code == 404
    t = upload(c).json()
    for method, path in [
        ("get", f"transcripts/{t['id']}"),
        ("delete", f"transcripts/{t['id']}"),
        ("get", f"transcripts/{t['id']}/export"),
    ]:
        assert getattr(c, method)(path, headers=other).status_code == 404
    assert c.patch(f"transcripts/{t['id']}", json={"title": "x"}, headers=other).status_code == 404
    assert c.get("transcripts", headers=other).json()["items"] == []


def test_a_wav_is_transcribed_kept_and_findable(api):
    c, engine, state = api
    r = upload(c, "Board meeting.wav")
    assert r.status_code == 201
    t = r.json()
    assert t["title"] == "Board meeting" and t["text"].startswith("Hello there.")
    assert t["segments"][1] == {"start": 1.5, "end": 3.0, "text": "Second sentence."}
    assert engine.transcribed[0][0] == "parakeet-tdt-0.6b-v3"
    kind, text = state.creation_index.items[t["id"]]
    assert kind == "transcript" and "Board meeting" in text and "Hello there" in text
    listed = c.get("transcripts").json()["items"]
    assert [x["id"] for x in listed] == [t["id"]] and listed[0]["segments"] == []
    assert c.get(f"transcripts/{t['id']}").json()["segments"]
    renamed = c.patch(f"transcripts/{t['id']}", json={"title": "  Q3 call "}).json()
    assert renamed["title"] == "Q3 call" and "Q3 call" in state.creation_index.items[t["id"]][1]
    assert c.patch(f"transcripts/{t['id']}", json={"title": ""}).status_code == 422
    assert c.delete(f"transcripts/{t['id']}").status_code == 204
    assert t["id"] not in state.creation_index.items
    assert c.get(f"transcripts/{t['id']}").status_code == 404


def test_a_transcript_is_exported_as_text_subrip_or_webvtt(api):
    c, *_ = api
    t = upload(c, "a.wav", title="My talk").json()
    txt = c.get(f"transcripts/{t['id']}/export")
    assert txt.text == "Hello there. Second sentence.\n"
    assert "My talk.txt" in txt.headers["content-disposition"]
    srt = c.get(f"transcripts/{t['id']}/export", params={"format": "srt"}).text
    assert srt.startswith("1\n00:00:00,000 --> 00:00:01,000\nHello there.\n")
    assert "2\n00:00:01,500 --> 00:00:03,000\nSecond sentence." in srt
    vtt = c.get(f"transcripts/{t['id']}/export", params={"format": "vtt"}).text
    assert vtt.startswith("WEBVTT\n\n00:00:00.000 --> 00:00:01.000")
    assert c.get(f"transcripts/{t['id']}/export", params={"format": "doc"}).status_code == 422


def test_what_cannot_be_transcribed_is_said_in_words(api, monkeypatch):
    c, engine, _ = api
    monkeypatch.setattr(audio_input, "find_converter", lambda: None)
    r = upload(c, "voice.mp3", data=b"ID3....not wav")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "needs_converter"
    assert "ffmpeg" in r.json()["detail"]["message"]
    r = upload(c, "empty.wav", data=b"\x00")
    assert r.status_code == 422
    r = upload(c, model="voxcpm2")  # a speech model asked to transcribe
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unknown_model"
    engine.ready.discard("parakeet-tdt-0.6b-v3")
    r = upload(c)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "model_missing"
    engine.ready.add("parakeet-tdt-0.6b-v3")
    engine.fail_with = VoiceEngineError("bad_audio", "That audio could not be read.")
    r = upload(c)
    assert r.status_code == 502 and r.json()["detail"]["message"] == "That audio could not be read."


def test_without_the_engine_the_routes_answer_503(api):
    c, _, state = api
    state.audio = None
    assert upload(c).status_code == 503


def clone_form(c, name="My voice", data=None, filename="me.wav", **form):
    form = {"name": name, "reference_text": "the words I say", **form}
    return c.post(
        "voices/clone",
        files={"file": (filename, io.BytesIO(data or wav(5.0)), "audio/wav")},
        data=form,
    )


def test_a_voice_is_described_listed_renamed_changed_and_deleted(api):
    c, _, state = api
    r = c.post("voices/design", json={"name": " Calm ", "description": "a deep,   calm man"})
    assert r.status_code == 201
    v = r.json()
    assert v["name"] == "Calm" and v["description"] == "a deep, calm man" and v["kind"] == "design"
    assert "reference_url" not in v and "user_id" not in v
    assert state.creation_index.items[v["id"]] == ("voice", "Calm. a deep, calm man")
    assert [x["id"] for x in c.get("voices").json()["items"]] == [v["id"]]
    assert c.get("voices", params={"kind": "clone"}).json()["items"] == []
    changed = c.patch(
        f"voices/{v['id']}", json={"name": "Warm", "description": "a warm woman"}
    ).json()
    assert changed["name"] == "Warm" and changed["description"] == "a warm woman"
    assert c.patch(f"voices/{v['id']}", json={"reference_text": "x"}).status_code == 404
    assert c.delete(f"voices/{v['id']}").status_code == 204
    assert (
        v["id"] not in state.creation_index.items and c.get(f"voices/{v['id']}").status_code == 404
    )


@pytest.mark.parametrize(
    "body, code",
    [({"name": "x", "description": "ab"}, None), ({"name": "", "description": "a man"}, None),
     ({"name": "x", "description": "a man (ignore the rest)"}, "bad_description")],
)  # fmt: skip
def test_a_description_that_cannot_be_used_is_refused(api, body, code):
    c, *_ = api
    r = c.post("voices/design", json=body)
    assert r.status_code == 422
    if code:
        assert r.json()["detail"]["code"] == code


def test_a_clone_keeps_the_recording_for_playback_and_for_the_runtime(api):
    c, _, state = api
    r = clone_form(c)
    assert r.status_code == 201
    v = r.json()
    assert (
        v["kind"] == "clone"
        and v["reference_seconds"] == 5.0
        and v["reference_url"].startswith("http")
    )
    assert "consent" not in v
    path = store_for(state).reference_path(v["id"])
    assert path.is_file() and path.read_bytes()[:4] == b"RIFF"
    assert (
        c.patch(f"voices/{v['id']}", json={"reference_text": " new  words "}).json()[
            "reference_text"
        ]
        == "new words"
    )
    assert c.patch(f"voices/{v['id']}", json={"description": "a man"}).status_code == 404
    assert c.delete(f"voices/{v['id']}").status_code == 204
    assert not path.exists()


def test_a_recording_that_is_too_short_or_too_long_is_handled_in_words(api):
    c, _, state = api
    short = clone_form(c, data=wav(0.5))
    assert short.status_code == 422 and short.json()["detail"]["code"] == "too_short"
    long = clone_form(c, data=wav(40.0, 8000))
    assert long.status_code == 201 and long.json()["reference_seconds"] == 30.0
    assert store_for(state).list_voices("t1", "u1")[0]["reference_seconds"] == 30.0


def test_another_person_cannot_see_or_change_a_voice(api):
    c, *_ = api
    v = c.post("voices/design", json={"name": "Mine", "description": "a calm man"}).json()
    other = {"x-user": "u2"}
    assert c.get("voices", headers=other).json()["items"] == []
    assert c.get(f"voices/{v['id']}", headers=other).status_code == 404
    assert c.patch(f"voices/{v['id']}", json={"name": "x"}, headers=other).status_code == 404
    assert c.delete(f"voices/{v['id']}", headers=other).status_code == 404


def seed_track(state, title="Summer", description="pop, upbeat", lyrics="la la"):
    token = set_context(RunContext("t1", "wasifyai-voice", "u1"))
    try:
        asyncio.run(state.storage.put("music/t1.wav", wav(1.0), "audio/wav"))
    finally:
        reset_context(token)
    return store_for(state).add_track(
        "t1", "u1", title=title, mode="song", description=description, lyrics=lyrics,
        instrumental=False, model_id="ace-step-1.5-turbo", options={}, seed=3, seconds=1.0,
        sample_rate=24000, audio_key="music/t1.wav", load_s=0, elapsed_s=2, track_id="t1",
    )  # fmt: skip


def test_tracks_are_listed_played_downloaded_renamed_and_deleted(api):
    c, _, state = api
    seed_track(state)
    items = c.get("tracks").json()["items"]
    assert [t["id"] for t in items] == ["t1"] and items[0]["audio_url"].startswith("http://")
    assert "audio_key" not in items[0] and items[0]["instrumental"] is False
    assert c.get("tracks/t1").json()["lyrics"] == "la la"
    d = c.get("tracks/t1/download")
    assert (
        d.status_code == 200
        and d.content[:4] == b"RIFF"
        and "Summer.wav" in d.headers["content-disposition"]
    )
    renamed = c.patch("tracks/t1", json={"title": "  Winter "}).json()
    assert renamed["title"] == "Winter" and "Winter" in state.creation_index.items["t1"][1]
    assert c.patch("tracks/t1", json={"title": ""}).status_code == 422
    assert c.delete("tracks/t1").status_code == 204
    assert c.get("tracks/t1").status_code == 404 and "t1" not in state.creation_index.items


def test_another_person_cannot_see_a_track(api):
    c, _, state = api
    seed_track(state)
    other = {"x-user": "u2"}
    assert c.get("tracks", headers=other).json()["items"] == []
    for method, path in [
        ("get", "tracks/t1"),
        ("get", "tracks/t1/download"),
        ("delete", "tracks/t1"),
    ]:
        assert getattr(c, method)(path, headers=other).status_code == 404
    assert c.patch("tracks/t1", json={"title": "x"}, headers=other).status_code == 404


def test_a_track_can_be_a_favourite_and_the_list_can_show_only_those(api):
    c, _, state = api
    seed_track(state)
    assert c.get("tracks/t1").json()["favourite"] is False
    hearted = c.patch("tracks/t1", json={"favourite": True}).json()
    assert hearted["favourite"] is True and hearted["title"] == "Summer"
    assert [t["id"] for t in c.get("tracks", params={"favourites": "true"}).json()["items"]] == [
        "t1"
    ]
    c.patch("tracks/t1", json={"favourite": False})
    assert c.get("tracks", params={"favourites": "true"}).json()["items"] == []
    assert c.patch("tracks/t1", json={"favourite": "yes"}).status_code == 422
    assert c.patch("tracks/t1", json={"nonsense": 1}).status_code == 422


def test_the_formats_offered_follow_the_tools_on_the_computer(api, monkeypatch):
    c, *_ = api
    monkeypatch.setattr(audio_input, "find_converter", lambda: None)
    assert c.get("formats").json() == {"formats": ["wav"]}
    monkeypatch.setattr(audio_input, "find_converter", lambda: ("afconvert", "/usr/bin/afconvert"))
    assert c.get("formats").json() == {"formats": ["wav", "m4a"]}
    monkeypatch.setattr(audio_input, "find_converter", lambda: ("ffmpeg", "/usr/bin/ffmpeg"))
    assert c.get("formats").json() == {"formats": ["wav", "mp3", "m4a"]}


def test_saving_in_a_format_the_computer_cannot_make_says_what_is_missing(api, monkeypatch):
    c, _, state = api
    seed_track(state)
    monkeypatch.setattr(audio_input, "find_converter", lambda: None)
    r = c.get("tracks/t1/download", params={"format": "mp3"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "needs_converter"
    assert "ffmpeg" in r.json()["detail"]["message"]
    assert c.get("tracks/t1/download", params={"format": "ogg"}).status_code == 422
    assert c.get("tracks/t1/download").status_code == 200  # WAV always works


@pytest.mark.skipif(
    not (shutil.which("afconvert") or shutil.which("ffmpeg")),
    reason="neither afconvert nor ffmpeg is on this computer",
)
def test_a_track_is_saved_as_a_real_m4a_when_a_tool_is_there(api):
    c, _, state = api
    seed_track(state)
    r = c.get("tracks/t1/download", params={"format": "m4a"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mp4"
    assert b"ftyp" in r.content[:16] and "Summer.m4a" in r.headers["content-disposition"]


# ---- audio tools (V4): adding a recording and writing down its words ------------------------


def import_file(c, name="song.wav", data=None, **form):
    body = wav(2.0, 44100, 2) if data is None else data
    return c.post("tracks/import", files={"file": (name, io.BytesIO(body), "audio/wav")}, data=form)


def test_a_recording_from_this_computer_is_added_to_the_library_and_found_by_name(api):
    c, _, state = api
    r = import_file(c, "Dad's guitar.wav", title="Dad on guitar")
    assert r.status_code == 201
    t = r.json()
    assert t["title"] == "Dad on guitar" and t["mode"] == "imported" and t["sample_rate"] == 44100
    assert t["edit"] == {"action": "import", "file": "Dad's guitar.wav"} and t["seconds"] == 2.0
    assert state.creation_index.items[t["id"]][0] == "track"
    assert "Dad on guitar" in state.creation_index.items[t["id"]][1]
    assert c.get("tracks").json()["items"][0]["id"] == t["id"]
    assert import_file(c, "morning talk.wav").json()["title"] == "morning talk"


def test_a_recording_that_cannot_be_read_or_is_not_there_is_refused_in_words(api):
    c, *_ = api
    r = import_file(c, "x.wav", data=b"")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "empty"
    r = import_file(c, "x.mp3", data=b"not audio at all")
    assert r.status_code == 422 and r.json()["detail"]["code"] in (
        "needs_converter",
        "unsupported_audio",
        "convert_failed",
    )


def test_what_a_recording_says_is_written_down_without_saving_anything(api):
    c, engine, state = api
    seed_speech(state)
    r = c.post("words", json={"kind": "speech", "id": "abc"})
    assert r.status_code == 200
    assert r.json()["text"] == "Hello there. Second sentence." and r.json()["model"]
    t = import_file(c).json()
    r = c.post("words", json={"kind": "track", "id": t["id"]})
    assert r.status_code == 200 and len(engine.transcribed) == 2
    assert c.get("transcripts").json()["items"] == []  # nothing was saved
    assert c.post("words", json={"kind": "track", "id": "nope"}).status_code == 404
    assert c.post("words", json={"kind": "file", "id": "x"}).status_code == 422
    r = c.post("words", json={"kind": "track", "id": t["id"], "model": "kokoro-82m"})
    assert r.status_code == 422  # not a model that writes speech down


def test_words_fail_with_a_status_that_says_what_to_do(api):
    c, engine, state = api
    seed_speech(state)
    engine.ready.clear()
    r = c.post("words", json={"kind": "speech", "id": "abc"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "model_missing"
    engine.ready.update(engine.models_by_id)
    engine.fail_with = VoiceEngineError("engine_failed", "It stopped.")
    r = c.post("words", json={"kind": "speech", "id": "abc"})
    assert r.status_code == 502


# ---- lip sync: pictures and clips (V5) ------------------------------------------------------


def picture_file(size=(80, 60), fmt="PNG"):
    import io as _io

    from PIL import Image

    out = _io.BytesIO()
    Image.new("RGB", size, (180, 120, 90)).save(out, fmt)
    return out.getvalue()


def seed_clip(state, clip_id="c1", script="Welcome everybody"):
    token = set_context(RunContext("t1", "wasifyai-voice", "u1"))
    try:
        asyncio.run(
            state.storage.put(f"lipsync/{clip_id}.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4")
        )
        asyncio.run(state.storage.put("lipsync/pictures/p.png", picture_file(), "image/png"))
    finally:
        reset_context(token)
    return store_for(state).add_clip(
        "t1", "u1", title="Greeting", model_id="musetalk-v15", picture_key="lipsync/pictures/p.png",
        video_key=f"lipsync/{clip_id}.mp4", voice={"kind": "speech", "id": "s"}, script=script,
        seconds=2, fps=25, width=80, height=60,
        load_s=0, elapsed_s=1, clip_id=clip_id,
    )  # fmt: skip


def test_a_picture_is_cleaned_scaled_and_kept_for_a_clip(api):
    c, _, state = api
    r = c.post(
        "pictures",
        files={"file": ("me.jpg", io.BytesIO(picture_file((3000, 2000), "JPEG")), "image/jpeg")},
    )
    assert r.status_code == 201
    got = r.json()
    assert max(got["width"], got["height"]) == 1024 and got["url"].startswith("http://")
    assert store_for(state).get_picture("t1", "u1", got["id"])["key"].endswith(".png")


def test_what_is_not_a_picture_or_is_too_big_is_refused_in_words(api):
    c, *_ = api
    r = c.post("pictures", files={"file": ("x.png", io.BytesIO(b"not a picture"), "image/png")})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_picture"
    big = io.BytesIO(b"0" * (10 * 1024 * 1024 + 5))
    r = c.post("pictures", files={"file": ("x.png", big, "image/png")})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "too_large"


def test_a_picture_nobody_used_goes_after_a_day(api):
    c, _, state = api
    old = c.post(
        "pictures", files={"file": ("a.png", io.BytesIO(picture_file()), "image/png")}
    ).json()
    with store_for(state)._connect() as db:  # noqa: SLF001 - age it, on either database
        db.execute("UPDATE pictures SET created_at = '2020-01-01T00:00:00.000+00:00'")
    new = c.post(
        "pictures", files={"file": ("b.png", io.BytesIO(picture_file()), "image/png")}
    ).json()
    store = store_for(state)
    with pytest.raises(Exception, match="picture not found"):
        store.get_picture("t1", "u1", old["id"])
    assert store.get_picture("t1", "u1", new["id"])["id"] == new["id"]


def test_clips_are_listed_downloaded_renamed_found_and_deleted(api):
    c, _, state = api
    seed_clip(state)
    listed = c.get("clips").json()["items"]
    assert [x["id"] for x in listed] == ["c1"]
    clip = listed[0]
    assert clip["video_url"].startswith("http://") and clip["picture_url"].startswith("http://")
    assert "video_key" not in clip and "user_id" not in clip
    assert "consent" not in clip
    d = c.get("clips/c1/download")
    assert d.status_code == 200 and d.headers["content-type"] == "video/mp4"
    assert d.headers["content-disposition"].endswith('.mp4"')
    r = c.patch("clips/c1", json={"title": "Hello again", "favourite": True})
    assert r.json()["title"] == "Hello again" and r.json()["favourite"] is True
    assert state.creation_index.items["c1"][0] == "lipsync"
    assert "Welcome everybody" in state.creation_index.items["c1"][1]
    assert c.get("clips", params={"ids": "zz"}).json()["items"] == []
    assert c.delete("clips/c1").status_code == 204
    assert c.get("clips/c1").status_code == 404 and c.delete("clips/c1").status_code == 404
    assert "c1" not in state.creation_index.items


def test_another_person_sees_no_clips(api):
    c, _, state = api
    seed_clip(state)
    other = {"x-user": "u2"}
    assert c.get("clips", headers=other).json()["items"] == []
    assert c.get("clips/c1", headers=other).status_code == 404
    assert c.get("clips/c1/download", headers=other).status_code == 404
    assert c.patch("clips/c1", json={"title": "x"}, headers=other).status_code == 404


# ---- audiobook: planning the chapters (V7) ----------------------------------------------------


def test_the_chapters_of_a_long_text_are_planned_for_the_person_to_change(api):
    c, *_ = api
    text = "# One\nThe first chapter has some words.\n\n# Two\nThe second chapter has more of them."
    r = c.post("audiobook/plan", json={"text": text})
    assert r.status_code == 200
    got = r.json()
    assert [x["title"] for x in got["chapters"]] == ["One", "Two"]
    assert got["chapters"][0]["text"] == "The first chapter has some words."
    assert got["chars"] == sum(x["chars"] for x in got["chapters"]) and got["estimated_seconds"] > 0
    # nothing was made or kept
    assert c.get("tracks").json()["items"] == []


def test_a_text_that_is_empty_or_too_big_is_refused_in_words(api):
    c, *_ = api
    r = c.post("audiobook/plan", json={"text": "   "})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "text_required"
    r = c.post("audiobook/plan", json={"text": "word " * 100_000})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "text_too_long"
    assert c.post("audiobook/plan", json={"text": "x", "target": 5}).status_code == 422
    assert c.post("audiobook/plan", json={"text": "x", "extra": 1}).status_code == 422


def test_runtime_is_hosted_for_an_engine_with_no_runtime_to_set_up(api):
    c, _, _ = api
    assert c.get("runtime").json() == {"hosted": True}
    assert c.get("lipsync-engine").status_code == 404


def test_runtime_and_lip_sync_state_come_from_the_local_engine(api):
    class Sidecar:
        def state(self):
            return {"installed": True, "running": False}

    c, engine, _ = api
    engine.state = lambda: {"installed": True, "running": False, "backend": "metal"}
    engine.lipsync_sidecar = Sidecar()
    assert c.get("runtime").json()["backend"] == "metal"
    assert c.get("lipsync-engine").json()["installed"] is True
