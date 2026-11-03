# ruff: noqa: E501  (prose and test data are easier to read on one line)
"""Motion (ADR-0090 CS4): which shots a draft excerpt and Make it better animate, what a clip is asked for, the estimate
corrected by what was measured, and the run that makes clips as takes. Only the picture and video models are stand-ins."""

import asyncio
import time
from pathlib import Path
from typing import Any

from test_shots import BASE, BRIEF, Pictures, setup, shot, wait_run
from wasifyai_creative import motion
from wasifyai_creative.runtime import store_for


class Clips(Pictures):
    """The image and video products: a still answers with an image id, a clip with a video id."""

    async def run_action(self, action: str, params: dict[str, Any], _origin: str, **kw: Any) -> Any:
        done = await super().run_action(action, params, _origin, **kw)
        if action == "video.animate" and done.status == "ok":
            done.output = {"video_id": f"v{len(self.calls):031d}"}
        return done


def stills_then(c: Any, item: str) -> None:
    c.post(f"{BASE}/projects/{item}/shots", json={})
    wait_run(c, item)


def test_the_draft_excerpt_is_whole_shots_from_the_loudest_part_and_reaches_back_near_the_end():
    shots = [shot(n + 1, n * 4.0, n * 4.0 + 4.0) for n in range(20)]  # 80 s of 4 s shots
    sections = [
        {"start": 0.0, "end": 20.0, "energy": 0.1, "label": "low"},
        {"start": 20.0, "end": 50.0, "energy": 0.4, "label": "high"},
        {"start": 50.0, "end": 80.0, "energy": 0.2, "label": "mid"},
    ]
    at = motion.loudest_start(sections)
    assert at == 20.0
    picked = motion.excerpt(shots, at)
    assert picked == [f"s{n}" for n in range(6, 14)]  # 20 s to 52 s: at least 30 s of whole shots
    # from 70 s there are only 10 s left, so it starts earlier and is still about 30 s
    late = motion.excerpt(shots, 70.0)
    assert late[-1] == "s20" and len(late) == 8
    assert motion.loudest_start([]) == 0.0 and motion.excerpt([], 0.0) == []


def test_make_it_better_is_the_shots_the_plan_marks_animate_or_sing():
    shots = [shot(1, 0, 1, motion="Animate"), shot(2, 1, 2), shot(3, 2, 3, motion="Sing")]
    assert motion.better(shots) == ["s1", "s3"]


def test_a_clip_is_asked_for_the_picture_in_words_then_its_move_under_the_limit():
    text = motion.clip_prompt(shot(1, 0, 1, camera="close slow push in", motion="Animate"), BRIEF)
    assert text.startswith("Mira walks down the road") and "short dark hair" in text
    assert text.endswith("Natural, gentle movement. The camera slowly pushes in.")
    long = motion.clip_prompt(shot(2, 0, 1, shows="x " * 400, camera="medium slow pan"), BRIEF)
    assert len(long) <= motion.MAX_PROMPT and long.endswith("The camera pans slowly.")


def test_the_estimate_is_a_range_from_cs0_corrected_by_the_clips_made_here():
    first = motion.estimate(10, motion.DRAFT, None, 100 * 2**30)
    assert (first["seconds_low"], first["seconds_high"], first["measured"]) == (450, 600, False)
    takes = [
        {"kind": "video", "mode": "draft", "seconds": 40.0},
        {"kind": "video", "mode": "final", "seconds": 180.0},
    ]
    seen = motion.measured(takes, motion.DRAFT)
    assert seen == 40.0
    after = motion.estimate(10, motion.DRAFT, seen, 100 * 2**30)
    assert (after["seconds_low"], after["seconds_high"], after["measured"]) == (340, 460, True)
    assert motion.estimate(10, motion.FINAL, None, 1000)["fit"] == "too_big"


def test_a_clip_starts_from_the_chosen_still_or_the_newest_one_when_a_clip_is_chosen():
    takes = [
        {"id": "a", "shot_id": "s1", "kind": "image", "mode": "plain", "inputs": "m"},
        {"id": "b", "shot_id": "s1", "kind": "image", "mode": "plain", "inputs": "m"},
        {"id": "c", "shot_id": "s1", "kind": "video", "mode": "draft", "inputs": "m"},
    ]
    chosen, newest = (
        motion.source_of(takes, {"s1": "a"}, "s1"),
        motion.source_of(takes, {"s1": "c"}, "s1"),
    )
    assert chosen is not None and chosen["id"] == "a"
    assert newest is not None and newest["id"] == "b"
    assert motion.source_of(takes, {}, "s2") is None
    # a draft clip is enough for a draft; a final one is needed for final, and a final one serves a draft too
    assert motion.has_clip(takes, "s1", motion.DRAFT, "m") and not motion.has_clip(
        takes, "s1", motion.FINAL, "m"
    )
    assert not motion.has_clip(takes, "s1", motion.DRAFT, "changed")


