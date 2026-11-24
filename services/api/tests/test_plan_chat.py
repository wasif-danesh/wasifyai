"""The chat on the person's own plan (ADR-0110): the conversation as text, the programs' events,
a round on a pretended program, the choice, the provider's routing and, on a Mac, the sandbox."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from wasifyai_api import plan_tools_server
from wasifyai_api.coding_harness import HARNESSES
from wasifyai_api.plan_chat import (
    SANDBOX_EXEC,
    PlanChat,
    PlanChoice,
    PlanChoiceStore,
    PlanTextProvider,
    Reader,
    mcp_tools,
    said_of,
    transcript,
    valid_choice,
)
from wasifyai_platform_sdk import ChatChunk, RunError
from wasifyai_platform_sdk.context import RunContext, reset_context, set_context

TOOL = {
    "type": "function",
    "function": {
        "name": "propose_action",
        "description": "Ask to run an action.",
        "parameters": {"type": "object", "properties": {"action_id": {"type": "string"}}},
    },
}


def test_the_conversation_becomes_instructions_and_one_prompt():
    system, prompt = transcript(
        [
            {"role": "system", "content": "Be kind."},
            {"role": "user", "content": [{"type": "text", "text": "A cat, please"},
                                         {"type": "image_url", "image_url": {"url": "x"}}]},
            {"role": "assistant", "content": "Making it.", "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "propose_action", "arguments": '{"action_id": "x"}'}}]},
            {"role": "tool", "tool_call_id": "c1", "name": "propose_action", "content": "made"},
        ]
    )  # fmt: skip
    assert system == "Be kind."
    assert "[The person]\nA cat, please" in prompt
    assert "a picture is attached here" in prompt  # a picture is said, never sent
    assert '[You called the tool propose_action with]\n{"action_id": "x"}' in prompt
    assert "[What propose_action answered]\nmade" in prompt
    assert prompt.endswith("[Your reply]")


def test_the_chats_tools_become_mcp_tools():
    assert mcp_tools([TOOL]) == [
        {
            "name": "propose_action",
            "description": "Ask to run an action.",
            "inputSchema": {"type": "object", "properties": {"action_id": {"type": "string"}}},
        }
    ]
    assert mcp_tools(None) == []


def test_the_tool_server_lists_the_tools_and_runs_nothing():
    tools = mcp_tools([TOOL])
    init = plan_tools_server.answer(
        {"id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}, tools
    )
    assert init and init["result"]["capabilities"] == {"tools": {}}
    listed = plan_tools_server.answer({"id": 2, "method": "tools/list"}, tools)
    assert listed and listed["result"]["tools"] == tools
    called = plan_tools_server.answer({"id": 3, "method": "tools/call", "params": {}}, tools)
    assert called and "Wasify AI runs this call" in called["result"]["content"][0]["text"]
    assert plan_tools_server.answer({"method": "notifications/initialized"}, tools) is None


def test_claude_codes_events_give_text_thinking_and_the_call():
    r = Reader("claude-code")

    def delta(kind: str, key: str, text: str) -> dict:
        return {"type": "stream_event", "event": {"type": "content_block_delta",
                                                  "delta": {"type": kind, key: text}}}  # fmt: skip

    assert r.feed(delta("thinking_delta", "thinking", "hmm")) == [ChatChunk(reasoning="hmm")]
    assert r.feed(delta("text_delta", "text", "Making it.")) == [ChatChunk(text="Making it.")]
    use = {"type": "tool_use", "id": "toolu_1", "name": "mcp__wasify__propose_action",
           "input": {"action_id": "image.generate"}}  # fmt: skip
    assert r.feed({"type": "assistant", "message": {"content": [use]}}) == []
    r.feed({"type": "assistant", "message": {"content": [use]}})  # said twice: kept once
    assert not r.stop
    r.feed({"type": "user", "message": {"content": []}})
    assert r.stop
    assert [(c.id, c.name, json.loads(c.arguments)) for c in r.calls] == [
        ("toolu_1", "propose_action", {"action_id": "image.generate"})
    ]


def test_claude_codes_refusal_is_kept_in_its_words():
    r = Reader("claude-code")
    r.feed({"type": "result", "subtype": "success", "is_error": True,
            "result": "Claude AI usage limit reached"})  # fmt: skip
    assert r.done and r.error == "Claude AI usage limit reached"
    assert said_of(HARNESSES["claude-code"], r.error) == (
        "Claude Code said: Claude AI usage limit reached"
    )
    assert "is not signed in" in said_of(
        HARNESSES["claude-code"], "Not logged in · Please run /login"
    )


def test_codexs_events_give_text_and_the_call():
    r = Reader("codex")
    out = r.feed({"type": "item.completed", "item": {"type": "agent_message", "text": "Sure."}})
    assert out == [ChatChunk(text="Sure.")]
    r.feed({"type": "item.started", "item": {"id": "item_2", "type": "mcp_tool_call",
            "server": "wasify", "tool": "propose_action", "arguments": {"action_id": "x"}}})  # fmt: skip  # noqa: E501
    assert r.stop and [(c.name, c.arguments) for c in r.calls] == [
        ("propose_action", '{"action_id": "x"}')
    ]
    failed = Reader("codex")
    failed.feed({"type": "turn.failed", "error": {"message": "You've hit your usage limit."}})
    assert failed.done and failed.error == "You've hit your usage limit."


def test_the_choice_is_kept_and_only_a_known_one(tmp_path: Path):
    store = PlanChoiceStore(tmp_path)
    assert store.get() is None
    store.set(PlanChoice("claude-code", "sonnet"))
    assert store.get() == PlanChoice("claude-code", "sonnet")
    store.set(None)
    assert store.get() is None
    assert valid_choice("claude-code", "opus") == PlanChoice("claude-code", "opus")
    assert valid_choice("codex", "") == PlanChoice("codex", "")
    assert valid_choice("codex", "o3") is None  # only what the chat offers
    assert valid_choice("gemini", "") is None  # no Google program (the owner, 2026-11-24)
    (tmp_path / "chat-plan.json").write_text("{not json")
    assert store.get() is None


# ---- a round on a pretended program --------------------------------------------------------------

FAKE = """#!{python}
import json, os, sys
argv = sys.argv[1:]
prompt = sys.stdin.read()
out = lambda e: print(json.dumps(e), flush=True)
with open(os.path.join(os.environ["TMPDIR"], "..", "seen.json"), "w") as f:
    json.dump({{"argv": argv, "prompt": prompt, "env": sorted(os.environ)}}, f)
