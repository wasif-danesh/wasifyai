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
import getpass
import hashlib
import http.server
import importlib.util
import json
import os
import platform
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from wasifyai_api.coding_gateway import ANTHROPIC, CodingGateway, ModelRoute, serve_alone
from wasifyai_api.coding_proxy import InstallProxy
from wasifyai_api.coding_server import SANDBOX_EXEC, CodingServer, find_install
from wasifyai_code import place as places
from wasifyai_code.checkpoints import CheckpointStore
from wasifyai_code.client import EDIT_TOOLS, READ_TOOLS, WRITE_TOOLS, ThisComputer
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
CHECK_FAILED = "The project's check did not pass"

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
        if CHECK_FAILED in text and f"{name}:after-check" in self.scripts:
            # the app sent a failed check back: the script for what the agent does then
            done = text.rsplit(CHECK_FAILED, 1)[1].count('"tool_result"')
            script = self.scripts[f"{name}:after-check"]
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
        self.proxy = InstallProxy()
        self.server = CodingServer(data, FILES, proxy=self.proxy)
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

    async def turn(
        self, session: str, text: str, after: str | None = None, seconds: float = 90,
        on_confirm: Any = None,
    ):  # fmt: skip
        """Listen, send, and read the turn to its end: the events, and the server's own.
        `on_confirm` is called with each `confirm` event (a session that edits waits there)."""
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
                    if event.kind == places.CONFIRM and on_confirm is not None:
                        await on_confirm(event)
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


def record(
    name: str, real: Real, events: list[dict[str, Any]], task: str, workspace: Path | None = None
) -> None:
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
            (str(workspace or real.project), "{{WORKSPACE}}"),
            (str(real.server.plan_file), "{{PLAN}}"),
            (str(real.data), "{{DATA}}"),
            # a command's result names the computer and the person: neither belongs in the repository
            (str((workspace or real.project).parent), "{{TMP}}"),
            (str(APP_DATA), "{{APP}}"),
            (str(Path.home()), "{{HOME}}"),
            (platform.node().split(".")[0], "this-computer"),
            (getpass.getuser(), "someone"),
        ):
            if path:
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


