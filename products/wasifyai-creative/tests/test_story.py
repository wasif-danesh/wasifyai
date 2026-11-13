# ruff: noqa: E501  (prose and test data are easier to read on one line)
"""CS5 (ADR-0090): a story read aloud (its parts, voices, times and the plan run that narrates and joins it), the Sing rule
of the plan, and sung shots made with lip sync on the part of the song they cover. The models are stand-ins."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError
from test_creative import BEATS, BRIEF, DOWNS, Model, client, services, wait_for, writer
from test_motion import Clips, stills_then
from test_shots import BASE, setup, shot, wait_run
from wasifyai_creative import motion, stills, story
from wasifyai_creative.document import Brief, problems
from wasifyai_creative.layout import SHORTEST_S, lay_out, lay_out_story
from wasifyai_creative.runtime import store_for
from wasifyai_creative.writer import SING_CAMERA, write_plan

CAST = [
    {"name": "Mira", "look": "short dark hair", "voice": "v-mira"},
    {"name": "Tom", "look": "grey coat", "voice": "v-tom"},
]
TEXT = (
    'Mira found the old key under the mat. "It still fits," said Mira, turning it slowly.\n\n'
    'Tom laughed from the gate. "Then open it," Tom said. The door swung in, and the dust rose in the light.'
)


# ---- the parts of a story ----------------------------------------------------------------------


def test_quotes_are_said_by_the_person_named_in_the_sentence_and_the_rest_is_narrated():
    parts = story.parts_of(TEXT, CAST)
    assert [(p["text"], p["who"]) for p in parts] == [
        ("Mira found the old key under the mat.", None),
        ("It still fits", "Mira"),
        ("said Mira, turning it slowly.", None),
        ("Tom laughed from the gate.", None),
        ("Then open it", "Tom"),
        ("Tom said.", None),
        ("The door swung in, and the dust rose in the light.", None),
    ]
    pauses = [p["pause"] for p in parts]
    assert pauses[1] == story.PAUSE_IN_SENTENCE and pauses[2] == story.PAUSE_PARAGRAPH
    assert pauses[0] == story.PAUSE_SENTENCE and pauses[-1] == story.PAUSE_END
    assert [p["paragraph"] for p in parts] == [0, 0, 0, 1, 1, 1, 1]


def test_a_quote_with_nobody_named_or_said_by_someone_seen_only_in_photos_is_narrated():
    parts = story.parts_of(
        '"Wait," someone called. Mira looked at "the photo".',
        [{"name": "Mira", "photos_only": True}],
    )
    assert all(p["who"] is None for p in parts)
    long = "word, " * 200
    chunks = story.parts_of(long, [])
    assert len(chunks) > 1 and all(len(p["text"]) <= story.MAX_PART for p in chunks)


def test_the_times_of_a_narration_become_lines_sections_and_places_to_cut():
    parts = story.parts_of(TEXT, CAST)
    times = [[i * 3.0, i * 3.0 + 2.5] for i in range(len(parts))]
    facts = story.facts_of(parts, times, 22.0)
    assert facts["lines_timed"] and facts["story"] and facts["seconds"] == 22.0
    assert facts["lines"][1] == {"text": "It still fits", "start": 3.0, "end": 5.5, "who": "Mira"}
    assert [(s["start"], s["end"]) for s in facts["sections"]] == [(0.0, 9.0), (9.0, 22.0)]
    assert facts["beats"][0] == 3.0 and facts["downbeats"] == []
    assert story.speaker_at(facts["lines"], 3.0, 6.0) == "Mira"
    assert story.speaker_at(facts["lines"], 0.0, 2.5) is None
    assert story.speaker_at(facts["lines"], 5.2, 6.0) is None  # too little of it


@pytest.mark.parametrize("speed", [-2, -1, 0, 1, 2])
def test_a_story_is_cut_where_its_lines_start_with_no_gap(speed):
    starts = [0.0, 2.1, 6.4, 8.0, 15.9, 18.2]
    slots = lay_out_story(starts[1:], 24.0, speed)
    assert slots[0].start == 0.0 and slots[-1].end == 24.0
    assert all(a.end == b.start for a, b in zip(slots, slots[1:], strict=False))
    assert all(s.end - s.start <= 5.0 + 1e-6 for s in slots)
    assert all(s.end - s.start >= SHORTEST_S - 1e-6 for s in slots[:-1])
    if speed == 0:
        assert {round(s.start, 1) for s in slots} >= {2.1, 6.4, 15.9, 18.2}


def test_a_brief_needs_a_song_or_a_story():
    with pytest.raises(ValidationError, match="Choose a song"):
        Brief.model_validate({"idea": "A walk"})
    with pytest.raises(ValidationError, match="Write the story"):
        Brief.model_validate({"skill": "story", "idea": "A walk", "story": "Too short."})
    ok = Brief.model_validate(
        {"skill": "story", "idea": "A walk", "story": TEXT, "cast": CAST, "narrator": "v-n"}
    )
    assert ok.track_id == "" and ok.cast[0].voice == "v-mira"


# ---- the Sing rule -----------------------------------------------------------------------------


async def test_a_song_sings_its_close_ups_of_the_face_while_a_line_is_sung():
    lines = [{"text": f"line {n}", "start": n * 6.0, "end": n * 6.0 + 5.5} for n in range(15)]
    w, _, _ = writer(Model())
    slots = lay_out(BEATS, DOWNS, 90.0)
    plan = await write_plan(w, BRIEF, slots, lines)
    sung = [s for s in plan["shots"] if s["motion"] == "Sing"]
    assert sung and all(
        s["camera"] == SING_CAMERA and s["line"] and s["who"][0] == "Mira" for s in sung
    )
    assert len(sung) <= len(plan["shots"]) // 5
    assert problems(plan, ["Mira"], 90.0) == []
    # with no timed lines, or nobody there in person, nothing sings
    none, _, _ = writer(Model())
    plain = await write_plan(none, BRIEF, slots, [])
    assert not any(s["motion"] == "Sing" for s in plain["shots"])
    photos, _, _ = writer(Model())
    away = await write_plan(
        photos, {**BRIEF, "cast": [{"name": "Mira", "photos_only": True}]}, slots, lines
    )
    assert not any(s["motion"] == "Sing" for s in away["shots"])


async def test_a_story_writes_its_bible_first_and_a_person_speaking_is_a_close_up_of_their_face():
    class Bible(Model):
        async def __call__(self, system: str, prompt: str, schema: dict[str, Any]) -> str:
            if "title" in schema["properties"]:
                self.calls.append(prompt)
                return json.dumps(
                    {"title": "The key", "tone": "quiet and warm", "ending": "The door opens."}
                )
            return await super().__call__(system, prompt, schema)

    parts = story.parts_of(TEXT, CAST)
    times = [[i * 3.0, i * 3.0 + 2.5] for i in range(len(parts))]
    facts = story.facts_of(parts, times, 22.0)
    brief = {
        "skill": "story",
        "story": TEXT,
        "idea": "Opening the old house",
        "cast": CAST,
        "places": ["porch", "hall"],
    }
    model = Bible()
    w, kept, _ = writer(model)
    plan = await write_plan(w, brief, lay_out_story(facts["beats"], 22.0), facts["lines"])
    assert kept["bible"] == {
        "title": "The key",
        "tone": "quiet and warm",
        "ending": "The door opens.",
    }
    assert plan["bible"]["title"] == "The key"
    assert "Mira found the old key" in model.calls[0]  # the bible reads the story
    parts_asked = [c for c in model.calls if "different shots of this beat" in c]
    assert parts_asked and all("Tone: quiet and warm" in c for c in parts_asked)
    assert all("the story, as the narrator reads it" not in c.lower() for c in parts_asked)
    assert any("the story says here" in c for c in parts_asked)
    spoken = [s for s in plan["shots"] if s["motion"] == "Sing"]
    assert spoken and {s["who"][0] for s in spoken} <= {"Mira", "Tom"}
    assert problems(plan, ["Mira", "Tom"], 22.0) == []


def test_a_sung_still_asks_for_the_face():
    found = stills.still_for(
        shot(1, 0, 1, motion="Sing", camera=SING_CAMERA), {**BRIEF, "fixed": []}, stills.PLAIN
    )
    assert stills.FACE in found.prompt


# ---- a story planned through the routes -------------------------------------------------------


class Voices:
    """The voice product: speech.speak makes a speech, speech.join keeps them as one track; `fail_join` fails once."""

    def __init__(self, fail_join: bool = False):
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_join = fail_join
        self.missing = False

    async def run_action(
        self,
        action: str,
        params: dict[str, Any],
        _origin: str,
        *,
        actor: Any,
        person_approved: bool = False,
    ) -> Any:
        self.calls.append((action, params))
        if action == "speech.speak":
            return SimpleNamespace(
                status="ok",
                output={"speech_id": f"sp{len(self.calls)}", "seconds": 2.5},
                text="",
                code=None,
            )
        if action == "speech.join":
            if self.missing:
                self.missing = False
                return SimpleNamespace(
                    status="refused",
                    output={},
                    text="A speech to join is no longer there.",
                    code="not_found",
                )
            if self.fail_join:
                self.fail_join = False
                return SimpleNamespace(
                    status="error", output={}, text="The disk is full.", code="failed"
                )
            times = [[i * 3.0, i * 3.0 + 2.5] for i in range(len(params["parts"]))]
            return SimpleNamespace(
                status="ok", text="", code=None,
                output={"track_id": "narration", "title": params["title"], "seconds": times[-1][1] + 1.0, "times": times},
            )  # fmt: skip
        raise AssertionError(f"not expected: {action}")


def test_a_story_is_read_aloud_in_its_voices_joined_and_planned_and_a_stop_does_not_speak_twice(
    tmp_path: Path,
):
    voices = Voices(fail_join=True)
    state = services(tmp_path, executor=voices)
    brief = {
        "skill": "story",
        "story": TEXT,
        "idea": "Opening the old house",
        "cast": CAST,
        "places": ["porch"],
        "narrator": "v-n",
    }
    with client(state) as c:
        r = c.post(f"{BASE}/projects", json={"brief": brief})
        assert r.status_code == 201, r.text
        item = r.json()["id"]
        c.post(f"{BASE}/projects/{item}/plan", json={})
        row = wait_for(c, item)
        assert row["status"] == "failed" and "The disk is full." in row["error"]
        spoken = [p for a, p in voices.calls if a == "speech.speak"]
        assert [p.get("saved_voice") for p in spoken] == [
            "v-n",
            "v-mira",
            "v-n",
            "v-n",
            "v-tom",
            "v-n",
            "v-n",
        ]
        c.post(f"{BASE}/projects/{item}/plan", json={})
        row = wait_for(c, item)
        assert row["status"] == "planned", row["error"]
        assert (
            len([a for a, _ in voices.calls if a == "speech.speak"]) == 7
        )  # nothing was said twice
        joined = [p for a, p in voices.calls if a == "speech.join"][-1]
        assert [x["pause"] for x in joined["parts"]][:3] == [
            story.PAUSE_SENTENCE,
            story.PAUSE_IN_SENTENCE,
            story.PAUSE_PARAGRAPH,
        ]
        assert row["brief"]["track_id"] == "narration" and row["facts"]["story"]
        assert row["facts"]["lines"][1]["who"] == "Mira"
        assert problems(row["plan"], ["Mira", "Tom"], row["facts"]["seconds"]) == []
        media = {(m["kind"], m["item_id"]) for m in store_for(state).media_of(item)}
        assert ("track", "narration") in media and ("speech", "sp1") in media
        # planned again: the narration is kept, nothing is said again
        c.post(f"{BASE}/projects/{item}/plan", json={"again": True})
        assert wait_for(c, item)["status"] == "planned"
        assert len([a for a, _ in voices.calls if a == "speech.speak"]) == 7
        # a spoken part was deleted: joining says so, and the next try speaks again
        voices.missing = True
        store_for(state).drop_checkpoints(item, "joined-")
        c.post(f"{BASE}/projects/{item}/plan", json={})
        assert wait_for(c, item)["status"] == "failed"
        c.post(f"{BASE}/projects/{item}/plan", json={})
        assert wait_for(c, item)["status"] == "planned"
        assert len([a for a, _ in voices.calls if a == "speech.speak"]) == 14


# ---- sung shots ------------------------------------------------------------------------------


class Singing(Clips):
    async def run_action(self, action: str, params: dict[str, Any], _origin: str, **kw: Any) -> Any:
        done = await super().run_action(action, params, _origin, **kw)
        if action == "lipsync.make" and done.status == "ok":
            done.output = {
                "clip_id": f"c{len(self.calls):031d}",
                "seconds": params["end"] - params["start"],
            }
        return done


def test_a_sung_shot_is_lip_sync_on_its_part_of_the_song_and_counts_at_every_setting(
    tmp_path: Path,
):
    clips = Singing()
    state, c, item = setup(tmp_path, clips, count=6)
    store = store_for(state)
    row = store.get("t1", "u1", item)
    plan = {
        **row["plan"],
        "shots": [
            {**s, "motion": "Sing", "line": "Take me home", "camera": SING_CAMERA} if s["id"] == "s2"
            else {**s, "motion": "Animate"} if s["id"] == "s4" else s
            for s in row["plan"]["shots"]
        ],
    }  # fmt: skip
    store.save_plan(item, plan, "one sings")
    stills_then(c, item)
    clips.calls.clear()
    ask = c.get(f"{BASE}/projects/{item}/motion/estimate?quality=final").json()
    assert ask["count"] == 2 and ask["sung"] == 1
    low = motion.SECONDS["final"][0] + 1.0 * motion.SING_RATE[0] + motion.SING_LOAD_S
    assert ask["seconds_low"] == round(low)
    c.post(f"{BASE}/projects/{item}/motion", json={"quality": "final"})
    row = wait_run(c, item)
    assert row["shots"]["run"]["status"] == "done", row["shots"]["run"]
    sung = [p for a, p in clips.calls if a == "lipsync.make"]
    assert sung == [{
        "image_id": sung[0]["image_id"], "source_kind": "track", "source_id": "song",
        "start": 1.0, "end": 2.0, "title": "A walk, shot 2",
    }]  # fmt: skip
    take = next(t for t in row["shots"]["takes"]["s2"] if t["chosen"])
    assert take["kind"] == "lipsync" and take["mode"] == "sing" and not take["out_of_date"]
    assert row["shots"]["out_of_date"] == []  # the sung clip is what the shot asks for now
    assert [p["kind"] for p in row["cut"]["items"][:2]] == ["image", "lipsync"]
    # a draft does not sing it again, and the time is now what this computer took
    again = c.get(f"{BASE}/projects/{item}/motion/estimate?quality=draft&start=0").json()
    assert again["sung"] == 0


def test_a_sung_shot_whose_part_of_the_song_moves_is_out_of_date():
    s = shot(2, 1.0, 2.0, motion="Sing", line="x")
    mark = motion.sing_mark(s, "m")
    takes = [{"shot_id": "s2", "kind": "lipsync", "mode": "sing", "inputs": mark}]
    assert motion.has_clip(takes, "s2", motion.FINAL, mark)
    assert not motion.has_clip(takes, "s2", motion.FINAL, motion.sing_mark({**s, "end": 2.5}, "m"))
    shots = {"s2": s}
    assert motion.measured_sing([{**takes[0], "seconds": 7.0}], shots) == 7.0
