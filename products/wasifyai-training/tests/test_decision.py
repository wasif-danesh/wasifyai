"""Teach it to decide: the questions, the checks, the report, and a run with a fake engine."""

from training_rig import BASE, wait
from wasifyai_training import bases, decision
from wasifyai_training.decision import Option, Question, Row, Said

D = f"{BASE}/decision"
TEAMS = [
    {"label": "billing", "about": "payments, invoices, refunds"},
    {"label": "bug", "about": "things that do not work"},
    {"label": "other", "about": ""},
]


def category() -> Question:
    return Question("category", "Which team?", tuple(Option(o["label"], o["about"]) for o in TEAMS))


# ---- the question and its answers ---------------------------------------------------------------


def test_a_question_is_checked_before_anything_else():
    assert (Question("yes_no", "").problem() or "").startswith("Write the question")
    assert (Question("category", "Which?", (Option("a"),)).problem() or "").startswith(
        "Give at least two"
    )
    assert "same name" in (
        Question("category", "Which?", (Option("a"), Option("A"))).problem() or ""
    )
    assert "between 3 and 10" in (Question("score", "How?", levels=1).problem() or "")
    many = tuple(Option(f"c{i}") for i in range(13))
    assert "12 categories or fewer" in (Question("category", "Which?", many).problem() or "")
    assert Question("yes_no", "Is it good?").problem() is None
    assert category().problem() is None


def test_a_typed_answer_is_one_of_the_questions_answers_or_nothing():
    yes = Question("yes_no", "Is it good?")
    assert [yes.canon(x) for x in ("Yes", " no ", "TRUE", "0", "maybe", "")] == [
        "yes", "no", "yes", "no", None, None,
    ]  # fmt: skip
    cat = category()
    assert cat.canon(" Billing ") == "billing" and cat.canon("sales") is None
    score = Question("score", "How angry?", levels=5)
    assert [score.canon(x) for x in ("3", "5.0", "0", "6", "x")] == ["3", "5", None, None, None]
    assert score.answers() == ["1", "2", "3", "4", "5"]


def test_the_question_is_asked_in_the_models_own_format():
    assert Question("yes_no", " Is it good? ").laya() == {
        "type": "noul",
        "instructions": "Is it good?",
    }
    assert category().laya()["criteria"] == {
        "billing": "payments, invoices, refunds", "bug": "things that do not work", "other": "",
    }  # fmt: skip
    score = Question("score", "How angry?", levels=4, low="calm", high="furious").laya()
    assert score["type"] == "score" and score["criteria"] == [
        "calm",
        "2 out of 4",
        "3 out of 4",
        "furious",
    ]
    assert Question("yes_no", "x").expected("yes") is True
    assert Question("score", "x", levels=5).expected("4") == 3  # the model counts from 0
    assert category().expected("bug") == "bug"


def test_what_the_model_said_is_read_as_an_answer_and_how_sure_it_is():
    cat = category().read(
        {"choice": "bug", "probabilities": {"billing": 0.1, "bug": 0.8, "other": 0.1}}
    )
    assert (cat.answer, cat.confidence) == ("bug", 0.8) and cat.shares["billing"] == 0.1
    yes = Question("yes_no", "x").read({"noul": 0.9857})
    assert yes.answer == "yes" and yes.confidence == 0.9857 and round(yes.shares["no"], 4) == 0.0143
    no = Question("yes_no", "x").read({"noul": 0.2})
    assert no.answer == "no" and no.confidence == 0.8
    score = Question("score", "x", levels=5).read({"probabilities": {"0": 0.0, "1": 0.9, "2": 0.1}})
    assert score.answer == "2" and score.confidence == 0.9  # level index 1 is the score 2


# ---- the examples ------------------------------------------------------------------------------


def test_clean_leaves_out_what_cannot_be_used_and_says_so():
    q = category()
    rows, said = decision.clean(q, [
        {"text": "charged twice", "answer": " Billing "},
        {"text": "charged twice", "answer": "billing"},
        {"text": "crash", "answer": "bug"}, {"text": "", "answer": "bug"},
        {"text": "hello", "answer": "sales"}, {"text": "hi", "answer": "SALES"},
    ])  # fmt: skip
    assert [(r.text, r.answer) for r in rows] == [("charged twice", "billing"), ("crash", "bug")]
    assert any("1 row has a text or an answer missing" in s for s in said)
    assert any(
        "2 rows have an answer that is not one of the options" in s and "sales" in s for s in said
    )
    assert any("1 repeated row" in s for s in said)