out({{"type": "system", "subtype": "init"}})
out({{"type": "stream_event", "event": {{"type": "content_block_delta",
     "delta": {{"type": "text_delta", "text": "On it."}}}}}})
if "{mode}" == "call":
    out({{"type": "assistant", "message": {{"content": [{{"type": "tool_use", "id": "toolu_9",
         "name": "mcp__wasify__propose_action", "input": {{"action_id": "image.generate"}}}}]}}}})
    out({{"type": "user", "message": {{"content": []}}}})
    import time; time.sleep(30)  # it would go on: it must be stopped
elif "{mode}" == "refuse":
    out({{"type": "result", "subtype": "success", "is_error": True, "result": "limit reached"}})
else:
    out({{"type": "result", "subtype": "success", "is_error": False, "result": "On it."}})
"""


def pretend_install(data: Path, mode: str) -> None:
    base = data / "engine" / "harness"
    root = base / "1"
    program = root / "node_modules" / Path(*HARNESSES["claude-code"].program)
    program.parent.mkdir(parents=True)
    program.write_text(FAKE.format(python=sys.executable, mode=mode))
    program.chmod(program.stat().st_mode | stat.S_IEXEC)
    adapter = "node_modules/adapter.js"
    (root / adapter).write_text("")
    (base / "state.json").write_text(
        json.dumps({"schema": 1, "version": "1", "dir": "1", "adapters": {"claude-code": adapter}})
    )


async def run_round(data: Path, tools=None) -> list[ChatChunk]:
    plan = PlanChat(data, home=data / "home", sandbox=False)
    msgs = [{"role": "system", "content": "Be kind."}, {"role": "user", "content": "A cat"}]
    return [c async for c in plan.run(PlanChoice("claude-code", "sonnet"), msgs, tools)]


async def test_a_round_streams_the_text_then_the_call_and_stops_the_program(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    pretend_install(tmp_path, "call")
    monkeypatch.setenv("WASIFY_TEST_SECRET", "never-given")
    seen: list[Path] = []
    import wasifyai_api.plan_chat as pc

    real = pc.shutil.rmtree

    def keep(path, *a, **k):  # read what the program saw before its folder goes
        seen.append(Path(path))
        f = Path(path) / "seen.json"
        if f.is_file():
            (tmp_path / "seen.json").write_text(f.read_text())
        real(path, *a, **k)

    monkeypatch.setattr(pc.shutil, "rmtree", keep)
    chunks = await run_round(tmp_path, [TOOL])
    assert chunks[0] == ChatChunk(text="On it.")
    calls = chunks[-1].tool_calls
    assert [(c.id, c.name) for c in calls] == [("toolu_9", "propose_action")]
    said = json.loads((tmp_path / "seen.json").read_text())
    argv = said["argv"]
    assert argv[argv.index("--tools") + 1] == ""  # none of its own tools
    assert argv[argv.index("--allowedTools") + 1] == "mcp__wasify"
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert "--strict-mcp-config" in argv and "--setting-sources" in argv
    assert argv[argv.index("--system-prompt") + 1] == "Be kind."
    assert "[The person]\nA cat" in said["prompt"]
    assert "WASIFY_TEST_SECRET" not in said["env"]  # nothing of the engine's environment
    assert seen and not seen[0].exists()  # the round's folder is gone


async def test_a_plain_answer_ends_with_no_call(tmp_path: Path):
    pretend_install(tmp_path, "answer")
    chunks = await run_round(tmp_path)
    assert [c.text for c in chunks] == ["On it."]


async def test_a_refusal_is_said_in_the_programs_words(tmp_path: Path):
    pretend_install(tmp_path, "refuse")
    with pytest.raises(RunError) as e:
        await run_round(tmp_path)
    assert e.value.message == "Claude Code said: limit reached"


async def test_a_program_not_set_up_is_said(tmp_path: Path):
    with pytest.raises(RunError) as e:
        await run_round(tmp_path)
    assert e.value.code == "plan_not_set_up" and "Claude Code is not set up" in e.value.message


# ---- the provider --------------------------------------------------------------------------------


class Inner:
    def __init__(self) -> None:
        self.asked = 0

    async def chat(self, capability, binding, messages, tools=None, thinking=False):
        self.asked += 1
        yield ChatChunk(text="local")


async def answers(provider: PlanTextProvider, product: str) -> list[str]:
    token = set_context(RunContext(tenant_id="t", product_id=product, user_id="u"))
    try:
        return [c.text async for c in provider.chat("text.chat", None, [], None)]  # type: ignore[arg-type]
    finally:
        reset_context(token)


async def test_only_the_assistants_chat_follows_the_plan(tmp_path: Path):
    pretend_install(tmp_path, "answer")
    inner = Inner()
    plan = PlanChat(tmp_path, home=tmp_path / "home", sandbox=False)
    provider = PlanTextProvider(inner, plan)
    assert await answers(provider, "wasifyai-assistant") == ["local"]  # no plan chosen
    plan.choices.set(PlanChoice("claude-code"))
    assert await answers(provider, "wasifyai-assistant") == ["On it."]
    assert await answers(provider, "wasifyai-notebooks") == ["local"]  # other products keep theirs
    assert inner.asked == 2


# ---- the sandbox, on a Mac -----------------------------------------------------------------------


@pytest.mark.skipif(not Path(SANDBOX_EXEC).exists(), reason="sandbox-exec is a Mac tool")
def test_the_sandbox_closes_the_home_folder_and_the_apps_data(tmp_path: Path):
    data = Path(os.path.realpath(tmp_path)) / "data"
    pretend_install(data, "answer")
    home = Path(os.path.realpath(tmp_path)) / "home"
    (home / ".claude").mkdir(parents=True)
    (home / "Documents").mkdir()
    (home / "Documents" / "private.txt").write_text("private")
    (home / ".claude" / "own.json").write_text("{}")
    plan = PlanChat(data, home=home, sandbox=True)
    work = data / "chat-plan" / "probe"
    work.mkdir(parents=True)
    argv, _, env = plan.command(PlanChoice("claude-code"), [], [], work)
    profile = argv[2]

    def can(*cmd: str) -> bool:
        return subprocess.run([SANDBOX_EXEC, "-f", profile, *cmd], env=env,
                              capture_output=True).returncode == 0  # fmt: skip

    assert not can("/bin/cat", str(home / "Documents" / "private.txt"))
    assert not can("/bin/ls", str(data / "engine"))  # the app's data, the program's folder aside
    assert not can("/usr/bin/touch", str(home / "left-behind"))
    assert can("/bin/cat", str(home / ".claude" / "own.json"))  # its own sign-in folder
    assert can("/usr/bin/touch", str(home / ".claude" / "written"))
    assert can("/usr/bin/touch", str(work / "written"))
