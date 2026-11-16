"""Meetings through the desktop engine's routes (ADR-0108, MT1): what is missing is said in words,
a meeting is made from a file in the background, its speakers can be named, it is found by search,
saved as text and deleted. The speaker model and the speech engine are stand-ins here; the real ones
run in `products/wasifyai-meetings/tests/test_meetings_real.py`."""

import io
import os
import time
import wave
from dataclasses import dataclass, field

import numpy as np
import pytest
from fastapi.testclient import TestClient
from wasifyai_api.actions_engine import default_catalogue
from wasifyai_api.main import create_app
from wasifyai_meetings import runtime
from wasifyai_meetings.sortformer import Diarization, Turn
from wasifyai_platform_sdk import Identity, TranscriptResult, TranscriptSegment

from tests.test_desktop_profile import auth, data_dir  # noqa: F401 (the fixture)

PRODUCT = "/products/wasifyai-meetings"


def _wav(seconds: float = 12.0) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        t = np.arange(int(16000 * seconds)) / 16000
        w.writeframes((np.sin(2 * np.pi * 220 * t) * 3000).astype("<i2").tobytes())
    return buf.getvalue()


@dataclass
class FakeModel:
    id: str = "fake-stt"
    title: str = "Fake STT"
    tasks: tuple[str, ...] = ("transcribe",)
    languages: tuple[str, ...] = ("en",)

    def option(self, name: str):  # noqa: ANN201
        return None


@dataclass
class FakeSpeech:
    heard: list[int] = field(default_factory=list)

    def resolve(self, task, model_id):  # noqa: ANN001, ANN201
        return FakeModel()

    async def transcribe(self, model, wav, options, beside=False):  # noqa: ANN001, ANN201
        self.heard.append(len(wav))
        segs = [
            TranscriptSegment(0.3, 4.5, "Good morning, shall we start?"),
            TranscriptSegment(5.2, 8.6, "Yes, the budget first."),
            TranscriptSegment(9.0, 11.5, "Fine by me."),
        ]
        return TranscriptResult(" ".join(s.text for s in segs), segs, 12.0, model.id, 0.1, None)


class FakeSortformer:
    def __init__(self, path):  # noqa: ANN001
        self.path = path

    def run(self, wav, progress=None, stop=None):  # noqa: ANN001, ANN201
        if progress:
            progress(1.0)
        turns = [Turn(0.0, 4.8, 1), Turn(5.0, 8.8, 3), Turn(8.9, 11.8, 1)]
        return Diarization(turns, 2, 12.0, 0.01)


def _wait(c: TestClient, item: str) -> dict:
    for _ in range(200):
        row = c.get(f"{PRODUCT}/meetings/{item}", headers=auth()).json()
        if row["status"] != "working":
            return row
        time.sleep(0.05)
    raise AssertionError("the meeting was not made")


def test_the_routes_need_the_shells_token(data_dir):  # noqa: F811
    with TestClient(create_app()) as c:
        assert c.get(f"{PRODUCT}/status").status_code == 401
        assert c.get(f"{PRODUCT}/meetings").status_code == 401


def test_without_the_speaker_model_the_window_is_told_what_to_get(data_dir):  # noqa: F811
    with TestClient(create_app()) as c:
        status = c.get(f"{PRODUCT}/status", headers=auth()).json()
        assert (
            status["speaker_model"] is False
            and status["speaker_model_id"] == "sortformer-4spk-v2.1"
        )
        assert status["busy"] is False and ".m4a" in status["formats"]
        r = c.post(f"{PRODUCT}/meetings", files={"file": ("a.wav", _wav(), "audio/wav")},
                   headers=auth())  # fmt: skip
        assert r.status_code == 409 and "speaker model" in r.json()["detail"]["message"]
        assert c.get(f"{PRODUCT}/meetings", headers=auth()).json() == {"items": []}


def test_the_speaker_model_is_offered_in_models(data_dir):  # noqa: F811
    with TestClient(create_app()) as c:
        models = c.get("/desktop/models", headers=auth()).json()["models"]
        (entry,) = [m for m in models if m["id"] == "sortformer-4spk-v2.1"]
        assert entry["product_id"] == "wasifyai-meetings" if "product_id" in entry else True
        assert entry["bytes_total"] == 492268840 if "bytes_total" in entry else True


