# ruff: noqa: E501  (prose and test data are easier to read on one line)
"""The Shots step (ADR-0090 CS2): what a still is asked for, the job that makes them, kill and resume, and the preview. The preview
here is a real ffmpeg join; only the picture model is a stand-in."""

import asyncio
import io
import json
import sqlite3
import struct
import subprocess
import time
import wave
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import imageio_ffmpeg
import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from PIL import Image
from wasifyai_creative import stills
from wasifyai_creative.cut import camera_filter
from wasifyai_creative.routes import build_routes
from wasifyai_creative.runtime import store_for
from wasifyai_creative.store import CreativeStore
from wasifyai_platform_sdk import EngineServices, Identity, RouteDeps
from wasifyai_platform_sdk.storage import LocalFileStorage, ScopedStorage

BASE = "/products/wasifyai-creative/creative"
ME = Identity("t1", "u1")


OPEN: list[TestClient] = []


@pytest.fixture(autouse=True)
def close_clients() -> Iterator[None]:
    yield
    while OPEN:
        OPEN.pop().__exit__(None, None, None)


def shot(n: int, start: float, end: float, **over: Any) -> dict[str, Any]:
    return {
        "id": f"s{n}", "start": start, "end": end, "beat": "", "shows": f"Mira walks down the road, moment {n}.", "who": ["Mira"],
        "place": "city street", "camera": "wide", "line": None, "note": "", "motion": "Hold", "fallback": False, **over,
    }  # fmt: skip


BRIEF: dict[str, Any] = {
    "track_id": "song", "idea": "A walk", "style": "warm film photo", "shape": "landscape", "places": ["city street"],
    "cast": [{"name": "Mira", "look": "short dark hair, green jacket", "photos_only": False, "pictures": ["a" * 32, "b" * 32]}],
    "fixed": [],
}  # fmt: skip


def png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (1344, 768), (90, 120, 200)).save(out, "PNG")
    return out.getvalue()


def song(seconds: float = 3.0) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(struct.pack("<h", 0) * int(8000 * seconds))
    return out.getvalue()


class Pictures:
    """The image product: `hold` keeps a call waiting, so a run can be caught half way, and `fail` lists the calls that go wrong."""

    def __init__(self, fail: set[int] | None = None, setup: str | None = None):
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail = fail or set()
        self.setup = setup
        self.hold: asyncio.Event | None = None
        self.reached = 0
        self.deleted: list[str] = []
        self.registry = SimpleNamespace(get=lambda _: object())

        async def read_image(_ctx: Any, _id: str) -> bytes:
            return png()

        async def read_song(_ctx: Any, _id: str) -> bytes:
            return song()

        async def delete(_ctx: Any, item: str) -> None:
            self.deleted.append(item)

        self.library = {
            "image": SimpleNamespace(read=read_image, delete=delete),
            "track": SimpleNamespace(read=read_song, delete=delete),
        }

    async def readiness(self, _action: Any) -> Any:
        if self.setup:
            return SimpleNamespace(state="needs_setup", step=self.setup, reason="")
        return SimpleNamespace(state="ready", step="", reason="")

    async def run_action(
        self,
        action: str,
        params: dict[str, Any],
        _origin: str,
        *,
        actor: Any,
        person_approved: bool = False,
    ) -> Any:
        assert person_approved
        self.calls.append((action, params))
        number = len(self.calls)
        self.reached = number
        if self.hold is not None and number >= 3:
            await self.hold.wait()
        if number in self.fail:
            return SimpleNamespace(
                status="error", output={}, text="The picture model stopped.", code="failed"
            )
        return SimpleNamespace(
            status="ok", output={"image_id": f"{number:032d}"}, text="", code=None
        )


def setup(
    tmp_path: Path, pictures: Pictures, count: int = 4, brief: dict[str, Any] | None = None
) -> tuple[EngineServices, TestClient, str]:
    state = EngineServices()
    state.desktop_dir = tmp_path  # type: ignore[assignment]
    state.actions = pictures  # type: ignore[assignment]
    state.storage = ScopedStorage(LocalFileStorage(tmp_path / "files", "http://x", "secret"))  # type: ignore[assignment]

    async def nothing(*_: Any) -> None:
        return None

    state.creation_index = SimpleNamespace(index=nothing, remove=nothing)
    state.caps = {}
    app = FastAPI()

    def who(x_user: str = Header("u1")) -> Identity:
        return Identity("t1", x_user)

    app.include_router(build_routes(RouteDeps(state, who)), prefix="/products/wasifyai-creative")
    store = store_for(state)
    row = store.add("t1", "u1", "A walk", brief or BRIEF)
    store.set_facts(row["id"], {"seconds": float(count)})
    store.save_plan(
        row["id"],
        {"shots": [shot(i + 1, float(i), float(i + 1)) for i in range(count)]},
        "the plan",
    )
    c = TestClient(app)
    c.__enter__()  # the runs are tasks, so the loop has to last from one request to the next
    OPEN.append(c)
    return state, c, row["id"]


