# ruff: noqa: E501  (test data is easier to read on one line)
"""A coding session that only reads, against the real Agent Server inside its sandbox (stage C1b
of docs/v2-coding-agent-start-plan.md; section 8's contract test). Opt-in, with the hostile tests:

    make test-coding            # CODING_E2E=1 pytest .../integration/test_coding_s*.py

The server is the real, pinned one, started by this engine's own supervisor on a throwaway data
folder. The gateway is the real one, on a loopback port of its own. The place is the real one
(`wasifyai_code/client.py`). **The model is scripted**: a small program on this computer that
speaks the provider's API and answers what each test tells it to, so the tests cost nothing, need
no network and say the same thing every time. What a real model does is the gate's business
(`docs/spikes/coding-c1b.md`).

What is checked here:

    the contract    the live API description still gives the excerpt we generated our types from
    the tools       a session that only reads offers the model no tool that writes or runs
    it cannot       a write is refused three ways: by the tool, by the plan file's folder, and
                    by the sandbox for anything the server itself runs
    the stream      steps, results, words and one end, through the live socket
    a refusal       the gateway's plain message ends the turn as "refused", not as "stuck"
    Stop            within a second, while the model is being waited for
    the key         it reaches the provider and is found nowhere inside the sandbox

With `CODING_RECORD=1` the event streams of these scripted turns are written to
`tests/fixtures/coding/`, which is what the fake Agent Server replays in `make test`.
"""

import asyncio
import hashlib
import http.server
import importlib.util
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from wasifyai_api.coding_gateway import ANTHROPIC, CodingGateway, ModelRoute, serve_alone
from wasifyai_api.coding_server import SANDBOX_EXEC, CodingServer, find_install
from wasifyai_code import place as places
from wasifyai_code.client import READ_TOOLS, WRITE_TOOLS, ThisComputer
from wasifyai_code.place import Account, SessionSpec
from wasifyai_platform_sdk.secrets import InMemorySecretStore
from wasifyai_platform_sdk.usage import InMemoryUsageRecorder

REPO = Path(__file__).resolve().parents[4]
FILES = REPO / "services" / "coding-engine"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "coding"
APP_DATA = Path(
    os.environ.get("CODING_E2E_DATA")
    or Path.home() / "Library/Application Support/ai.wasifyai.desktop"
)
KEY = "sk-ant-scripted-" + "k" * 40  # stands for the person's key: it must stay outside
RECORD = os.environ.get("CODING_RECORD") == "1"

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("CODING_E2E") != "1", reason="opt-in: CODING_E2E=1 (make test-coding)"
    ),
    pytest.mark.skipif(
        sys.platform != "darwin" or not Path(SANDBOX_EXEC).is_file(),
        reason="the coding engine's sandbox is the Mac's",
    ),
    pytest.mark.asyncio(loop_scope="module"),
]


# ---- a scripted model ----------------------------------------------------------------------------


def use(tool: str, **given: Any) -> dict[str, Any]:
    return {"tool": tool, "given": given}


def say(text: str) -> dict[str, Any]:
    return {"text": text}


REFUSE = {"refuse": True}


