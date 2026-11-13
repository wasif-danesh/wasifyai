"""Did it learn? The pictures to draw, the verdicts, the sentence and the mark on the card."""

import io

from PIL import Image
from training_rig import BASE, ready_dataset, wait
from wasifyai_training import evaluation

REF = 3


def trained(rig) -> dict:
    ds = ready_dataset(rig, pictures=8)
    run = rig.post(f"{BASE}/runs", json={"dataset_id": ds["id"]}).json()
    done = wait(rig, f"/runs/{run['id']}", lambda r: r["status"] != "working")
    return rig.get(f"{BASE}/models/{done['model_id']}").json()


def test_each_scene_is_drawn_three_ways_so_one_thing_differs():
    plan = evaluation.check_plan("character", "marlo")
    assert len(plan) == 6
    by = {(p["scene"], p["condition"]): p for p in plan}
    with_word, without_word = by[(0, "with_word")], by[(0, "without_word")]
    base = by[(0, "without_model")]
    assert "marlo" in with_word["prompt"] and with_word["with_model"] is True
    assert "marlo" not in without_word["prompt"] and without_word["with_model"] is True
    assert base["prompt"] == with_word["prompt"] and base["with_model"] is False
    # the word first, as in the descriptions the model was taught with
    assert evaluation.check_plan("style", "tazur")[0]["prompt"].startswith("tazur,")


def verdicts(**yes):
    """Items as the screen sends them: how many of each kind of picture looked the same."""
    out = []
    for condition, (same, total) in yes.items():
        for n in range(total):
            out.append(
                {"id": f"{condition}-{n}", "condition": condition, "prompt": "p", "same": n < same}
            )
    return out


def test_it_passes_when_it_looks_like_the_pictures_only_with_what_was_taught():
    result = evaluation.summarize(
        "character", verdicts(with_word=(2, 2), without_model=(0, 2), without_word=(0, 2)), "now"
    )
    assert result["passed"] is True and result["counts"]["with_word"] == [2, 2]
    assert "2 of 2" in result["note"] and "did not pass" not in result["note"]


def test_it_does_not_pass_when_the_base_model_alone_already_looks_the_same():
    result = evaluation.summarize(
        "character", verdicts(with_word=(2, 2), without_model=(2, 2)), "now"
    )
    assert result["passed"] is False and "did not pass" in result["note"]


def test_it_does_not_pass_when_it_never_looks_like_them():
    result = evaluation.summarize("style", verdicts(with_word=(0, 2), without_model=(0, 2)), "now")
    assert result["passed"] is False and "your style" in result["note"]


def test_a_model_that_also_shows_up_without_its_word_is_said_to_be_strong_not_wrong():
    result = evaluation.summarize(
        "character", verdicts(with_word=(2, 2), without_model=(0, 2), without_word=(1, 2)), "now"
    )
    assert result["passed"] is True and "also shows up without the magic word" in result["note"]


def test_nothing_judged_is_not_a_failure():
    result = evaluation.summarize(
        "character", [{"id": "a", "condition": "with_word", "prompt": "p", "same": None}], "now"
    )
    assert result["passed"] is None and "reads pictures" in result["note"]


def test_a_finished_model_keeps_a_few_small_pictures_to_compare_with(rig, tmp_path):
    model = trained(rig)
    plan = rig.get(f"{BASE}/models/{model['id']}/check").json()
    assert plan["refs"] == REF and len(plan["items"]) == 6


def draw() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (64, 64), (10, 120, 200)).save(out, "PNG")
    return out.getvalue()


def test_a_picture_is_judged_against_the_ones_it_learnt_from(rig):
    model = trained(rig)
    got = rig.post(f"{BASE}/models/{model['id']}/judge", content=draw())
    assert got.status_code == 200 and got.json() == {"same": True, "reason": "x"}
    assert "judge_image" in rig.vision.asked


def test_without_a_picture_reading_model_it_says_what_to_do(rig):
    model = trained(rig)
    rig.vision.fail_judge = True
    got = rig.post(f"{BASE}/models/{model['id']}/judge", content=draw())
    assert got.status_code == 409 and got.json()["detail"]["code"] == "judge_failed"
    assert "reads pictures" in got.json()["detail"]["message"]


def test_a_file_that_is_not_a_picture_is_refused(rig):
    model = trained(rig)
    got = rig.post(f"{BASE}/models/{model['id']}/judge", content=b"not a picture")
    assert got.status_code in (409, 422)


def test_what_the_check_found_is_kept_on_the_card_as_a_sentence_and_a_mark(rig):
    model = trained(rig)
    body = {"items": verdicts(with_word=(2, 2), without_model=(0, 2))}
    got = rig.put(f"{BASE}/models/{model['id']}/evaluation", json=body)
    assert got.status_code == 200
    card = got.json()["card"]
    assert card["evaluation"]["passed"] is True and "2 of 2" in card["evaluation"]["note"]
    again = rig.get(f"{BASE}/models/{model['id']}").json()
    assert again["card"]["evaluation"]["at"]
    assert rig.put(f"{BASE}/models/{'0' * 32}/evaluation", json=body).status_code == 404


def test_nobody_else_can_check_or_mark_a_persons_model(rig):
    model = trained(rig)
    other = {"x-user": "intruder"}
    assert rig.get(f"{BASE}/models/{model['id']}/check", headers=other).status_code == 404
    assert (
        rig.post(f"{BASE}/models/{model['id']}/judge", content=draw(), headers=other).status_code
        == 404
    )
    assert (
        rig.put(
            f"{BASE}/models/{model['id']}/evaluation", json={"items": []}, headers=other
        ).status_code
        == 404
    )
