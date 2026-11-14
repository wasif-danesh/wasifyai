"""A stand-in for OpenHands' Agent Server, for unit tests (docs/v2-coding-agent-start-plan.md,
section 8): a small program that answers the endpoints the Wasify engine uses
(`wasifyai_api/coding_server.py`, `wasifyai_code/client.py`) and replays event streams recorded
once from the real one, so `make test` needs no model, no network and none of OpenHands' packages.
It uses Python's standard library only.

It is started the way the real one is: `<python> -I -B -X utf8 -c <the guard> --host H --port N`,
where the test's "python" is a script that runs this file. The guard's own text is then run as it
is, with the one module it starts (`openhands.agent_server`) answered by `serve` below, so the
guard is tested for real. What it answers:

    GET /alive, /health      200, no key asked (as the real one)
    GET /ready               503 until FAKE_READY_AFTER seconds have passed, then 200
    GET /server_info         200 with the version in FAKE_VERSION; 401 without the session key
    GET /fake/env            what it was started with (its environment's names, its arguments,
                             its folder), so a test can read how it was started; 401 without the key

A session (stage C1b), with the session key on every call:

    POST /api/conversations                          a conversation; 201 with its id
    GET  /api/conversations/<id>                     where it is (`execution_status`)
    POST /api/conversations/<id>/events              a message; with `run` the "agent" starts
    POST /api/conversations/<id>/run, /interrupt     go on; stop at once
    GET  /api/conversations/<id>/events/<event>      one kept event
    GET  /fake/conversations/<id>                    the request it was made with, for a test
    WS   /sockets/events/<id>                        the live socket: the key is the first
                                                     message; `resend_mode=all`, or `since` with
                                                     `after_timestamp` (events at or after it,
                                                     so the one at the boundary comes twice)

**The "agent" replays a recording.** A recording is one turn's events as the real, pinned server
sent them (`tests/fixtures/coding/*.json`; each says what it was recorded from). It is replayed
in order with new ids and times. The message chooses it: `#replay:<name>` anywhere in the text,
else FAKE_RECORDING, else `analyse`. Three more marks, for what a recording cannot show:

    #hang        the turn never ends by itself: a word piece every 50 ms until it is interrupted
    #drop:<n>    every listener's socket is cut, without a goodbye, after n events of the turn
    #slow:<ms>   wait this long before each event (a recording is otherwise replayed at once)

FAKE_EXIT=<code> makes it leave at once with that code (a server that does not start);
FAKE_CHILD=1 makes it start a child in a session of its own, as the real one does for a command.
"""

import base64
import contextlib
import hashlib
import http.server
import json
import os
import queue
import re
import runpy
import select
import struct
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

STARTED = time.monotonic()
KEY_ENV = "OH_SESSION_API_KEYS_0"
RECORDINGS = Path(__file__).with_name("fixtures") / "coding"
WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
WORKSPACE_MARK = "{{WORKSPACE}}"  # where a recording names its workspace


def now() -> str:
    return datetime.now().isoformat(timespec="microseconds")


