# ruff: noqa: E501  (prose and test data are easier to read on one line)
"""The Cut step (CS3): the cut document and its edits, undo and redo, the captions file, and a real video made by the bundled
ffmpeg from stills, a song and captions, then kept in Your videos through the video product's action."""

import asyncio
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_shots import BASE, ME, Pictures, png, probe, setup, shot, wait_run
from wasifyai_creative import cut as cuts
from wasifyai_creative.runtime import store_for
from wasifyai_creative.store import CreativeStore
from wasifyai_platform_sdk import RouteDeps

BEATS = [round(0.5 * i, 3) for i in range(0, 25)]  # 120 bpm over 12 s


def plan(count: int = 4, length: float = 2.0) -> dict[str, Any]:
    return {"shots": [shot(i + 1, i * length, (i + 1) * length) for i in range(count)]}


FACTS = {
    "seconds": 8.0, "beats": BEATS, "lines_timed": True,
    "lines": [{"text": "Morning on the road", "start": 0.5, "end": 2.5}, {"text": "No {tags} here\\N", "start": 3.0, "end": 5.0}],
}  # fmt: skip


def edit(cut: dict[str, Any], *edits: dict[str, Any]) -> dict[str, Any]:
    return cuts.apply_cut_edits(cut, list(edits), BEATS, 8.0)


# ---- the document ------------------------------------------------------------------------------


def test_a_cut_starts_as_the_plan_with_the_songs_timed_lines_as_captions():
    cut = cuts.default_cut(plan(), FACTS)
    assert [x["shot_id"] for x in cut["items"]] == ["s1", "s2", "s3", "s4"]
    assert [x["start"] for x in cuts.timeline(cut)] == [0.0, 2.0, 4.0, 6.0]
    assert [c["text"] for c in cut["captions"]] == ["Morning on the road", "No {tags} here\\N"]
    assert cut["captions_on"] is True
    untimed = cuts.default_cut(plan(), {**FACTS, "lines_timed": False})
    assert untimed["captions"] == [] and untimed["captions_on"] is False
    assert cuts.summary(cut, plan(), 8.0) == {
        "pictures_end": 8.0,
        "song_s": 8.0,
        "black_tail": 0.0,
        "cut_short": 0.0,
        "plan_changed": False,
    }
    assert cuts.summary(cut, plan(4, 1.5), 8.0)["plan_changed"] is True


def test_pieces_move_lengthen_by_beats_split_fade_and_come_out():
    cut = cuts.default_cut(plan(), FACTS)
    moved = edit(cut, {"op": "move", "item_id": "c4", "to": 0})
    assert [x["id"] for x in moved["items"]] == ["c4", "c1", "c2", "c3"]
    longer = edit(cut, {"op": "length", "item_id": "c2", "by_beats": 2})
    assert longer["items"][1]["length"] == 3.0 and cuts.timeline(longer)[2]["start"] == 5.0
    shorter = edit(cut, {"op": "length", "item_id": "c1", "by_beats": -3})
    assert shorter["items"][0]["length"] == 0.5
    with pytest.raises(cuts.CutRefused, match="at least"):
        edit(cut, {"op": "length", "item_id": "c1", "by_beats": -4})
    split = edit(cut, {"op": "split", "item_id": "c2"})
    assert [(x["id"], x["shot_id"], x["length"]) for x in split["items"][1:3]] == [
        ("c2", "s2", 1.0),
        ("c5", "s2", 1.0),
    ]
    faded = edit(cut, {"op": "fade", "item_id": "c3", "fade": True})
    assert faded["items"][2]["fade"] is True
    fewer = edit(cut, {"op": "remove", "item_id": "c1"})
    assert len(fewer["items"]) == 3
    put = edit(
        cut, {"op": "insert", "after": "c1", "kind": "video", "item_id": "clip-1", "length": 1.5}
    )
    assert (
        put["items"][1]["source"] == {"kind": "video", "item_id": "clip-1"}
        and put["items"][1]["shot_id"] is None
    )


