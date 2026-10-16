"""The voice product's routes on a fake engine: speeches, transcripts, exports, ownership."""

import asyncio
import io

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
def api(tmp_path):
    engine = FakeEngine()
    state = app_state(tmp_path, engine)
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
    form = {"name": name, "consent": "own", "reference_text": "the words I say", **form}
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


def test_a_clone_keeps_the_recording_for_playback_and_for_the_runtime_with_its_consent(api):
    c, _, state = api
    r = clone_form(c)
    assert r.status_code == 201
    v = r.json()
    assert (
        v["kind"] == "clone"
        and v["reference_seconds"] == 5.0
        and v["reference_url"].startswith("http")
    )
    assert v["consent"]["basis"] == "own" and v["consent"]["statement"] == "This is my own voice."
    assert v["consent"]["accepted_at"]
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


@pytest.mark.parametrize("consent", ["", "yes", "everyone"])
def test_a_clone_is_not_saved_without_saying_whose_voice_it_is(api, consent):
    c, _, state = api
    r = clone_form(c, consent=consent)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "consent_required"
    assert store_for(state).list_voices("t1", "u1") == []


def test_permission_is_a_valid_basis_and_is_recorded_as_such(api):
    c, *_ = api
    v = clone_form(c, consent="permission").json()
    assert v["consent"]["basis"] == "permission"
    assert "permission" in v["consent"]["statement"]


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
