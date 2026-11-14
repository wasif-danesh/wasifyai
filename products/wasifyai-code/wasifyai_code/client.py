"""This computer as a place: OpenHands' Agent Server inside its sandbox (ADR-0101, decisions 4 and
5; ADR-0102). **The only file that knows the Agent Server's API.**

The Wasify engine gives two things, and this file imports neither:

    the server    `wasifyai_api.coding_server.CodingServer`: `ensure_running(write, read_only)`
                  starts the sandboxed server and names the folders it may reach; `request(...)`
                  puts the server's own session key on a call; `session_key` is for the socket
    the gateway   `wasifyai_api.coding_gateway.CodingGateway`: `open(...)` gives a token for one
                  session's model calls; the server is told the gateway's address and that token,
                  never a key (ADR-0102, decision 4)

What the place does with them:

    start     a conversation on a workspace, with the model pointed at the gateway. A session
              that only reads gets three tools: find files by name, search in files, and look at
              a file. None of them can change a file or run a command
    send      a message, and the agent starts on it
    stop      interrupt: the model call in flight is cancelled, so it takes effect at once
    follow    one live socket per listener. After a drop it connects again and asks for what
              came "since" the last event it had; an event that arrives twice is dropped
    events    translated to the place's own kinds by `events.py`, and each turn closed with one
              `ended` event

**One server, several sessions.** A sandbox profile cannot change while its process runs, so the
server is started with every folder the person has opened as a workspace (`known`), and a session
on one of them starts nothing. A folder that is new means the server starts again; that is refused
while another session is in the middle of a turn. A workspace is opened for reading only unless a
session that may write is on it, so in a session that only reads the operating system refuses a
write whatever a tool tries (`docs/spikes/coding-c1b.md`).
"""

import asyncio
import contextlib
import json
import logging
import os
import uuid
from collections.abc import AsyncGenerator, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus, WebSocketException

from wasifyai_code import place as places
from wasifyai_code.agent_types import SendMessageRequest, StartConversationRequest
from wasifyai_code.events import RUNNING, Reader
from wasifyai_code.place import Busy, NoSuchSession, PlaceError, PlaceEvent, SessionSpec

log = logging.getLogger(__name__)

# the Agent Server's own names for the tools of a session that only reads
READ_TOOLS = ("glob", "grep", "planning_file_editor")
# its tools that write a file or run a command: never given to a session that only reads
WRITE_TOOLS = ("terminal", "file_editor", "apply_patch", "task_tracker", "browser_tool_set")
READ_ONLY_NOTE = (
    "This session only reads. You have no tool that changes a file or runs a command, and the "
    "file viewer cannot edit anything, the plan file included: do not try. Look at the files "
    "you need, then give your whole answer, or your plan, as your final message."
)
USAGE_ID = "wasify-code"
CLOSED_BAD_KEY, CLOSED_NOT_FOUND = 4001, 4004
START_TIMEOUT_S = 90.0  # making a conversation loads the tools and the skills
CALL_TIMEOUT_S = 20.0
STOP_TIMEOUT_S = 5.0
SETTLE_S = 0.3  # after a conversation comes to rest, an error that explains it may still arrive
RETRY_S = (0.2, 0.5, 1.0, 2.0, 2.0)  # between tries to connect the socket again


def _within(folder: Path, opened: set[Path]) -> bool:
    """Whether `folder` is one of the opened folders or inside one."""
    return folder in opened or any(parent in opened for parent in folder.parents)


@dataclass
class _Live:
    """One session of the place."""

    id: str  # the Agent Server's conversation
    spec: SessionSpec
    account: str  # what the gateway counts this session under
    reader: Reader = field(default_factory=Reader)
    turn_open: bool = False  # a message was sent and its end has not been read