def test_one_bad_edit_refuses_them_all_and_nothing_changes():
    cut = cuts.default_cut(plan(), FACTS)
    before = json.dumps(cut)
    with pytest.raises(cuts.CutRefused, match="no such piece"):
        edit(cut, {"op": "fade", "item_id": "c1", "fade": True}, {"op": "remove", "item_id": "c9"})
    with pytest.raises(cuts.CutRefused, match="at least one"):
        edit(cuts.default_cut(plan(1), FACTS), {"op": "remove", "item_id": "c1"})
    with pytest.raises(cuts.CutRefused, match="Unknown"):
        edit(cut, {"op": "explode"})
    assert json.dumps(cut) == before


def test_captions_change_move_by_beats_are_added_in_order_and_switch_off():
    cut = cuts.default_cut(plan(), FACTS)
    moved = edit(
        cut, {"op": "caption", "caption_id": "t1", "by_beats": 2, "text": "Morning, the road"}
    )
    assert moved["captions"][0] == {
        **cut["captions"][0],
        "text": "Morning, the road",
        "start": 1.5,
        "end": 3.5,
    }
    titled = edit(
        cut, {"op": "add_caption", "kind": "title", "text": "Dawn drive", "start": 0.0, "end": 1.0}
    )
    assert [c["kind"] for c in titled["captions"]] == ["title", "line", "line"] and titled[
        "captions"
    ][0]["id"] == "t3"
    with pytest.raises(cuts.CutRefused, match="inside the song"):
        edit(cut, {"op": "add_caption", "kind": "lower", "text": "x", "start": 7.0, "end": 9.0})
    with pytest.raises(cuts.CutRefused, match="some words"):
        edit(cut, {"op": "caption", "caption_id": "t1", "text": "  "})
    off = edit(
        titled, {"op": "captions", "on": False}, {"op": "remove_caption", "caption_id": "t2"}
    )
    ass = cuts.ass_of(off, "landscape")
    assert "Dawn drive" in ass and "Morning" not in ass
    assert (
        cuts.captions_of(titled) == "Dawn drive"
    )  # what was typed is searchable; the lyrics already are


def test_the_captions_file_is_sized_for_the_shape_and_keeps_words_as_words():
    ass = cuts.ass_of(cuts.default_cut(plan(), FACTS), "portrait")
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    assert "Dialogue: 0,0:00:00.50,0:00:02.50,line,,0,0,0,,Morning on the road" in ass
    assert "No (tags) here/N" in ass and "{" not in ass.split("[Events]")[1]


# ---- undo and redo ------------------------------------------------------------------------------


def test_undo_and_redo_walk_the_revisions_and_a_new_change_drops_the_redo(tmp_path: Path):
    store = CreativeStore.in_folder(tmp_path)
    cut = cuts.default_cut(plan(), FACTS)
    assert store.cut_of("p") is None and store.step_cut("p", -1) is None
    store.save_cut("p", cut, "from the plan")
    store.save_cut("p", edit(cut, {"op": "fade", "item_id": "c2", "fade": True}), "fade")
    assert store.cut_of("p")["can_undo"] is True  # type: ignore[index]
    assert store.step_cut("p", -1) == "fade"
    assert store.cut_of("p") == {"cut": cut, "can_undo": False, "can_redo": True}
    assert store.step_cut("p", -1) is None
    assert store.step_cut("p", 1) == "fade" and store.cut_of("p")["cut"]["items"][1]["fade"] is True  # type: ignore[index]
    store.step_cut("p", -1)
    store.save_cut("p", edit(cut, {"op": "remove", "item_id": "c4"}), "remove")
    assert store.cut_of("p")["can_redo"] is False and store.step_cut("p", 1) is None  # type: ignore[index]


