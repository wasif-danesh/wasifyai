"""The training product on the desktop (ADR-0073, T1): the pictures and what is said about them,
the descriptions the app writes, the magic word, the runs and the trained models, with the
preview trainer."""

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from training_rig import (
    BASE,
    add_picture,
    blurry,
    jpeg,
    make_app,
    new_dataset,
    noise,
    png,
    ready_dataset,
    wait,
)
from wasifyai_training.store import LEFT_RUNNING, TrainingStore

PHOTO = (
    Path(__file__).resolve().parents[2]
    / "wasifyai-voice"
    / "wasifyai_voice"
    / "fixtures"
    / "product.jpg"
)


def test_the_status_says_it_is_a_preview_and_what_a_run_asks_for(rig):
    s = rig.get(f"{BASE}/status").json()
    assert s["ready"] is True and s["preview"] is True and s["place"] == "device"
    assert s["min_pictures"] == 8 and set(s["kinds"]) == {"character", "style", "object"}
    assert s["estimates"]["character"] == "About 20 minutes"  # 200 steps at 6 s (512 pixels)
    assert s["estimates"]["style"] == "About 42 minutes"  # 250 steps at 10 s (768 pixels)
    assert s["steps"] == {"character": 200, "style": 250, "object": 150}


def test_a_dataset_has_a_kind_a_name_and_a_magic_word(rig):
    ds = new_dataset(rig)
    assert ds["kind"] == "character" and ds["name"] == "Marlo" and ds["pictures"] == 0
    bad = rig.post(f"{BASE}/datasets", json={"kind": "dragon"})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "bad_kind"
    r = rig.patch(f"{BASE}/datasets/{ds['id']}", json={"trigger_word": "Zorbak"})
    assert r.json()["trigger_word"] == "zorbak"
    for word in ("dog", "no", "has space", "x" * 20, "marlo1"):
        r = rig.patch(f"{BASE}/datasets/{ds['id']}", json={"trigger_word": word})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_word", word


def test_each_picture_is_checked_in_words_as_it_arrives(rig):
    ds = new_dataset(rig)
    good = add_picture(rig, ds["id"]).json()
    assert [c["code"] for c in good["checks"]] == ["good"] and good["suggest_remove"] is False
    small = add_picture(rig, ds["id"], png(noise(size=300))).json()
    assert "too_small" in [c["code"] for c in small["checks"]] and small["suggest_remove"] is True
    soft = add_picture(rig, ds["id"], blurry()).json()
    assert "blurry" in [c["code"] for c in soft["checks"]]
    photo = Image.open(PHOTO).convert("RGB").resize((700, 700))  # a picture with a picture in it
    add_picture(rig, ds["id"], png(photo))
    again = add_picture(rig, ds["id"], jpeg(photo.resize((520, 520)))).json()
    assert "copy" in [c["code"] for c in again["checks"]]
    assert "copy of another" in again["checks"][0]["message"]
    assert rig.get(f"{BASE}/datasets/{ds['id']}").json()["pictures"] == 5


def test_a_file_that_is_not_a_usable_picture_is_refused_in_words_and_not_kept(rig):
    ds = new_dataset(rig)
    for data, words in (
        (b"", "empty"),
        (b"not a picture", "could not be read"),
        (png(noise(size=40)), "too small"),
    ):
        r = add_picture(rig, ds["id"], data)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_picture"
        assert words in r.json()["detail"]["message"]
    assert rig.get(f"{BASE}/datasets/{ds['id']}").json()["pictures"] == 0


def test_pictures_are_served_and_removed_with_their_files(rig, tmp_path):
    ds = new_dataset(rig)
    item = add_picture(rig, ds["id"]).json()
    base = f"{BASE}/datasets/{ds['id']}/items/{item['id']}"
    assert rig.get(f"{base}/thumb").headers["content-type"] == "image/jpeg"
    assert rig.get(f"{base}/picture").headers["content-type"] == "image/png"
    assert rig.delete(base).status_code == 204
    assert rig.get(f"{base}/thumb").status_code == 404
    assert not list((tmp_path / "training" / "files").rglob("picture.png"))