class ThisComputer:
    """The place "this computer". `server` and `gateway` are the Wasify engine's; `known` gives
    every folder that is a workspace, so that one server can serve them all."""

    def __init__(
        self,
        server: Any,
        gateway: Any,
        *,
        known: Callable[[], Sequence[Path | str]] | None = None,
        on_call: Callable[[Any], Any] | None = None,
        stream: bool = True,
    ):
        self.server, self.gateway = server, gateway
        self._known = known or (lambda: ())
        self._on_call = on_call
        self.stream = stream
        self._sessions: dict[str, _Live] = {}
        self._writable: set[Path] = set()  # folders a session that may write is on
        self._lock = asyncio.Lock()

    # ---- the server ----------------------------------------------------------------------------

    @staticmethod
    def _real(path: Path | str) -> Path:
        return Path(os.path.realpath(path))

    def working(self) -> list[str]:
        """The sessions that are in the middle of a turn."""
        return [s.id for s in self._sessions.values() if s.turn_open]

    async def open_folder(self, folder: Path, *, write: bool = False) -> None:
        """Start the server with `folder` in reach before any session needs it. Sessions on
        folders inside it then start nothing (the evaluation makes one folder per task)."""
        await self._serve(folder, write=write)

    async def _serve(self, workspace: Path, *, write: bool) -> None:
        """A running server that can reach `workspace`, for writing if `write`."""
        async with self._lock:
            workspace = self._real(workspace)
            if not workspace.is_dir():
                raise PlaceError(f"There is no folder at {workspace}.")
            running = self.server.running
            writable = {self._real(p) for p in self.server.workspaces} if running else set()
            readable = {self._real(p) for p in self.server.read_only} if running else set()
            if _within(workspace, writable) or (not write and _within(workspace, readable)):
                return
            if running and self.working():
                raise Busy(
                    "The coding engine must start again to open this folder, and another "
                    "session is in the middle of a turn. Try again when it has ended."
                )
            if write:
                self._writable.add(workspace)
            everything = {self._real(p) for p in self._known()} | writable | readable | {workspace}
            write_to = sorted(self._writable | writable)
            try:
                # a start is never cut in half: if the caller is stopped while the server starts
                # (Stop pressed at once), the start goes on to its end by itself
                await asyncio.shield(
                    self.server.ensure_running(write_to, sorted(everything - set(write_to)))
                )
            except Exception as e:
                if not hasattr(e, "message"):  # not the engine's own, sayable failure
                    raise
                raise PlaceError(str(getattr(e, "message", e))) from None

    async def _call(self, method: str, path: str, *, wait_s: float = CALL_TIMEOUT_S, **more: Any):
        try:
            return await self.server.request(method, path, timeout=wait_s, **more)
        except httpx.HTTPError:
            raise PlaceError("The coding engine did not answer.") from None
        except Exception as e:
            if not hasattr(e, "message"):
                raise
            raise PlaceError(str(getattr(e, "message", e))) from None

    def _get(self, session: str) -> _Live:
        if session not in self._sessions:
            raise NoSuchSession(session)
        return self._sessions[session]

    # ---- the interface -------------------------------------------------------------------------

    async def start(self, spec: SessionSpec) -> str:
        await self._serve(spec.workspace, write=not spec.read_only)
        workspace = self._real(spec.workspace)
        who = spec.account
        account = who.session_id if who else f"nobody-{uuid.uuid4().hex}"
        try:
            grant = self.gateway.open(
                tenant_id=who.tenant_id if who else "-",
                product_id=who.product_id if who else "wasifyai-code",
                user_id=who.user_id if who else "-",
                session_id=account,
                model=spec.model or None,
                spent_usd=who.spent_usd if who else 0.0,
                limit_usd=who.limit_usd if who else None,
                on_call=self._on_call,
            )
        except Exception as e:
            if not hasattr(e, "message"):
                raise
            raise PlaceError(str(getattr(e, "message", e))) from None
        settings: dict[str, Any] = {
            "agent_kind": "openhands",
            "llm": {
                **grant.engine_settings,
                "model": grant.engine_model,
                "base_url": grant.base_url,
                "api_key": grant.token,  # a token of the gateway's, never a key
                "usage_id": USAGE_ID,
                "stream": self.stream,
            },
        }
        if spec.read_only:
            # the viewer may edit one file, its "plan": that file is in a folder the sandbox
            # does not let the server write, so there is nothing it can change
            plan = {"plan_path": str(self.server.plan_file)}
            settings["tools"] = [
                {"name": name, "params": plan} if name == "planning_file_editor" else {"name": name}
                for name in READ_TOOLS
            ]
            settings["agent_context"] = {"system_message_suffix": READ_ONLY_NOTE}
        body: StartConversationRequest = {
            "workspace": {"working_dir": str(workspace)},
            "max_iterations": spec.step_limit,
            "agent_settings": settings,
        }
        answer = await self._call("POST", "/api/conversations", json=body, wait_s=START_TIMEOUT_S)
        if answer.status_code not in (200, 201):
            self.gateway.close_session(account)
            log.warning("the coding engine refused a conversation: %s", answer.status_code)
            raise PlaceError("The coding engine could not start a session on this folder.")
        made = str(answer.json()["id"])
        self._sessions[made] = _Live(made, spec, account)
        return made

    async def send(self, session: str, text: str, *, run: bool = True) -> None:
        live = self._get(session)
        if run and await self._status(live) == RUNNING:
            raise Busy(session)
        body: SendMessageRequest = {
            "role": "user",
            "content": [{"type": "text", "text": text}],
            "run": run,
        }
        if run:
            live.turn_open = True
        answer = await self._call("POST", f"/api/conversations/{session}/events", json=body)
        if answer.status_code == 404:
            live.turn_open = False
            raise NoSuchSession(session)
        if answer.status_code >= 400:
            live.turn_open = False
            raise PlaceError("The coding engine did not take the message.")

    async def run(self, session: str) -> None:
        live = self._get(session)
        answer = await self._call("POST", f"/api/conversations/{session}/run")
        if answer.status_code == 409:
            raise Busy(session)
        if answer.status_code == 404:
            raise NoSuchSession(session)
        if answer.status_code >= 400:
            raise PlaceError("The coding engine could not go on.")
        live.turn_open = True

    async def stop(self, session: str) -> None:
        self._get(session)
        answer = await self._call(
            "POST", f"/api/conversations/{session}/interrupt", wait_s=STOP_TIMEOUT_S
        )
        if answer.status_code == 404:
            raise NoSuchSession(session)

    async def answer(self, session: str, confirmation: str, allow: bool, reason: str = "") -> None:
        self._get(session)
        answer = await self._call(
            "POST",
            f"/api/conversations/{session}/events/respond_to_confirmation",
            json={"accept": allow, "reason": reason or "The person said no."},
        )
        if answer.status_code >= 400:
            raise PlaceError("Nothing is waiting for an answer in this session.")

    async def end(self, session: str) -> None:
        """Forget a session: its token stops working. The conversation itself stays in the
        coding engine's own state."""
        live = self._sessions.pop(session, None)
        if live is not None:
            self.gateway.close_session(live.account)

    def adopt(self, session: str, spec: SessionSpec) -> bool:
        """Take up a session this place started earlier in this run of the app (the product's
        row names it). False when its token is gone, which is when the app was started again:
        the conversation can then not reach its model, and a new one must be started."""
        if session in self._sessions:
            return True
        who = spec.account
        if who is None or not self.gateway.is_open(who.session_id):
            return False
        self._sessions[session] = _Live(session, spec, who.session_id)
        return True

    # ---- following -----------------------------------------------------------------------------

    async def _status(self, live: _Live) -> str:
        answer = await self._call("GET", f"/api/conversations/{live.id}")
        if answer.status_code == 404:
            raise NoSuchSession(live.id)
        if answer.status_code >= 400:
            raise PlaceError("The coding engine did not answer.")
        return str(answer.json().get("execution_status") or "")

    async def _when(self, session: str, event_id: str) -> str | None:
        """The time of an event the caller already has, to ask for what came since."""
        answer = await self._call("GET", f"/api/conversations/{session}/events/{event_id}")
        if answer.status_code != 200:
            return None
        return str(answer.json().get("timestamp") or "") or None

    def _socket(self, session: str, since: str | None, everything: bool) -> str:
        url = str(self.server.url or "")
        if not url:
            raise PlaceError("The coding engine is not running.")
        query = ""
        if since:
            query = f"?resend_mode=since&after_timestamp={quote(since)}"
        elif everything:
            query = "?resend_mode=all"
        return url.replace("http://", "ws://", 1) + f"/sockets/events/{session}{query}"

    connects_first = True  # `follow(..., opened=)` says when it listens: send after that

    async def follow(
        self, session: str, after: str | None = None, *, opened: asyncio.Event | None = None
    ) -> AsyncGenerator[PlaceEvent, None]:
        """`opened` is set once the socket listens. Words as they are written are sent only to
        who listens at that moment, so a caller that wants them all starts following, waits for
        `opened`, and sends its message then."""
        live = self._get(session)
        reader = live.reader
        cursor = after.split(":", 1)[0].split("#", 1)[0] if after else None
        since = await self._when(session, cursor) if cursor else None
        skipping = cursor if since else None  # events up to and with this one are the caller's
        seen: set[str] = set()
        last_at = since
        tries = 0
        while True:
            try:
                url = self._socket(session, last_at, everything=cursor is None)
                async with connect(url, max_size=None, open_timeout=10, close_timeout=1) as socket:
                    # the key goes in the first message, never in the address
                    await socket.send(
                        json.dumps({"type": "auth", "session_api_key": self.server.session_key})
                    )
                    if opened is not None:
                        opened.set()
                    while True:
                        try:
                            wait = SETTLE_S if reader.over else None
                            raw = await asyncio.wait_for(socket.recv(), timeout=wait)
                        except TimeoutError:
                            yield self._ended(live, last_at)
                            continue
                        tries = 0
                        event = json.loads(raw)
                        if not isinstance(event, dict):
                            continue
                        event_id = str(event.get("id") or "")
                        if event_id and event_id in seen:
                            continue  # the one at the boundary arrives twice after a drop
                        seen.add(event_id)
                        last_at = str(event.get("timestamp") or "") or last_at
                        if skipping is not None:
                            if event_id == skipping:
                                skipping = None
                            continue
                        if reader.over and event.get("kind") != "ConversationErrorEvent":
                            yield self._ended(live, last_at)
                        for n, (kind, data) in enumerate(reader.read(event)):
                            yield PlaceEvent(
                                event_id if n == 0 else f"{event_id}#{n}",
                                kind,
                                str(event.get("timestamp") or ""),
                                data,
                            )
            except ConnectionClosed as closed:
                code = closed.rcvd.code if closed.rcvd else 0
                if code == CLOSED_NOT_FOUND:
                    raise NoSuchSession(session) from None
                if code == CLOSED_BAD_KEY and tries:
                    raise PlaceError("The coding engine refused the connection.") from None
            except (OSError, InvalidStatus, WebSocketException, TimeoutError):
                pass
            # the socket dropped: come back and ask for what was missed
            if reader.over:
                yield self._ended(live, last_at)
            if tries >= len(RETRY_S):
                raise PlaceError("The coding engine stopped answering.")
            await asyncio.sleep(RETRY_S[tries])
            tries += 1
            if not self.server.running:
                raise PlaceError("The coding engine was stopped.")

    def _ended(self, live: _Live, at: str | None) -> PlaceEvent:
        """The turn's one `ended` event, once the conversation has come to rest."""
        note = self.gateway.take_note(live.account)
        data = live.reader.end(note)
        live.reader.over = False
        live.turn_open = False
        return PlaceEvent(f"{live.reader.rest_id}:ended", places.ENDED, at or "", data)

    async def close(self) -> None:
        for session in list(self._sessions):
            with contextlib.suppress(PlaceError):
                await self.end(session)