@pytest.fixture
def ready(data_dir, monkeypatch):  # noqa: F811
    model = data_dir / "models" / "meetings" / runtime.SPEAKER_FILE[1]
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"stand-in")
    monkeypatch.setattr(runtime, "Sortformer", FakeSortformer)
    return data_dir


def test_a_meeting_is_made_from_a_file_named_found_saved_and_deleted(ready):
    with TestClient(create_app()) as c:
        speech = FakeSpeech()
        c.app.state.services.audio = speech  # type: ignore[attr-defined]
        status = c.get(f"{PRODUCT}/status", headers=auth()).json()
        assert status["speaker_model"] and status["speech"]
        assert status["speech_model"] == {"id": "fake-stt", "title": "Fake STT"}
        r = c.post(f"{PRODUCT}/meetings", files={"file": ("Budget call.wav", _wav(), "audio/wav")},
                   headers=auth())  # fmt: skip
        assert r.status_code == 201, r.text
        made = r.json()
        assert made["title"] == "Budget call" and made["status"] == "working"
        row = _wait(c, made["id"])
        assert row["status"] == "done", row["error"]
        assert row["seconds"] == 12.0 and row["model_id"] == "fake-stt"
        assert [s["key"] for s in row["speakers"]] == ["S1", "S2"]
        assert [x["speaker"] for x in row["lines"]] == ["S1", "S2", "S1"]
        assert speech.heard and speech.heard[0] > 300_000  # the 16 kHz WAV, not the upload
        assert set(row["timings"]) == {"read_s", "speakers_s", "words_s"}

        r = c.patch(f"{PRODUCT}/meetings/{row['id']}/speakers/S2", json={"name": "Ravi"},
                    headers=auth())  # fmt: skip
        assert r.json()["speakers"][1]["name"] == "Ravi"
        assert c.patch(f"{PRODUCT}/meetings/{row['id']}/speakers/S9", json={"name": "x"},
                       headers=auth()).status_code == 404  # fmt: skip

        text = c.get(f"{PRODUCT}/meetings/{row['id']}/export", headers=auth())
        assert 'filename="Budget call.txt"' in text.headers["content-disposition"]
        assert "[0:05] Ravi: Yes, the budget first." in text.text

        a = c.get(f"{PRODUCT}/meetings/{row['id']}/audio", headers=auth())
        assert a.status_code == 200 and a.content[:4] == b"RIFF"
        # the player's link: signed, served from the desktop's files, read in ranges
        link = c.get(f"{PRODUCT}/meetings/{row['id']}/audio-link", headers=auth()).json()["url"]
        path = link.split("://", 1)[1].split("/", 1)[1]
        part = c.get(f"/{path}", headers={"Range": "bytes=0-3"})
        assert part.status_code == 206 and part.content == b"RIFF"
        assert int(part.headers["content-range"].split("/")[1]) == len(a.content)
        assert c.get(f"/{path.replace('s=', 's=0')}").status_code == 403

        listed = c.get(f"{PRODUCT}/meetings", headers=auth()).json()["items"]
        assert [m["id"] for m in listed] == [row["id"]] and "lines" not in listed[0]

        assert c.delete(f"{PRODUCT}/meetings/{row['id']}", headers=auth()).status_code == 204
        assert c.get(f"{PRODUCT}/meetings/{row['id']}", headers=auth()).status_code == 404
        assert not any(ready.rglob("audio.wav"))
        assert not any((ready / "meetings" / "incoming").iterdir())


def test_a_file_that_is_not_sound_fails_in_words(ready):
    with TestClient(create_app()) as c:
        c.app.state.services.audio = FakeSpeech()  # type: ignore[attr-defined]
        upload = {"file": ("notes.txt", b"hello there", "text/plain")}
        r = c.post(f"{PRODUCT}/meetings", files=upload, headers=auth())
        assert r.status_code == 201
        row = _wait(c, r.json()["id"])
        assert row["status"] == "failed" and "could not be read" in row["error"]


def test_the_actions_are_in_the_catalogue():
    ids = {a.id for a in default_catalogue()}
    assert {"meetings.make", "meetings.make_recorded", "meetings.name_speaker"} <= ids