def test_nobody_else_can_see_or_change_a_persons_pictures(rig):
    ds = new_dataset(rig)
    item = add_picture(rig, ds["id"]).json()
    other = {"x-user": "u2"}
    assert rig.get(f"{BASE}/datasets/{ds['id']}", headers=other).status_code == 404
    assert (
        rig.get(f"{BASE}/datasets/{ds['id']}/items/{item['id']}/picture", headers=other).status_code
        == 404
    )
    assert add_picture(rig, ds["id"], headers=other).status_code == 404
    assert rig.get(f"{BASE}/datasets", headers=other).json()["datasets"] == []


def test_the_app_writes_a_description_of_every_picture_and_the_person_can_change_one(rig):
    ds = new_dataset(rig)
    for n in range(3):
        add_picture(rig, ds["id"], png(noise((100 + n * 30, 80, 120))))
    assert rig.post(f"{BASE}/datasets/{ds['id']}/captions").json() == {"writing": 3}
    got = wait(rig, f"/datasets/{ds['id']}", lambda d: not d["writing"])
    assert {i["caption_state"] for i in got["items"]} == {"done"}
    assert got["items"][0]["caption"].startswith("Standing on a beach")
    first = got["items"][0]["id"]
    r = rig.patch(f"{BASE}/datasets/{ds['id']}/items/{first}", json={"caption": "  On   a hill. "})
    assert r.json()["caption"] == "On a hill." and r.json()["caption_state"] == "edited"
    # "again" for one picture rewrites only that one
    assert rig.post(
        f"{BASE}/datasets/{ds['id']}/captions", json={"again": True, "item_ids": [first]}
    ).json() == {"writing": 1}
    wait(rig, f"/datasets/{ds['id']}", lambda d: not d["writing"])
    again = rig.get(f"{BASE}/datasets/{ds['id']}").json()["items"]
    assert again[0]["caption_state"] == "done" and again[0]["caption"].startswith("Standing")
    assert rig.post(f"{BASE}/datasets/{ds['id']}/captions").json() == {
        "writing": 0
    }  # nothing to do


def test_a_picture_that_cannot_be_described_says_so_and_can_be_tried_again(rig):
    ds = new_dataset(rig)
    add_picture(rig, ds["id"])
    rig.vision.fail_caption = True
    rig.post(f"{BASE}/datasets/{ds['id']}/captions")
    got = wait(rig, f"/datasets/{ds['id']}", lambda d: not d["writing"])
    assert got["items"][0]["caption_state"] == "failed"
    assert "could not be described" in got["items"][0]["caption_error"]
    rig.vision.fail_caption = False
    assert rig.post(f"{BASE}/datasets/{ds['id']}/captions").json() == {"writing": 1}


def test_without_a_vision_model_the_descriptions_say_what_to_do(tmp_path):
    app, _ = make_app(tmp_path)
    app.state.services.caps = {}
    with TestClient(app) as client:
        ds = new_dataset(client)
        add_picture(client, ds["id"])
        r = client.post(f"{BASE}/datasets/{ds['id']}/captions")
        assert r.status_code == 409 and r.json()["detail"]["code"] == "no_vision_model"
        assert "can read pictures" in r.json()["detail"]["message"]


def test_three_magic_words_are_suggested_and_the_persons_name_comes_first(rig):
    ds = new_dataset(rig, name="Marlo")
    words = rig.get(f"{BASE}/datasets/{ds['id']}").json()["suggestions"]
    assert len(words) == 3 and words[0] == "marlo" and len(set(words)) == 3
    for w in words:
        assert 4 <= len(w) <= 12 and w.isalpha() and w == w.lower()
    common = new_dataset(rig, name="Dog")
    assert "dog" not in rig.get(f"{BASE}/datasets/{common['id']}").json()["suggestions"]
    # a word one set uses is not suggested to another
    rig.patch(f"{BASE}/datasets/{ds['id']}", json={"trigger_word": "marlo"})
    again = new_dataset(rig, name="Marlo")
    assert "marlo" not in rig.get(f"{BASE}/datasets/{again['id']}").json()["suggestions"]


def test_a_run_says_what_is_missing_before_it_starts(rig):
    ds = new_dataset(rig)
    r = rig.post(f"{BASE}/runs", json={"dataset_id": ds["id"]})
    assert r.status_code == 409 and "at least 8 pictures" in r.json()["detail"]["message"]
    for n in range(8):
        add_picture(rig, ds["id"], png(noise((60 + n * 20, 90, 200))))

    def why() -> str:
        return rig.post(f"{BASE}/runs", json={"dataset_id": ds["id"]}).json()["detail"]["message"]

    assert why() == "Choose the magic word first."  # nothing is asked about whose it is
    rig.patch(f"{BASE}/datasets/{ds['id']}", json={"trigger_word": "marlo"})
    assert why() == "Write the descriptions first."


