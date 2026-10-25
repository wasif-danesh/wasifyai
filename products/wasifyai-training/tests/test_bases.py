"""The choice of base model and method (ADR-0073, amendment 2026-10-24): what can be chosen, what is
listed with a reason, and that a run records what was chosen."""

import time

from training_rig import BASE, ready_dataset
from wasifyai_training import bases, trainer


def done(rig, run_id: str) -> dict:
    row: dict = {}
    for _ in range(400):
        row = rig.get(f"{BASE}/runs/{run_id}").json()
        if row["status"] in ("done", "failed"):
            return row
        time.sleep(0.02)
    raise AssertionError(row)


def test_the_choices_name_the_recommendation_and_say_why_a_method_cannot_be_used(rig):
    got = rig.get(f"{BASE}/choices?kind=style").json()
    assert got["family"] == "image"
    assert got["default_base"] == trainer.BASE and got["default_method"] == "lora"
    first = got["bases"][0]
    assert first["recommended"] and first["can_teach"] and first["licence"] == "Apache-2.0"
    by_id = {m["id"]: m for m in first["methods"]}
    assert by_id["lora"]["can"] and by_id["lora"]["technical"] == "LoRA"
    # QLoRA and full fine-tuning are listed, with the reason, not hidden
    assert not by_id["qlora"]["can"] and "writing models" in by_id["qlora"]["reason"]
    assert not by_id["full"]["can"] and by_id["full"]["advanced"] and by_id["full"]["reason"]


def test_an_installed_model_with_no_descriptor_is_listed_as_not_teachable_yet():
    found = [
        {"kind": "diffusion", "name": "Some other model", "licence": "MIT"},
        {"kind": "language", "name": "A chat model"},  # not a picture model: not listed
    ]
    rows = bases.choices("character", {"verdict": "fits"}, True, found)["bases"]
    other = [r for r in rows if r["title"] == "Some other model"]
    assert len(other) == 1 and not other[0]["can_teach"] and other[0]["id"] == ""
    assert "cannot be taught yet" in other[0]["reason"]
    assert all(r["title"] != "A chat model" for r in rows)


def test_a_base_that_does_not_fit_or_is_not_set_up_says_so():
    too_big = bases.choices("style", {"verdict": "too_big", "reason": "Needs 35 GB."}, True, [])
    assert not too_big["bases"][0]["can_teach"] and "35 GB" in too_big["bases"][0]["reason"]
    unset = bases.choices("style", None, False, [])
    assert not unset["bases"][0]["can_teach"] and "Set up training" in unset["bases"][0]["reason"]


def test_a_run_with_no_choice_uses_the_recommendation_and_records_it(rig):
    ds = ready_dataset(rig, pictures=8)
    run = rig.post(f"{BASE}/runs", json={"dataset_id": ds["id"]}).json()
    assert run["settings"]["method"] == "lora" and run["settings"]["engine"] == "mflux"
    assert run["base"] == trainer.BASE
    row = done(rig, run["id"])
    assert row["status"] == "done"
    model = rig.get(f"{BASE}/models/{row['model_id']}").json()
    assert model["card"]["settings"]["method"] == "lora"
    assert model["card"]["settings"]["engine"] == "mflux"


def test_a_choice_that_cannot_be_used_is_refused_with_the_reason(rig):
    ds = ready_dataset(rig, pictures=8)
    for body, words in (
        ({"method": "qlora"}, "writing models"),
        ({"method": "full"}, "memory"),
        ({"base": "some-other-model"}, "cannot be taught yet"),
        ({"method": "dora"}, "small adapter"),
    ):
        refused = rig.post(f"{BASE}/runs", json={"dataset_id": ds["id"], **body})
        assert refused.status_code in (409, 422), body
        assert words in str(refused.json()), body
    # the refusals left nothing running
    assert rig.get(f"{BASE}/status").json()["busy"] is False


def test_the_recommended_choice_can_be_named_outright(rig):
    ds = ready_dataset(rig, pictures=8)
    run = rig.post(
        f"{BASE}/runs", json={"dataset_id": ds["id"], "base": trainer.BASE, "method": "lora"}
    )
    assert run.status_code == 202
    assert done(rig, run.json()["id"])["status"] == "done"