def test_the_checks_say_what_to_fix_in_words():
    q = category()

    def many(n: int, share=(1, 1, 1)) -> list[Row]:
        out = []
        for i in range(n):
            out.append(Row(f"text {i}", ("billing", "bug", "other")[i % 3]))
        return out

    assert decision.checks(q, many(5))[0]["message"].startswith(
        "Add at least 20 examples. You have 5."
    )
    same = [Row(f"t{i}", "bug") for i in range(30)]
    assert "same answer (bug)" in decision.checks(q, same)[0]["message"]
    few = decision.checks(q, many(30))
    assert few[0]["level"] == "warn" and "Only 30 examples" in few[0]["message"]
    ok = decision.checks(q, many(90))
    assert ok == [{"level": "ok", "code": "ok", "message": "90 examples, ready."}]
    lopsided = [Row(f"t{i}", "billing") for i in range(90)] + [Row("x", "bug"), Row("y", "other")]
    msgs = " ".join(c["message"] for c in decision.checks(q, lopsided))
    assert "98 percent of the examples answer “billing”" in msgs
    assert "“bug” has only 1 example" in msgs
    clash = many(90) + [Row("text 0", "bug")]
    assert "1 text appears more than once with different answers" in " ".join(
        c["message"] for c in decision.checks(q, clash)
    )
    private = many(90)
    private[0] = Row("write to me at a@b.com", "bug")
    assert "personal data" in " ".join(c["message"] for c in decision.checks(q, private))
    assert decision.blocker(q, many(5)) is not None and decision.blocker(q, many(90)) is None


def test_the_texts_to_check_on_are_a_fifth_of_every_answer_and_always_the_same():
    q = category()
    rows = [Row(f"text {i}", ("billing", "bug", "other")[i % 3]) for i in range(60)]
    train, held = decision.split(rows)
    assert len(held) == 12 and len(train) == 48
    assert sorted(set(r.answer for r in held)) == ["billing", "bug", "other"]
    assert all(sum(r.answer == a for r in held) == 4 for a in q.answers())
    assert decision.split(rows) == (train, held)
    assert not {r.text for r in train} & {r.text for r in held}
    big = [Row(f"t{i}", ("a", "b")[i % 2]) for i in range(2000)]
    assert len(decision.split(big)[1]) == decision.MAX_HELD


def test_the_steps_are_a_few_passes_and_never_too_few_or_too_many():
    assert decision.plan_steps(40, "quick") == (4, 20)  # a small set gets more passes
    epochs, steps = decision.plan_steps(1000, "better")
    assert epochs == 6 and steps == 6 * 113  # 900 learnt on + a tenth kept back for confidence
    assert decision.plan_steps(5000, "quick")[1] <= decision.MAX_STEPS


# ---- the report --------------------------------------------------------------------------------


def said(answer: str, confidence: float = 0.9) -> Said:
    return Said(answer, confidence, {answer: confidence})


def test_the_report_counts_right_answers_mix_ups_and_whether_the_confidence_holds():
    q = category()
    held = [Row(f"t{i}", a) for i, a in enumerate(["billing"] * 4 + ["bug"] * 4 + ["other"] * 2)]
    after = [said("billing")] * 3 + [said("bug", 0.9)] + [said("bug")] * 4 + [said("other")] * 2
    before = [said("other", 0.4)] * 10
    base = ["billing"] * 4 + ["other"] * 4 + ["other"] * 2
    r = decision.report(q, held, before, after, base)
    assert r["right"] == {"before": 2, "after": 9, "word_counter": 6, "exactly": 9}
    assert r["percent"]["after"] == 90 and r["passed"] is True
    assert (
        "right 9 times (90 percent)" in r["note"]
        and "Counting words alone was right 6" in r["note"]
    )
    assert r["per_answer"][0] == {"answer": "billing", "of": 4, "right": 3}
    assert r["mix_ups"] == [{"right": "billing", "said": "bug", "times": 1}]
    assert r["confidence"]["sure_right"] == 9 and "9 of 10" in r["confidence"]["note"]
    assert (
        len(r["wrong"]) == 1
        and r["wrong"][0]["right"] == "billing"
        and r["wrong"][0]["said"] == "bug"
    )