class Conversation:
    """One pretended conversation: its kept events, who listens, and the turn in flight."""

    def __init__(self, request: dict):
        self.id = str(uuid.uuid4())
        self.request = request
        self.events: list[dict] = []
        self.status = "idle"
        self.lock = threading.Lock()
        self.listeners: list[queue.Queue] = []
        self.stop = threading.Event()
        self.turn: threading.Thread | None = None
        self.drop_after: int | None = None

    def emit(self, event: dict, keep: bool = True) -> dict:
        event = {**event, "id": str(uuid.uuid4()), "timestamp": now()}
        with self.lock:
            if keep:
                self.events.append(event)
            for listener in self.listeners:
                listener.put(event)
        return event

    def say_status(self, status: str) -> None:
        self.status = status
        self.emit(
            {
                "kind": "ConversationStateUpdateEvent", "source": "environment",
                "key": "execution_status", "value": status,
            }
        )  # fmt: skip

    def message(self, body: dict) -> None:
        text = " ".join(
            str(p.get("text", "")) for p in body.get("content") or [] if isinstance(p, dict)
        )
        self.emit(
            {
                "kind": "MessageEvent", "source": "user",
                "llm_message": {"role": "user", "content": body.get("content") or []},
            }
        )  # fmt: skip
        if body.get("run") and self.status != "running":
            self.begin(text)

    def begin(self, text: str = "") -> None:
        self.stop.clear()
        self.turn = threading.Thread(target=self.play, args=(text,), daemon=True)
        self.say_status("running")
        self.turn.start()

    def interrupt(self) -> None:
        was = self.status == "running"
        self.stop.set()
        if self.turn is not None:
            self.turn.join(timeout=5)
        if was:
            self.emit({"kind": "InterruptEvent", "source": "user"})
            self.say_status("paused")

    def play(self, text: str) -> None:
        """The "agent": a recording replayed, or a turn that hangs until it is interrupted."""
        slow = re.search(r"#slow:(\d+)", text)
        wait = int(slow.group(1)) / 1000 if slow else 0.0
        drop = re.search(r"#drop:(\d+)", text)
        self.drop_after = int(drop.group(1)) if drop else None
        if "#hang" in text:
            while not self.stop.wait(0.05):
                self.emit(
                    {"kind": "StreamingDeltaEvent", "source": "agent", "content": "… "}, keep=False
                )
            return
        chosen = re.search(r"#replay:([\w-]+)", text)
        name = chosen.group(1) if chosen else os.environ.get("FAKE_RECORDING", "analyse")
        recording = json.loads((RECORDINGS / f"{name}.json").read_text())
        workspace = str((self.request.get("workspace") or {}).get("working_dir") or "")
        renamed: dict[str, str] = {}
        for item in recording["events"]:
            if self.stop.wait(wait):
                return
            event = json.loads(json.dumps(item["event"]).replace(WORKSPACE_MARK, workspace))
            if event.get("kind") == "ConversationStateUpdateEvent":
                if event.get("key") == "execution_status":
                    if event.get("value") != "running":  # it is running already
                        self.say_status(str(event.get("value")))
                    continue
            old = event.pop("id", None)
            event.pop("timestamp", None)
            if event.get("action_id") in renamed:
                event["action_id"] = renamed[event["action_id"]]
            made = self.emit(event, keep=event.get("kind") != "StreamingDeltaEvent")
            if old:
                renamed[old] = made["id"]


class State:
    def __init__(self) -> None:
        self.conversations: dict[str, Conversation] = {}


def ws_send(wfile, text: str) -> None:
    data = text.encode()
    head = b"\x81"
    if len(data) < 126:
        head += bytes([len(data)])
    elif len(data) < 65536:
        head += b"\x7e" + struct.pack(">H", len(data))
    else:
        head += b"\x7f" + struct.pack(">Q", len(data))
    wfile.write(head + data)
    wfile.flush()


def ws_close(wfile, code: int) -> None:
    wfile.write(b"\x88\x02" + struct.pack(">H", code))
    wfile.flush()


def ws_read(rfile) -> str | None:
    """One text message from the client (its frames are masked). None when it has gone."""
    head = rfile.read(2)
    if len(head) < 2 or head[0] & 0x0F == 0x8:
        return None
    size = head[1] & 0x7F
    if size == 126:
        size = struct.unpack(">H", rfile.read(2))[0]
    elif size == 127:
        size = struct.unpack(">Q", rfile.read(8))[0]
    mask = rfile.read(4)
    data = bytes(b ^ mask[i % 4] for i, b in enumerate(rfile.read(size)))
    return data.decode()


