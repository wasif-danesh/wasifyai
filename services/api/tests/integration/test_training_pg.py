# ruff: noqa: E501
"""The training product's rows on real Postgres (docs/train-web-plan.md, WT0): the same store as the
desktop's, run on both databases with the same steps, and the ownership rules."""

from uuid import uuid4

import pytest
from wasifyai_training.pgstore import PostgresTrainingStore
from wasifyai_training.store import NotFound, TrainingStore


@pytest.fixture
def pg(engine):
    from wasifyai_api.config import get_settings

    s = PostgresTrainingStore(get_settings().database_url, schema="trn_t_" + uuid4().hex[:8])
    yield s
    s.drop_schema()
    s.close()


@pytest.fixture
def lite(tmp_path):
    return TrainingStore(tmp_path)


def steps(store) -> dict:
    """Everything a person does, in order; what comes back is compared between the two databases."""
    out: dict = {}
    d = store.add_dataset("t1", "u1", "character", "Ena", "video")
    out["dataset"] = {k: d[k] for k in ("kind", "name", "family", "trigger_word", "rights")}
    store.update_dataset("t1", "u1", d["id"], trigger_word="enavqx", rights="artwork")
    pic = store.add_item("t1", "u1", d["id"], name="a.png", width=640, height=480, sha256="s1",
                         dhash=5, checks=[{"code": "good", "level": "ok", "message": "Good."}])  # fmt: skip
    clip = store.add_item("t1", "u1", d["id"], name="c.mp4", width=512, height=768, sha256="s2",
                          dhash=9, checks=[], media="clip", seconds=3.2, frames=77)  # fmt: skip
    store.set_caption(pic["id"], "enavqx, a woman", "done")
    store.mark_writing(clip["id"])
    items = store.list_items("t1", "u1", d["id"])
    out["items"] = [
        (i["media"], i["seconds"], i["frames"], i["caption_state"], i["checks"]) for i in items
    ]
    run = store.add_run("t1", "u1", d["id"], base="ltx-video-2b", steps=600,
                        settings={"family": "video"}, preview=False)  # fmt: skip
    store.set_progress(run["id"], 10, "Learning")
    store.add_sample(run["id"], "a.png")
    store.finish_run(run["id"], "done", elapsed_s=12.5, model_id=None)
    got = store.get_run("t1", "u1", run["id"])
    out["run"] = (got["status"], got["step"], got["samples"], got["elapsed_s"], got["settings"])
    m = store.add_model("t1", "u1", run_id=run["id"], dataset_id=d["id"], name="Ena",
                        trigger_word="enavqx", kind="character", base="ltx-video-2b",
                        card={"family": "video"}, preview=False, adapter_bytes=3_000_000_000)  # fmt: skip
    store.rename_model("t1", "u1", m["id"], "Ena look")
    out["model"] = (
        store.get_model("t1", "u1", m["id"])["name"],
        store.get_model("t1", "u1", m["id"])["card"],
    )
    w = store.add_writing_set("t1", "u1", "Replies")
    store.set_examples(
        "t1", "u1", w["id"], [{"ask": "a", "answer": "b"}, {"ask": "c", "answer": "d"}]
    )
    store.set_examples("t1", "u1", w["id"], [{"ask": "e", "answer": "f"}])  # replaces
    out["examples"] = store.list_examples("t1", "u1", w["id"])
    ds = store.add_decision_set("t1", "u1", "Reviews")
    store.set_decision_examples("t1", "u1", ds["id"], [{"text": "good", "answer": "yes"}])
    out["decisions"] = store.list_decision_examples("t1", "u1", ds["id"])
    out["lists"] = (
        [x["family"] for x in store.list_datasets("t1", "u1", 10)],
        [x["name"] for x in store.list_models("t1", "u1", 10)],
    )
    # a person sees only their own
    for call in (
        lambda: store.get_dataset("t1", "other", d["id"]),
        lambda: store.get_model("t1", "other", m["id"]),
        lambda: store.get_run("t1", "other", run["id"]),
    ):
        with pytest.raises(NotFound):
            call()
    assert store.list_datasets("t1", "other", 10) == []
    assert store.delete_dataset("t1", "u1", d["id"]) is True
    assert store.list_items("t1", "u1", d["id"]) == []
    return out


def test_the_web_store_does_what_the_desktop_store_does(pg, lite):
    assert steps(pg) == steps(lite)


def test_runs_a_gone_service_left_going_are_failed_with_a_sentence(pg):
    d = pg.add_dataset("t1", "u1", "style", "Ink")
    run = pg.add_run("t1", "u1", d["id"], base="b", steps=10, settings={}, preview=False)
    left = pg.runs_left_working()
    assert [r["id"] for r in left] == [run["id"]]
    row = pg.get_run("t1", "u1", run["id"])
    assert row["status"] == "failed" and "restarted" in row["error"]