def wait_run(c: TestClient, item: str, seconds: float = 30.0) -> dict[str, Any]:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        row = c.get(f"{BASE}/projects/{item}").json()
        if not row["shots_live"]:
            return row
        time.sleep(0.02)
    raise AssertionError("the run did not finish")


def test_a_database_from_before_the_stills_is_brought_up_to_date(tmp_path: Path):
    folder = tmp_path / "old"
    folder.mkdir()
    db = sqlite3.connect(folder / "creative.db")
    db.executescript(
        "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL); INSERT INTO meta VALUES ('schema', '1');"
        "CREATE TABLE media(project_id TEXT NOT NULL, kind TEXT NOT NULL, item_id TEXT NOT NULL, shot_id TEXT,"
        " created_at TEXT NOT NULL, PRIMARY KEY (project_id, kind, item_id));"
        "INSERT INTO media VALUES ('p', 'image', 'i', NULL, 'then');"
    )
    db.close()
    store = CreativeStore.in_folder(folder)
    assert store.media_of("p")[0]["made"] == 0
    store.close()
    CreativeStore.in_folder(folder).close()  # and a second opening leaves it alone


# ---- what a still is asked for ----------------------------------------------------------------


def test_a_shot_with_a_person_asks_from_their_two_pictures_and_repeats_their_look():
    found = stills.still_for(shot(1, 0, 1), BRIEF, stills.REFERENCE)
    assert found.action == "image.reference"
    assert found.params["image_ids"] == ["a" * 32, "b" * 32]
    assert found.params["size"] == "wide"
    assert (
        "short dark hair" in found.prompt
        and "Place: city street." in found.prompt
        and "Wide shot." in found.prompt
    )


def test_two_people_use_one_picture_each_and_one_picture_is_used_twice():
    two = {
        **BRIEF,
        "cast": [*BRIEF["cast"], {"name": "Tom", "look": "grey coat", "pictures": ["c" * 32]}],
    }
    found = stills.still_for(shot(1, 0, 1, who=["Mira", "Tom"]), two, stills.REFERENCE)
    assert found.params["image_ids"] == ["a" * 32, "c" * 32]
    assert "Mira is the person in picture 1 and Tom the person in picture 2." in found.prompt
    one = {**BRIEF, "cast": [{"name": "Mira", "look": "x", "pictures": ["a" * 32]}]}
    assert stills.still_for(shot(1, 0, 1), one, stills.REFERENCE).params["image_ids"] == [
        "a" * 32,
        "a" * 32,
    ]


def test_plain_and_a_shot_with_nobody_do_not_use_pictures():
    assert stills.still_for(shot(1, 0, 1), BRIEF, stills.PLAIN).action == "image.generate"
    empty = stills.still_for(shot(1, 0, 1, who=[], shows="An empty road."), BRIEF, stills.REFERENCE)
    assert empty.action == "image.generate" and empty.mode == stills.PLAIN


def test_someone_seen_only_in_photos_is_never_drawn_as_present():
    brief = {
        **BRIEF,
        "cast": [*BRIEF["cast"], {"name": "Sam", "look": "tall with a beard", "photos_only": True}],
    }
    found = stills.still_for(
        shot(1, 0, 1, shows="Mira holds a picture of Sam."), brief, stills.REFERENCE
    )
    assert (
        "Sam" not in found.prompt
        and "Mira holds a picture of someone." in found.prompt
        and "beard" not in found.prompt
    )
    other = stills.still_for(shot(1, 0, 1, shows="Sam waves."), brief, stills.REFERENCE)
    assert other.prompt.startswith("someone in a photograph waves.")
    assert stills.needs_portraits({"shots": [shot(1, 0, 1, who=["Sam"])]}, brief) == []


