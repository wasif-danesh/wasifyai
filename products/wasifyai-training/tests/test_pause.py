"""Pause and pick up: a run stopped with its last checkpoint kept, the older database a run can be
paused in, and a run the app left going."""

import sqlite3
import time
from pathlib import Path

from training_rig import BASE, ready_dataset
from wasifyai_training.store import LEFT_PAUSED, LEFT_RUNNING, TrainingStore


def going(rig, step: int = 15) -> dict:
    ds = ready_dataset(rig, pictures=8)
    run = rig.post(f"{BASE}/runs", json={"dataset_id": ds["id"]}).json()
    rig.app_state.training.step_s = 0.02
    row: dict = {}
    for _ in range(300):
        row = rig.get(f"{BASE}/runs/{run['id']}").json()
        if row["step"] >= step or row["status"] != "working":
            return row
        time.sleep(0.01)
    raise AssertionError(row)


def wait_for(rig, run_id: str, status: str) -> dict:
    row: dict = {}
    for _ in range(400):
        row = rig.get(f"{BASE}/runs/{run_id}").json()
        if row["status"] == status:
            return row
        time.sleep(0.02)
    raise AssertionError(row)


def test_a_run_can_be_paused_and_picked_up_where_it_stopped(rig):
    row = going(rig)
    assert row["status"] == "working"
    paused = rig.post(f"{BASE}/runs/{row['id']}/pause")
    assert paused.status_code == 200 and paused.json() == {"paused": True}
    stopped = wait_for(rig, row["id"], "paused")
    assert stopped["stage"].startswith("Paused at step") and stopped["live"] is False
    assert 1 <= stopped["step"] < stopped["steps"]
    # nothing is learnt as finished and no model is made while it is paused
    assert rig.get(f"{BASE}/models").json()["models"] == []
    resumed = rig.post(f"{BASE}/runs/{row['id']}/resume")
    assert resumed.status_code == 202 and resumed.json()["status"] == "working"
    done = wait_for(rig, row["id"], "done")
    assert done["model_id"] and done["progress"] == 1
    assert len(done["samples"]) == len(set(done["samples"]))  # none added twice


def test_only_a_paused_run_can_be_resumed_and_only_one_that_is_going_can_be_paused(rig):
    row = going(rig, step=5)
    assert rig.post(f"{BASE}/runs/{row['id']}/resume").json()["detail"]["code"] == "not_paused"
    done = wait_for(rig, row["id"], "done")
    assert rig.post(f"{BASE}/runs/{done['id']}/pause").json() == {"paused": False}


def test_a_paused_run_can_be_discarded(rig):
    row = going(rig)
    rig.post(f"{BASE}/runs/{row['id']}/pause")
    wait_for(rig, row["id"], "paused")
    assert rig.post(f"{BASE}/runs/{row['id']}/cancel").json() == {"cancelled": True}
    gone = rig.get(f"{BASE}/runs/{row['id']}").json()
    assert gone["status"] == "cancelled" and gone["error"] == "Discarded."


def test_nobody_else_can_pause_or_resume_a_persons_run(rig):
    row = going(rig, step=3)
    other = {"x-user": "intruder"}
    assert rig.post(f"{BASE}/runs/{row['id']}/pause", headers=other).status_code == 404
    assert rig.post(f"{BASE}/runs/{row['id']}/resume", headers=other).status_code == 404


def old_database(folder: Path) -> None:
    """A training database from before a run could be paused: the status check has four values."""
    folder.mkdir(parents=True)
    db = sqlite3.connect(folder / "training.db")
    db.executescript(
        """
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE runs(
          id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
          user_id TEXT NOT NULL,
          status TEXT NOT NULL CHECK (status IN ('working', 'done', 'failed', 'cancelled')),
          stage TEXT NOT NULL DEFAULT '', step INTEGER NOT NULL DEFAULT 0,
          steps INTEGER NOT NULL DEFAULT 0, progress REAL NOT NULL DEFAULT 0, error TEXT,
          base TEXT NOT NULL DEFAULT '', settings TEXT NOT NULL DEFAULT '{}',
          samples TEXT NOT NULL DEFAULT '[]', preview INTEGER NOT NULL DEFAULT 0, model_id TEXT,
          elapsed_s REAL, created_at TEXT NOT NULL, finished_at TEXT);
        INSERT INTO runs(id, dataset_id, tenant_id, user_id, status, steps, created_at)
          VALUES ('a' || hex(zeroblob(15)), 'd', 't1', 'u1', 'done', 200, '2026-10-24');
        """
    )
    db.commit()
    db.close()


def test_an_older_database_keeps_its_runs_and_can_now_pause_one(tmp_path: Path):
    old_database(tmp_path / "t")
    store = TrainingStore(tmp_path / "t")
    runs = store.list_runs("t1", "u1")
    assert len(runs) == 1 and runs[0]["status"] == "done"
    row = store.add_run("t1", "u1", "d" * 32, base="b", steps=10, settings={}, preview=False)
    store.pause_run(row["id"], "Paused at step 4 of 10")
    assert store.get_run("t1", "u1", row["id"])["status"] == "paused"
    assert (
        store.resume_run(row["id"]) and store.get_run("t1", "u1", row["id"])["status"] == "working"
    )


def test_a_run_the_app_left_going_is_paused_when_it_kept_a_checkpoint_else_stopped(tmp_path: Path):
    store = TrainingStore(tmp_path)
    kept = store.add_run("t1", "u1", "d" * 32, base="b", steps=10, settings={}, preview=False)
    lost = store.add_run("t1", "u1", "d" * 32, base="b", steps=10, settings={}, preview=False)
    checkpoints = store.folder_of("t1", "u1", "runs", kept["id"]) / "out" / "checkpoints"
    checkpoints.mkdir(parents=True)
    (checkpoints / "0000025_checkpoint.zip").write_bytes(b"zip")
    store._db.close()  # noqa: SLF001
    again = TrainingStore(tmp_path)
    a, b = again.get_run("t1", "u1", kept["id"]), again.get_run("t1", "u1", lost["id"])
    assert (a["status"], a["error"]) == ("paused", LEFT_PAUSED)
    assert (b["status"], b["error"]) == ("failed", LEFT_RUNNING)