def test_a_run_goes_through_its_steps_and_leaves_a_model_with_its_card(rig):
    ds = ready_dataset(rig)
    assert ds["missing"] is None
    started = rig.post(f"{BASE}/runs", json={"dataset_id": ds["id"]})
    assert started.status_code == 202, started.text
    run = started.json()
    assert run["status"] == "working" and run["steps"] == 200 and run["preview"] is True
    assert run["estimate"] == "About 20 minutes"
    assert rig.post(f"{BASE}/runs", json={"dataset_id": ds["id"]}).json()["detail"]["code"] in (
        "busy",
        "not_ready_to_train",
    )
    done = wait(rig, f"/runs/{run['id']}", lambda r: r["status"] != "working")
    assert done["status"] == "done" and done["progress"] == 1 and done["model_id"]
    assert len(done["samples"]) == 4 and done["samples"][0] == "step-0050.png"
    sample = rig.get(f"{BASE}/runs/{run['id']}/samples/{done['samples'][0]}")
    assert sample.status_code == 200 and sample.headers["content-type"] == "image/png"
    model = rig.get(f"{BASE}/models/{done['model_id']}").json()
    assert (
        model["name"] == "Marlo" and model["trigger_word"] == "marlo" and model["preview"] is True
    )
    card = model["card"]
    assert card["dataset"]["pictures"] == 8 and card["trigger_word"] == "marlo"
    assert "statement" not in card and "licence" not in card
    assert card["preview"] is True and card["steps"] == 200
    assert "not a trained model" in card["note"]
    file = rig.get(f"{BASE}/models/{model['id']}/file")
    assert file.status_code == 200 and "marlo.safetensors" in file.headers["content-disposition"]


def test_a_run_can_be_stopped_and_keeps_nothing(rig):
    rig.app_state.training.step_s = 0.05
    ds = ready_dataset(rig)
    run = rig.post(f"{BASE}/runs", json={"dataset_id": ds["id"]}).json()
    assert rig.post(f"{BASE}/runs/{run['id']}/cancel").json() == {"cancelled": True}
    got = rig.get(f"{BASE}/runs/{run['id']}").json()
    assert got["status"] == "cancelled" and got["model_id"] is None
    assert rig.get(f"{BASE}/models").json()["models"] == []
    assert rig.post(f"{BASE}/runs/{run['id']}/cancel").json() == {"cancelled": False}


def test_a_trained_model_is_found_by_its_name_and_magic_word_and_can_be_renamed_and_deleted(rig):
    ds = ready_dataset(rig)
    run = rig.post(f"{BASE}/runs", json={"dataset_id": ds["id"]}).json()
    done = wait(rig, f"/runs/{run['id']}", lambda r: r["status"] != "working")
    index = rig.app_state.creation_index.items
    kind, text = index[done["model_id"]]
    assert kind == "lora" and "Marlo" in text and "marlo" in text
    r = rig.patch(f"{BASE}/models/{done['model_id']}", json={"name": "Marlo the fox"})
    assert r.json()["name"] == "Marlo the fox" and "fox" in index[done["model_id"]][1]
    assert rig.delete(f"{BASE}/models/{done['model_id']}").status_code == 204
    assert done["model_id"] not in index
    assert rig.get(f"{BASE}/models/{done['model_id']}").status_code == 404


def test_deleting_a_set_removes_its_pictures(rig, tmp_path):
    ds = new_dataset(rig)
    add_picture(rig, ds["id"])
    assert list((tmp_path / "training" / "files").rglob("picture.png"))
    assert rig.delete(f"{BASE}/datasets/{ds['id']}").status_code == 204
    assert not list((tmp_path / "training" / "files").rglob("picture.png"))
    assert rig.get(f"{BASE}/datasets").json()["datasets"] == []