def test_a_person_named_in_the_sentence_counts_though_who_is_empty():
    for words in ("Mira's face is pale.", "Miras face is pale.", "Mira walks."):
        found = stills.still_for(shot(1, 0, 1, who=[], shows=words), BRIEF, stills.REFERENCE)
        assert found.action == "image.reference", words
        assert "short dark hair" in found.prompt


def test_fixed_words_come_with_the_thing_they_name():
    brief = {
        **BRIEF,
        "fixed": [
            {"name": "car", "words": "old red estate car"},
            {"name": "barn", "words": "white barn"},
        ],
    }
    found = stills.still_for(shot(1, 0, 1, shows="Mira drives the car."), brief, stills.PLAIN)
    assert "old red estate car" in found.prompt and "white barn" not in found.prompt


def test_a_prompt_stays_under_the_image_products_limit_and_keeps_what_the_shot_shows():
    long = {
        **BRIEF,
        "style": "s" * 400,
        "cast": [{"name": "Mira", "look": "l" * 300, "pictures": []}],
    }
    found = stills.still_for(shot(1, 0, 1, shows="Mira runs. " * 30), long, stills.PLAIN)
    assert len(found.prompt) <= stills.MAX_PROMPT
    assert found.prompt.startswith("Mira runs.")


def test_a_still_goes_out_of_date_when_what_it_depends_on_changes_and_not_otherwise():
    base = stills.inputs_of(shot(1, 0, 1), BRIEF)
    assert stills.inputs_of(shot(1, 5, 9, note="x", motion="Sing"), BRIEF) == base
    assert stills.inputs_of(shot(1, 0, 1, camera="close"), BRIEF) != base
    assert stills.inputs_of(shot(1, 0, 1), {**BRIEF, "style": "ink"}) != base
    changed = {**BRIEF, "cast": [{**BRIEF["cast"][0], "look": "long red hair"}]}
    assert stills.inputs_of(shot(1, 0, 1), changed) != base


def test_the_estimate_is_a_range_corrected_by_what_was_measured_and_says_when_it_will_not_fit():
    first = stills.estimate(48, 0, stills.REFERENCE, None, 180.0, 100 * 2**30)
    assert (
        first["seconds_low"] == 48 * 34
        and first["seconds_high"] == 48 * 42
        and first["fit"] == "fits"
    )
    assert first["measured"] is False
    fast = stills.estimate(48, 0, stills.REFERENCE, 20.0, 180.0, 100 * 2**30)
    assert fast["seconds_high"] < first["seconds_low"] and fast["measured"] is True
    assert stills.estimate(48, 0, stills.PLAIN, None, 180.0, 2**30 + 10)["fit"] == "too_big"
    assert stills.estimate(48, 0, stills.PLAIN, None, 180.0, 2 * 2**30)["fit"] == "tight"


# ---- the job ----------------------------------------------------------------------------------


def test_the_job_makes_a_still_per_shot_and_saves_each_as_a_chosen_take_of_the_library(
    tmp_path: Path,
):
    pictures = Pictures()
    state, c, item = setup(tmp_path, pictures)
    assert c.post(f"{BASE}/projects/{item}/shots", json={}).status_code == 202
    row = wait_run(c, item)
    assert row["shots"]["run"]["status"] == "done" and row["shots"]["run"]["finished"] == 4
    assert row["shots"]["missing"] == [] and len(pictures.calls) == 4
    for takes in row["shots"]["takes"].values():
        assert len(takes) == 1 and takes[0]["chosen"] and takes[0]["seconds"] is not None
    media = store_for(state).media_of(item)
    assert {m["shot_id"] for m in media} == {"s1", "s2", "s3", "s4"} and all(
        m["made"] for m in media
    )


def test_a_person_with_words_and_no_pictures_gets_two_first_and_every_shot_starts_from_them(
    tmp_path: Path,
):
    pictures = Pictures()
    brief = {**BRIEF, "cast": [{"name": "Mira", "look": "short dark hair"}]}
    state, c, item = setup(tmp_path, pictures, 2, brief)
    c.post(f"{BASE}/projects/{item}/shots", json={})
    row = wait_run(c, item)
    assert [a for a, _ in pictures.calls] == [
        "image.generate",
        "image.generate",
        "image.reference",
        "image.reference",
    ]
    assert pictures.calls[2][1]["image_ids"] == [f"{1:032d}", f"{2:032d}"]
    assert row["brief"]["cast"][0]["pictures"] == [f"{1:032d}", f"{2:032d}"]
    kept = store_for(state).characters("t1", "u1")
    assert kept[0]["name"] == "Mira" and kept[0]["pictures"] == [f"{1:032d}", f"{2:032d}"]