def test_a_language_the_chosen_model_does_not_know_goes_to_one_that_does():
    from wasifyai_meetings.runtime import model_for, ready_speech_models

    bengali = FakeModel(id="indic", title="IndicConformer", languages=("bn", "hi"))

    class TwoModels(FakeSpeech):
        def resolve(self, task, model_id):  # noqa: ANN001, ANN201
            return bengali if model_id == "indic" else FakeModel()

        def models(self, task):  # noqa: ANN001, ANN201
            return [
                {"id": "fake-stt", "title": "Fake STT", "languages": ["en"], "state": "ready"},
                {"id": "indic", "title": "IndicConformer", "languages": ["bn", "hi"],
                 "state": "ready"},
                {"id": "far", "title": "Not here", "languages": ["fr"], "state": "can_install"},
            ]  # fmt: skip

    speech = TwoModels()
    assert [m["id"] for m in ready_speech_models(speech)] == ["fake-stt", "indic"]
    assert model_for(speech, "", None).id == "fake-stt"
    assert model_for(speech, "en", None).id == "fake-stt"
    assert model_for(speech, "bn-IN", None).id == "indic"
    assert model_for(speech, "fr", None).id == "fake-stt"  # none knows it: the chosen one refuses
    assert model_for(speech, "bn", "fake-stt").id == "fake-stt"  # one asked for is used
    assert ready_speech_models(FakeSpeech()) == []


def test_search_finds_a_meeting_by_its_title_its_people_and_what_was_said():
    from wasifyai_meetings.runtime import words_of

    words = words_of(
        {
            "title": "Budget call",
            "speakers": [{"name": "Asha"}, {"name": "Speaker 2"}],
            "text": "The school roof first.",
        }
    )
    for part in ("Budget call", "meeting", "Asha", "school roof"):
        assert part in words


def _stereo(mine_s: float, theirs_s: float, seconds: float = 12.0) -> bytes:
    """A recording as the shell writes it: the microphone, then the computer's sound."""
    t = np.arange(int(16000 * seconds)) / 16000
    mine = np.where(t < mine_s, np.sin(2 * np.pi * 220 * t) * 3000, 0)
    theirs = np.where(t >= theirs_s, np.sin(2 * np.pi * 330 * t) * 3000, 0)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(np.stack([mine, theirs], axis=1).astype("<i2").tobytes())
    return buf.getvalue()


def test_a_recording_made_in_the_app_becomes_a_meeting_with_you_and_the_others(ready):
    folder = ready / "meetings" / "recordings"
    folder.mkdir(parents=True)
    (folder / "rec-20261116-140500-a1b2.wav").write_bytes(_stereo(5.0, 5.0))
    (folder / "rec-20261116-150000-c3d4.wav.part").write_bytes(b"still being recorded")
    with TestClient(create_app()) as c:
        speech = FakeSpeech()
        c.app.state.services.audio = speech  # type: ignore[attr-defined]
        waiting = c.get(f"{PRODUCT}/status", headers=auth()).json()["recordings"]
        assert [r["name"] for r in waiting] == ["rec-20261116-140500-a1b2.wav"]
        assert waiting[0]["seconds"] == 12.0

        for bad in ("../meetings.db", "rec-x.wav.part", "rec-missing.wav", "audio.wav"):
            r = c.post(f"{PRODUCT}/meetings/recorded", json={"name": bad}, headers=auth())
            assert r.status_code in (404, 422), bad

        r = c.post(f"{PRODUCT}/meetings/recorded",
                   json={"name": "rec-20261116-140500-a1b2.wav", "title": "Stand-up"},
                   headers=auth())  # fmt: skip
        assert r.status_code == 201, r.text
        row = _wait(c, r.json()["id"])
        assert row["status"] == "done", row["error"]
        assert row["source"] == "recorded" and row["title"] == "Stand-up"
        # both channels were written down, each its own; the microphone is "You"
        assert len(speech.heard) == 2
        names = [s["name"] for s in row["speakers"]]
        assert names[0] == "You" and all(n.startswith("Speaker ") for n in names[1:])
        assert {x["speaker"] for x in row["lines"]} >= {"S1", "S2"}
        # the recording is the meeting's now; only the mix is kept, to play
        assert not (folder / "rec-20261116-140500-a1b2.wav").exists()
        kept = sorted(p.name for p in ready.rglob("*.wav") if "meetings/recordings" not in str(p))
        assert kept == ["audio.wav"]
        assert c.get(f"{PRODUCT}/status", headers=auth()).json()["recordings"] == []


