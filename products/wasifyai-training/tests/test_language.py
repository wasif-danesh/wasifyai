"""The examples of a writing model: what is dropped and said, how they split, the steps."""

import json

from wasifyai_training import language


def rows(n: int, prefix: str = "q") -> list[dict[str, str]]:
    return [{"ask": f"{prefix} {i}?", "answer": f"Answer {i}. - Wasi"} for i in range(n)]


def test_empty_and_repeated_rows_are_left_out_and_said_in_words():
    got, said = language.clean(
        [*rows(3), {"ask": "", "answer": "x"}, {"ask": "q 0?", "answer": "answer 0. - wasi"}]
    )
    assert [e.ask for e in got] == ["q 0?", "q 1?", "q 2?"]
    assert any("1 row has a question or an answer missing" in s for s in said)
    assert any("1 repeated row" in s for s in said)


def test_too_few_examples_cannot_start_and_few_ones_are_warned_about():
    few, _ = language.clean(rows(4))
    assert "at least 10" in (language.blocker(few) or "")
    some, _ = language.clean(rows(30))
    assert language.blocker(some) is None
    assert [c["code"] for c in language.checks(some)] == ["few"]
    many, _ = language.clean(rows(60))
    assert [c["level"] for c in language.checks(many)] == ["ok"]


def test_long_answers_and_personal_data_are_warned_about_not_refused():
    data = rows(60)
    data[0]["answer"] = "x" * (language.LONG_ANSWER + 1)
    data[1]["answer"] = "Write to me at someone@example.com"
    data[2]["ask"] = "Call +61 400 123 456 please"
    examples, _ = language.clean(data)
    codes = {c["code"]: c["message"] for c in language.checks(examples)}
    assert "long" in codes and "personal" in codes and "2 examples look" in codes["personal"]
    assert language.blocker(examples) is None


def test_the_split_keeps_a_tenth_with_a_fixed_seed_and_loses_nothing():
    examples, _ = language.clean(rows(50))
    train, valid = language.split(examples)
    assert len(valid) == 5 and len(train) == 45
    assert sorted(e.ask for e in train + valid) == sorted(e.ask for e in examples)
    assert language.split(examples) == (train, valid)  # the same set splits the same way
    small, _ = language.clean(rows(10))
    assert len(language.split(small)[1]) == 2  # at least two to check on
    big, _ = language.clean(rows(500))
    assert len(language.split(big)[1]) == 20  # at most twenty


def test_the_records_are_chat_messages_the_trainer_reads():
    examples, _ = language.clean(rows(2))
    first = json.loads(language.jsonl(examples).splitlines()[0])
    assert first == {
        "messages": [
            {"role": "user", "content": "q 0?"},
            {"role": "assistant", "content": "Answer 0. - Wasi"},
        ]
    }


def test_the_steps_are_a_few_passes_between_a_floor_and_a_ceiling():
    assert language.steps_for(10, "quick") == 30  # the floor: what learnt a style in the spike
    assert language.steps_for(45, "quick") == 69  # 23 batches of 2, three passes
    assert language.steps_for(45, "better") == 138
    assert language.steps_for(5000, "better") == 600  # the ceiling


def test_the_test_questions_are_held_out_ones_first_and_not_repeated():
    examples, _ = language.clean(rows(20))
    train, valid = language.split(examples)
    asked = language.test_questions(train, valid)
    assert len(asked) == 3 and len(set(asked)) == 3
    assert asked[0] == valid[0].ask