def test_a_kill_half_way_makes_only_the_missing_shots_when_it_goes_on(tmp_path: Path):
    """A real kill leaves `running` in the database with no task; the next open calls it interrupted."""
    pictures = Pictures()
    state, c, item = setup(tmp_path, pictures)
    store = store_for(state)
    row = store.get("t1", "u1", item)
    shots = row["plan"]["shots"]
    store.add_take(
        item,
        "s1",
        "image",
        "1" * 32,
        stills.inputs_of(shots[0], BRIEF),
        "p",
        "reference",
        1.0,
        1,
        choose=False,
    )
    store.add_take(
        item,
        "s2",
        "image",
        "2" * 32,
        stills.inputs_of(shots[1], BRIEF),
        "p",
        "reference",
        1.0,
        1,
        choose=False,
    )
    store.begin_run(item, "stills", "Making the still of shot 3", 4)
    store.close()
    reopened = CreativeStore.in_folder(tmp_path / "creative")
    assert (reopened.run_of(item) or {})["status"] == "interrupted"
    reopened.close()
    state.creative_store = None  # type: ignore[attr-defined]
    assert c.get(f"{BASE}/projects/{item}").json()["shots"]["missing"] == ["s3", "s4"]
    assert c.post(f"{BASE}/projects/{item}/shots", json={}).status_code == 202
    after = wait_run(c, item)
    assert (
        len(pictures.calls) == 2
        and after["shots"]["missing"] == []
        and after["shots"]["run"]["status"] == "done"
    )


def test_stopping_keeps_what_is_made_and_going_on_makes_the_rest(tmp_path: Path):
    pictures = Pictures()
    pictures.hold = asyncio.Event()
    _state, c, item = setup(tmp_path, pictures)
    c.post(f"{BASE}/projects/{item}/shots", json={})
    end = time.monotonic() + 10
    while pictures.reached < 3 and time.monotonic() < end:
        time.sleep(0.01)
    row = c.post(f"{BASE}/projects/{item}/shots/stop").json()
    assert row["shots"]["run"]["status"] == "stopped"
    assert row["shots"]["missing"] == ["s3", "s4"]
    pictures.hold = None
    c.post(f"{BASE}/projects/{item}/shots", json={})
    assert wait_run(c, item)["shots"]["missing"] == []


def test_one_failure_goes_on_and_says_so_and_three_in_a_row_stop_the_run(tmp_path: Path):
    pictures = Pictures(fail={2})
    _s, c, item = setup(tmp_path, pictures)
    c.post(f"{BASE}/projects/{item}/shots", json={})
    row = wait_run(c, item)
    assert (
        row["shots"]["run"]["status"] == "failed"
        and "1 could not be made" in row["shots"]["run"]["error"]
    )
    assert row["shots"]["missing"] == ["s2"]
    many = Pictures(fail={1, 2, 3})
    _s, c, other = setup(tmp_path / "b", many, 6)
    c.post(f"{BASE}/projects/{other}/shots", json={})
    row = wait_run(c, other)
    assert len(many.calls) == 3 and "The picture model stopped." in row["shots"]["run"]["error"]


def test_no_picture_model_or_no_room_or_nothing_to_do_is_refused_in_words(
    tmp_path: Path, monkeypatch: Any
):
    _s, c, item = setup(tmp_path, Pictures(setup="Choose a picture model first."))
    r = c.post(f"{BASE}/projects/{item}/shots", json={})
    assert r.status_code == 409 and "Choose a picture model first." in r.text
    assert c.get(f"{BASE}/projects/{item}/shots/estimate").json()["ready"] is False

    monkeypatch.setattr("wasifyai_creative.shots.free_bytes", lambda _: 1000)
    _s, c, item = setup(tmp_path / "b", Pictures())
    assert c.get(f"{BASE}/projects/{item}/shots/estimate").json()["fit"] == "too_big"
    assert c.post(f"{BASE}/projects/{item}/shots", json={}).status_code == 409
    monkeypatch.undo()

    _s, c, item = setup(tmp_path / "c", Pictures())
    c.post(f"{BASE}/projects/{item}/shots", json={})
    wait_run(c, item)
    r = c.post(f"{BASE}/projects/{item}/shots", json={})
    assert r.status_code == 409 and "Every shot has its still." in r.text