def test_a_recording_with_the_computer_silent_is_you_alone(ready):
    folder = ready / "meetings" / "recordings"
    folder.mkdir(parents=True)
    (folder / "rec-solo.wav").write_bytes(_stereo(12.0, 99.0))
    with TestClient(create_app()) as c:
        speech = FakeSpeech()
        c.app.state.services.audio = speech  # type: ignore[attr-defined]
        r = c.post(f"{PRODUCT}/meetings/recorded", json={"name": "rec-solo.wav"}, headers=auth())
        row = _wait(c, r.json()["id"])
        assert row["status"] == "done" and len(speech.heard) == 1
        assert [s["name"] for s in row["speakers"]] == ["You"]
        assert row["title"] == "Recorded meeting"


def test_a_recording_can_be_thrown_away(ready):
    folder = ready / "meetings" / "recordings"
    folder.mkdir(parents=True)
    (folder / "rec-old.wav").write_bytes(_stereo(1, 1))
    with TestClient(create_app()) as c:
        assert c.delete(f"{PRODUCT}/recordings/rec-old.wav", headers=auth()).status_code == 204
        assert c.delete(f"{PRODUCT}/recordings/rec-old.wav", headers=auth()).status_code == 404
        assert c.delete(f"{PRODUCT}/recordings/..%2Fmeetings.db", headers=auth()).status_code == 404
    assert not (folder / "rec-old.wav").exists()


def test_the_assistant_makes_a_meeting_from_the_newest_waiting_recording(ready):
    folder = ready / "meetings" / "recordings"
    folder.mkdir(parents=True)
    (folder / "rec-old.wav").write_bytes(_stereo(5.0, 5.0))
    newest = folder / "rec-new.wav"
    newest.write_bytes(_stereo(5.0, 5.0))
    old = time.time() - 600
    os.utime(folder / "rec-old.wav", (old, old))
    with TestClient(create_app()) as c:
        c.app.state.services.audio = FakeSpeech()  # type: ignore[attr-defined]
        run = c.app.state.services.actions.run_action  # type: ignore[attr-defined]

        async def go(params):  # noqa: ANN001, ANN202
            return await run(
                "meetings.make_recorded", params, "window", actor=Identity("local", "me")
            )

        made = c.portal.call(go, {"title": "Weekly sync"})
        assert made.status == "ok", made
        assert made.output["title"] == "Weekly sync"
        assert made.output["speakers"][0]["name"] == "You"
        assert not newest.exists() and (folder / "rec-old.wav").exists()

        assert c.portal.call(go, {"name": "rec-gone.wav"}).status == "refused"
        assert c.portal.call(go, {"name": "../meetings.db"}).status == "refused"


class FakeVoices:
    """Stand-in voiceprints: each meeting's first speaker sounds like Asha, the second like Ben."""

    def __init__(self):  # noqa: ANN204
        rng = np.random.default_rng(3)
        self.voices = [v / np.linalg.norm(v) for v in rng.normal(size=(2, 192))]
        self.n = 0

    def of(self, wav):  # noqa: ANN001, ANN201
        v = self.voices[self.n % 2].astype(np.float32)
        self.n += 1
        return v


def _make(c: TestClient, name: str = "Budget call.wav") -> dict:
    r = c.post(f"{PRODUCT}/meetings", files={"file": (name, _wav(), "audio/wav")}, headers=auth())
    assert r.status_code == 201, r.text
    row = _wait(c, r.json()["id"])
    assert row["status"] == "done", row["error"]
    return c.get(f"{PRODUCT}/meetings/{row['id']}", headers=auth()).json()