def test_a_draft_run_animates_the_excerpt_saves_each_clip_as_the_chosen_take_and_goes_on_after_a_stop(
    tmp_path: Path,
):
    clips = Clips()
    state, c, item = setup(
        tmp_path, clips, count=40
    )  # 40 shots of 1 s, no sections: from the start
    stills_then(c, item)
    clips.calls.clear()
    ask = c.get(f"{BASE}/projects/{item}/motion/estimate").json()
    assert ask["count"] == 30 and ask["shots"] == 30 and (ask["start"], ask["end"]) == (0.0, 30.0)
    assert ask["quality"] == "draft" and ask["ready"] and not ask["measured"]

    clips.hold = asyncio.Event()
    assert c.post(f"{BASE}/projects/{item}/motion", json={}).status_code == 202
    end = time.monotonic() + 10
    while clips.reached < 3 and time.monotonic() < end:
        time.sleep(0.01)
    row = c.post(f"{BASE}/projects/{item}/shots/stop").json()
    assert row["shots"]["run"]["status"] == "stopped" and row["shots"]["run"]["kind"] == "motion"
    action, params = clips.calls[0]
    assert action == "video.animate" and params["quality"] == "draft" and params["seconds"] == 5
    assert params["image_id"] == row["shots"]["takes"]["s1"][0]["item_id"]

    clips.hold = None
    again = c.get(f"{BASE}/projects/{item}/motion/estimate").json()
    assert again["count"] == 28  # two were made
    c.post(f"{BASE}/projects/{item}/motion", json={})
    row = wait_run(c, item)
    assert row["shots"]["run"]["status"] == "done"
    for n in range(1, 31):
        chosen = next(t for t in row["shots"]["takes"][f"s{n}"] if t["chosen"])
        assert chosen["kind"] == "video" and chosen["mode"] == "draft"
    assert all(t["kind"] == "image" for t in row["shots"]["takes"]["s31"])
    # the cut uses the clips, and the clips are part of the project
    assert [p["kind"] for p in row["cut"]["items"][:3]] == ["video"] * 3
    media = {(m["kind"], m["shot_id"]) for m in store_for(state).media_of(item)}
    assert ("video", "s30") in media
    r = c.post(f"{BASE}/projects/{item}/motion", json={})
    assert r.status_code == 409 and "already have their clips" in r.text


def test_final_animates_the_animate_shots_and_one_shot_is_made_again_on_its_own(tmp_path: Path):
    clips = Clips()
    state, c, item = setup(tmp_path, clips, count=4)
    store = store_for(state)
    row = store.get("t1", "u1", item)
    plan = {
        **row["plan"],
        "shots": [
            {**s, "motion": "Animate"} if s["id"] in ("s2", "s4") else s
            for s in row["plan"]["shots"]
        ],
    }
    store.save_plan(item, plan, "two move")
    stills_then(c, item)
    clips.calls.clear()
    c.post(f"{BASE}/projects/{item}/motion", json={"quality": "final"})
    row = wait_run(c, item)
    assert [p["quality"] for _a, p in clips.calls] == ["final", "final"]
    assert {
        s for s, takes in row["shots"]["takes"].items() if any(t["kind"] == "video" for t in takes)
    } == {"s2", "s4"}
    c.post(f"{BASE}/projects/{item}/motion", json={"shot_id": "s2"})
    row = wait_run(c, item)
    assert (
        len([t for t in row["shots"]["takes"]["s2"] if t["kind"] == "video"]) == 2
    )  # made again, the old one kept


def test_no_video_model_no_stills_or_no_room_are_refused_in_words(tmp_path: Path, monkeypatch: Any):
    _s, c, item = setup(tmp_path, Clips())
    r = c.post(f"{BASE}/projects/{item}/motion", json={})
    assert r.status_code == 409 and "Make the stills first" in r.text
    _s, c, item = setup(tmp_path / "b", Clips(setup="Get the video model first."))
    r = c.post(f"{BASE}/projects/{item}/motion", json={})
    assert r.status_code == 409 and "Get the video model first." in r.text
    monkeypatch.setattr("wasifyai_creative.shots.free_bytes", lambda _: 1000)
    _s, c, item = setup(tmp_path / "c", Clips())
    stills_then(c, item)
    assert c.get(f"{BASE}/projects/{item}/motion/estimate").json()["fit"] == "too_big"
    assert c.post(f"{BASE}/projects/{item}/motion", json={}).status_code == 409


def test_a_clip_being_made_elsewhere_stops_the_run_at_once_and_says_so(tmp_path: Path):
    class Busy(Clips):
        async def run_action(
            self, action: str, params: dict[str, Any], _origin: str, **kw: Any
        ) -> Any:
            done = await super().run_action(action, params, _origin, **kw)
            if action == "video.animate":
                done.status, done.code, done.output = "refused", "busy", {}
            return done

    clips = Busy()
    _s, c, item = setup(tmp_path, clips, count=4)
    stills_then(c, item)
    clips.calls.clear()
    c.post(f"{BASE}/projects/{item}/motion", json={})
    row = wait_run(c, item)
    assert len(clips.calls) == 1 and "Another video is being made" in row["shots"]["run"]["error"]