def test_a_database_of_cs2_gains_the_cut(tmp_path: Path):
    folder = tmp_path / "cs2"
    CreativeStore.in_folder(folder).close()
    db = sqlite3.connect(folder / "creative.db")
    db.executescript(
        "DROP TABLE cuts; DROP TABLE cut_revisions; DROP TABLE renders; DROP TABLE exports; UPDATE meta SET value = '2';"
    )
    db.close()
    store = CreativeStore.in_folder(folder)
    store.save_cut("p", cuts.default_cut(plan(), FACTS), "x")
    assert store.db.one("SELECT value FROM meta")["value"] == "3"
    store.close()


# ---- the video, for real -------------------------------------------------------------------------


class Keeper(Pictures):
    """The image product, and the video product's video.keep, which reads the project's video as the real one does."""

    def __init__(self) -> None:
        super().__init__()
        self.kept: list[bytes] = []
        self.read_video: Any = None

    async def run_action(
        self,
        action: str,
        params: dict[str, Any],
        _origin: str,
        *,
        actor: Any,
        person_approved: bool = False,
    ) -> Any:
        if action != "video.keep":
            return await super().run_action(
                action, params, _origin, actor=actor, person_approved=person_approved
            )
        assert person_approved and params["from_kind"] == "creative_project"
        data = await self.read_video(actor, params["from_id"])
        self.kept.append(data)
        return type(
            "Done", (), {"status": "ok", "output": {"video_id": f"v{len(self.kept)}"}, "text": ""}
        )()


def test_the_video_is_made_at_full_size_with_song_and_captions_and_kept_as_a_new_video_each_time(
    tmp_path: Path,
):
    from wasifyai_creative import cutting

    keeper = Keeper()
    state, c, item = setup(tmp_path, keeper, 3)
    store = store_for(state)
    store.set_facts(
        item,
        {
            "seconds": 3.0,
            "beats": [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0],
            "lines_timed": True,
            "lines": [{"text": "Hello road", "start": 0.2, "end": 1.4}],
        },
    )
    deps = RouteDeps(state, lambda: ME)
    keeper.read_video = lambda actor, project: cutting.read_render(deps, store, actor, project)
    assert c.post(f"{BASE}/projects/{item}/cut/video").status_code == 409  # no stills yet
    c.post(f"{BASE}/projects/{item}/shots", json={})
    wait_run(c, item)
    row = c.get(f"{BASE}/projects/{item}").json()
    assert [p["number"] for p in row["cut"]["items"]] == [1, 2, 3] and row["cut"]["captions"][0][
        "text"
    ] == "Hello road"
    changed = c.post(
        f"{BASE}/projects/{item}/cut/edits",
        json={
            "edits": [
                {"op": "fade", "item_id": "c2", "fade": True},
                {
                    "op": "add_caption",
                    "kind": "title",
                    "text": "Dawn drive",
                    "start": 2.0,
                    "end": 3.0,
                },
            ]
        },
    )
    assert changed.status_code == 200 and changed.json()["cut"]["can_undo"] is True
    bad = c.post(
        f"{BASE}/projects/{item}/cut/edits", json={"edits": [{"op": "remove", "item_id": "c9"}]}
    )
    assert (
        bad.status_code == 422
        and bad.json()["detail"]["message"] == "There is no such piece in the cut."
    )

    assert c.post(f"{BASE}/projects/{item}/cut/video").status_code == 202
    row = wait_run(c, item, 300.0)
    assert row["shots"]["run"]["status"] == "done", row["shots"]["run"]
    made = row["cut"]["render"]
    assert made["current"] is True and made["shape"] == "landscape" and made["url"]
    file = next((tmp_path / "files").rglob("cuts/*/*.mp4"))
    info = probe(file)
    assert (
        "Duration: 00:00:03.0" in info
        and "1920x1080" in info
        and "Audio:" in info
        and "h264" in info
    )

    assert (
        c.post(f"{BASE}/projects/{item}/cut/keep", json={"title": "Dawn drive"}).status_code == 202
    )
    row = wait_run(c, item, 60.0)
    assert (
        row["shots"]["run"]["status"] == "done"
        and len(keeper.kept) == 1
        and keeper.kept[0] == file.read_bytes()
    )
    assert (
        row["cut"]["exports"][0]["video_id"] == "v1"
        and row["cut"]["exports"][0]["title"] == "Dawn drive"
    )
    assert (
        len(list((tmp_path / "files").rglob("cuts/*/*.mp4"))) == 1
    )  # it was current, so it was not made again

    c.post(f"{BASE}/projects/{item}/cut/undo")
    assert c.get(f"{BASE}/projects/{item}").json()["cut"]["render"]["current"] is False
    c.post(f"{BASE}/projects/{item}/cut/keep", json={})
    row = wait_run(c, item, 300.0)
    assert [e["video_id"] for e in row["cut"]["exports"]] == ["v2", "v1"] and row["cut"]["exports"][
        0
    ]["title"] == "A walk"
    assert (
        row["cut"]["render"]["current"] is True
        and len(list((tmp_path / "files").rglob("cuts/*/*.mp4"))) == 1
    )