def test_a_named_speaker_is_suggested_in_the_next_meeting_and_people_can_forget_them(
    ready, monkeypatch
):
    voices = FakeVoices()
    monkeypatch.setattr(runtime, "voices_for", lambda state: voices)
    with TestClient(create_app()) as c:
        c.app.state.services.audio = FakeSpeech()  # type: ignore[attr-defined]
        first = _make(c)
        assert [s["suggestion"] for s in first["speakers"]] == [None, None]
        url = f"{PRODUCT}/meetings/{first['id']}/speakers"
        c.patch(f"{url}/S1", json={"name": "Asha"}, headers=auth()).raise_for_status()
        c.patch(f"{url}/S2", json={"name": "Ben"}, headers=auth()).raise_for_status()
        folk = c.get(f"{PRODUCT}/people", headers=auth()).json()["items"]
        assert [(p["name"], p["meetings"], p["voices"]) for p in folk] == [
            ("Asha", 1, 1), ("Ben", 1, 1)
        ]  # fmt: skip

        second = _make(c, "Next call.wav")
        hints = {s["key"]: s["suggestion"] for s in second["speakers"]}
        assert hints["S1"]["name"] == "Asha" and hints["S2"]["name"] == "Ben"
        assert hints["S1"]["status"] == "possible"
        assert [s["name"] for s in second["speakers"]] == ["Speaker 1", "Speaker 2"]
        # Yes: name them as that person; No: not suggested again
        asha = hints["S1"]["person_id"]
        url = f"{PRODUCT}/meetings/{second['id']}/speakers"
        yes = c.patch(f"{url}/S1", json={"person_id": asha}, headers=auth()).json()
        assert yes["speakers"][0]["name"] == "Asha" and yes["speakers"][0]["person_id"] == asha
        no = c.post(f"{url}/S2/not", json={"person_id": hints["S2"]["person_id"]},
                    headers=auth()).json()  # fmt: skip
        assert no["speakers"][1]["suggestion"] is None

        r = c.patch(f"{PRODUCT}/people/{asha}", json={"name": "Asha Rahman"}, headers=auth())
        assert r.json()["name"] == "Asha Rahman"
        names = [
            c.get(f"{PRODUCT}/meetings/{m['id']}", headers=auth()).json()["speakers"][0]["name"]
            for m in (first, second)
        ]
        assert names == ["Asha Rahman", "Asha Rahman"]
        assert c.delete(f"{PRODUCT}/people/{asha}", headers=auth()).status_code == 204
        assert [p["name"] for p in c.get(f"{PRODUCT}/people", headers=auth()).json()["items"]] == [
            "Ben"
        ]
        assert c.delete(f"{PRODUCT}/people/{asha}", headers=auth()).status_code == 404


def test_the_status_says_whether_the_voiceprint_model_is_here(ready):
    with TestClient(create_app()) as c:
        c.app.state.services.audio = FakeSpeech()  # type: ignore[attr-defined]
        s = c.get(f"{PRODUCT}/status", headers=auth()).json()
        assert s["voiceprint_model"] is False and s["voiceprint_model_id"] == "eres2net-voxceleb"
        model = ready / "models" / runtime.VOICEPRINT_FILE[0] / runtime.VOICEPRINT_FILE[1]
        model.write_bytes(b"stand-in")
        assert c.get(f"{PRODUCT}/status", headers=auth()).json()["voiceprint_model"] is True


class FakeChat:
    def __init__(self):  # noqa: ANN204
        self.asked: list[str] = []

    async def complete(self, name, system, prompt, schema=None):  # noqa: ANN001, ANN201
        self.asked.append(prompt)
        return "## Summary\n- The budget was agreed."