def test_a_sorter_that_does_worse_than_counting_words_does_not_pass():
    q = category()
    held = [Row(f"t{i}", "billing" if i % 2 else "bug") for i in range(10)]
    bad = [said("other")] * 10
    r = decision.report(q, held, bad, bad, [h.answer for h in held])
    assert (
        r["passed"] is False
        and "did not pass" in r["note"]
        and "word counter did better" in r["note"]
    )
    assert decision.report(q, [], [], [], [])["passed"] is None


def test_a_score_counts_a_level_off_by_one_as_right():
    q = Question("score", "How angry?", levels=5)
    held = [Row("a", "3"), Row("b", "4"), Row("c", "1")]
    r = decision.report(
        q, held, [said("1")] * 3, [said("4"), said("4"), said("5")], ["3", "3", "3"]
    )
    assert r["right"]["after"] == 2 and r["right"]["exactly"] == 1 and "one level off" in r["note"]


def test_the_word_counter_learns_from_words_alone():
    rows = [Row("refund my payment", "billing"), Row("invoice is wrong", "billing"),
            Row("app crashes on start", "bug"), Row("the page crashes", "bug")]  # fmt: skip
    c = decision.WordCounter(rows)
    assert (
        c.predict("another refund please") == "billing" and c.predict("it crashes again") == "bug"
    )


# ---- the bases ---------------------------------------------------------------------------------


def test_the_decision_models_are_taught_as_a_whole_and_say_why_not_as_an_adapter():
    d = bases.descriptors("decision")
    assert [x.id for x in d] == ["laya-english", "laya-multilingual"]
    got = bases.choices("decision", {"verdict": "fits"}, True, [])
    assert got["family"] == "decision" and got["default_method"] == "full"
    by = {m["id"]: m for m in got["bases"][0]["methods"]}
    assert (
        by["full"]["can"]
        and not by["lora"]["can"]
        and "all of it is taught" in by["lora"]["reason"]
    )
    chosen, how = bases.resolve("decision", None, None)
    assert chosen.id == "laya-english" and how == "full"


# ---- the sets and runs, through the routes -------------------------------------------------------


def make_set(
    rig, n: int = 60, rights: str = "mine", name: str = "Messages", kind: str = "category"
) -> dict:
    s = rig.post(f"{D}/sets", json={"name": name})
    assert s.status_code == 201, s.text
    sid = s.json()["id"]
    body = {"kind": kind, "question": "Which team should handle this message?", "options": TEAMS}
    assert rig.patch(f"{D}/sets/{sid}", json=body).status_code == 200
    rows = [
        {"text": f"{TEAMS[i % 3]['label']} message number {i}", "answer": TEAMS[i % 3]["label"]}
        for i in range(n)
    ]
    assert rig.put(f"{D}/sets/{sid}/examples", json={"rows": rows}).status_code == 200
    if rights:
        assert rig.patch(f"{D}/sets/{sid}", json={"rights": rights}).status_code == 200
    return rig.get(f"{D}/sets/{sid}").json()


def run_to_end(rig, sid: str) -> dict:
    started = rig.post(f"{D}/sets/{sid}/runs")
    assert started.status_code == 202, started.text
    return wait(rig, f"/runs/{started.json()['id']}", lambda r: r["status"] != "working")


def test_the_status_names_the_model_to_teach_and_how_it_is_taught(rig):
    s = rig.get(f"{D}/status").json()
    assert (
        s["ready"] is True
        and s["min_examples"] == 20
        and s["kinds"] == ["yes_no", "category", "score"]
    )
    first = s["choices"]["bases"][0]
    assert first["id"] == "laya-english" and first["recommended"] and first["can_teach"]
    assert s["choices"]["default_method"] == "full"


