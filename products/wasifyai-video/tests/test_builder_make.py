"""Making something for a project (ADR-0096 MX6): the products' own actions are stood in for, and
everything of ours around them is real: the checks on the file, the store and the document."""

import asyncio
import io
import threading
import time
import wave
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict
from test_builder import FakeEngine
from video_rig import mp4, png
from wasifyai_platform_sdk import EngineServices, Identity, RouteDeps, ScopedStorage, memory_storage
from wasifyai_platform_sdk.actions import ActionExecutor, ActionRegistry, builtin_actions
from wasifyai_platform_sdk.actions.library import LibraryKind
from wasifyai_platform_sdk.actions.model import (
    Action,
    CallBinding,
    Outcome,
    Readiness,
    need_model,
)
from wasifyai_platform_sdk.actions.testing import FakeActionHost
from wasifyai_platform_sdk.sqlite import create_sqlite_engine
from wasifyai_video.actions import actions, library_kinds
from wasifyai_video.builder import make, media, templates
from wasifyai_video.routes import build_routes

BASE = "/products/wasifyai-video/builder"
ME = Identity("t1", "u1")
WORDS = "Mornings are hard. We steep Northbean for eighteen hours, never rushed."
HEARD = [
    {"start": 0.5, "end": 1.5, "text": "Mornings are hard."},
    {"start": 2.0, "end": 6.0, "text": "We steep north bean for 18 hours, never rushed."},
]


def a_wav(seconds: float = 6.5) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x10\x20" * int(8000 * seconds))
    return out.getvalue()


class Anything(BaseModel):
    model_config = ConfigDict(extra="allow")