def test_a_report_is_written_kept_found_saved_and_deleted(ready):
    with TestClient(create_app()) as c:
        c.app.state.services.audio = FakeSpeech()  # type: ignore[attr-defined]
        chat = FakeChat()
        caps = c.app.state.services.caps["wasifyai-meetings"]  # type: ignore[attr-defined]
        caps.text = chat
        row = _make(c)
        templates = c.get(f"{PRODUCT}/templates", headers=auth()).json()["items"]
        assert [t["id"] for t in templates][:2] == ["summary", "minutes"]
        ask = {"title": "Client update", "instructions": "What the client asked for."}
        own = c.post(f"{PRODUCT}/templates", json=ask, headers=auth()).json()
        assert own["own"] and own["id"].startswith("own-")

        url = f"{PRODUCT}/meetings/{row['id']}/reports"
        assert c.post(url, json={"template": "nope"}, headers=auth()).status_code == 404
        r = c.post(url, json={"template": "summary"}, headers=auth())
        assert r.status_code == 201, r.text
        rid = r.json()["id"]
        for _ in range(100):
            got = c.get(f"{PRODUCT}/reports/{rid}", headers=auth()).json()
            if got["status"] != "working":
                break
            time.sleep(0.05)
        assert got["status"] == "done" and got["text"].startswith("## Summary")
        assert "Good morning, shall we start?" in chat.asked[0]
        meeting = c.get(f"{PRODUCT}/meetings/{row['id']}", headers=auth()).json()
        assert [x["title"] for x in meeting["reports"]] == ["Summary"]
        file = c.get(f"{PRODUCT}/reports/{rid}/export", headers=auth())
        assert 'filename="Summary.md"' in file.headers["content-disposition"]
        assert file.text.startswith("## Summary")

        r = c.post(url, json={"template": own["id"]}, headers=auth())
        assert r.json()["title"] == "Client update"
        assert c.delete(f"{PRODUCT}/reports/{rid}", headers=auth()).status_code == 204
        assert c.get(f"{PRODUCT}/reports/{rid}", headers=auth()).status_code == 404
        assert c.delete(f"{PRODUCT}/templates/{own['id']}", headers=auth()).status_code == 204