def test_a_short_cut_ends_in_black_with_the_song_and_a_lost_picture_is_black_too(tmp_path: Path):
    keeper = Keeper()
    state, c, item = setup(tmp_path, keeper, 3)
    c.post(f"{BASE}/projects/{item}/shots", json={})
    wait_run(c, item)
    c.post(f"{BASE}/projects/{item}/cut/edits", json={"edits": [{"op": "remove", "item_id": "c3"}]})
    row = c.get(f"{BASE}/projects/{item}").json()
    assert row["cut"]["summary"]["black_tail"] == 1.0

    async def gone(_ctx: Any, _id: str) -> None:
        return None

    keeper.library["image"] = SimpleNamespace(read=gone)
    c.post(f"{BASE}/projects/{item}/cut/video")
    row = wait_run(c, item, 300.0)
    assert row["shots"]["run"]["status"] == "done", row["shots"]["run"]
    info = probe(next((tmp_path / "files").rglob("cuts/*/*.mp4")))
    assert "Duration: 00:00:03.0" in info


def test_a_cut_cannot_change_while_its_video_is_being_made(tmp_path: Path):
    keeper = Keeper()
    state, c, item = setup(tmp_path, keeper, 2)
    c.post(f"{BASE}/projects/{item}/shots", json={})
    wait_run(c, item)
    hold = asyncio.Event()

    async def slow(_ctx: Any, _id: str) -> bytes:
        await hold.wait()
        return png()

    keeper.library["image"] = SimpleNamespace(read=slow)
    c.post(f"{BASE}/projects/{item}/cut/video")
    busy = c.post(
        f"{BASE}/projects/{item}/cut/edits",
        json={"edits": [{"op": "fade", "item_id": "c2", "fade": True}]},
    )
    assert busy.status_code == 409 and busy.json()["detail"]["code"] == "busy"
    c.post(f"{BASE}/projects/{item}/shots/stop")
    assert c.get(f"{BASE}/projects/{item}").json()["shots"]["run"]["status"] == "stopped"


def test_the_songs_words_come_back_where_they_were_sung_and_titles_stay():
    cut = cuts.default_cut(plan(), FACTS)
    changed = edit(
        cut,
        {"op": "remove_caption", "caption_id": "t1"},
        {"op": "add_caption", "kind": "title", "text": "Dawn drive", "start": 0.0, "end": 1.0},
        {"op": "captions", "on": False},
    )
    back = cuts.apply_cut_edits(changed, [{"op": "song_lines"}], BEATS, 8.0, FACTS["lines"])
    assert [(c["kind"], c["text"]) for c in back["captions"]] == [
        ("title", "Dawn drive"), ("line", "Morning on the road"), ("line", "No {tags} here\\N"),
    ]  # fmt: skip
    assert back["captions_on"] is True and len({c["id"] for c in back["captions"]}) == 3
    with pytest.raises(cuts.CutRefused, match="not known"):
        edit(cut, {"op": "song_lines"})
