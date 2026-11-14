"""The place a coding session runs in (ADR-0101, decision 5).

The product never talks to an engine directly. It talks to a *place*: start a session, send it a
message, let it run, stop it, follow what happens, answer a question it asks. In v1 there will be
one real place, this computer (the Agent Server inside the sandbox, ADR-0102): `client.py`. What
is here is the interface and a pretended place for tests, so that the loop, the scheduler and the
evaluation are tested without an engine.

The words are ours, not the Agent Server's: an event has one of a few plain kinds, and a turn ends
for one of a few plain reasons. The real place will translate.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

# ---- the kinds of event a place sends ---------------------------------------------------------

STATE = "state"  # data: {"state": "running" | "idle"}
TEXT = "text"  # a finished message of the agent; data: {"text": ...}
PIECE = "piece"  # a few characters of a message as it is written; data: {"text": ...}
STEP = "step"  # one use of a tool; data: {"tool": ..., "id": ..., and what the tool was given}
# what a step gave back; data: {"id": the step's, "tool": ..., "ok": bool, "text": ...}
RESULT = "result"
CONFIRM = "confirm"  # the agent waits for a yes or no; data: {"id": ..., "what": ...}
ENDED = "ended"  # the turn is over; data: {"why": one of ENDINGS, "detail": ..., "steps": n}
EVENT_KINDS = (STATE, TEXT, PIECE, STEP, RESULT, CONFIRM, ENDED)

# ---- why a turn ended ----------------------------------------------------------------------------

FINISHED = "finished"  # the agent said it was done; this is not our "done" (ADR-0101, decision 6)
STEP_LIMIT = "step_limit"  # it used every step it was allowed
STOPPED = "stopped"  # somebody stopped it
ERROR = "error"  # the engine or the model failed
REFUSED = "refused"  # the model declined the request (seen by the gateway, ADR-0102 decision 4)
ENDINGS = (FINISHED, STEP_LIMIT, STOPPED, ERROR, REFUSED)


class PlaceError(Exception):
    """The place could not do what was asked."""


class NoSuchSession(PlaceError):
    """The place has no session of that id."""


class Busy(PlaceError):
    """The session is in the middle of a turn."""


@dataclass(frozen=True)
class Account:
    """Whose session it is and what it may spend: what the model gateway counts against
    (ADR-0102, decision 4). `session_id` is the product's id for the session, not the place's."""

    tenant_id: str
    product_id: str
    user_id: str
    session_id: str
    spent_usd: float = 0.0
    limit_usd: float = 0.0  # 0: the gateway's own limit for one session


@dataclass(frozen=True)
class SessionSpec:
    """What a place needs to start a session."""

    workspace: Path
    model: str = ""  # the product's name for the model; the place knows what it stands for
    step_limit: int = 40
    unattended: bool = False  # nobody is there to answer (a scheduled run, ADR-0105 decision 11)
    ask: tuple[str, ...] = ()  # patterns of commands that must be asked first (ADR-0102, 6)
    read_only: bool = False  # the agent gets no tool that writes a file or runs a command
    account: Account | None = None  # None: nobody's (an evaluation run)


@dataclass(frozen=True)
class PlaceEvent:
    id: str
    kind: str
    at: str  # UTC, ISO
    data: dict[str, Any] = field(default_factory=dict)


class Place(Protocol):
    """Where sessions run. Every call names a session by the id `start` gave."""

    async def start(self, spec: SessionSpec) -> str:
        """Make a session on a workspace and give its id. Nothing runs yet."""
        ...

    async def send(self, session: str, text: str, *, run: bool = True) -> None:
        """Give the session a message. With `run` the agent starts on it at once."""
        ...

    async def run(self, session: str) -> None:
        """Let the agent work on what it was sent."""
        ...

    async def stop(self, session: str) -> None:
        """Interrupt the turn. The session can be sent to again. Stopping an idle session is
        allowed and does nothing."""
        ...

    def follow(self, session: str, after: str | None = None) -> AsyncIterator[PlaceEvent]:
        """The session's events in order: the kept ones first, then each new one as it happens,
        for as long as the caller goes on reading. `after` is the id of the last event the
        caller has; only later ones are given."""
        ...

    async def answer(self, session: str, confirmation: str, allow: bool, reason: str = "") -> None:
        """Say yes or no to a `confirm` event."""
        ...


# ---- a pretended place, for tests ----------------------------------------------------------------


class _OverLimit(Exception):
    pass


class FakeTurn:
    """What a pretended agent holds during one turn: the message, the workspace, and ways to say
    something, use a step, change a file and ask for a yes or no."""

    def __init__(self, place: "FakePlace", session: "_Session", text: str, number: int):
        self._place, self._session = place, session
        self.session = session.id
        self.text = text
        self.number = number  # 1 for the session's first turn
        self.workspace = session.spec.workspace
        self.steps = 0

    def say(self, text: str) -> None:
        self._place._emit(self._session, TEXT, {"text": text})

    def piece(self, text: str) -> None:
        self._place._emit(self._session, PIECE, {"text": text})

    def step(self, tool: str, **data: Any) -> None:
        """Use one step. The step after the last allowed one ends the turn at the limit."""
        if self.steps >= self._session.spec.step_limit:
            raise _OverLimit
        self.steps += 1
        self._place._emit(self._session, STEP, {"tool": tool, **data})

    def write(self, path: str, content: str | bytes) -> None:
        self.step("file_editor", path=path)
        target = self.workspace / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content)

    def delete(self, path: str) -> None:
        self.step("file_editor", path=path)
        (self.workspace / path).unlink()

    async def confirm(self, what: str) -> bool:
        """Ask for a yes or no and wait for it."""
        ask = uuid.uuid4().hex
        waiting: asyncio.Future[tuple[bool, str]] = asyncio.get_running_loop().create_future()
        self._session.confirmations[ask] = waiting
        self._place._emit(self._session, CONFIRM, {"id": ask, "what": what})
        allow, _reason = await waiting
        return allow


Agent = Callable[[FakeTurn], Awaitable[str | None]]
"""A pretended agent: it is called once a turn. It ends the turn by returning (`None` means
finished; one of `ENDINGS` ends it that way) or by raising (an error)."""


def scripted(*turns: Agent) -> Agent:
    """An agent that does `turns[0]` on its first turn, `turns[1]` on its second, and so on. The
    last one is repeated."""

    async def agent(turn: FakeTurn) -> str | None:
        return await turns[min(turn.number, len(turns)) - 1](turn)

    return agent


@dataclass
class _Session:
    id: str
    spec: SessionSpec
    events: list[PlaceEvent] = field(default_factory=list)
    news: asyncio.Event = field(default_factory=asyncio.Event)
    inbox: list[str] = field(default_factory=list)
    confirmations: dict[str, "asyncio.Future[tuple[bool, str]]"] = field(default_factory=dict)
    task: "asyncio.Task[None] | None" = None
    turns: int = 0


class FakePlace:
    """A place held in memory. Its "agent" is a function the test gives, which really writes and
    deletes files in the workspace, so that checkpoints and checks see real changes. Every call is
    kept in `calls`, in order."""

    def __init__(self, agent: Agent | None = None):
        self.agent: Agent = agent or _finish_at_once
        self.sessions: dict[str, _Session] = {}
        self.calls: list[tuple[Any, ...]] = []

    # ---- the interface -------------------------------------------------------------------------

    async def start(self, spec: SessionSpec) -> str:
        session = _Session(uuid.uuid4().hex, spec)
        self.sessions[session.id] = session
        self.calls.append(("start", session.id, spec))
        return session.id

    async def send(self, session: str, text: str, *, run: bool = True) -> None:
        s = self._get(session)
        if run and self.running(session):
            raise Busy(session)
        self.calls.append(("send", session, text, run))
        s.inbox.append(text)
        if run:
            self._begin(s)

    async def run(self, session: str) -> None:
        s = self._get(session)
        if self.running(session):
            raise Busy(session)
        self.calls.append(("run", session))
        self._begin(s)

    async def stop(self, session: str) -> None:
        s = self._get(session)
        self.calls.append(("stop", session))
        if s.task is not None and not s.task.done():
            s.task.cancel()
            await asyncio.wait([s.task])

    async def follow(self, session: str, after: str | None = None) -> AsyncIterator[PlaceEvent]:
        s = self._get(session)
        at = 0
        if after is not None:
            ids = [e.id for e in s.events]
            if after not in ids:
                raise PlaceError(f"no event {after} in session {session}")
            at = ids.index(after) + 1
        while True:
            while at < len(s.events):
                yield s.events[at]
                at += 1
            await s.news.wait()

    async def answer(self, session: str, confirmation: str, allow: bool, reason: str = "") -> None:
        s = self._get(session)
        self.calls.append(("answer", session, confirmation, allow, reason))
        waiting = s.confirmations.pop(confirmation, None)
        if waiting is None:
            raise PlaceError(f"nothing is waiting for an answer under {confirmation}")
        if not waiting.done():
            waiting.set_result((allow, reason))

    # ---- for tests -----------------------------------------------------------------------------

    def running(self, session: str) -> bool:
        task = self._get(session).task
        return task is not None and not task.done()

    def sent(self, session: str) -> list[str]:
        """The messages the session was sent, in order."""
        return [c[2] for c in self.calls if c[0] == "send" and c[1] == session]

    def events(self, session: str, kind: str | None = None) -> list[PlaceEvent]:
        return [e for e in self._get(session).events if kind is None or e.kind == kind]

    # ---- inside --------------------------------------------------------------------------------

    def _get(self, session: str) -> _Session:
        if session not in self.sessions:
            raise NoSuchSession(session)
        return self.sessions[session]

    def _emit(self, s: _Session, kind: str, data: dict[str, Any]) -> None:
        at = datetime.now(UTC).isoformat(timespec="milliseconds")
        s.events.append(PlaceEvent(uuid.uuid4().hex, kind, at, data))
        s.news.set()  # wake whoever follows, then give the next ones a new thing to wait on
        s.news = asyncio.Event()

    def _begin(self, s: _Session) -> None:
        text, s.inbox = "\n\n".join(s.inbox), []
        s.turns += 1
        s.task = asyncio.ensure_future(self._turn(s, FakeTurn(self, s, text, s.turns)))

    async def _turn(self, s: _Session, turn: FakeTurn) -> None:
        self._emit(s, STATE, {"state": "running"})
        why, detail = FINISHED, ""
        try:
            why = await self.agent(turn) or FINISHED
        except _OverLimit:
            why = STEP_LIMIT
        except asyncio.CancelledError:
            why = STOPPED  # `stop` waits for this task, which ends here in the ordinary way
        except Exception as e:  # noqa: BLE001  (a pretended agent that fails is an "error" ending)
            why, detail = ERROR, str(e)
        for waiting in s.confirmations.values():
            waiting.cancel()
        s.confirmations.clear()
        self._emit(s, STATE, {"state": "idle"})
        self._emit(s, ENDED, {"why": why, "detail": detail, "steps": turn.steps})


async def _finish_at_once(turn: FakeTurn) -> str | None:
    return None