class FakeNotebooks:
    """The notebooks' actions as the executor runs them (MT5): the real notebooks are checked in
    docs/spikes/meetings-mt5.md."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.made: dict[str, str] = {"nb-acme": "Acme"}

    async def run_action(self, action, params, origin, *, actor):  # noqa: ANN001, ANN201
        from types import SimpleNamespace

        self.calls.append((action, params))
        if action == "notebook.list":
            out = {"notebooks": [{"notebook_id": k, "title": v} for k, v in self.made.items()]}
        elif action == "notebook.create":
            nid = f"nb-{len(self.made)}"
            self.made[nid] = params["title"]
            out = {"notebook_id": nid, "title": params["title"]}
        elif action == "notebook.add_source":
            out = {"document_id": f"doc-{len(self.calls)}"}
        elif action == "notebook.ask":
            cite = {"n": 1, "document_id": params["document_ids"][0], "text": "Fine by me."}
            out = {"reply": "They start with the budget [1].", "citations": [cite],
                   "conversation_id": "c1"}  # fmt: skip
        else:
            return SimpleNamespace(status="refused", output=None, text="no", code="no")
        return SimpleNamespace(status="ok", output=out, text="", code="")


def test_a_meeting_is_added_to_a_notebook_and_asked_about_on_its_page(ready, monkeypatch):
    from wasifyai_meetings import asking

    # the notebook has read the source at once here
    monkeypatch.setattr(
        runtime, "AskJobs", lambda deps, p, s: asking.AskJobs(deps, p, s, lambda *_: "ready")
    )
    with TestClient(create_app()) as c:
        services = c.app.state.services  # type: ignore[attr-defined]
        services.audio = FakeSpeech()
        row = _make(c)
        notebooks = FakeNotebooks()
        services.actions = notebooks
        assert c.get(f"{PRODUCT}/notebooks", headers=auth()).json()["items"] == [
            {"id": "nb-acme", "title": "Acme"}
        ]
        url = f"{PRODUCT}/meetings/{row['id']}"
        r = c.post(f"{url}/notebook", json={"notebook_id": "nb-gone"}, headers=auth())
        assert r.status_code == 404, r.text
        r = c.post(f"{url}/notebook", json={"notebook_id": "nb-acme"}, headers=auth())
        assert r.status_code == 200, r.text
        doc = r.json()["document_id"]
        source = notebooks.calls[-1][1]
        assert source["title"] == "Meeting: Budget call" and "Fine by me." in source["content"]

        r = c.post(f"{url}/questions", json={"question": "What comes first?"}, headers=auth())
        assert r.status_code == 201, r.text
        qid = r.json()["id"]
        for _ in range(100):
            got = c.get(f"{PRODUCT}/questions/{qid}", headers=auth()).json()
            if got["status"] != "working":
                break
            time.sleep(0.05)
        assert got["status"] == "done", got["error"]
        assert got["reply"].startswith("They start") and got["notebook_id"] == "nb-acme"
        # limited to the meeting's own source in the notebook
        assert notebooks.calls[-1][1]["document_ids"] == [doc]
        meeting = c.get(url, headers=auth()).json()
        assert [n["notebook_title"] for n in meeting["notebooks"]] == ["Acme"]
        assert [q["question"] for q in meeting["questions"]] == ["What comes first?"]
        assert c.delete(f"{PRODUCT}/questions/{qid}", headers=auth()).status_code == 204
        assert c.get(f"{PRODUCT}/questions/{qid}", headers=auth()).status_code == 404


@dataclass
class FakeCloudModel(FakeModel):
    id: str = "key:transcribe"
    title: str = "Scribe v2 (cloud)"


@dataclass
class FakeCloudSpeech:
    """The cloud model on the key (decision 13): the whole recording at once, every word with who
    said it."""

    asked: list[dict] = field(default_factory=list)

    def resolve(self, task, model_id):  # noqa: ANN001, ANN201
        return FakeCloudModel()

    async def transcribe(self, model, wav, options, beside=False):  # noqa: ANN001, ANN201
        self.asked.append(options)
        words = [
            TranscriptSegment(0.3, 0.8, "Good", "speaker_0"),
            TranscriptSegment(0.9, 4.5, "morning.", "speaker_0"),
            TranscriptSegment(5.2, 8.6, "Budget.", "speaker_1"),
            TranscriptSegment(9.0, 11.5, "Fine.", "speaker_0"),
        ]
        segs = [TranscriptSegment(0.3, 11.5, "Good morning. Budget. Fine.")]
        return TranscriptResult(segs[0].text, segs, 12.0, model.id, 0.1, None, words=tuple(words))


class FakeStorage:
    def __init__(self) -> None:
        self.kept: dict[str, bytes] = {}

    async def put(self, key, data, content_type):  # noqa: ANN001, ANN201
        self.kept[key] = data

    async def exists(self, key):  # noqa: ANN001, ANN201
        return key in self.kept

    async def url(self, key, ttl):  # noqa: ANN001, ANN201
        return f"https://storage.test/{key}"

    async def delete(self, key):  # noqa: ANN001, ANN201
        self.kept.pop(key, None)


def test_on_the_web_a_file_is_written_down_with_speakers_by_the_cloud_model(
    data_dir,  # noqa: F811
    tmp_path,
):
    from wasifyai_meetings.store import MeetingStore

    with TestClient(create_app()) as c:
        services = c.app.state.services  # type: ignore[attr-defined]
        storage = FakeStorage()
        services.meetings_web = runtime.WebMeetings(tmp_path / "work", storage)
        services.meetings_store = MeetingStore.in_folder(tmp_path / "rows")
        # a model on this machine is not one the web may use
        services.audio = FakeSpeech()
        status = c.get(f"{PRODUCT}/status", headers=auth()).json()
        assert status["hosted"] and not status["speech"]
        assert status["speech_problem"] == runtime.WEB_NO_CLOUD

        cloud = FakeCloudSpeech()
        services.audio = cloud
        row = _make(c)
        assert cloud.asked[0]["diarize"] is True
        assert [s["default"] for s in row["speakers"]] == ["Speaker 1", "Speaker 2"]
        said = [(ln["speaker"], ln["text"]) for ln in row["lines"]]
        assert said[0][0] == said[-1][0] != said[1][0]
        # the recording is in storage, not left in the scratch folder
        assert len(storage.kept) == 1
        link = c.get(f"{PRODUCT}/meetings/{row['id']}/audio-link", headers=auth()).json()
        assert link["url"].startswith("https://storage.test/")
        assert not (tmp_path / "work" / "work" / row["id"]).exists()
        assert c.delete(f"{PRODUCT}/meetings/{row['id']}", headers=auth()).status_code == 204
        assert storage.kept == {}


def test_turns_follow_who_said_each_word():
    w = TranscriptSegment
    words = [w(0, 1, "a", "B"), w(1.2, 2, "b", "B"), w(2.1, 3, "c", "A"), w(6, 7, "d", "A"),
             w(7.1, 8, "e", None)]  # fmt: skip
    turns = runtime.turns_of(words)
    # numbered as they first speak; a long pause starts a new turn; a word with no one is left out
    assert [(t.start, t.end, t.speaker) for t in turns] == [(0, 2, 0), (2.1, 3, 1), (6, 7, 1)]