class Model:
    """A provider on loopback that speaks the Messages API and answers from a script. Each
    session's first user message picks the script: `#script:<name>`."""

    def __init__(self) -> None:
        self.scripts: dict[str, list[dict[str, Any]]] = {}
        self.requests: list[dict[str, Any]] = []
        self.keys: set[str] = set()
        self.hold = threading.Event()  # set: the next answer waits until it is cleared
        self._lock = threading.Lock()
        model = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:
                size = int(self.headers.get("content-length") or 0)
                body = json.loads(self.rfile.read(size) or b"{}")
                model.keys.add(self.headers.get("x-api-key") or "")
                with model._lock:
                    model.requests.append(body)
                while model.hold.is_set():  # a model that is slow to answer
                    time.sleep(0.05)
                answer = model.answer(body)
                data = model.stream(answer) if body.get("stream") else model.whole(answer)
                kind = "text/event-stream" if body.get("stream") else "application/json"
                try:
                    self.send_response(200)
                    self.send_header("content-type", kind)
                    self.send_header("content-length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass  # the caller went away (it was interrupted)

            def log_message(self, format: str, *args: object) -> None:
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.hold.clear()
        self.server.shutdown()

    def answer(self, body: dict[str, Any]) -> dict[str, Any]:
        """The next line of the session's script: how many tool results the conversation holds
        says how far it is."""
        if not body.get("tools"):
            return say("A coding session")  # the engine asking for a title
        text = json.dumps(body.get("messages") or [])
        name = next((n for n in self.scripts if f"#script:{n}" in text), None)
        if name is None:
            return say("No script was named.")
        done = text.count('"tool_result"')
        script = self.scripts[name]
        return script[min(done, len(script) - 1)]

    @staticmethod
    def _message(answer: dict[str, Any]) -> dict[str, Any]:
        usage = {
            "input_tokens": 1200, "output_tokens": 40, "cache_read_input_tokens": 9000,
            "cache_creation_input_tokens": 300,
        }  # fmt: skip
        base = {
            "id": "msg_scripted",
            "type": "message",
            "role": "assistant",
            "model": "scripted-1",
            "usage": usage,
        }
        if answer.get("refuse"):
            details = {
                "type": "refusal",
                "category": "cyber",
                "explanation": "I can't help with that.",
            }
            return {**base, "content": [], "stop_reason": "refusal", "stop_details": details}
        if "tool" in answer:
            block = {
                "type": "tool_use", "id": f"toolu_{hashlib.sha1(os.urandom(8)).hexdigest()[:16]}",
                "name": answer["tool"], "input": answer["given"],
            }  # fmt: skip
            return {**base, "content": [block], "stop_reason": "tool_use"}
        return {
            **base,
            "content": [{"type": "text", "text": answer["text"]}],
            "stop_reason": "end_turn",
        }

    def whole(self, answer: dict[str, Any]) -> bytes:
        return json.dumps(self._message(answer)).encode()

    def stream(self, answer: dict[str, Any]) -> bytes:
        message = self._message(answer)
        out: list[dict[str, Any]] = [
            {"type": "message_start", "message": {**message, "content": [], "stop_reason": None}}
        ]
        for index, block in enumerate(message["content"]):
            if block["type"] == "text":
                words = block["text"].split(" ")
                out.append(
                    {
                        "type": "content_block_start",
                        "index": index,
                        "content_block": {"type": "text", "text": ""},
                    }
                )
                for n, word in enumerate(words):
                    piece = word if n == len(words) - 1 else word + " "
                    out.append(
                        {
                            "type": "content_block_delta",
                            "index": index,
                            "delta": {"type": "text_delta", "text": piece},
                        }
                    )
            else:
                start = {**block, "input": {}}
                out.append({"type": "content_block_start", "index": index, "content_block": start})
                out.append(
                    {
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {
                            "type": "input_json_delta",
                            "partial_json": json.dumps(block["input"]),
                        },
                    }
                )
            out.append({"type": "content_block_stop", "index": index})
        delta: dict[str, Any] = {"stop_reason": message["stop_reason"], "stop_sequence": None}
        if "stop_details" in message:
            delta["stop_details"] = message["stop_details"]
        out.append({"type": "message_delta", "delta": delta, "usage": {"output_tokens": 40}})
        out.append({"type": "message_stop"})
        return b"".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode() for e in out)


# ---- the engine's parts, for real ------------------------------------------------------------------