def test_a_set_keeps_its_question_and_examples_and_says_what_is_missing(rig):
    s = rig.post(f"{D}/sets", json={"name": "Messages"}).json()
    assert s["missing"].startswith("Write the question")
    sid = s["id"]
    got = rig.patch(
        f"{D}/sets/{sid}", json={"kind": "category", "question": "Which team?", "options": TEAMS}
    ).json()
    assert got["missing"].startswith("Add at least 20 examples") and got["answers"] == [
        "billing",
        "bug",
        "other",
    ]
    full = make_set(rig, n=60)
    assert full["examples"] == 60 and full["missing"] is None
    assert (
        full["plan"]["counts"] == {"billing": 20, "bug": 20, "other": 20}
        and full["plan"]["held_back"] == 12
    )
    assert rig.patch(f"{D}/sets/{sid}", json={"kind": "maybe"}).status_code == 422
    assert rig.patch(f"{D}/sets/{sid}", json={"quality": "best"}).status_code == 422
    assert rig.patch(f"{D}/sets/{sid}", json={"rights": "theirs"}).status_code == 422
    assert rig.patch(f"{D}/sets/{sid}", json={"base": "gpt"}).status_code == 422
    yes = rig.patch(f"{D}/sets/{sid}", json={"kind": "yes_no"}).json()
    assert yes["answers"] == [
        "yes",
        "no",
    ]  # the same texts, now with answers that are not yes or no


def test_sets_belong_to_their_owner(rig):
    sid = make_set(rig)["id"]
    other = {"x-user": "u2"}
    assert rig.get(f"{D}/sets/{sid}", headers=other).status_code == 404
    assert rig.get(f"{D}/sets", headers=other).json()["sets"] == []
    assert rig.delete(f"{D}/sets/{sid}", headers=other).status_code == 204
    assert rig.get(f"{D}/sets/{sid}").status_code == 200
    assert rig.delete(f"{D}/sets/{sid}").status_code == 204
    assert rig.get(f"{D}/sets/{sid}").status_code == 404


def test_a_run_refuses_what_is_not_ready_in_words(rig):
    few = make_set(rig, n=8)
    refused = rig.post(f"{D}/sets/{few['id']}/runs")
    assert refused.status_code == 422 and "at least 20" in refused.json()["detail"]["message"]
    nobody = make_set(rig, rights="")
    refused = rig.post(f"{D}/sets/{nobody['id']}/runs")
    assert (
        refused.status_code == 422
        and "whose these texts are" in refused.json()["detail"]["message"]
    )


def test_a_run_leaves_a_model_with_a_report_and_a_mark(rig):
    sid = make_set(rig, n=60)["id"]
    run = run_to_end(rig, sid)
    assert run["status"] == "done" and run["progress"] == 1 and run["model_id"]
    assert run["settings"]["family"] == "decision" and run["settings"]["method"] == "full"
    model = rig.get(f"{BASE}/models/{run['model_id']}").json()
    assert model["kind"] == "decision" and model["base"] == "laya-english"
    card = model["card"]
    assert card["dataset"]["examples"] == 60 and card["engine"] == "fake-laya"
    assert card["question"]["text"] == "Which team should handle this message?"
    rep = card["report"]
    assert rep["texts"] == 12 and rep["right"]["after"] == 12 and rep["percent"]["after"] == 100
    assert rep["right"]["before"] < rep["right"]["after"] and card["evaluation"]["passed"] is True
    assert "right 12 times (100 percent)" in card["evaluation"]["note"]
    peek = card["peek"][0]
    assert peek["before"]["confidence"] == 0.4 and peek["after"]["confidence"] == 0.95
    assert card["statement"]  # the person's statement of whose they are travels with the model


def test_a_failed_run_says_so_and_a_stopped_one_keeps_nothing(rig):
    engine = rig.app_state.decision_training
    sid = make_set(rig)["id"]
    engine.fail_with = "boom"
    run = run_to_end(rig, sid)
    assert run["status"] == "failed" and run["error"] == "The model could not be taught. Try again."
    engine.fail_with = None
    engine.hold.clear()
    started = rig.post(f"{D}/sets/{sid}/runs").json()
    wait(rig, f"/runs/{started['id']}", lambda r: r["step"] >= 1)
    assert rig.post(f"{BASE}/runs/{started['id']}/cancel").json() == {"cancelled": True}
    run = wait(rig, f"/runs/{started['id']}", lambda r: r["status"] != "working")
    assert run["status"] == "cancelled" and run["model_id"] is None