def test_a_run_left_working_by_a_closed_app_is_failed_when_the_store_opens(tmp_path):
    store = TrainingStore.in_folder(tmp_path / "training")
    ds = store.add_dataset("t1", "u1", "style", "Ink")
    run = store.add_run("t1", "u1", ds["id"], base="b", steps=10, settings={}, preview=True)
    store.add_item(
        "t1", "u1", ds["id"], name="a", width=1, height=1, sha256="x", dhash=0, checks=[]
    )
    again = TrainingStore.in_folder(tmp_path / "training")
    got = again.get_run("t1", "u1", run["id"])
    assert got["status"] == "failed" and got["error"] == LEFT_RUNNING
    # a late failure does not undo a finished run
    store.finish_run(run["id"], "done")
    assert store.get_run("t1", "u1", run["id"])["status"] == "failed"


def test_the_trained_models_are_a_kind_of_creation_in_the_database_search_reads(tmp_path):
    store = TrainingStore.in_folder(tmp_path / "training")
    store.add_model(
        "t1",
        "u1",
        run_id="r",
        dataset_id=None,
        name="Marlo",
        trigger_word="marlo",
        kind="character",
        base="b",
        card={},
        preview=True,
        adapter_bytes=4,
    )
    db = sqlite3.connect(Path(tmp_path / "training" / "training.db"))
    assert db.execute("SELECT name, trigger_word FROM models").fetchall() == [("Marlo", "marlo")]


# ---- usage ------------------------------------------------------------------------------------


def test_pictures_and_runs_are_counted_and_nothing_limits_the_next(rig):
    ds = ready_dataset(rig)
    run = rig.post(f"{BASE}/runs", json={"dataset_id": ds["id"]}).json()
    wait(rig, f"/runs/{run['id']}", lambda r: r["status"] != "working")
    events = [(e.kind, e.quantity, e.unit) for e in rig.app_state.usage.events]
    assert events.count(("train.picture", 1, "pictures")) == 8
    assert ("train.run", 1, "runs") in events
    again = rig.post(f"{BASE}/runs", json={"dataset_id": ds["id"]})
    assert again.status_code == 202, again.text


def test_a_picture_is_never_checked_but_its_usage_is_recorded(rig):
    ds = new_dataset(rig)
    assert add_picture(rig, ds["id"]).status_code == 201
    assert [e.kind for e in rig.app_state.usage.events] == ["train.picture"]


def test_the_steps_follow_the_number_of_pictures_between_the_preset_and_a_ceiling():
    from wasifyai_training import trainer

    # 14 passes over the pictures, never fewer steps than the preset, never more than 500
    assert trainer.steps_for("character", 11) == 200  # 154 passes-worth: the preset holds
    assert trainer.steps_for("character", 25) == 350
    assert trainer.steps_for("character", 37) == 500  # 518 would be 14 passes: the ceiling
    assert trainer.steps_for("character", 80) == 500
    assert trainer.steps_for("style", 15) == 250 and trainer.steps_for("object", 8) == 150
    # a character is taught at 512 pixels (6 s a step), the others at 768 (10 s a step)
    assert trainer.side_for("character") == 512 and trainer.side_for("style") == 768
    assert trainer.estimate_words(500, "character") == "About 50 minutes"
    assert trainer.estimate_words(500, "object") == "About 83 minutes"


def test_a_set_says_what_teaching_it_would_take_and_the_run_keeps_the_side(rig):
    ds = ready_dataset(rig, pictures=8)
    got = rig.get(f"{BASE}/datasets/{ds['id']}").json()
    assert got["steps"] == 200 and got["estimate"] == "About 20 minutes"
    run = rig.post(f"{BASE}/runs", json={"dataset_id": ds["id"]}).json()
    assert run["steps"] == 200 and run["settings"]["side"] == 512


def test_a_runs_kind_is_found_from_the_start_of_its_id(tmp_path):
    """The image screens' styles name Train's runs by their first 8 characters (ADR-0091)."""
    from wasifyai_training.store import TrainingStore

    store = TrainingStore.in_folder(tmp_path)
    store.add_model(
        "t1", "u1", run_id="b37ba287f9604199b22047e56ad709ce", dataset_id=None, name="Ena",
        trigger_word="gabrin", kind="character", base="flux2-klein-base-4b", card={},
        preview=False, adapter_bytes=1,
    )  # fmt: skip
    assert store.taught_in_run("b37ba287") == {"kind": "character", "word": "gabrin"}
    assert store.taught_in_run("00000000") is None
    assert store.taught_in_run("b37%") is None  # not a run id: nothing is matched