class Real:
    def __init__(self, data: Path, project: Path, model: Model):
        self.data, self.project, self.model = data, project, model
        self.server = CodingServer(data, FILES)
        self.secrets = InMemorySecretStore()
        self.usage = InMemoryUsageRecorder()
        self.address = ""
        route = ModelRoute(
            id="scripted", title="A scripted model", where="this-computer", shape=ANTHROPIC,
            provider="scripted", engine_model="anthropic/scripted-1", provider_model="scripted-1",
            upstream=model.url, secret="keys.chat.anthropic",
            price={"input": 2.0, "output": 10.0, "cache_read": 0.1, "cache_write": 2.5},
            engine_settings={"num_retries": 0},
        )  # fmt: skip
        self.gateway = CodingGateway(
            secrets=self.secrets, usage=self.usage, base_url=lambda: self.address,
            models=("scripted", {"scripted": route}),
        )  # fmt: skip
        self.place = ThisComputer(self.server, self.gateway)

    def spec(self, session: str, **more: Any) -> SessionSpec:
        more.setdefault("read_only", True)
        return SessionSpec(
            self.project, model="scripted",
            account=Account("t1", "wasifyai-code", "u1", session), **more,
        )  # fmt: skip

    async def turn(self, session: str, text: str, after: str | None = None, seconds: float = 90):
        """Listen, send, and read the turn to its end: the events, and the server's own."""
        opened = asyncio.Event()
        stream = self.place.follow(session, after=after, opened=opened)
        first = asyncio.ensure_future(anext(stream))
        seen = []
        try:
            async with asyncio.timeout(seconds):
                await opened.wait()
                await self.place.send(session, text, run=True)
                event = await first
                while True:
                    seen.append(event)
                    if event.kind == places.ENDED:
                        return seen
                    event = await anext(stream)
        finally:
            first.cancel()
            await stream.aclose()

    async def raw_events(self, session: str) -> list[dict[str, Any]]:
        """Every event the server kept for a conversation, as it sent them."""
        items: list[dict[str, Any]] = []
        page = None
        while True:
            query = "?limit=100&sort_order=TIMESTAMP" + (f"&page_id={page}" if page else "")
            r = await self.server.request(
                "GET", f"/api/conversations/{session}/events/search{query}", timeout=30
            )
            body = r.json()
            items += body["items"]
            page = body.get("next_page_id")
            if not page:
                return items

    async def sh(self, command: str) -> tuple[int, str]:
        r = await self.server.request(
            "POST", "/api/bash/execute_bash_command",
            json={"command": command, "cwd": str(self.server.run_dir / "workspace"), "timeout": 30},
            timeout=60,
        )  # fmt: skip
        body = r.json()
        return int(body.get("exit_code") or 0), (body.get("stdout") or "") + (
            body.get("stderr") or ""
        )


def tree(folder: Path) -> dict[str, str]:
    """Every file of a folder with its content's hash, and every folder: what "nothing was
    written" is checked against."""
    out = {}
    for path in sorted(folder.rglob("*")):
        name = str(path.relative_to(folder))
        out[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "folder"
    return out


@pytest.fixture(scope="module")
async def real(tmp_path_factory):
    if find_install(APP_DATA) is None:
        pytest.fail(
            f"The coding engine is not set up in {APP_DATA}. Set it up in the app (Settings, "
            "Optional parts), or point CODING_E2E_DATA at a data folder that has it."
        )
    data = tmp_path_factory.mktemp("coding-data")
    (data / "engine").mkdir()
    (data / "engine" / "coding").symlink_to(APP_DATA / "engine" / "coding")
    project = tmp_path_factory.mktemp("bakery-site")
    (project / "shop").mkdir()
    (project / "app.py").write_text("from shop.prices import total\n\nprint(total([1, 2]))\n")
    (project / "shop" / "prices.py").write_text("def total(xs):\n    return sum(xs)\n")
    (project / "README.md").write_text("# Bakery site\n\nOpening hours are in `shop/hours.py`.\n")
    model = Model()
    box = Real(data, project, model)
    await box.secrets.put("keys.chat.anthropic", KEY)
    async with serve_alone(box.gateway) as address:
        box.address = address
        try:
            yield box
        finally:
            await box.server.close()
            await box.gateway.close()
            model.close()


def record(name: str, real: Real, events: list[dict[str, Any]], task: str) -> None:
    """Keep one turn's events, as the server sent them, for the fake server to replay."""
    if not RECORD:
        return
    info = {"SystemPromptEvent", "LLMCompletionLogEvent", "TokenEvent"}
    kept = []
    for event in events:
        if event.get("kind") in info or event.get("source") == "user":
            continue  # the engine's own long instructions and the person's message are not ours to keep
        text = json.dumps(event)
        for path, mark in (
            (str(real.project), "{{WORKSPACE}}"),
            (str(real.server.plan_file), "{{PLAN}}"),
            (str(real.data), "{{DATA}}"),
        ):
            text = text.replace(path, mark)
        kept.append({"event": json.loads(text)})
    version = (FILES / "VERSION").read_text().strip()
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / f"{name}.json").write_text(
        json.dumps(
            {
                "recorded_from": f"openhands-agent-server {version} in its sandbox, with a scripted model, through the gateway",
                "task": task,
                "events": kept,
            },
            indent=1,
        )
        + "\n"
    )


