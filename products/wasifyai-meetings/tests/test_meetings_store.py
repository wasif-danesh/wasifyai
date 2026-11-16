"""The meetings' rows: scoped by person, one state at a time, left-running ones failed in words."""

import pytest
from wasifyai_meetings.people import name_speaker
from wasifyai_meetings.store import LEFT_RUNNING, MeetingStore, NotFound

SPEAKERS = [{"key": "S1", "default": "Speaker 1", "name": "Speaker 1", "seconds": 4.0}]
LINES = [{"start": 0.0, "end": 4.0, "speaker": "S1", "text": "Hello."}]


def _done(store, row):
    store.finish(
        row["id"], seconds=4.0, model_id="m", speakers=SPEAKERS, lines=LINES,
        text="Speaker 1: Hello.", timings={"words_s": 1.0}, elapsed_s=2.0,
    )  # fmt: skip


def test_a_meeting_is_made_finished_named_and_deleted(tmp_path):
    store = MeetingStore.in_folder(tmp_path)
    row = store.add("t", "u", title="Stand-up", source_name="standup.m4a")
    assert row["status"] == "working" and row["speakers"] == [] and row["timings"] == {}
    store.set_stage(row["id"], "Telling the speakers apart", 0.4)
    _done(store, row)
    got = store.get("t", "u", row["id"])
    assert got["status"] == "done" and got["progress"] == 1 and got["lines"] == LINES
    got = name_speaker(store, "t", "u", row["id"], "S1", "  Asha ")
    assert got["speakers"][0]["name"] == "Asha"
    assert name_speaker(store, "t", "u", row["id"], "S1", "")["speakers"][0]["name"] == "Speaker 1"
    assert store.list_meetings("t", "u")[0]["text"] == "Speaker 1: Hello."
    assert store.rename("t", "u", row["id"], "Daily")["title"] == "Daily"
    assert store.delete("t", "u", row["id"]) and store.list_meetings("t", "u") == []


def test_another_persons_meeting_is_not_there(tmp_path):
    store = MeetingStore.in_folder(tmp_path)
    row = store.add("t", "u", title="Mine")
    with pytest.raises(NotFound):
        store.get("t", "other", row["id"])
    with pytest.raises(NotFound):
        store.rename("other", "u", row["id"], "x")
    assert not store.delete("t", "other", row["id"])
    assert store.list_meetings("t", "other") == []


def test_a_finished_meeting_cannot_be_failed_and_a_stopped_one_cannot_finish(tmp_path):
    store = MeetingStore.in_folder(tmp_path)
    row = store.add("t", "u", title="A")
    _done(store, row)
    store.fail(row["id"], "late")
    assert store.get("t", "u", row["id"])["status"] == "done"
    other = store.add("t", "u", title="B")
    store.fail(other["id"], "Stopped.", "cancelled")
    _done(store, other)
    assert store.get("t", "u", other["id"])["status"] == "cancelled"


def test_what_a_closed_app_left_being_made_is_failed_in_words(tmp_path):
    row = MeetingStore.in_folder(tmp_path).add("t", "u", title="A")
    again = MeetingStore.in_folder(tmp_path)
    got = again.get("t", "u", row["id"])
    assert got["status"] == "failed" and got["error"] == LEFT_RUNNING


def test_a_meetings_folder_is_inside_the_store_and_needs_an_id(tmp_path):
    store = MeetingStore.in_folder(tmp_path)
    row = store.add("local", "me", title="A")
    assert store.folder_of("local", "me", row["id"]).is_relative_to(tmp_path / "files")
    with pytest.raises(ValueError):
        store.folder_of("local", "me", "../../etc")
