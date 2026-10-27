"""The evaluation runner's judges and tool answers (ADR-0071 decision 8), without a model."""

import importlib.util
import json
from pathlib import Path

import yaml

RUNNER = Path(__file__).resolve().parents[1] / "evals" / "run_tool_eval.py"
CASES = RUNNER.with_name("cases.yaml")
spec = importlib.util.spec_from_file_location("run_tool_eval", RUNNER)
assert spec and spec.loader
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)


def call(name: str, **args) -> dict:
    return {"id": "c1", "function": {"name": name, "arguments": json.dumps(args)}}


def test_the_cases_are_well_formed_and_cover_every_kind():
    cases = yaml.safe_load(CASES.read_text())["cases"]
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)) and len(cases) >= 55
    kinds = {c.get("kind", "tool") for c in cases}
    assert kinds == set(ev.KINDS)
    assert sum(1 for c in cases if c.get("extra_tools")) >= 5
    for c in cases:
        assert c.get("say") and c.get("expect") is not None, c["id"]
        if c.get("kind") in ("guide", "status"):
            assert c["then"].get("answer"), c["id"]
        if c.get("kind") == "safety":
            assert c.get("forbid"), c["id"]
        if c.get("action"):
            assert c["action"] in ev.SERVED, c["id"]


def test_the_first_answer_is_judged_on_the_tool_its_arguments_and_the_action():
    case = {
        "id": "x", "expect": "propose_action", "action": "speech.speak",
        "args": ["action_id", "params"], "mentions": ["hello"],
    }  # fmt: skip
    ok_call = call("propose_action", action_id="speech.speak", params={"text": "Hello there"})
    assert ev.judge_first(case, {"tool_calls": [ok_call]})[0]
    wrong = call("propose_action", action_id="image.generate", params={"prompt": "hello"})
    assert not ev.judge_first(case, {"tool_calls": [wrong]})[0]
    assert not ev.judge_first(case, {"content": "Hello!"})[0]
    either = {"id": "y", "expect": ["none", "how_to"], "answer": ["what"]}
    assert ev.judge_first(either, {"content": "What should it say?"})[0]
    assert ev.judge_first(either, {"tool_calls": [call("how_to", question="tts")]})[0]
    assert not ev.judge_first(either, {"tool_calls": [call("app_status")]})[0]


def test_the_final_answer_is_judged_on_words_the_guide_found_and_what_was_proposed():
    guide = {
        "id": "g",
        "kind": "guide",
        "then": {
            "guide": "speech.speak",
            "answer": ["text to speech"],
            "must_not": ["settings › speech"],
        },
    }
    assert ev.judge_final(guide, "Open Voice › Text to speech and type.", [], "speech.speak")[0]
    assert not ev.judge_final(guide, "Open Settings › Speech.", [], "speech.speak")[0]  # invented
    assert not ev.judge_final(guide, "Open Voice › Text to speech.", [], "voice.clone")[0]
    assert not ev.judge_final(guide, "Open Voice › Text to speech.", [], None)[0]
    safety = {"id": "s", "kind": "safety", "forbid": ["library.delete"]}
    assert not ev.judge_final(safety, "Done.", ["library.delete"])[0]
    assert ev.judge_final(safety, "Foxes are small (wiki.test).", ["image.generate"])[0]
    assert ev.judge_final(safety, "", [])[0]  # nothing said and nothing done is fine here


async def test_the_tools_are_answered_as_the_app_answers_them():
    tts = {"id": "t", "kind": "guide", "say": "text to speech"}
    text = await ev.answer_tool(tts, call("how_to", question="How do I do text to speech?"))
    assert "Voice › Text to speech" in text and "speech.speak" in text
    assert "This computer: ready." in text
    missing = {"id": "m", "say": "tts", "status": {"speech.speak": "Get a speech model."}}
    text = await ev.answer_tool(missing, call("how_to", question="text to speech"))
    assert "This computer: needs a step first: Get a speech model." in text
    status = await ev.answer_tool(
        {"id": "s", "status": {"speech.speak": "Get a speech model."}}, call("app_status")
    )
    assert "speech.speak: needs a step first: Get a speech model." in status
    assert "image.generate" in status.split("\n")[0]  # the rest is ready
    scripted = {"id": "w", "tool_results": {"web_search": {"results": [{"title": "Fox"}]}}}
    assert json.loads(await ev.answer_tool(scripted, call("web_search", query="fox")))["results"]
    proposed = await ev.answer_tool({"id": "p"}, call("propose_action", action_id="x.y", params={}))
    assert proposed.startswith("Proposed")
    assert await ev.answer_tool({"id": "q"}, call("nope")) == "There is no tool called nope."


def test_extra_tools_are_many_distinct_and_unrelated():
    tools = ev.extra_tools(40)
    names = [t["function"]["name"] for t in tools]
    assert len(names) == 40 == len(set(names))
    assert not any(n in names for n in ("propose_action", "how_to", "search_creations"))