def turn_events(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The events of the last turn: from the last time the conversation began to run."""
    starts = [
        n for n, e in enumerate(raw)
        if e.get("kind") == "ConversationStateUpdateEvent" and e.get("value") == "running"
    ]  # fmt: skip
    return raw[starts[-1] :] if starts else raw


# ---- the contract ----------------------------------------------------------------------------------


async def test_the_live_api_description_still_gives_the_excerpt_our_types_are_made_from(real):
    await real.server.ensure_running((), (real.project,))
    spec = importlib.util.spec_from_file_location(
        "gen", REPO / "scripts" / "coding-engine-types.py"
    )
    assert spec is not None and spec.loader is not None
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    live = (await real.server.request("GET", "/openapi.json", timeout=30)).json()
    assert generator.excerpt_of(live) == json.loads(generator.EXCERPT.read_text())
    assert generator.check() == []


# ---- a session that only reads ---------------------------------------------------------------------


async def test_a_session_that_only_reads_is_offered_no_tool_that_writes_or_runs(real):
    real.model.scripts["look"] = [
        use("glob", pattern="**/*.py", path=str(real.project)),
        use("planning_file_editor", command="view", path=str(real.project / "app.py")),
        use("finish", message="It is a small Python project: app.py uses shop/prices.py."),
    ]
    before = tree(real.project)
    session = await real.place.start(real.spec("s-look"))
    events = await real.turn(session, "Analyse this codebase. #script:look")
    # what the model was offered: the three tools that read, and the engine's own way to finish
    asked = [r for r in real.model.requests if r.get("tools")][-1]
    offered = {t["name"] for t in asked["tools"]}
    assert set(READ_TOOLS) <= offered
    assert not offered & set(WRITE_TOOLS), offered
    assert offered - set(READ_TOOLS) <= {"finish", "think"}, offered
    assert "only reads" in json.dumps(asked.get("system"))
    kinds = [e.kind for e in events if e.kind != places.PIECE]
    assert kinds == [
        places.STATE, places.STEP, places.RESULT, places.STEP, places.RESULT,
        places.TEXT, places.STATE, places.ENDED,
    ]  # fmt: skip
    steps = [e for e in events if e.kind == places.STEP]
    assert [s.data["tool"] for s in steps] == ["glob", "planning_file_editor"]
    results = [e for e in events if e.kind == places.RESULT]
    assert all(r.data["ok"] for r in results) and "prices.py" in results[0].data["text"]
    assert "from shop.prices import total" in results[1].data["text"]
    said = [e.data["text"] for e in events if e.kind == places.TEXT]
    assert said == ["It is a small Python project: app.py uses shop/prices.py."]
    assert events[-1].data == {"why": places.FINISHED, "detail": "", "steps": 2}
    assert tree(real.project) == before  # nothing was written
    record("analyse", real, turn_events(await real.raw_events(session)), "Analyse this codebase.")


async def test_it_cannot_write_whatever_it_tries(real):
    plan = str(real.server.plan_file)
    real.model.scripts["write"] = [
        use(
            "planning_file_editor",
            command="create",
            path=str(real.project / "notes.txt"),
            file_text="hello",
        ),
        use(
            "planning_file_editor",
            command="str_replace",
            path=str(real.project / "app.py"),
            old_str="total",
            new_str="sum",
        ),
        use("planning_file_editor", command="create", path=plan, file_text="my plan"),
        use("terminal", command="touch made-by-the-agent.txt"),
        use("file_editor", command="create", path=str(real.project / "other.txt"), file_text="x"),
        use("finish", message="I could not write anything."),
    ]
    before, plan_before = tree(real.project), real.server.plan_file.read_text()
    session = await real.place.start(real.spec("s-write"))
    events = await real.turn(session, "Write some files. #script:write")
    results = [e for e in events if e.kind == places.RESULT]
    assert len(results) == 5 and not any(r.data["ok"] for r in results), [r.data for r in results]
    assert events[-1].data["why"] == places.FINISHED
    assert tree(real.project) == before
    assert real.server.plan_file.read_text() == plan_before
    assert not list(real.project.glob("made-by-the-agent*"))
    record("write-refused", real, turn_events(await real.raw_events(session)), "Write some files.")


async def test_the_sandbox_refuses_a_write_to_a_workspace_that_is_only_read(real):
    await real.place.open_folder(real.project)
    before = tree(real.project)
    # the server's own command endpoint: how any command of the engine would run
    code, out = await real.sh(f"cat '{real.project}/README.md'")
    assert code == 0 and "Bakery site" in out  # reading works
    for command in (
        f"echo x > '{real.project}/made.txt'",
        f"echo x >> '{real.project}/app.py'",
        f"rm '{real.project}/app.py'",
        f"mkdir '{real.project}/new-folder'",
        f"python3 -c \"open('{real.project}/py.txt', 'w').write('x')\"",
        f"echo x > '{real.server.plan_file}'",
        f"rm '{real.server.plan_file}'",
    ):
        _, said = await real.sh(f"{command}; echo exit=$?")
        assert "exit=0" not in said, f"not refused: {command}: {said}"
        assert "not permitted" in said or "Permission" in said or "Read-only" in said, said
    assert tree(real.project) == before


async def test_a_refusal_ends_the_turn_as_refused_and_not_as_stuck(real):
    real.model.scripts["refuse"] = [REFUSE]
    session = await real.place.start(real.spec("s-refuse"))
    events = await real.turn(session, "Do something it will not. #script:refuse")
    assert events[-1].data["why"] == places.REFUSED
    assert events[-1].data["detail"] == "The model declined this request. I can't help with that."
    said = [e.data["text"] for e in events if e.kind == places.TEXT]
    assert said == ["The model declined this request. I can't help with that."]
    # one call was enough: the engine did not nudge an empty answer three times
    calls = [
        r
        for r in real.model.requests
        if r.get("tools") and "#script:refuse" in json.dumps(r.get("messages"))
    ]  # with tools: the engine's own call for a title has none
    assert len(calls) == 1
    record(
        "refusal",
        real,
        turn_events(await real.raw_events(session)),
        "A request the model declines.",
    )


async def test_the_step_limit_ends_a_turn_that_would_go_on(real):
    real.model.scripts["loop"] = [use("grep", pattern="TODO", path=str(real.project))]
    session = await real.place.start(real.spec("s-loop", step_limit=3))
    events = await real.turn(session, "Search for ever. #script:loop")
    assert events[-1].data["why"] == places.STEP_LIMIT, events[-1].data
    record(
        "step-limit",
        real,
        turn_events(await real.raw_events(session)),
        "A turn that reaches its step limit.",
    )


async def test_stop_works_within_a_second_while_the_model_is_waited_for(real):
    real.model.scripts["slow"] = [use("glob", pattern="*", path=str(real.project)), say("Done.")]
    session = await real.place.start(real.spec("s-slow"))
    opened = asyncio.Event()
    stream = real.place.follow(session, opened=opened)
    seen: list = []

    async def read():
        async for event in stream:
            seen.append(event)
            if event.kind == places.ENDED:
                return event

    reading = asyncio.ensure_future(read())
    await opened.wait()
    real.model.hold.set()
    try:
        await real.place.send(session, "Look around. #script:slow", run=True)
        await asyncio.sleep(2.0)  # the engine is waiting for the model
        began = time.monotonic()
        await real.place.stop(session)
        ended = await asyncio.wait_for(reading, 10)
        took = time.monotonic() - began
    finally:
        real.model.hold.clear()
    assert ended is not None and ended.data["why"] == places.STOPPED
    assert took < 1.0, took
    # and it answers the next message
    real.model.scripts["again"] = [say("Here again.")]
    again = await real.turn(session, "And now? #script:again", after=ended.id)
    assert again[-1].data["why"] == places.FINISHED


async def test_words_arrive_as_they_are_written_through_the_gateway(real):
    real.model.scripts["words"] = [say("One two three four five six seven eight nine ten.")]
    session = await real.place.start(real.spec("s-words"))
    events = await real.turn(session, "Count. #script:words")
    pieces = [
        e.data["text"] for e in events if e.kind == places.PIECE and not e.data.get("thinking")
    ]
    assert (
        len(pieces) >= 3 and "".join(pieces) == "One two three four five six seven eight nine ten."
    )
    assert [e.data["text"] for e in events if e.kind == places.TEXT][-1].startswith("One two three")


async def test_each_call_is_counted_and_the_key_is_found_nowhere_inside_the_sandbox(real):
    spent = real.gateway.spent("s-look")
    assert spent["calls"] >= 3 and spent["usd"] > 0 and spent["input_tokens"] > 0
    assert {e.meta["session_id"] for e in real.usage.events} >= {"s-look", "s-write"}
    assert real.model.keys == {KEY}  # the provider got the key, from the gateway
    # ... and the engine never did: not in a file it wrote, not in its log, not in its environment
    for folder in (real.server.run_dir, real.data / "logs", real.data / "coding-fixed"):
        for path in folder.rglob("*"):
            if path.is_file():
                assert KEY.encode() not in path.read_bytes(), path
    _, env = await real.sh("env; cat /proc/self/environ 2>/dev/null; true")
    assert KEY not in env
    # what it does hold is the session's token, which opens one session's model calls and nothing else
    assert "wcg-" not in env
