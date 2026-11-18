"""People (MT3): naming a speaker makes a person and keeps their voice; later speakers are suggested
by voice and never named alone; "not them" is remembered; a person can be renamed or forgotten."""

import numpy as np
from wasifyai_meetings import people
from wasifyai_meetings.people import (
    name_speaker,
    not_this_person,
    pack,
    solo_spans,
    suggest,
    with_suggestions,
)
from wasifyai_meetings.store import MeetingStore
from wasifyai_meetings.voiceprint import features, unit

RNG = np.random.default_rng(7)
ASHA, BEN, CARA = (unit(RNG.normal(size=192)) for _ in range(3))


def near(v: np.ndarray, d: float) -> np.ndarray:
    """A voice at cosine distance about `d` from `v`."""
    other = RNG.normal(size=192)
    other -= (other @ v) * v
    other = unit(other)
    c = 1 - d
    return unit(c * v + np.sqrt(1 - c * c) * other)


def meeting(store: MeetingStore, n: int, source: str = "file") -> dict:
    row = store.add("t", "u", title="Weekly", source=source)
    speakers = [
        {"key": f"S{i}", "default": f"Speaker {i}", "name": f"Speaker {i}", "seconds": 30.0}
        for i in range(1, n + 1)
    ]
    lines = [
        {"start": 10.0 * k, "end": 10.0 * k + 8, "speaker": f"S{k % n + 1}", "text": "Words."}
        for k in range(3 * n)
    ]
    store.finish(
        row["id"], seconds=30.0 * n, model_id="m", speakers=speakers, lines=lines, text="",
        timings={}, elapsed_s=1.0,
    )  # fmt: skip
    return store.get("t", "u", row["id"])


def prints(store: MeetingStore, row: dict, voices: list[np.ndarray], seconds: float = 24.0):
    store.save_prints("t", "u", row["id"], [
        {"speaker": f"S{i + 1}", "kind": people.kind_of(row["source"], f"S{i + 1}"),
         "vector": pack(v), "seconds": seconds, "turns": 3}
        for i, v in enumerate(voices)
    ])  # fmt: skip


def suggestions(store: MeetingStore, row: dict) -> dict:
    got = with_suggestions(store, "t", "u", store.get("t", "u", row["id"]))
    return {s["key"]: s["suggestion"] for s in got["speakers"]}


def test_naming_makes_a_person_keeps_their_voice_and_suggests_them_later(tmp_path):
    store = MeetingStore.in_folder(tmp_path)
    first = meeting(store, 2)
    prints(store, first, [ASHA, BEN])
    name_speaker(store, "t", "u", first["id"], "S1", "Asha")
    name_speaker(store, "t", "u", first["id"], "S2", "ben")
    listed = {p["name"]: p for p in store.people("t", "u")}
    assert listed["Asha"]["meetings"] == 1 and listed["Asha"]["voices"] == 1
    # naming the same name again is the same person (any case), who keeps their first spelling
    assert name_speaker(store, "t", "u", first["id"], "S2", "Ben")["speakers"][1]["name"] == "ben"
    assert len(store.people("t", "u")) == 2

    later = meeting(store, 2)
    prints(store, later, [near(BEN, 0.3), near(ASHA, 0.32)])
    got = suggestions(store, later)
    assert got["S1"]["name"] == "ben" and got["S2"]["name"] == "Asha"
    # one meeting of evidence: possible, not likely
    assert got["S1"]["status"] == "possible"
    # nothing is named until the person says so
    assert [s["name"] for s in store.get("t", "u", later["id"])["speakers"]] == [
        "Speaker 1", "Speaker 2"
    ]  # fmt: skip


def test_a_suggestion_is_likely_only_with_two_meetings_of_the_same_kind_and_enough_speech(tmp_path):
    store = MeetingStore.in_folder(tmp_path)
    for _ in range(2):
        m = meeting(store, 1)
        prints(store, m, [ASHA])
        name_speaker(store, "t", "u", m["id"], "S1", "Asha")
    third = meeting(store, 1)
    prints(store, third, [near(ASHA, 0.25)])
    assert suggestions(store, third)["S1"]["status"] == "likely"
    short = meeting(store, 1)
    prints(store, short, [near(ASHA, 0.25)], seconds=6.0)
    assert suggestions(store, short)["S1"]["status"] == "possible"
    # the same voice recorded otherwise (on a call) is compared with what there is, but not likely
    call = meeting(store, 2, source="recorded")
    prints(store, call, [CARA, near(ASHA, 0.25)])
    assert suggestions(store, call)["S2"]["status"] == "possible"