def whole_turn(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The events of the last turn of a session that waits in the middle: from the first time
    the conversation ran after the person's last message (it runs, waits, and runs again)."""
    said = [
        n
        for n, e in enumerate(raw)
        if e.get("kind") == "MessageEvent" and e.get("source") == "user"
    ]
    return raw[said[-1] + 1 :] if said else raw


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


# ---- a session that changes files (stage C2) -------------------------------------------------------


@pytest.fixture(scope="module")
def site(tmp_path_factory) -> Path:
    """A second project, for the sessions that may write."""
    project = tmp_path_factory.mktemp("hours-site")
    (project / "src").mkdir()
    (project / "src" / "home.html").write_text("<h1>Bakery</h1>\n<p>Welcome</p>\n")
    (project / "run.sh").write_text("#!/bin/sh\necho hi\n")
    (project / "run.sh").chmod(0o755)
    return project


def edit_spec(real: Real, site: Path, session: str) -> SessionSpec:
    return SessionSpec(
        site, model="scripted", read_only=False,
        account=Account("t1", "wasifyai-code", "u1", session),
    )  # fmt: skip


def files_of(folder: Path) -> dict[str, tuple[str, int]]:
    return {
        str(p.relative_to(folder)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mode)
        for p in sorted(folder.rglob("*")) if p.is_file()
    }  # fmt: skip


async def test_a_session_that_edits_waits_before_each_change_and_a_yes_lets_it_run(real, site):
    real.model.scripts["edit"] = [
        use("file_editor", command="view", path=str(site / "src" / "home.html")),
        use(
            "file_editor", command="str_replace", path=str(site / "src" / "home.html"),
            old_str="<p>Welcome</p>", new_str="<p>Open 9 to 5</p>",
        ),
        use("file_editor", command="create", path=str(site / "tests" / "home.test.js"), file_text="test('hours', () => {})\n"),
        use("finish", message="The hours are on the home page."),
    ]  # fmt: skip
    cps = CheckpointStore(real.data / "code" / "checkpoints" / "w-edit", site)
    was = files_of(site)
    before = cps.checkpoint("before the turn")
    session = await real.place.start(edit_spec(real, site, "s-edit"))
    asked: list[Any] = []

    async def yes(event: Any) -> None:
        asked.append(event)
        # nothing has run while it waits
        assert "Welcome" in (site / "src" / "home.html").read_text() or len(asked) > 1
        await real.place.answer(session, event.data["id"], True)

    events = await real.turn(session, "Add the opening hours. #script:edit", on_confirm=yes)
    assert events[-1].data["why"] == places.FINISHED, events[-1].data
    # the model was offered the tools of a session that edits, the terminal among them
    offered = {t["name"] for r in real.model.requests for t in r.get("tools") or []}
    assert set(EDIT_TOOLS) <= offered and "terminal" in offered and "apply_patch" not in offered
    # looking did not wait; each of the two changes did, and named its step
    assert [e.data["steps"][0]["command"] for e in asked] == ["str_replace", "create"]
    assert all(e.data["steps"][0]["tool"] == "file_editor" for e in asked)
    assert asked[0].data["steps"][0]["path"] == str(site / "src" / "home.html")
    results = [e for e in events if e.kind == places.RESULT]
    # (the new file is in a folder that was not there: the place made it when it said yes)
    assert len(results) == 3 and all(r.data["ok"] for r in results), [r.data for r in results]
    assert "Open 9 to 5" in (site / "src" / "home.html").read_text()
    assert (site / "tests" / "home.test.js").is_file()
    record(
        "edit-asked", real, whole_turn(await real.raw_events(session)), "Add the opening hours.",
        site,
    )  # fmt: skip
    # and every change is undone exactly, from a store the sandbox cannot reach
    after = cps.checkpoint("after the turn")
    assert {(c.path, c.what) for c in cps.changes(before.id, after.id)} == {
        ("src/home.html", "changed"), ("tests/home.test.js", "added"),
    }  # fmt: skip
    cps.undo(before.id)
    assert files_of(site) == was and not (site / "tests").exists()
    # the project had no git of its own, and the engine did not give it one
    assert not (site / ".git").exists()


async def test_a_no_leaves_the_file_and_the_agent_goes_on(real, site):
    real.model.scripts["no"] = [
        use("file_editor", command="create", path=str(site / "secret.txt"), file_text="x"),
        use("finish", message="I left it."),
    ]
    session = await real.place.start(edit_spec(real, site, "s-no"))

    async def no(event: Any) -> None:
        await real.place.answer(session, event.data["id"], False, "The person said no.")

    events = await real.turn(session, "Write a secret. #script:no", on_confirm=no)
    assert events[-1].data["why"] == places.FINISHED, events[-1].data
    (result,) = [e for e in events if e.kind == places.RESULT]
    assert result.data["ok"] is False and result.data["refused"] is True
    assert "said no" in result.data["text"] and not (site / "secret.txt").exists()
    assert [e.data["text"] for e in events if e.kind == places.TEXT][-1] == "I left it."
    record(
        "edit-refused", real, whole_turn(await real.raw_events(session)), "Write a secret.", site
    )


async def test_stop_while_a_change_waits_ends_the_turn_and_nothing_is_written(real, site):
    real.model.scripts["wait"] = [
        use("file_editor", command="create", path=str(site / "late.txt"), file_text="x"),
        use("finish", message="Done."),
    ]
    session = await real.place.start(edit_spec(real, site, "s-wait"))
    took: list[float] = []

    async def stop(event: Any) -> None:
        began = time.monotonic()
        await real.place.stop(session)
        took.append(time.monotonic() - began)

    events = await real.turn(session, "Write late. #script:wait", on_confirm=stop)
    assert events[-1].data["why"] == places.STOPPED, events[-1].data
    assert took and took[0] < 1.0 and not (site / "late.txt").exists()
    # the session can be sent to again
    real.model.scripts["again"] = [use("finish", message="Here.")]
    again = await real.turn(session, "Are you there? #script:again", after=events[-1].id)
    assert again[-1].data["why"] == places.FINISHED


async def test_a_session_that_edits_cannot_change_anything_outside_its_project(real, site):
    store = real.data / "code" / "checkpoints" / "w-edit"
    CheckpointStore(store, site).checkpoint("one")
    assert (store / "HEAD").is_file()
    outside = site.parent / "outside-the-project.txt"
    real.model.scripts["out"] = [
        use("file_editor", command="create", path=str(outside), file_text="x"),
        use("file_editor", command="create", path=str(store / "hooks" / "x"), file_text="x"),
        use("file_editor", command="view", path=str(store / "HEAD")),
        use("file_editor", command="create", path=str(real.project / "x.txt"), file_text="x"),
        use("finish", message="I could not."),
    ]
    session = await real.place.start(edit_spec(real, site, "s-out"))

    async def yes(event: Any) -> None:
        await real.place.answer(session, event.data["id"], True)

    read_only_before = tree(real.project)
    events = await real.turn(session, "Write elsewhere. #script:out", on_confirm=yes)
    results = [e for e in events if e.kind == places.RESULT]
    assert len(results) == 4 and not any(r.data["ok"] for r in results), [r.data for r in results]
    assert not outside.exists() and not (store / "hooks" / "x").exists()
    assert tree(real.project) == read_only_before  # a project that is only read stays so
    # whatever the engine runs: the checkpoint store can be neither read nor written
    for command in (f"cat '{store}/HEAD'", f"ls '{store}'", f"echo x > '{store}/HEAD'", f"rm '{store}/HEAD'"):  # fmt: skip
        _, said = await real.sh(f"{command}; echo exit=$?")
        assert "exit=0" not in said, f"not refused: {command}: {said}"
    assert (store / "HEAD").read_text().startswith("ref:")
    # inside its own project it does write
    code, _ = await real.sh(f"echo x > '{site}/by-the-engine.txt'; echo exit=$?")
    assert (site / "by-the-engine.txt").is_file()
    (site / "by-the-engine.txt").unlink()


# ---- a session that runs commands (stage C3) -------------------------------------------------------


def said_by(events: list[Any]) -> list[str]:
    return [e.data["text"] for e in events if e.kind == places.RESULT]


async def test_a_command_waits_then_runs_inside_the_sandbox_and_the_agent_may_make_a_repository(
    real, site
):
    outside = site.parent / "outside-by-a-command.txt"
    real.model.scripts["run"] = [
        use("terminal", command="printf made > made.txt && cat made.txt"),
        use("terminal", command="git init -q . && ls -d .git"),
        use("terminal", command=f"echo x > '{outside}'; echo exit=$?"),
        use("terminal", command=f"cat '{Path.home()}/.zshrc' '{real.data}/secrets.json'; echo exit=$?"),
        use("terminal", command="curl -sS -m 5 -o /dev/null https://example.com; echo exit=$?"),
        use("finish", message="Ran them."),
    ]  # fmt: skip
    session = await real.place.start(edit_spec(real, site, "s-run"))
    # opening the project did not make it a repository
    assert not (site / ".git").exists()
    asked: list[Any] = []

    async def yes(event: Any) -> None:
        asked.append(event)
        if len(asked) == 1:  # nothing has run while it waits
            assert not (site / "made.txt").exists()
        await real.place.answer(session, event.data["id"], True)

    events = await real.turn(session, "Run a few things. #script:run", on_confirm=yes)
    assert events[-1].data["why"] == places.FINISHED, events[-1].data
    assert [e.data["steps"][0]["tool"] for e in asked] == ["terminal"] * 5
    assert asked[0].data["steps"][0]["command"].startswith("printf made")
    said = said_by(events)
    assert "made" in said[0] and (site / "made.txt").read_text() == "made"
    # the agent asked for a repository, and got one
    assert ".git" in said[1] and (site / ".git").is_dir()
    # outside the project nothing is written and nothing of the person's is read
    assert "exit=0" not in said[2] and not outside.exists()
    assert "exit=0" not in said[3]
    # and no command reaches the network: it was not an install, so the proxy is closed to it
    assert "exit=0" not in said[4]
    record("run-commands", real, whole_turn(await real.raw_events(session)), "Run a few things.", site)  # fmt: skip
    import shutil

    shutil.rmtree(site / ".git")
    (site / "made.txt").unlink()


async def test_an_install_that_is_let_through_reaches_a_package_index_and_nothing_else(real, site):
    """This one test uses the network: one small page of the Python package index."""
    fetch = "curl -sS -m 20 -o /dev/null -w 'code=%{http_code}' "
    real.model.scripts["install"] = [
        use("terminal", command=f"{fetch}https://pypi.org/simple/six/; echo"),
        use("terminal", command=f"pip install --help > /dev/null; {fetch}https://pypi.org/simple/six/; echo"),
        use("terminal", command=f"{fetch}https://example.com/; echo"),
        use("finish", message="Done."),
    ]  # fmt: skip
    real.proxy.close_for_agent()
    session = await real.place.start(edit_spec(real, site, "s-install"))

    async def yes(event: Any) -> None:
        await real.place.answer(session, event.data["id"], True)

    events = await real.turn(session, "Install. #script:install", on_confirm=yes)
    assert events[-1].data["why"] == places.FINISHED, events[-1].data
    said = said_by(events)
    assert "code=200" not in said[0]  # not an install: the proxy is closed to the agent
    assert "code=200" in said[1], said[1]  # an install was let through: the index answers
    assert "code=200" not in said[2]  # a host that is not on the list, even now
    hosts = [(seen["host"], seen["ok"]) for seen in real.proxy.seen]
    assert ("pypi.org", True) in hosts and ("example.com", False) in hosts
    real.proxy.close_for_agent()


async def test_our_own_sandbox_for_a_project_holds_a_check_inside_it(real, site):
    wrapper, env = await real.place.sandbox(site)
    assert wrapper[0] == SANDBOX_EXEC and KEY not in json.dumps(env)
    outside = site.parent / "outside-by-a-check.txt"

    async def run(command: str) -> tuple[int, str]:
        proc = await asyncio.create_subprocess_exec(
            *wrapper, "/bin/sh", "-c", command, cwd=site, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )  # fmt: skip
        out, _ = await proc.communicate()
        return int(proc.returncode or 0), out.decode()

    code, said = await run(
        "echo inside > by-a-check.txt && cat by-a-check.txt && python3 -c 'print(6*7)'"
    )
    assert code == 0 and "inside" in said and "42" in said, said
    (site / "by-a-check.txt").unlink()
    code, _ = await run(f"echo x > '{outside}'")
    assert code != 0 and not outside.exists()
    code, _ = await run(f"ls '{Path.home()}'")
    assert code != 0
    code, _ = await run(f"ls '{real.data}/code'")
    assert code != 0


# ---- the loop and the person's terminal, for real (stage C3) ---------------------------------------


async def test_the_reviews_case_from_the_sessions_with_the_check_run_in_the_sandbox(
    real, tmp_path_factory
):
    """An old bug, a task that adds a function, a check that covers both: one refusal, one fix,
    one pass, and the check file untouched. The agent is scripted; the engine, the sandbox, the
    check and the store are real."""
    from types import SimpleNamespace

    from wasifyai_code.runtime import CHECK, Sessions
    from wasifyai_code.store import CodeStore, Owner

    shop = tmp_path_factory.mktemp("tax-shop")
    (shop / "prices.py").write_text("def total(xs):\n    return sum(xs) if xs else None\n")
    (shop / "check.py").write_text(
        "import os, prices\n"
        "assert prices.total([]) == 0, 'total of nothing must be 0'\n"
        "assert prices.with_tax(100) == 120\n"
        "print('checked in', os.getcwd())\n"
        f"open('{shop.parent}/written-by-the-check.txt', 'w')\n"  # the sandbox must refuse this
    )
    was = (shop / "check.py").read_bytes()
    real.model.scripts["loop"] = [
        use("file_editor", command="insert", path=str(shop / "prices.py"), insert_line=2,
            new_str="\n\ndef with_tax(x):\n    return x * 120 // 100\n"),
        use("finish", message="Added with_tax."),
    ]  # fmt: skip
    real.model.scripts["loop:after-check"] = [
        use("file_editor", command="str_replace", path=str(shop / "prices.py"),
            old_str="sum(xs) if xs else None", new_str="sum(xs)"),
        use("finish", message="Fixed total."),
    ]  # fmt: skip
    store = CodeStore.in_folder(real.data / "code-loop")
    state = SimpleNamespace(
        code_store=store, code_sessions=None, coding_server=real.server,
        coding_gateway=real.gateway, creation_index=None, desktop_dir=real.data,
    )  # fmt: skip
    live = Sessions(state, place=real.place)
    me = Owner("t1", "u1")
    try:
        made = await live.start(me, folder=str(shop), mode="own", model="scripted")
        live.set_check(me, made["id"], "python3 -B check.py")
        await live.send(me, made["id"], "Add with_tax. #script:loop")
        closed = await asyncio.wait_for(live.wait(me, made["id"]), 120)
        found = [e for e in live.feed(made["id"]).kept if e["event"] == CHECK]
        assert [(c["round"], c["result"]) for c in found] == [(1, "failed"), (2, "failed")] or [
            (c["round"], c["result"]) for c in found
        ] == [(1, "failed"), (2, "passed")], found
        # round 1 failed for the old bug; round 2 fails only at the write outside the project,
        # which is the sandbox doing its work: the two asserts before it passed
        assert "total of nothing must be 0" in found[0]["tail"]
        assert "checked in" in found[1]["tail"] and "Operation not permitted" in found[1]["tail"]
        assert not (shop.parent / "written-by-the-check.txt").exists()
        assert (shop / "check.py").read_bytes() == was
        assert "def with_tax" in (shop / "prices.py").read_text()
        assert "if xs else None" not in (shop / "prices.py").read_text()
        assert closed["rounds"] >= 2 and closed["changed"] == 1
        # with the check kept inside the project it passes, by hand
        (shop / "check.py").write_text((shop / "check.py").read_text().rsplit("open(", 1)[0])
        row = await live.check_now(me, made["id"])
        assert (row["result"], row["exit_code"]) == ("passed", 0)
        assert live.view(me, made["id"])["result"] == "passed"
    finally:
        await live.stop_all()
        await live.terminals.close_all()
        store.close()


async def test_the_persons_terminal_is_held_by_the_same_sandbox(real, site):
    import base64

    from wasifyai_code.terminal import Terminals

    async def own(folder: Path):
        return await real.place.sandbox(folder, who="person")

    terminals = Terminals(own)
    outside = site.parent / "outside-by-the-terminal.txt"
    t = await terminals.open("s-term", site, 120, 30)

    read_to = [0]  # the number of the last event read

    async def type_and_read(line: str, until: str) -> str:
        seen = ""
        t.write(line + "\n")
        async with asyncio.timeout(30):
            async for event in t.follow(read_to[0]):
                read_to[0] = event["seq"]
                if "data" in event:
                    seen += base64.b64decode(event["data"]).decode(errors="replace")
                    if until in seen.split(line[-12:], 1)[-1]:
                        return seen
        return seen

    try:
        said = await type_and_read(
            "echo typed > by-hand.txt; cat by-hand.txt; echo done-$((1+1))", "done-2"
        )
        assert (site / "by-hand.txt").read_text() == "typed\n"
        said = await type_and_read(f"echo x > '{outside}'; echo out-$?-", "out-")
        assert "out-0-" not in said and not outside.exists()
        said = await type_and_read(f"ls '{Path.home()}' > /dev/null 2>&1; echo home-$?-", "home-")
        assert "home-0-" not in said
        said = await type_and_read("ps > /dev/null 2>&1; echo ps-$?-", "ps-")
        assert "ps-0-" not in said  # as the Terminal tab's note says
        # the person's terminal reaches a package index at any time, and nothing else
        fetch = "curl -sS -m 20 -o /dev/null -w 'code=%{http_code}=' "
        said = await type_and_read(
            f"{fetch}https://pypi.org/simple/six/; echo index-done", "index-done"
        )
        assert "code=200=" in said, said
        said = await type_and_read(f"{fetch}https://example.com/; echo other-done", "other-done")
        assert "code=200=" not in said
    finally:
        await terminals.close_all()
        (site / "by-hand.txt").unlink(missing_ok=True)