def test_redo_keeps_the_old_take_chooses_the_new_and_a_take_can_be_chosen_back(tmp_path: Path):
    pictures = Pictures()
    _s, c, item = setup(tmp_path, pictures, 2)
    c.post(f"{BASE}/projects/{item}/shots", json={})
    wait_run(c, item)
    assert c.post(f"{BASE}/projects/{item}/shots/s1/redo", json={}).status_code == 202
    takes = wait_run(c, item)["shots"]["takes"]["s1"]
    assert [t["chosen"] for t in takes] == [False, True]
    back = c.put(f"{BASE}/projects/{item}/shots/s1/chosen", json={"take_id": takes[0]["id"]}).json()
    assert [t["chosen"] for t in back["shots"]["takes"]["s1"]] == [True, False]
    assert (
        c.put(
            f"{BASE}/projects/{item}/shots/s2/chosen", json={"take_id": takes[0]["id"]}
        ).status_code
        == 404
    )


def test_changing_a_shot_marks_its_still_out_of_date_and_it_is_made_again_only_when_asked(
    tmp_path: Path,
):
    pictures = Pictures()
    state, c, item = setup(tmp_path, pictures, 2)
    c.post(f"{BASE}/projects/{item}/shots", json={})
    wait_run(c, item)
    store = store_for(state)
    plan = store.get("t1", "u1", item)["plan"]
    plan["shots"][0]["shows"] = "Mira sits on a bench."
    store.save_plan(item, plan, "a change")
    row = c.get(f"{BASE}/projects/{item}").json()
    assert row["shots"]["out_of_date"] == ["s1"] and row["shots"]["takes"]["s1"][0]["out_of_date"]
    assert c.post(f"{BASE}/projects/{item}/shots", json={}).status_code == 409
    assert (
        c.post(f"{BASE}/projects/{item}/shots", json={"redo_out_of_date": True}).status_code == 202
    )
    assert wait_run(c, item)["shots"]["out_of_date"] == [] and len(pictures.calls) == 3


def test_deleting_a_project_can_delete_what_was_made_for_it_or_leave_it(tmp_path: Path):
    pictures = Pictures()
    _s, c, item = setup(tmp_path, pictures, 2)
    c.post(f"{BASE}/projects/{item}/shots", json={})
    wait_run(c, item)
    c.delete(f"{BASE}/projects/{item}")
    assert pictures.deleted == []
    pictures = Pictures()
    _s, c, item = setup(tmp_path / "b", pictures, 2)
    c.post(f"{BASE}/projects/{item}/shots", json={})
    wait_run(c, item)
    c.delete(f"{BASE}/projects/{item}", params={"with_media": True})
    assert sorted(pictures.deleted) == [f"{1:032d}", f"{2:032d}"]


# ---- the preview ------------------------------------------------------------------------------


def probe(path: Path) -> str:
    done = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
    )
    return done.stderr


def test_the_preview_is_a_real_video_as_long_as_the_plan_over_the_song_and_counts_black_shots(
    tmp_path: Path,
):
    pictures = Pictures(fail={2})
    state, c, item = setup(tmp_path, pictures, 3)
    assert c.post(f"{BASE}/projects/{item}/preview").status_code == 409  # nothing to join yet
    c.post(f"{BASE}/projects/{item}/shots", json={})
    wait_run(c, item)
    assert c.post(f"{BASE}/projects/{item}/preview").status_code == 202
    row = wait_run(c, item, 120.0)
    assert row["shots"]["run"]["status"] == "done", row["shots"]["run"]
    preview = row["shots"]["preview"]
    assert preview["empty_shots"] == 1 and preview["seconds"] == 3.0 and preview["current"] is True
    made = store_for(state).preview_of(item)
    file = next((tmp_path / "files").rglob("*.mp4"))
    assert made and file.name == Path(made["rel"]).name
    info = probe(file)
    assert "Duration: 00:00:03.0" in info and "1280x720" in info and "Audio:" in info
    c.post(f"{BASE}/projects/{item}/shots/s1/redo", json={})
    after = wait_run(c, item)
    assert after["shots"]["preview"]["current"] is False, json.dumps(after["shots"]["preview"])


def test_the_camera_words_choose_the_move():
    assert "min(1.0+0.10" in camera_filter("close push in", 24, 1280, 720)
    assert "(iw-iw/zoom)*on/24" in camera_filter("wide pan", 24, 1280, 720)
    still = camera_filter("wide", 24, 1280, 720)
    assert "1.04" in still and "s=1280x720" in still