def test_nothing_is_suggested_for_a_far_voice_or_two_close_people(tmp_path):
    store = MeetingStore.in_folder(tmp_path)
    first = meeting(store, 2)
    twin = near(ASHA, 0.05)
    prints(store, first, [ASHA, twin])
    name_speaker(store, "t", "u", first["id"], "S1", "Asha")
    name_speaker(store, "t", "u", first["id"], "S2", "Dee")
    later = meeting(store, 2)
    # S1 is as close to Asha as to Dee: no suggestion; S2 is nobody known
    prints(store, later, [near(ASHA, 0.2), CARA])
    assert suggestions(store, later) == {"S1": None, "S2": None}


def test_no_is_remembered_and_counts_against_that_person(tmp_path):
    store = MeetingStore.in_folder(tmp_path)
    first = meeting(store, 1)
    prints(store, first, [ASHA])
    name_speaker(store, "t", "u", first["id"], "S1", "Asha")
    asha = store.people("t", "u")[0]["id"]

    second = meeting(store, 1)
    prints(store, second, [near(ASHA, 0.3)])
    assert suggestions(store, second)["S1"]["person_id"] == asha
    not_this_person(store, "t", "u", second["id"], "S1", asha)
    assert suggestions(store, second)["S1"] is None
    # a voice as close to that "no" as to Asha is not suggested as her in a later meeting either
    third = meeting(store, 1)
    prints(store, third, [near(store_vector(store, second), 0.02)])
    assert suggestions(store, third)["S1"] is None


def store_vector(store: MeetingStore, row: dict) -> np.ndarray:
    v = people.unpack(store.prints_of("t", "u", row["id"])["S1"]["vector"])
    assert v is not None
    return v


def test_a_meeting_with_two_named_people_keeps_each_as_not_the_other(tmp_path):
    store = MeetingStore.in_folder(tmp_path)
    first = meeting(store, 2)
    prints(store, first, [ASHA, BEN])
    name_speaker(store, "t", "u", first["id"], "S1", "Asha")
    name_speaker(store, "t", "u", first["id"], "S2", "Ben")
    ev = store.evidence("t", "u")
    reasons = sorted((e["speaker"], e["reason"]) for e in ev)
    assert reasons == [("S1", "confirmed"), ("S1", "voice"), ("S2", "confirmed"), ("S2", "voice")]
    # naming S2 back to nobody takes back what naming them added
    name_speaker(store, "t", "u", first["id"], "S2", "")
    assert sorted((e["speaker"], e["reason"]) for e in store.evidence("t", "u")) == [
        ("S1", "voice")
    ]


def test_renaming_and_forgetting_a_person(tmp_path):
    store = MeetingStore.in_folder(tmp_path)
    first = meeting(store, 1)
    prints(store, first, [ASHA])
    name_speaker(store, "t", "u", first["id"], "S1", "Asha")
    pid = store.people("t", "u")[0]["id"]
    assert people.rename_person(store, "t", "u", pid, "Asha Rahman") == [first["id"]]
    assert store.get("t", "u", first["id"])["speakers"][0]["name"] == "Asha Rahman"
    assert people.forget_person(store, "t", "u", pid) == [first["id"]]
    speaker = store.get("t", "u", first["id"])["speakers"][0]
    assert speaker["name"] == "Asha Rahman" and "person_id" not in speaker
    assert store.people("t", "u") == [] and store.evidence("t", "u") == []
    # deleting a meeting deletes what was learnt from it
    name_speaker(store, "t", "u", first["id"], "S1", "Asha")
    store.delete("t", "u", first["id"])
    assert store.evidence("t", "u") == [] and store.prints_of("t", "u", first["id"]) == {}


def test_another_persons_people_are_not_there(tmp_path):
    store = MeetingStore.in_folder(tmp_path)
    first = meeting(store, 1)
    prints(store, first, [ASHA])
    name_speaker(store, "t", "u", first["id"], "S1", "Asha")
    assert store.people("t", "other") == [] and store.evidence("t", "other") == []


def test_solo_spans_leave_out_overlaps_and_short_bits():
    lines = [
        {"start": 0.0, "end": 5.0, "speaker": "S1", "text": "a"},
        {"start": 4.0, "end": 9.0, "speaker": "S2", "text": "b"},
        {"start": 10.0, "end": 14.0, "speaker": "S1", "text": "c"},
        {"start": 15.0, "end": 15.5, "speaker": "S1", "text": "d"},
    ]
    assert solo_spans(lines, "S1") == [(10.0, 14.0)]
    assert solo_spans(lines, "S2") == []


def test_suggest_needs_a_voiceprint_and_skips_named_speakers():
    speakers = [{"key": "S1", "person_id": "p"}, {"key": "S2"}]
    assert suggest("m", speakers, {}, {"p": "Asha"}, []) == {}


def test_features_are_kaldi_shaped():
    t = np.arange(16000) / 16000
    f = features(0.1 * np.sin(2 * np.pi * 440 * t))
    assert f.shape == (100, 80)  # a frame every 10 ms, centred
    assert abs(float(f.mean())) < 1e-4  # each band's mean taken out