def serve() -> None:
    args = sys.argv[1:]
    port = int(args[args.index("--port") + 1])
    host = args[args.index("--host") + 1]
    key = os.environ.get(KEY_ENV, "")
    if os.environ.get("FAKE_EXIT"):
        print("fake agent server: told to fail", flush=True)
        raise SystemExit(int(os.environ["FAKE_EXIT"]))
    child = None
    if os.environ.get("FAKE_CHILD"):
        child = subprocess.Popen(["/bin/sleep", "600"], start_new_session=True)
    ready_after = float(os.environ.get("FAKE_READY_AFTER", "0.2"))
    state = State()

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _keyed(self) -> bool:
            if self.headers.get("X-Session-API-Key") != key or not key:
                self._send(401, {"detail": "Unauthorized"})
                return False
            return True

        def _conversation(self, found_id: str) -> Conversation | None:
            found = state.conversations.get(found_id)
            if found is None:
                self._send(404, {"detail": "Not Found"})
            return found

        def do_GET(self) -> None:
            url = urlparse(self.path)
            if url.path in ("/alive", "/health"):
                return self._send(200, {"status": "ok"})
            if url.path == "/ready":
                if time.monotonic() - STARTED < ready_after:
                    return self._send(503, {"status": "initializing"})
                return self._send(200, {"status": "ready"})
            if url.path.startswith("/sockets/events/"):
                return self._socket(url.path.rsplit("/", 1)[1], parse_qs(url.query))
            if not self._keyed():
                return None
            if url.path == "/server_info":
                return self._send(
                    200, {"title": "fake", "version": os.environ.get("FAKE_VERSION", "1.62.0")}
                )
            if url.path == "/fake/env":
                return self._send(
                    200,
                    {
                        "env": {k: v for k, v in os.environ.items() if k != KEY_ENV},
                        "args": args,
                        "cwd": os.getcwd(),
                        "pid": os.getpid(),
                        "pgid": os.getpgid(0),
                        "sid": os.getsid(0),
                        "child": child.pid if child else None,
                        "fds": sorted(int(n) for n in os.listdir("/dev/fd") if n.isdigit()),
                    },
                )
            parts = url.path.strip("/").split("/")
            if parts[:2] == ["fake", "conversations"] and len(parts) == 3:
                found = self._conversation(parts[2])
                return self._send(200, found.request) if found else None
            if parts[:2] == ["api", "conversations"] and len(parts) >= 3:
                found = self._conversation(parts[2])
                if found is None:
                    return None
                if len(parts) == 3:
                    return self._send(200, {"id": found.id, "execution_status": found.status})
                if len(parts) == 5 and parts[3] == "events":
                    event = next((e for e in found.events if e["id"] == parts[4]), None)
                    return self._send(200, event) if event else self._send(404, {"detail": "-"})
            return self._send(404, {"detail": "Not Found"})

        def do_POST(self) -> None:
            if not self._keyed():
                return None
            size = int(self.headers.get("content-length") or 0)
            body = json.loads(self.rfile.read(size) or b"{}")
            parts = urlparse(self.path).path.strip("/").split("/")
            if parts == ["api", "conversations"]:
                made = Conversation(body)
                state.conversations[made.id] = made
                return self._send(201, {"id": made.id, "execution_status": "idle"})
            if parts[:2] == ["api", "conversations"] and len(parts) == 4:
                found = self._conversation(parts[2])
                if found is None:
                    return None
                if parts[3] == "events":
                    found.message(body)
                    return self._send(200, {"success": True})
                if parts[3] == "interrupt":
                    found.interrupt()
                    return self._send(200, {"success": True})
                if parts[3] == "run":
                    if found.status == "running":
                        return self._send(409, {"detail": "Conversation already running."})
                    found.begin()
                    return self._send(200, {"success": True})
            return self._send(404, {"detail": "Not Found"})

        def _socket(self, found_id: str, query: dict) -> None:
            """The live socket: the handshake, the key as the first message, what was asked to
            be sent again, then each new event."""
            accept = base64.b64encode(
                hashlib.sha1((self.headers["Sec-WebSocket-Key"] + WS_MAGIC).encode()).digest()
            ).decode()
            self.send_response(101)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            self.close_connection = True
            try:
                said = json.loads(ws_read(self.rfile) or "{}")
                if said.get("session_api_key") != key or not key:
                    return ws_close(self.wfile, 4001)
                found = state.conversations.get(found_id)
                if found is None:
                    return ws_close(self.wfile, 4004)
                mine: queue.Queue = queue.Queue()
                with found.lock:
                    found.listeners.append(mine)
                    kept = list(found.events)
                try:
                    mode = (query.get("resend_mode") or [""])[0]
                    since = unquote((query.get("after_timestamp") or [""])[0])
                    sent: set[str] = set()
                    n = 0
                    for event in kept:
                        if mode == "all" or (mode == "since" and event["timestamp"] >= since):
                            ws_send(self.wfile, json.dumps(event))
                            sent.add(event["id"])
                    while True:
                        try:
                            event = mine.get(timeout=0.05)
                        except queue.Empty:
                            # has the listener said goodbye, or gone?
                            if select.select([self.connection], [], [], 0)[0]:
                                if ws_read(self.rfile) is None:
                                    with contextlib.suppress(OSError):
                                        ws_close(self.wfile, 1000)
                                    return None
                            continue
                        if event["id"] in sent:
                            continue
                        ws_send(self.wfile, json.dumps(event))
                        n += 1
                        if found.drop_after is not None and n >= found.drop_after:
                            found.drop_after = None
                            return None  # cut, without a goodbye
                finally:
                    with found.lock:
                        found.listeners.remove(mine)
            except (OSError, ValueError):
                return None

        def log_message(self, format: str, *args: object) -> None:
            pass

    print(f"fake agent server on {host}:{port}", flush=True)
    server = http.server.ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.serve_forever()


def main() -> None:
    argv = sys.argv[1:]
    at = argv.index("-c")
    guard, rest = argv[at + 1], argv[at + 2 :]
    sys.argv = ["openhands.agent_server", *rest]
    setattr(runpy, "run_module", lambda *a, **k: serve())  # noqa: B010 (the module the guard starts)
    exec(compile(guard, "<guard>", "exec"), {"__name__": "__main__"})


if __name__ == "__main__":
    main()