def test_only_one_run_at_a_time_across_pictures_writing_and_deciding(rig):
    engine = rig.app_state.decision_training
    sid = make_set(rig)["id"]
    engine.hold.clear()
    first = rig.post(f"{D}/sets/{sid}/runs").json()
    wait(rig, f"/runs/{first['id']}", lambda r: r["step"] >= 1)
    second = rig.post(f"{D}/sets/{sid}/runs")
    assert second.status_code == 409 and "being taught" in second.json()["detail"]["message"]
    assert rig.get(f"{D}/status").json()["busy"] is True
    # a writing run is refused too, and so is a question to a taught model
    writing = rig.post(f"{BASE}/writing/sets", json={"name": "W"}).json()["id"]
    rows = [{"ask": f"Q{i}?", "answer": f"A{i}"} for i in range(12)]
    rig.put(f"{BASE}/writing/sets/{writing}/examples", json={"rows": rows})
    rig.patch(f"{BASE}/writing/sets/{writing}", json={"rights": "mine"})
    assert rig.post(f"{BASE}/writing/sets/{writing}/runs").status_code == 409
    rig.post(f"{BASE}/runs/{first['id']}/cancel")
    wait(rig, f"/runs/{first['id']}", lambda r: r["status"] != "working")


def test_a_missing_model_is_said_in_words_with_the_way_to_get_it(rig):
    engine = rig.app_state.decision_training
    engine.missing = frozenset({"laya-multilingual"})
    sid = make_set(rig)["id"]
    rig.patch(f"{D}/sets/{sid}", json={"base": "laya-multilingual"})
    got = rig.get(f"{D}/sets/{sid}").json()
    assert (
        got["missing"]
        == "Laya (many languages) is not on this computer yet. Get it first, next to its name."
    )
    refused = rig.post(f"{D}/sets/{sid}/runs")
    assert refused.status_code == 409 and "Get it first" in refused.json()["detail"]["message"]


def test_a_taught_model_answers_one_text_beside_the_untaught_one_and_many_in_a_batch(rig):
    sid = make_set(rig)["id"]
    mid = run_to_end(rig, sid)["model_id"]
    one = rig.post(f"{D}/models/{mid}/ask", json={"text": "my bug report"})
    assert one.status_code == 200, one.text
    got = one.json()
    assert got["mine"]["answer"] == "bug" and got["mine"]["confidence"] == 0.95
    assert got["original"]["answer"] == "billing" and got["original"]["confidence"] == 0.4
    assert got["answers"] == ["billing", "bug", "other"]
    many = rig.post(
        f"{D}/models/{mid}/sort", json={"texts": ["a billing issue", "something other", "  "]}
    )
    rows = many.json()["results"]
    assert [r["answer"] for r in rows] == ["billing", "other", "billing"] and len(rows) == 3
    assert rig.post(f"{D}/models/{mid}/sort", json={"texts": []}).status_code == 422
    assert rig.post(f"{D}/models/{'0' * 32}/ask", json={"text": "x"}).status_code == 404
    # a model of another kind is not a decision model
    other = {"x-user": "u2"}
    assert rig.post(f"{D}/models/{mid}/ask", json={"text": "x"}, headers=other).status_code == 404


def test_a_decision_model_is_found_in_search_by_its_name_and_its_question(rig):
    sid = make_set(rig, name="Support messages")["id"]
    mid = run_to_end(rig, sid)["model_id"]
    kind, text = rig.app_state.creation_index.items[mid]
    assert kind == "lora" and "support messages" in text.lower() and "decision" in text.lower()
    assert "which team should handle this message" in text.lower()


def test_a_model_gone_from_disk_is_said_so(rig):
    import shutil

    sid = make_set(rig)["id"]
    mid = run_to_end(rig, sid)["model_id"]
    store = rig.app_state.training_store
    folder = next(store.folder.rglob("model.safetensors")).parent
    shutil.rmtree(folder)
    gone = rig.post(f"{D}/models/{mid}/ask", json={"text": "x"})
    assert gone.status_code == 404 and gone.json()["detail"]["code"] == "gone"