class Models:
    """The products, as far as this needs them: what they were asked and what they do about it."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, dict]] = []
        self.refuse: dict[str, Outcome] = {}
        self.segments = HEARD
        self.gate = None  # held by a test to keep a make running

    def action(self, action_id: str, key: str) -> Action:
        async def run(p: Anything, ctx: Any) -> Outcome:
            self.asked.append((action_id, p.model_dump()))
            while self.gate is not None and not self.gate.is_set():  # noqa: ASYNC110 (from a thread)
                await asyncio.sleep(0.01)
            if action_id in self.refuse:
                return self.refuse[action_id]
            if action_id == "speech.transcribe":
                return Outcome.ok({"segments": self.segments}, "heard")
            return Outcome.ok({key: "m1"}, "made")

        return Action(
            id=action_id, title=action_id, summary=action_id, description=action_id,
            input=Anything, output=Anything, effect="make", flags=("costly",),
            requires=(need_model(action_id),), bind=CallBinding(run), ui="motion",
        )  # fmt: skip


def a_kind(kind: str, data: bytes | None) -> LibraryKind:
    async def none(*_: Any) -> Any:
        return None

    async def read(_: Any, item: str) -> bytes | None:
        return data if item == "m1" else None

    return LibraryKind(kind, "x", kind, none, none, none, read=read)


class MakeRig:
    def __init__(self, tmp_path: Path, engine: Any, picture: bytes | None = None):
        self.models = Models()
        self.state = EngineServices(
            engine=engine, storage=ScopedStorage(memory_storage()), desktop_dir=tmp_path,
            video_builder=FakeEngine(tmp_path),
        )  # fmt: skip
        self.host = FakeActionHost(RouteDeps(self.state, lambda: ME))
        m = self.models
        self.ex = ActionExecutor(
            ActionRegistry([
                *builtin_actions(), *(a for a in actions() if a.id != "video.generate"),
                m.action("image.generate", "image_id"),
                m.action("video.generate", "video_id"), m.action("speech.speak", "speech_id"),
                m.action("music.generate", "track_id"), m.action("speech.transcribe", "x"),
            ]),
            self.host,
            library={
                **{k.kind: k for k in library_kinds()},
                "image": a_kind("image", png((64, 48)) if picture is None else picture),
                "video": a_kind("video", mp4()),
                "speech": a_kind("speech", a_wav()),
                "track": a_kind("track", a_wav(30)),
            },
        )  # fmt: skip
        self.state.actions = self.ex

    def not_installed(self, action_id: str) -> None:
        self.host.not_ready(need_model(action_id), Readiness.needs_setup("Install it in Models."))

    async def go(self, action_id: str, params: dict, origin="window", **kw):
        return await self.ex.run_action(action_id, params, origin, actor=ME, **kw)

    async def project(self) -> tuple[str, str]:
        made = await self.go(
            "motion.write_scenes",
            {"name": "Beans", "scenes": [{"kind": "title", "fields": {"title": "Hello"}}]},
        )
        assert made.status == "ok", made.text
        cid = made.output["composition_id"]
        return cid, (await self.document(cid))["scenes"][0]["id"]

    async def document(self, cid: str) -> dict[str, Any]:
        store = self.state.builder_store
        return (await asyncio.to_thread(store.get_composition, "t1", "u1", cid))["slots"]

    async def kept(self, cid: str, asset: dict[str, Any]) -> int:
        who = ("t1", "wasifyai-video", "u1")
        return await self.state.storage.size_for(who, media.rel_path(cid, asset["file"]))


@pytest.fixture
async def mrig(tmp_path):
    engine = create_sqlite_engine(tmp_path / "wasifyai.db")
    yield MakeRig(tmp_path, engine)
    await engine.dispose()


async def test_a_picture_is_made_by_the_image_product_and_becomes_a_file_of_the_project(mrig):
    cid, _ = await mrig.project()
    done = await mrig.go(
        "motion.make_file", {"composition_id": cid, "what": "picture", "text": "A red can"},
        person_approved=True,
    )  # fmt: skip
    assert done.status == "ok", done.text
    assert mrig.models.asked == [("image.generate", {"prompt": "A red can", "size": "landscape"})]
    asset = done.output["asset"]
    assert asset["kind"] == "image" and asset["name"].startswith("A red can")
    document = await mrig.document(cid)
    assert document["assets"] == [asset] and document["scenes"][0].get("background") is None
    assert await mrig.kept(cid, asset) > 0


@pytest.mark.parametrize(
    ("what", "action", "asked"),
    [
        ("clip", "video.generate", {"prompt": "Pouring", "shape": "landscape", "seconds": 5}),
        ("music", "music.generate", {"description": "Pouring", "instrumental": True, "seconds": 5}),
        ("speech", "speech.speak", {"text": "Pouring"}),
    ],
)
async def test_each_kind_goes_to_its_own_product(mrig, what, action, asked):
    cid, _ = await mrig.project()
    done = await mrig.go(
        "motion.make_file", {"composition_id": cid, "what": what, "text": "Pouring", "seconds": 5},
        person_approved=True,
    )  # fmt: skip
    assert done.status == "ok", done.text
    assert mrig.models.asked[0] == (action, asked)
    assert done.output["asset"]["kind"] == ("video" if what == "clip" else "audio")


async def test_the_person_is_asked_first_and_once(mrig):
    cid, _ = await mrig.project()
    asked = await mrig.go(
        "motion.make_file", {"composition_id": cid, "what": "picture", "text": "A can"},
        origin="assistant",
    )  # fmt: skip
    assert asked.status == "needs_approval" and mrig.models.asked == []


async def test_a_voiceover_lands_on_its_scene_with_the_typed_words_timed_by_the_speech(mrig):
    cid, sid = await mrig.project()
    done = await mrig.go(
        "motion.make_file",
        {"composition_id": cid, "what": "speech", "text": WORDS, "use": "sound", "scene_id": sid,
         "captions": True, "voice": "v1"},
        person_approved=True,
    )  # fmt: skip
    assert done.status == "ok", done.text
    assert mrig.models.asked[0] == ("speech.speak", {"text": WORDS, "saved_voice": "v1"})
    scene = (await mrig.document(cid))["scenes"][0]
    assert scene["sound"]["asset"] == done.output["asset"]["id"]
    # the model heard "north bean" and "18": what shows is what the person typed
    assert " ".join(c["text"] for c in scene["cues"]) == WORDS
    first = scene["cues"][0]
    assert first["text"] == "Mornings are hard." and first["start"] == 0.5
    assert 1.5 <= first["end"] <= 2.3  # about where that stretch of speech ends
    assert scene["cues"][-1]["end"] == 6.0
    assert scene["fields"]["seconds"] >= 6.5  # the scene is long enough to say it


async def test_a_scene_grows_only_as_far_as_its_kind_can_go(mrig):
    cid, sid = await mrig.project()
    mrig.ex.library["speech"] = a_kind("speech", a_wav(100))
    done = await mrig.go(
        "motion.make_file",
        {"composition_id": cid, "what": "speech", "text": "Hi", "use": "sound", "scene_id": sid},
        person_approved=True,
    )  # fmt: skip
    assert done.status == "ok", done.text
    scene = (await mrig.document(cid))["scenes"][0]
    assert scene["fields"]["seconds"] == 90 and scene["sound"]


async def test_captions_are_still_timed_where_no_speech_to_text_is_installed(mrig):
    cid, sid = await mrig.project()
    mrig.not_installed("speech.transcribe")
    done = await mrig.go(
        "motion.make_file",
        {"composition_id": cid, "what": "speech", "text": WORDS, "captions": True},
        person_approved=True,
    )  # fmt: skip
    assert done.status == "ok", done.text
    cues = done.output["cues"]
    assert " ".join(c["text"] for c in cues) == WORDS
    assert cues[0]["start"] == 0 and cues[-1]["end"] == pytest.approx(6.5, abs=0.05)


@pytest.mark.parametrize(
    ("what", "use", "where"),
    [("picture", "background", "background"), ("picture", "place", "images")],
)
async def test_a_picture_goes_where_it_was_asked_for(mrig, what, use, where):
    cid, sid = await mrig.project()
    done = await mrig.go(
        "motion.make_file",
        {"composition_id": cid, "what": what, "text": "A can", "use": use, "scene_id": sid},
        person_approved=True,
    )  # fmt: skip
    assert done.status == "ok", done.text
    scene = (await mrig.document(cid))["scenes"][0]
    found = scene[where]
    assert (found if where == "background" else found[0])["asset"] == done.output["asset"]["id"]


async def test_music_becomes_the_soundtrack_and_one_undo_takes_it_off_keeping_the_file(mrig):
    cid, _ = await mrig.project()
    done = await mrig.go(
        "motion.make_file",
        {"composition_id": cid, "what": "music", "text": "Warm guitar", "use": "soundtrack"},
        person_approved=True,
    )  # fmt: skip
    assert done.status == "ok", done.text
    document = await mrig.document(cid)
    assert document["soundtrack"]["asset"] == done.output["asset"]["id"]
    await mrig.go("motion.undo", {"composition_id": cid})
    document = await mrig.document(cid)
    assert document.get("soundtrack") is None and len(document["assets"]) == 1


async def test_what_cannot_be_made_is_said_and_nothing_is_added(mrig):
    cid, _ = await mrig.project()
    mrig.not_installed("speech.speak")
    mrig.models.refuse["image.generate"] = Outcome.refused("The picture model is busy.", "busy")
    setup = await mrig.go(
        "motion.make_file", {"composition_id": cid, "what": "speech", "text": "Hi"},
        person_approved=True,
    )  # fmt: skip
    assert setup.status == "refused" and "Install it" in setup.text
    busy = await mrig.go(
        "motion.make_file", {"composition_id": cid, "what": "picture", "text": "Hi"},
        person_approved=True,
    )  # fmt: skip
    assert busy.status == "refused" and busy.text == "The picture model is busy."
    assert busy.code == "busy" and not (await mrig.document(cid)).get("assets")


async def test_a_file_that_fails_the_checks_is_not_kept(tmp_path):
    engine = create_sqlite_engine(tmp_path / "wasifyai.db")
    rig = MakeRig(tmp_path, engine, picture=b"not a picture")
    cid, _ = await rig.project()
    done = await rig.go(
        "motion.make_file", {"composition_id": cid, "what": "picture", "text": "A can"},
        person_approved=True,
    )  # fmt: skip
    assert done.status == "error" and "Library" not in done.text
    assert not (await rig.document(cid)).get("assets")
    await engine.dispose()


async def test_only_a_project_of_your_own_gets_a_file(mrig):
    missing = await mrig.go(
        "motion.make_file", {"composition_id": "0" * 32, "what": "picture", "text": "A can"},
        person_approved=True,
    )  # fmt: skip
    assert missing.status == "refused" and mrig.models.asked == []


async def test_a_scene_is_needed_when_it_goes_on_one(mrig):
    cid, _ = await mrig.project()
    none = await mrig.go(
        "motion.make_file",
        {"composition_id": cid, "what": "picture", "text": "A can", "use": "background"},
        person_approved=True,
    )  # fmt: skip
    assert none.status == "refused" and mrig.models.asked == []


# ---- the words, in time --------------------------------------------------------------------------


def test_lines_end_at_a_stop_or_after_a_few_words_and_no_word_is_changed():
    lines = make.timed_lines("One two three four five six seven. Eight, nine", [], 9.0)
    assert [c["text"] for c in lines] == ["One two three four five six", "seven.", "Eight, nine"]


def test_times_come_from_what_was_heard_and_only_grow():
    lines = make.timed_lines(WORDS, HEARD, 6.5)
    assert all(a["end"] <= b["start"] + 0.01 for a, b in zip(lines, lines[1:], strict=False))
    assert all(c["end"] > c["start"] for c in lines)


def test_nothing_to_say_has_no_lines():
    assert make.timed_lines("   ", HEARD, 4) == [] and make.timed_lines("Hi", [], 0) == []


def test_a_stretch_with_nothing_in_it_is_not_a_clock():
    out = make.timed_lines(
        "Hi there", [{"start": 1, "end": 1, "text": "x"}, {"start": 2, "end": 3, "text": ""}], 4
    )
    assert out == [{"text": "Hi there", "start": 0.0, "end": 4.0}]


# ---- from the window -----------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path):
    engine = create_sqlite_engine(tmp_path / "wasifyai.db")
    rig = MakeRig(tmp_path, engine)
    app = FastAPI()
    app.state.services = rig.state
    app.include_router(
        build_routes(RouteDeps(rig.state, lambda: ME)), prefix="/products/wasifyai-video"
    )
    with TestClient(app) as c:
        c.rig = rig  # type: ignore[attr-defined]
        yield c
    asyncio.run(engine.dispose())


def a_film(client) -> str:
    made = client.post(
        f"{BASE}/projects",
        json={
            "template": templates.SCENES,
            "slots": {"scenes": [{"kind": "title", "fields": {"title": "Hi"}}]},
        },
    )
    assert made.status_code == 201, made.text
    return made.json()["id"]


def test_the_window_makes_without_being_asked_again_and_places_the_file_itself(client):
    cid = a_film(client)
    r = client.post(
        f"{BASE}/projects/{cid}/make",
        json={"what": "speech", "text": WORDS, "captions": True, "use": "sound"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    if body["state"] == "working":
        for _ in range(100):
            body = client.get(f"{BASE}/make-jobs/{body['job_id']}").json()
            if body["state"] != "working":
                break
    assert body["state"] == "done" and body["asset"]["kind"] == "audio" and body["cues"]
    slots = client.get(f"{BASE}/projects/{cid}").json()["slots"]
    # the file is listed, and where it goes is the window's to say, in its own next save
    assert slots["assets"] == [body["asset"]] and slots["scenes"][0].get("sound") is None


def test_the_window_is_told_why_not_in_words(client):
    cid = a_film(client)
    client.rig.not_installed("image.generate")
    r = client.post(f"{BASE}/projects/{cid}/make", json={"what": "picture", "text": "A can"})
    if r.status_code == 200 and r.json()["state"] == "working":
        for _ in range(100):
            r = client.get(f"{BASE}/make-jobs/{r.json()['job_id']}")
            if r.status_code != 200 or r.json()["state"] != "working":
                break
    assert r.status_code == 422 and "Install it" in r.json()["detail"]["message"]


def test_a_long_make_is_followed_and_can_be_stopped(client):
    cid = a_film(client)
    client.rig.models.gate = threading.Event()
    started = client.post(f"{BASE}/projects/{cid}/make", json={"what": "picture", "text": "A can"})
    assert started.status_code == 200, started.text
    job = started.json()
    assert job["state"] == "working"
    assert client.get(f"{BASE}/make-jobs/{job['job_id']}").json()["state"] == "working"
    client.rig.models.gate.set()
    for _ in range(300):
        done = client.get(f"{BASE}/make-jobs/{job['job_id']}").json()
        if done["state"] != "working":
            break
        time.sleep(0.01)
    assert done["state"] == "done" and done["asset"]["kind"] == "image"

    client.rig.models.gate = threading.Event()
    second = client.post(
        f"{BASE}/projects/{cid}/make", json={"what": "picture", "text": "B"}
    ).json()
    assert client.post(f"{BASE}/make-jobs/{second['job_id']}/cancel").json() == {"state": "stopped"}
    for _ in range(300):
        stopped = client.get(f"{BASE}/make-jobs/{second['job_id']}")
        if stopped.status_code != 200 or stopped.json()["state"] != "working":
            break
        time.sleep(0.01)
    assert stopped.status_code == 422
    assert len(client.get(f"{BASE}/projects/{cid}").json()["slots"]["assets"]) == 1


def test_another_persons_project_is_not_found(client):
    r = client.post(f"{BASE}/projects/{'0' * 32}/make", json={"what": "picture", "text": "A can"})
    assert r.status_code == 404
    assert client.get(f"{BASE}/make-jobs/nope").status_code == 404
