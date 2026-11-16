"""The coding sessions in flight.

This is where the product meets the engine's services, which it reads from the app state and never
imports: the coding server and the model gateway (`state.coding_server`, `state.coding_gateway`)
become the place "this computer" (`client.py`), and the rows are `state.code_store`.

    Sessions.start   a folder becomes a workspace (once) and gets a new session; it is added to
                     search (ADR-0041)
    Sessions.send    one turn, in the background: the agent works, its events are relayed to
                     whoever follows the session, and the turn's row is closed with how it ended
    Sessions.stop    stops the turn at any moment: before the engine has started, while the
                     session is being made, and while the agent works

**The modes.** In Plan the agent only reads: nothing can change and no checkpoint is taken. In
"Ask me" and "Work on its own" it changes files with the file editor and runs commands in a
terminal inside the sandbox (stage C3):

    before the turn   a checkpoint of the project (`checkpoints.py`), outside the project
    a change or a     waits in the coding engine; `rules.py` answers at once, or the person is
    command           asked with a card (`interrupt`, kind `code_ask`) and may allow the kind
                      for the project
    after the turn    a second checkpoint: what the turn changed is the difference
    Sessions.undo     puts the files back to before the turn; `Sessions.redo` brings it back

**The check.** Every turn is run by the implement, check, fix loop (`loop.Loop.run_turn`, the one
function a scheduled run will call too). When the agent says it has finished and files changed,
the project's check command is run by us, inside a sandbox of our own for that project; a
failure goes back to the agent, up to three rounds. This file gives the loop its `Hooks`: how a
session is opened in the place, how a question is answered, and what is said on the feed.

**The relay.** Each session has a `Feed`: the turn's states, the agent's steps, its words and a
refusal, in order, in the shape of the SSE contract's section "A coding session's stream"
(`docs/contracts/sse-events.md`; ADR-0101, amendment of 2026-11-14). The route
`GET /code/sessions/{id}/events` sends it to the window as it is.
"""

import asyncio
import contextlib
import difflib
import logging
import os
import re
import shutil
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk import Identity, search_text

from wasifyai_code import PRODUCT_ID, assets, checks, extensions, rules, starters
from wasifyai_code import place as places
from wasifyai_code import preview as previews
from wasifyai_code import store as rows
from wasifyai_code.checkpoints import CheckpointError, CheckpointStore
from wasifyai_code.checks import is_test_file
from wasifyai_code.loop import CUT_OFF, Hooks, Loop, TurnRunning
from wasifyai_code.place import (
    Account,
    Place,
    PlaceError,
    PlaceEvent,
    SessionSpec,
    harness_model,
)
from wasifyai_code.store import CodeStore, Owner
from wasifyai_code.terminal import Terminal, TerminalError, Terminals

log = logging.getLogger(__name__)

KIND = "code_session"  # what a session is called in search (ADR-0041)
SCHEDULE_KIND = "code_schedule"  # ... and a schedule the person made (ADR-0105)
EXTENSION_KIND = "code_extension"  # ... and an extension the person added (ADR-0104)
EXTENSIONS_DIR = "extensions"  # under <app data>/code: our copies of what a person added
SKILLS_USED = "code_skills"  # the stream's event: the person's message switched skills on
STEP_LIMIT = 60  # tool steps in one turn of a session that reads
RUN_STEP_LIMIT = 120  # ... and of one that changes files and runs commands
STOP_GRACE_S = 3.0  # after Stop, how long the place's own "ended" is waited for
# the stream's event kinds (the SSE contract, "A coding session's stream")
STATE, MESSAGE, REFUSAL = "code_state", "code_message", "code_refusal"
CHECK = "code_check"  # one run of the project's check, with its result
CHECK_OUTPUTS = "check-output"  # under <app data>/code: the full output of every check
MAX_CHECK_BYTES = 400_000  # of a check's output, when the window asks for it
TAIL_SHOWN = 4000
TRY_AGAIN = "The check still fails. Try again to fix what fails."
TOOL_CALL, TOOL_RESULT = "tool_call", "tool_result"
INTERRUPT, ASK_KIND = "interrupt", "code_ask"  # the approval card (the contract's `interrupt`)
TOKEN, REASONING = "token", "reasoning"  # words as they are written: relayed, never kept
NOT_KEPT = (TOKEN, REASONING)
NODE = "agent"
MODE_CHANGED = (
    "The session's mode or its project's extensions changed, so the agent begins again from "
    "this message. It was given the last answer to go on from."
)
UNDONE_NOTE = (
    "(Since your last turn the person undid its changes: the project's files are back to how "
    "they were before that turn.)"
)
CHECKPOINTS_DIR = "checkpoints"
MAX_SHOWN_BYTES = 400_000  # of one side of a changed file, in the Changes tab
MAX_SHOWN_LINES = 4000
RECAP_CHARS = 6000
ASK_NOT_ON_HARNESS = (
    "Ask me is not offered on your own agent program: it does not wait for a yes or no. Choose "
    "Plan, or Work on its own (every turn can be undone)."
)
APP_RESTARTED = (
    "The app was started again since this session's last message, so the agent begins from "
    "this message and does not know the earlier ones."
)


def how_it_ended(why: str) -> tuple[str, str]:
    """A turn's reason as the window is told it: how the agent's own turn ended (one of the
    place's five endings), and beside it why the check has the result it has. The loop writes
    one word for both; when it is a reason of the check, the agent itself had finished."""
    if not why or why in places.ENDINGS:
        return why, ""
    if why == CUT_OFF:
        return places.ERROR, ""
    return places.FINISHED, why


def _outward(turn: dict[str, Any]) -> dict[str, Any]:
    why, check_why = how_it_ended(str(turn.get("why") or ""))
    if not why and turn.get("state") == rows.DONE:
        why = places.FINISHED  # the check passed: the loop gives no reason for that
    return {**turn, "why": why, "check_why": check_why}


class NotAvailable(Exception):
    """This deployment has no coding engine."""


# The person's own agent programs' models that were run through the coding evaluation's 36 tasks
# (`evals/run_eval.py --model <harness>:<model>`; ADR-0107, stage H3), by the program's own name for
# the model (a part of its id), with what was measured. Results: docs/spikes/coding-harness-h3.md.
HARNESS_TESTED: dict[tuple[str, str], str] = {
    ("claude-code", "haiku"): "36 of 36 tasks passed (2026-11-15)",
    ("claude-code", "sonnet"): "36 of 36 tasks passed (2026-11-16)",
    ("claude-code", "opus"): "36 of 36 tasks passed (2026-11-16)",
    ("codex", "gpt-5.6-terra"): (
        "19 of 19 tasks passed before the plan's limit stopped the run (2026-11-15)"
    ),
}


# what an agent program says when the person's plan has run out, or its sign-in has ended
# (ADR-0107); the window's cards read the same words (`PLAN_LIMIT`, `SIGNED_OUT` in
# packages/ui/src/code/Code.tsx)
PLAN_LIMIT = re.compile(
    r"usage limit|rate limit|limit (is |was )?reached|reached your|quota|\b429\b"
    r"|too many requests|out of credits",
    re.IGNORECASE,
)
SIGNED_OUT = re.compile(
    r"not (logged|signed) in|log ?in again|sign ?in again|authenticat|unauthori[sz]ed|\b401\b"
    r"|token (has )?expired|session expired|invalid (api key|credentials|token)",
    re.IGNORECASE,
)


def program_said(title: str, said: str) -> str:
    """A stop of the person's own agent program in plain words, with what it said (without the
    protocol's error code)."""
    clean = re.sub(r"^\s*\[-?\d+\]\s*(internal error:\s*)?", "", said, flags=re.IGNORECASE).strip()
    if PLAN_LIMIT.search(said):
        return f"Stopped: your plan's limit was reached. {title} said: \u201c{clean}\u201d"
    if SIGNED_OUT.search(said):
        return f"Stopped: {title} is not signed in any more. Sign in to {title}, then run it again."
    return f"{title} said: \u201c{clean}\u201d"


class Refused(Exception):
    """A request that cannot be done, with the sentence the person is shown."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def store_for(state: Any) -> CodeStore:
    store = state.code_store
    if store is None:
        raise NotAvailable("Coding is not available in this deployment.")
    return store


def scheduled_for(state: Any) -> Any:
    """The schedules of this engine and their timer (`scheduled.Scheduled`), made once."""
    sessions = sessions_for(state)
    if sessions.scheduled is None:
        from wasifyai_code.scheduled import Scheduled

        sessions.scheduled = Scheduled(sessions)
    return sessions.scheduled


def sessions_for(state: Any) -> "Sessions":
    existing = state.code_sessions
    if existing is None:
        if state.coding_server is None or state.coding_gateway is None:
            raise NotAvailable("Coding is not available in this deployment.")
        existing = Sessions(state)
        state.code_sessions = existing
    return existing


def owner_of(identity: Any) -> Owner:
    return Owner(identity.tenant_id, identity.user_id)


# ---- which folders may be a workspace ---------------------------------------------------------


def check_folder(
    folder: str, *, data_dir: Path | None, home: Path | None = None, must_exist: bool = True
) -> Path:
    """The folder a session may be opened on, as its real path, or `Refused`.

    The sandbox opens a workspace to the coding engine, so a folder must not hold anything the
    sandbox exists to keep out of reach: the app's own data (its keys file is there), the
    person's whole home folder, their Library, or a hidden folder at the top of their home
    (`.ssh`, `.aws`, `.config`)."""
    if not folder.strip() or not os.path.isabs(os.path.expanduser(folder.strip())):
        raise Refused("bad_folder", "Give the folder's whole path, starting at the top.")
    path = Path(os.path.realpath(os.path.expanduser(folder.strip())))
    if must_exist and not path.is_dir():
        raise Refused("no_folder", f"There is no folder at {path}.")
    home = Path(os.path.realpath(home or Path.home()))
    if path == home or path in home.parents:
        raise Refused(
            "too_wide", "Choose one project's folder, not the whole home folder or a disk."
        )
    private = [home / "Library"]
    if data_dir is not None:
        private.append(Path(os.path.realpath(data_dir)))
    for closed in private:
        if path == closed or closed in path.parents or path in closed.parents:
            raise Refused(
                "private_folder",
                "That folder holds the app's or the system's own files and cannot be opened "
                "as a project.",
            )
    inside_home = home in path.parents
    if inside_home and path.relative_to(home).parts[0].startswith("."):
        raise Refused(
            "private_folder", "A hidden folder of the home folder cannot be opened as a project."
        )
    return path


# ---- the relay inside the engine --------------------------------------------------------------


class Feed:
    """One session's events for listeners in this process, in order. Everything is kept except
    the word pieces, which only those listening at that moment get."""

    def __init__(self) -> None:
        self.kept: list[dict[str, Any]] = []
        self._seq = 0
        self._listeners: set[asyncio.Queue[dict[str, Any]]] = set()

    def add(self, name: str, session_id: str, turn_id: str, /, **data: Any) -> dict[str, Any]:
        """One event in the contract's envelope: the session is the thread, the turn the run."""
        self._seq += 1
        event = {
            "event": name,
            "run_id": turn_id,
            "thread_id": session_id,
            "seq": self._seq,
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            **data,
        }
        if name not in NOT_KEPT:
            self.kept.append(event)
        for queue in self._listeners:
            queue.put_nowait(event)
        return event

    async def follow(self, after: int = 0) -> AsyncIterator[dict[str, Any]]:
        """The kept events after `after`, then each new one as it happens."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._listeners.add(queue)
        try:
            last = after
            for event in list(self.kept):
                if event["seq"] > last:
                    last = event["seq"]
                    yield event
            while True:
                event = await queue.get()
                if event["seq"] > last:
                    last = event["seq"]
                    yield event
        finally:
            self._listeners.discard(queue)


@dataclass
class _Turn:
    """One turn in flight."""

    turn_id: str
    task: "asyncio.Task[dict[str, Any]] | None" = None
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    where: str | None = None  # the place's session, once there is one
    answer: str = ""
    steps: int = 0
    # the questions that wait for the person: the card's id -> where the answer goes
    asks: "dict[str, asyncio.Future[str]]" = field(default_factory=dict)
    marks: dict[str, str] = field(default_factory=dict)  # a step's id -> how it was answered
    told: bool = False  # the turn's last state was said on the feed
    unattended: bool = False  # nobody is there to answer (a scheduled run)


class _Hooks(Hooks):
    """What the loop asks of the product's sessions."""

    # an unattended turn's steps wait like any other: the rules answer them, and what would ask
    # a person is refused and written down (`Sessions._confirm`)
    answers_unattended = True

    def __init__(self, sessions: "Sessions"):
        self.s = sessions

    def spec(
        self, owner: Owner, session: dict[str, Any], workspace: dict[str, Any], unattended: bool
    ) -> SessionSpec:
        reads = session["mode"] == rows.PLAN
        # a harness is given no skill, plugin or hook of ours (ADR-0104's amendment for ADR-0107)
        own = self.s.harness_of(session["model"]) is None
        return SessionSpec(
            Path(workspace["path"]),
            model=session["model"],
            step_limit=STEP_LIMIT if reads else RUN_STEP_LIMIT,
            unattended=unattended,
            read_only=reads,
            skills=tuple(self.s.skills_for(owner, workspace["id"])) if own else (),
            hooks=self.s.hooks_for(owner, workspace["id"]) if own else None,
            account=Account(
                owner.tenant_id, owner.product_id, owner.user_id, session["id"],
                spent_usd=float(session["cost_usd"]), limit_usd=float(session["cost_limit_usd"]),
                spent_tokens=int(session["tokens_in"]) + int(session["tokens_out"]),
                limit_tokens=int(session["token_limit"] or 0),
            ),
        )  # fmt: skip

    async def open(
        self,
        owner: Owner,
        session: dict[str, Any],
        workspace: dict[str, Any],
        turn: dict[str, Any],
        spec: SessionSpec,
        place: Place,
    ) -> tuple[str, str | None]:
        where, cursor = session["place_session"], session["last_event"]
        adopt = getattr(place, "adopt", None)
        if where and adopt is not None and not adopt(where, spec):
            where = None
            self.s.store.note_turn(owner, turn["id"], APP_RESTARTED)
        if not where:
            where, cursor = await place.start(spec), None
        flight = self.s._turns.get(session["id"])
        if flight is not None:
            flight.where = where
        return where, cursor

    def request(self, owner: Owner, session: dict[str, Any], turn: dict[str, Any]) -> str:
        return self.s._request(owner, session, turn)

    async def event(
        self,
        owner: Owner,
        session: dict[str, Any],
        workspace: dict[str, Any],
        turn: dict[str, Any],
        where: str,
        event: PlaceEvent,
    ) -> None:
        flight = self.s._turns.get(session["id"])
        if flight is None:
            return
        feed = self.s.feed(session["id"])
        if event.kind == places.CONFIRM and session["mode"] != rows.PLAN:
            await self.s._confirm(owner, session, workspace, turn, flight, feed, event)
        else:
            self.s._relay(feed, session, turn, flight, event)

    async def ended(
        self,
        owner: Owner,
        session: dict[str, Any],
        workspace: dict[str, Any],
        turn: dict[str, Any],
        why: str,
        detail: str,
    ) -> dict[str, Any]:
        return await self.s._closing(owner, session, workspace, turn, why, detail)


class Sessions:
    def __init__(self, state: Any, place: Place | None = None):
        """`place` is given by tests; the app's is this computer."""
        self.state = state
        self.store = store_for(state)
        if place is None:
            from wasifyai_code.client import ThisComputer

            place = ThisComputer(
                state.coding_server,
                state.coding_gateway,
                known=self.store.workspace_paths,
                on_call=self._on_call,
            )
        self.place: Any = place
        self._turns: dict[str, _Turn] = {}
        self._feeds: dict[str, Feed] = {}
        self._checking: set[str] = set()  # sessions whose check the person is running by hand
        self.scheduled: Any = None  # `scheduled.Scheduled`, once something asks for it
        data = state.desktop_dir
        outputs = (
            Path(data) / "code" / CHECK_OUTPUTS
            if data is not None
            else Path(tempfile.gettempdir()) / "wasify-code-checks"
        )
        self.loop = Loop(
            self.place,
            self.store,
            checkpoints=self._cps,
            outputs=outputs,
            on_event=self._on_loop,
            hooks=_Hooks(self),
            stop_wait_s=STOP_GRACE_S,
            # the check never runs outside a sandbox: a place that has none runs it as it is
            # only in tests, where the place is pretended
            sandbox=getattr(self.place, "sandbox", None),
        )
        own = getattr(self.place, "sandbox", None)
        self.terminals = Terminals(
            (lambda folder: own(folder, who="person")) if own is not None else None
        )
        # the preview is the person's own: like their terminal, it may fetch from a package index
        self.previews = previews.Previews(
            (lambda folder: own(folder, who="person")) if own is not None else None
        )

    # ---- what the actions and routes call ------------------------------------------------------

    def feed(self, session_id: str) -> Feed:
        return self._feeds.setdefault(session_id, Feed())

    def running(self, session_id: str) -> bool:
        return session_id in self._turns or session_id in self._checking

    async def models(self) -> list[dict[str, Any]]:
        return await self.state.coding_gateway.list_models()

    # ---- harnesses: the person's own agent programs (ADR-0107) --------------------------------

    def harness_of(self, model: str) -> tuple[str, str] | None:
        """(harness, the program's model) for a model of a harness; None for Wasify AI's own."""
        known = tuple(getattr(self.state.coding_server, "harness_ids", ()) or ())
        return harness_model(model, known)

    def _accounts(self) -> Any:
        accounts = getattr(self.state, "coding_harnesses", None)
        if accounts is None:
            raise Refused("no_harness", "The agent programs are not available here.")
        return accounts

    def _harness_id(self, harness: str) -> str:
        if harness not in (getattr(self.state.coding_server, "harness_ids", ()) or ()):
            raise Refused("not_found", "There is no such agent program.")
        return harness

    async def harnesses(self) -> list[dict[str, Any]]:
        """Each agent program: set up or not, signed in or not, how, and the plan's name. Never an
        email or a token: the program keeps those."""
        return await self._accounts().statuses()

    async def sign_in(self, harness: str) -> dict[str, Any]:
        """Start the program's own sign-in, in the person's browser."""
        try:
            return await self._accounts().sign_in(self._harness_id(harness))
        except LookupError as e:
            raise Refused("harness_not_installed", str(e)) from None

    async def cancel_sign_in(self, harness: str) -> dict[str, Any]:
        accounts = self._accounts()
        await accounts.cancel(self._harness_id(harness))
        return await accounts.status(harness)

    @staticmethod
    def harness_tested(harness: str, program_model: str) -> str:
        """What the coding evaluation measured for a program's model (ADR-0107, stage H3), in
        words; empty for one that was not run through it."""
        said = program_model.lower()
        for (h, name), words in HARNESS_TESTED.items():
            if h == harness and name and name in said:
                return words
        return ""

    async def harness_models(self, harness: str) -> dict[str, Any]:
        """The models the program offers on the person's plan, as it says."""
        self._harness_id(harness)
        listed = getattr(self.place, "harness_models", None)
        if listed is None:
            raise Refused("no_harness", "The agent programs are not available here.")
        try:
            found = await listed(harness)
        except PlaceError as e:
            raise Refused("model_not_ready", str(e)) from None
        return {
            **found,
            "models": [
                {
                    **m,
                    "id": f"{harness}:{m['id']}",
                    "program_model": m["id"],
                    "tested": self.harness_tested(harness, m["id"]),
                }
                for m in found["models"]
            ],
        }

    async def _harness_ready(self, harness: str) -> str:
        """A session may start on a harness that is set up and signed in. Gives its name."""
        state = await self._accounts().status(harness)
        title = state.get("title") or harness
        if not state.get("installed"):
            raise Refused(
                "harness_not_installed",
                f"{title} is not set up yet. Set up the agent programs in Settings, under "
                "Optional parts.",
            )
        if not state.get("signed_in"):
            raise Refused("not_signed_in", f"Sign in to {title} first.")
        return str(title)

    async def start(
        self,
        owner: Owner,
        *,
        folder: str,
        title: str = "",
        model: str = "",
        cost_limit_usd: float = 0.0,
        mode: str = rows.PLAN,
    ) -> dict[str, Any]:
        """A new session on a folder. Nothing runs yet, and the coding engine is not started."""
        if mode not in rows.MODES:
            raise Refused("no_such_mode", "Choose Plan, Ask me or Work on its own.")
        path = check_folder(folder, data_dir=self.state.desktop_dir)
        on_harness = self.harness_of(model)
        if on_harness is not None:
            if mode == rows.ASK:
                raise Refused("no_such_mode", ASK_NOT_ON_HARNESS)
            await self._harness_ready(on_harness[0])
            model_id = f"{on_harness[0]}:{on_harness[1] or 'default'}"
        else:
            gateway = self.state.coding_gateway
            try:
                route = gateway.model(model or None)
            except Exception as e:
                raise Refused("no_such_model", str(getattr(e, "message", e))) from None
            if (why := await gateway.ready(route.id)) is not None:
                raise Refused("model_not_ready", why)
            model_id = route.id
        workspace = await asyncio.to_thread(self.store.find_workspace, owner, str(path))
        if workspace is None:
            workspace = await asyncio.to_thread(
                self.store.add_workspace, owner, str(path), name=path.name
            )
        session = await asyncio.to_thread(
            self.store.add_session,
            owner,
            workspace["id"],
            title=title.strip() or path.name,
            model=model_id,
            mode=mode,
            cost_limit_usd=cost_limit_usd,
        )
        await self._index(owner, session["id"])
        return self.view(owner, session["id"])

    async def send(
        self, owner: Owner, session_id: str, text: str, *, unattended: bool = False
    ) -> dict[str, Any]:
        """Begin a turn and give its row. The turn goes on in the background: follow the feed,
        or `wait` for its end. `unattended`: nobody is there to answer (a scheduled run)."""
        if not text.strip():
            raise Refused("nothing_to_do", "Say what the agent should look at.")
        session = self._session(owner, session_id)
        if self.running(session_id):
            raise Refused(
                "busy", "The agent is still working on the last message. Stop it or wait."
            )
        workspace = self.store.get_workspace(owner, session["workspace_id"])
        first = not self.store.list_turns(owner, session_id)
        turn = self.store.add_turn(owner, session_id, text.strip())
        flight = self._turns[session_id] = _Turn(turn["id"], unattended=unattended)
        if first:
            # a session nobody named is called by what was asked first
            if session["title"] == workspace["name"]:
                self.store.set_session_title(owner, session_id, _title_of(text))
            # and what was asked first is part of what search finds it by
            await self._index(owner, session_id)
        flight.task = asyncio.ensure_future(self._turn(owner, session, workspace, turn, flight))
        return turn

    async def wait(self, owner: Owner, session_id: str) -> dict[str, Any]:
        """The turn in flight, once it has ended (or the last one, when none is)."""
        self._session(owner, session_id)
        flight = self._turns.get(session_id)
        if flight is not None and flight.task is not None:
            await asyncio.shield(flight.task)
        turns = self.store.list_turns(owner, session_id)
        if not turns:
            raise Refused("no_turn", "Nothing was asked in this session yet.")
        return _outward(turns[-1])

    async def stop(self, owner: Owner, session_id: str) -> bool:
        """Stop the session's turn. False when none is running. Returns once the turn is closed."""
        self._session(owner, session_id)
        flight = self._turns.get(session_id)
        if flight is None:
            # no turn: a check the person started by hand may be running
            return self.loop.stop(session_id)
        flight.stop.set()
        if flight.task is not None:
            with contextlib.suppress(Exception):
                await asyncio.shield(flight.task)
        return True

    # ---- modes, questions and what a project may do ---------------------------------------------

    async def set_mode(self, owner: Owner, session_id: str, mode: str) -> dict[str, Any]:
        """How much the agent asks, from now on. Between "Ask me" and "Work on its own" it holds
        at once, also in the middle of a turn. To or from Plan the agent's tools change, so the
        session's next message begins a new conversation in the coding engine."""
        if mode not in rows.MODES:
            raise Refused("no_such_mode", "Choose Plan, Ask me or Work on its own.")
        session = self._session(owner, session_id)
        if mode == rows.ASK and self.harness_of(session["model"]) is not None:
            raise Refused("no_such_mode", ASK_NOT_ON_HARNESS)
        if session["mode"] == mode:
            return self.view(owner, session_id)
        if (session["mode"] == rows.PLAN) != (mode == rows.PLAN):
            if session_id in self._turns:
                raise Refused(
                    "busy", "The agent is working. Stop it or wait, then change the mode."
                )
            end = getattr(self.place, "end", None)
            if session["place_session"] and end is not None:
                with contextlib.suppress(PlaceError):
                    await end(session["place_session"])
            if session["place_session"]:
                self.store.set_place_session(owner, session_id, None)
                self.store.set_cursor(owner, session_id, None)
        self.store.set_session_mode(owner, session_id, mode)
        return self.view(owner, session_id)

    async def answer(self, owner: Owner, session_id: str, ask_id: str, answer: str) -> bool:
        """The person's answer to a card: yes, allow (yes, and stop asking about this kind in
        this project) or no. False when nothing waits under that id any more."""
        if answer not in rules.ANSWERS:
            raise Refused("no_such_answer", "Answer yes, allow or no.")
        self._session(owner, session_id)
        flight = self._turns.get(session_id)
        waiting = flight.asks.get(ask_id) if flight is not None else None
        if waiting is None or waiting.done():
            return False
        waiting.set_result(answer)
        return True

    def project(self, owner: Owner, session_id: str) -> dict[str, Any]:
        """What this session's project may do: each kind of request, and whether it is allowed."""
        session = self._session(owner, session_id)
        workspace = self.store.get_workspace(owner, session["workspace_id"])
        allowed = set(workspace["allowed"])
        return {
            "project": workspace["name"],
            "folder": workspace["path"],
            "mode": session["mode"],
            "kinds": [
                {"id": kind, "allowed": kind in allowed, "asked_now": kind in rules.ASKED_NOW}
                for kind in rules.KINDS
            ],
        }

    def allow(self, owner: Owner, session_id: str, kind: str, allowed: bool) -> dict[str, Any]:
        """Allow a kind of request for the project, or take that back."""
        if kind not in rules.KINDS:
            raise Refused("no_such_kind", "There is no such kind of request.")
        session = self._session(owner, session_id)
        workspace = self.store.get_workspace(owner, session["workspace_id"])
        kinds = set(workspace["allowed"])
        kinds = kinds | {kind} if allowed else kinds - {kind}
        self.store.set_allowed(owner, workspace["id"], sorted(kinds))
        return self.project(owner, session_id)

    # ---- the check ------------------------------------------------------------------------------

    def check(self, owner: Owner, session_id: str) -> dict[str, Any]:
        """The project's check: the command, where it came from, what the project's files
        suggest, and the checks of this session, the newest first."""
        session = self._session(owner, session_id)
        workspace = self.store.get_workspace(owner, session["workspace_id"])
        try:
            found = checks.suggest(Path(workspace["path"]))
        except OSError:
            found = []
        return {
            "project": workspace["name"],
            "command": workspace["check_command"],
            "source": workspace["check_from"],
            "limit_s": int(workspace["check_limit_s"]),
            "rounds": self.loop.rounds,
            "suggested": [{"command": f.command, "why": f.why} for f in found],
            "result": session["result"],
            "running": session_id in self._checking,
            "checks": [
                _check_row(row)
                for row in reversed(self.store.list_checks(owner, session_id=session_id))
            ][:20],
        }

    def set_check(
        self, owner: Owner, session_id: str, command: str, limit_s: int | None = None
    ) -> dict[str, Any]:
        """Set the project's check command; empty means the project has none."""
        session = self._session(owner, session_id)
        command = command.strip()
        if len(command) > 2000 or "\0" in command:
            raise Refused("bad_command", "That command is too long.")
        if limit_s is not None and not 5 <= limit_s <= 3600:
            raise Refused("bad_limit", "A check may run between 5 seconds and one hour.")
        workspace = self.store.get_workspace(owner, session["workspace_id"])
        try:
            suggested = {f.command for f in checks.suggest(Path(workspace["path"]))}
        except OSError:
            suggested = set()
        self.store.set_check(
            owner, workspace["id"], command,
            source="suggested" if command in suggested else "person", limit_s=limit_s,
        )  # fmt: skip
        return self.check(owner, session_id)

    async def check_now(self, owner: Owner, session_id: str) -> dict[str, Any]:
        """Run the project's check now, outside a turn, and give its row."""
        session = self._session(owner, session_id)
        if self.running(session_id):
            raise Refused("busy", "The agent is working. Stop it or wait, then try again.")
        workspace = self.store.get_workspace(owner, session["workspace_id"])
        if not workspace["check_command"].strip():
            raise Refused("no_check", "This project has no check yet. Set one first.")
        turns = self.store.list_turns(owner, session_id)
        self._checking.add(session_id)
        feed = self.feed(session_id)
        turn_id = turns[-1]["id"] if turns else ""
        cost = self._cost(session_id)
        feed.add(STATE, session_id, turn_id, state=rows.CHECKING, round=0, cost_usd=cost)
        try:
            row = await self.loop.check_now(owner, session_id)
        except TurnRunning:
            raise Refused("busy", "The agent is working. Stop it or wait.") from None
        finally:
            self._checking.discard(session_id)
        feed.add(
            STATE, session_id, turn_id, state=rows.DONE, result=row["result"], why=row["why"],
            cost_usd=self._cost(session_id),
        )  # fmt: skip
        return _check_row(row)

    def check_output(self, owner: Owner, session_id: str, check_id: str) -> dict[str, Any]:
        """The whole output of one check of this session (its end, when it is very long)."""
        self._session(owner, session_id)
        mine = self.store.list_checks(owner, session_id=session_id)
        row = next((r for r in mine if r["id"] == check_id), None)
        if row is None:
            raise Refused("not_found", "There is no such check in this session.")
        text, cut = "", False
        with contextlib.suppress(OSError):
            data = Path(row["output_file"]).read_bytes() if row["output_file"] else b""
            cut = len(data) > MAX_CHECK_BYTES
            text = data[-MAX_CHECK_BYTES:].decode("utf-8", "replace")
        return {**_check_row(row), "output": text, "cut": cut}

    async def try_again(self, owner: Owner, session_id: str) -> dict[str, Any]:
        """Three more rounds: a new turn that tells the agent the check still fails."""
        return await self.send(owner, session_id, TRY_AGAIN)

    # ---- extensions (ADR-0104) -------------------------------------------------------------------

    def _catalogue(self) -> Path | None:
        """The pinned catalogue installed with the coding engine; None when it is not there."""
        found = getattr(self.state.coding_server, "install", None)
        folder = getattr(found, "extensions", None)
        return Path(folder) if folder is not None and Path(folder).is_dir() else None

    def _offered(self, owner: Owner) -> list[extensions.Skill]:
        return extensions.offered(self._catalogue(), self.store.list_extensions(owner))

    def _skill_titles(self, names: list[str]) -> list[str]:
        """The names a person knows the skills by; a name of the engine's own stays as it is."""
        known = {s.name: s.title for s in extensions.offered(self._catalogue(), [])}
        return [known.get(n, n.replace("-", " ").capitalize()) for n in names]

    def _on_for(
        self, owner: Owner, workspace_id: str
    ) -> tuple[list[extensions.Skill], dict[str, Path]]:
        """The extensions that are on for a project, and where the sandbox reads each."""
        switches = self.store.switches(owner, workspace_id)
        on = [s for s in self._offered(owner) if extensions.is_on(s, switches)]
        data = self.state.desktop_dir
        shown = extensions.show_to_sandbox(on, Path(data) / "coding-fixed") if data else {}
        return on, shown

    def skills_for(self, owner: Owner, workspace_id: str) -> list[dict[str, Any]]:
        """The skills that are on for a project, as the place takes them. Their folders are put
        where the sandbox can read them. Whatever fails here, a session still starts: with no
        skills, never with others."""
        try:
            return extensions.for_engine(*self._on_for(owner, workspace_id))
        except (OSError, ValueError) as e:
            log.warning("the project's skills could not be read: %s", e)
            return []

    def hooks_for(self, owner: Owner, workspace_id: str) -> dict[str, Any] | None:
        """The hooks of the approved plugins that are on for a project; None when there are
        none, and when anything fails: never a hook nobody approved."""
        try:
            return extensions.hooks_for_engine(*self._on_for(owner, workspace_id))
        except (OSError, ValueError) as e:
            log.warning("the project's plugins could not be read: %s", e)
            return None

    def workspaces(self, owner: Owner) -> list[dict[str, Any]]:
        """The person's projects, the newest first: what an extension is switched on for."""
        found = self.store.list_workspaces(owner)
        return [
            {"id": w["id"], "name": w["name"], "folder": w["path"]}
            for w in reversed(found)
            if not w.get("copy_of")  # a scheduled run's copy is not a project of the person's
        ]

    def running_in(self, owner: Owner, workspace_id: str) -> bool:
        """Whether a turn is in flight in one of the project's sessions."""
        return any(
            s["id"] in self._turns
            for s in self.store.list_sessions(owner)
            if s["workspace_id"] == workspace_id
        )

    def list_extensions(self, owner: Owner, workspace_id: str = "") -> list[dict[str, Any]]:
        """What is offered, each with whether it is on for the project (when one is named)."""
        switches = self._switches(owner, workspace_id)
        added = {f"{extensions.ADDED}:{r['id']}": r for r in self.store.list_extensions(owner)}
        return [
            {
                **s.view(),
                "on": extensions.is_on(s, switches) if workspace_id else None,
                # when the person added it; empty for one of the short list
                "added_at": added[s.id]["created_at"] if s.id in added else "",
            }
            for s in self._offered(owner)
        ]

    def _switches(self, owner: Owner, workspace_id: str) -> dict[str, bool]:
        if not workspace_id:
            return {}
        try:
            self.store.get_workspace(owner, workspace_id)
        except rows.NotFound:
            raise Refused("not_found", "There is no such project.") from None
        return self.store.switches(owner, workspace_id)

    def _extension(self, owner: Owner, extension_id: str) -> extensions.Skill:
        found = next((s for s in self._offered(owner) if s.id == extension_id), None)
        if found is None:
            raise Refused("not_found", "There is no such extension.")
        return found

    def extension(self, owner: Owner, extension_id: str) -> dict[str, Any]:
        """One extension with its whole text, and for each project whether it is on."""
        skill = self._extension(owner, extension_id)
        where = []
        for w in self.workspaces(owner):
            on = extensions.is_on(skill, self.store.switches(owner, w["id"]))
            where.append({**w, "on": on})
        return {**skill.view(with_text=True), "where": where}

    async def switch_extension(
        self, owner: Owner, extension_id: str, workspace_id: str, on: bool
    ) -> dict[str, Any]:
        """Switch an extension on or off for one project. A conversation's skills are fixed
        when it starts, so the project's sessions begin a new one with their next message."""
        skill = self._extension(owner, extension_id)
        self._switches(owner, workspace_id)
        if on and skill.needs_approval:
            raise Refused(
                "needs_approval",
                "This plugin brings more than text. Look at what it brings and approve it first.",
            )
        self.store.set_switch(owner, workspace_id, skill.id, on)
        await self._begin_again(owner, workspace_id)
        return {**skill.view(), "on": on}

    def approve_extension(self, owner: Owner, extension_id: str) -> dict[str, Any]:
        """The person has seen what a plugin brings and says yes. Once; it is switched on for a
        project as a separate step."""
        skill = self._extension(owner, extension_id)
        if skill.kind != extensions.PLUGIN:
            raise Refused("not_a_plugin", "A skill brings text only: there is nothing to approve.")
        self.store.approve_extension(owner, extension_id.partition(":")[2])
        return self._extension(owner, extension_id).view(with_text=True)

    async def _begin_again(self, owner: Owner, workspace_id: str) -> None:
        """Let go of the conversations of a project's sessions that are at rest. One that is
        in the middle of a turn keeps its skills until that turn has ended."""
        end = getattr(self.place, "end", None)
        for session in self.store.list_sessions(owner):
            if session["workspace_id"] != workspace_id or not session["place_session"]:
                continue
            if session["id"] in self._turns:
                continue
            if end is not None:
                with contextlib.suppress(PlaceError):
                    await end(session["place_session"])
            self.store.set_place_session(owner, session["id"], None)
            self.store.set_cursor(owner, session["id"], None)

    def look_at_folder(self, folder: str) -> dict[str, Any]:
        """What a folder the person chose holds, before anything is copied."""
        try:
            return extensions.look(_real(folder))
        except extensions.ExtensionError as e:
            raise Refused(e.code, e.message) from None

    async def add_extension(
        self, owner: Owner, folder: str, workspace_id: str = ""
    ) -> dict[str, Any]:
        """Copy a skill's or a plugin's folder in and offer it. With a project a skill is
        switched on for it; a plugin that brings a hook or a tool connection is not: it waits
        for the person's approval."""
        data = self.state.desktop_dir
        if data is None:
            raise Refused("unavailable", "Extensions cannot be added here.")
        self._switches(owner, workspace_id)
        source = await asyncio.to_thread(_real, folder)
        item = rows.new_id()
        try:
            seen = await asyncio.to_thread(extensions.look, source)
            if any(s.name == seen["name"] for s in self._offered(owner)):
                raise Refused(
                    "taken", f"One called {seen['name']} is already here. Remove it first."
                )
            kept = await asyncio.to_thread(
                extensions.copy_in, source, Path(data) / "code" / EXTENSIONS_DIR, item
            )
        except extensions.ExtensionError as e:
            raise Refused(e.code, e.message) from None
        self.store.add_extension(
            owner, item, name=seen["name"], title=seen["title"], path=str(kept),
            added_from=str(source), kind=seen["kind"],
        )  # fmt: skip
        skill = self._extension(owner, f"{extensions.ADDED}:{item}")
        on = bool(workspace_id) and not skill.needs_approval
        if on:
            self.store.set_switch(owner, workspace_id, skill.id, True)
            await self._begin_again(owner, workspace_id)
        await self._index_extension(owner, item, skill)
        return {**skill.view(with_text=True), "on": on}

    async def remove_extension(self, owner: Owner, extension_id: str) -> bool:
        """Forget an extension the person added. Our copy is removed; their folder was never
        touched. One of the short list cannot be removed, only switched off."""
        source, _, item = extension_id.partition(":")
        if source != extensions.ADDED:
            raise Refused("not_yours", "Only an extension you added can be removed.")
        try:
            row = self.store.get_extension(owner, item)
        except rows.NotFound:
            return False
        was_on = [
            w["id"]
            for w in self.workspaces(owner)
            if self.store.switches(owner, w["id"]).get(extension_id)
        ]
        self.store.delete_extension(owner, item)
        data = self.state.desktop_dir
        kept = Path(row["path"])
        if data is not None and Path(data) / "code" / EXTENSIONS_DIR in kept.parents:
            await asyncio.to_thread(shutil.rmtree, kept, True)
        for workspace_id in was_on:
            await self._begin_again(owner, workspace_id)
        return True

    async def _index_extension(self, owner: Owner, item: str, skill: extensions.Skill) -> None:
        """Make an added extension findable (ADR-0041): best effort, never fails the request."""
        index = self.state.creation_index
        if index is None:
            return
        try:
            await index.index(
                owner.tenant_id, PRODUCT_ID, owner.user_id, EXTENSION_KIND, item,
                search_text(extensions.words_of(skill)),
            )  # fmt: skip
        except Exception:
            log.warning("the extension could not be added to search", exc_info=True)

    # ---- the preview ----------------------------------------------------------------------------

    def preview(self, owner: Owner, session_id: str) -> dict[str, Any]:
        """The project's preview: its command, what the project's files suggest, and where the
        running one is."""
        session = self._session(owner, session_id)
        workspace = self.store.get_workspace(owner, session["workspace_id"])
        try:
            found = previews.suggest(Path(workspace["path"]))
        except OSError:
            found = []
        running = self.previews.get(session_id)
        return {
            "project": workspace["name"],
            "command": workspace["preview_command"],
            "suggested": found,
            "running": running.view() if running is not None else None,
        }

    def set_preview(self, owner: Owner, session_id: str, command: str) -> dict[str, Any]:
        session = self._session(owner, session_id)
        command = command.strip()
        if len(command) > previews.MAX_COMMAND or "\0" in command:
            raise Refused("bad_command", "That command is too long.")
        self.store.set_preview(owner, session["workspace_id"], command)
        return self.preview(owner, session_id)

    async def start_preview(
        self, owner: Owner, session_id: str, command: str | None = None
    ) -> dict[str, Any]:
        """Start the project in its sandbox. `command` is kept as the project's when given."""
        session = self._session(owner, session_id)
        if command is not None and command.strip():
            self.set_preview(owner, session_id, command)
        workspace = self.store.get_workspace(owner, session["workspace_id"])
        try:
            await self.previews.start(
                session_id, Path(workspace["path"]), workspace["preview_command"]
            )
        except previews.PreviewError as e:
            raise Refused(e.code, e.message) from None
        except PlaceError as e:
            raise Refused("no_sandbox", str(e) or "A preview is not available here.") from None
        return self.preview(owner, session_id)

    async def stop_preview(self, owner: Owner, session_id: str) -> dict[str, Any]:
        self._session(owner, session_id)
        await self.previews.stop(session_id)
        return self.preview(owner, session_id)

    # ---- a new project from a starter -----------------------------------------------------------

    async def start_new(
        self,
        owner: Owner,
        *,
        parent: str,
        name: str,
        starter: str = "web",
        model: str = "",
        mode: str = rows.ASK,
    ) -> dict[str, Any]:
        """A new project in a new folder inside `parent`, from a starter, and a session on it.
        The starter's own preview and check commands are set: they are part of what was made."""
        inside = check_folder(
            (parent.strip().rstrip("/") or "/") + "/x",  # a folder inside it: is that allowed?
            data_dir=self.state.desktop_dir,
            must_exist=False,
        ).parent
        try:
            chosen = starters.get(starter)
            folder = await asyncio.to_thread(starters.make, starter, inside, name)
        except starters.StarterError as e:
            raise Refused(e.code, e.message) from None
        try:
            made = await self.start(owner, folder=str(folder), model=model, mode=mode)
        except Refused:
            await asyncio.to_thread(shutil.rmtree, folder, True)
            raise
        workspace_id = self.store.get_session(owner, made["id"])["workspace_id"]
        self.store.set_check(owner, workspace_id, chosen.check, source="suggested")
        self.store.set_preview(owner, workspace_id, chosen.preview)
        return self.view(owner, made["id"])

    # ---- the person's terminal -------------------------------------------------------------------

    async def open_terminal(
        self, owner: Owner, session_id: str, cols: int = 80, rows: int = 24
    ) -> dict[str, Any]:
        """A new terminal of the person's own in the session's project, inside the sandbox."""
        session = self._session(owner, session_id)
        workspace = self.store.get_workspace(owner, session["workspace_id"])
        try:
            made = await self.terminals.open(session_id, Path(workspace["path"]), cols, rows)
        except TerminalError as e:
            raise Refused(e.code, e.message) from None
        except PlaceError as e:
            raise Refused("no_sandbox", str(e) or "A terminal is not available here.") from None
        return made.view()

    def terminal(self, owner: Owner, session_id: str, terminal_id: str) -> Terminal:
        self._session(owner, session_id)
        try:
            return self.terminals.get(session_id, terminal_id)
        except TerminalError as e:
            raise Refused(e.code, e.message) from None

    def list_terminals(self, owner: Owner, session_id: str) -> list[dict[str, Any]]:
        self._session(owner, session_id)
        return [t.view() for t in self.terminals.of(session_id)]

    async def close_terminal(self, owner: Owner, session_id: str, terminal_id: str) -> bool:
        self._session(owner, session_id)
        return await self.terminals.close(session_id, terminal_id)

    # ---- changes and undo -----------------------------------------------------------------------

    def _cps(self, workspace: dict[str, Any]) -> CheckpointStore | None:
        """The project's checkpoint store, under the app's data folder: outside the project,
        and where the sandbox lets the coding engine neither read nor write."""
        data = self.state.desktop_dir
        if data is None:
            return None
        folder = Path(data) / "code" / CHECKPOINTS_DIR / workspace["id"]
        return CheckpointStore(folder, Path(workspace["path"]))

    def _marks(self, turns: list[dict[str, Any]]) -> tuple[str | None, str | None]:
        """Which turn can be undone and which brought back. Undo goes back one turn at a time,
        the newest that still stands first. What comes back is the turn undone last, and only
        while no turn that came after that undo has changed the files."""
        changed = [t for t in turns if t["changed"] and t["before_commit"]]
        live = [t for t in changed if not t["undone_at"]]
        undo = live[-1]["id"] if live else None
        gone = [t for t in changed if t["undone_at"] and t["redo_commit"]]
        redo = None
        if gone:
            last = max(gone, key=lambda t: t["undone_at"])
            if not any(t["started_at"] > last["undone_at"] for t in live):
                redo = last["id"]
        return undo, redo

    def _turn_rows(self, owner: Owner, session_id: str) -> list[dict[str, Any]]:
        turns = self.store.list_turns(owner, session_id)
        for turn in turns:
            turn["before_commit"] = None
            if turn["checkpoint_id"]:
                with contextlib.suppress(rows.NotFound):
                    kept = self.store.get_checkpoint(owner, turn["checkpoint_id"])
                    turn["before_commit"] = kept["commit_id"]
        return turns

    async def changes(self, owner: Owner, session_id: str) -> dict[str, Any]:
        """The turns of the session that changed files, the newest first, each with its files
        (the Changes tab)."""
        session = self._session(owner, session_id)
        workspace = self.store.get_workspace(owner, session["workspace_id"])
        turns = self._turn_rows(owner, session_id)
        undo, redo = (None, None) if session_id in self._turns else self._marks(turns)
        cps = self._cps(workspace)
        items = []
        for turn in reversed(turns):
            if not turn["changed"] or not turn["before_commit"] or cps is None:
                continue
            try:
                found = await asyncio.to_thread(
                    cps.changes, turn["before_commit"], turn["after_commit"]
                )
            except CheckpointError:
                found = []
            items.append(
                {
                    "turn_id": turn["id"],
                    "position": turn["position"],
                    "request": turn["request"][:200],
                    "started_at": turn["started_at"],
                    "undone": bool(turn["undone_at"]),
                    "can_undo": turn["id"] == undo,
                    "can_redo": turn["id"] == redo,
                    "files": [
                        {"path": c.path, "what": c.what, "test": is_test_file(c.path)}
                        for c in found
                    ],
                }
            )
        return {"items": items}

    async def change(
        self, owner: Owner, session_id: str, turn_id: str, path: str
    ) -> dict[str, Any]:
        """One file a turn changed, before and after, and the two as lines side by side."""
        session = self._session(owner, session_id)
        workspace = self.store.get_workspace(owner, session["workspace_id"])
        turn = next((t for t in self._turn_rows(owner, session_id) if t["id"] == turn_id), None)
        cps = self._cps(workspace)
        if turn is None or cps is None or not turn["before_commit"] or not turn["after_commit"]:
            raise Refused("not_found", "That turn changed no file.")
        try:
            before, after = await asyncio.to_thread(
                lambda: (
                    cps.file_at(turn["before_commit"], path),
                    cps.file_at(turn["after_commit"], path),
                )
            )
        except CheckpointError:
            raise Refused("not_found", "That file is not among the turn's changes.") from None
        if before is None and after is None:
            raise Refused("not_found", "That file is not among the turn's changes.")
        return await asyncio.to_thread(_shown, path, before, after)

    async def undo(self, owner: Owner, session_id: str, turn_id: str) -> dict[str, Any]:
        """Put the project's files back to how they were before the turn. A checkpoint is taken
        first, so `redo` brings the turn's changes back."""
        return await self._put_back(owner, session_id, turn_id, back=True)

    async def redo(self, owner: Owner, session_id: str, turn_id: str) -> dict[str, Any]:
        """Bring an undone turn's changes back."""
        return await self._put_back(owner, session_id, turn_id, back=False)

    async def _put_back(
        self, owner: Owner, session_id: str, turn_id: str, *, back: bool
    ) -> dict[str, Any]:
        session = self._session(owner, session_id)
        if self.running(session_id):
            raise Refused("busy", "The agent is working. Stop it or wait, then try again.")
        workspace = self.store.get_workspace(owner, session["workspace_id"])
        turns = self._turn_rows(owner, session_id)
        turn = next((t for t in turns if t["id"] == turn_id), None)
        cps = self._cps(workspace)
        if turn is None or cps is None:
            raise Refused("not_found", "There is no such turn in this session.")
        undo, redo = self._marks(turns)
        if back and turn_id != undo:
            raise Refused(
                "not_last",
                "Only the newest turn that changed files can be undone. Undo the later ones first.",
            )
        if not back and turn_id != redo:
            raise Refused(
                "not_last", "This turn cannot be brought back: the files were changed since."
            )
        target = turn["before_commit"] if back else turn["redo_commit"]
        was = turn["after_commit"] if back else turn["before_commit"]
        try:
            own = await asyncio.to_thread(cps.changed_since, was)
            done = await asyncio.to_thread(cps.undo, target)
        except CheckpointError as e:
            log.warning("a coding turn could not be put back: %s", e)
            raise Refused(
                "cannot_undo", "The files could not be put back. Nothing was changed."
            ) from None
        self.store.add_checkpoint(
            owner, workspace_id=workspace["id"], kind="undo", commit_id=done.before.id,
            tree_id=done.before.tree, label="before undo" if back else "before bringing back",
            session_id=session_id, turn_id=turn_id,
        )  # fmt: skip
        self.store.set_turn_undone(owner, turn_id, done.before.id if back else None)
        return {
            "turn_id": turn_id,
            "undone": back,
            "files": int(turn["changed"]),
            # the person changed files themselves since: those went with it, and come back
            # with the other button
            "own_changes": bool(own),
            "notes": list(done.notes),
        }

    async def delete(self, owner: Owner, session_id: str) -> bool:
        """Forget a session. The folder is the person's and is not touched."""
        session = self._session(owner, session_id)
        await self.stop(owner, session_id)
        await self.terminals.close_session(session_id)
        await self.previews.stop(session_id)
        end = getattr(self.place, "end", None)
        if session["place_session"] and end is not None:
            with contextlib.suppress(PlaceError):
                await end(session["place_session"])
        self._feeds.pop(session_id, None)
        return await asyncio.to_thread(self.store.delete_session, owner, session_id)

    def view(self, owner: Owner, session_id: str) -> dict[str, Any]:
        """A session as the window will show it: its rows, where it is, its last answer and
        its cost. Never the place's own ids."""
        session = self._session(owner, session_id)
        workspace = self.store.get_workspace(owner, session["workspace_id"])
        turns = self.store.list_turns(owner, session_id)
        last = turns[-1] if turns else None
        return {
            "id": session["id"],
            "product_id": PRODUCT_ID,
            "title": session["title"],
            "folder": workspace["path"],
            "project": workspace["name"],
            "mode": session["mode"],
            "model": session["model"],
            # the person's own agent program it runs on, or "" for Wasify AI's own (ADR-0107)
            "harness": (self.harness_of(session["model"]) or ("", ""))[0],
            "state": last["state"] if last else "new",
            "working": self.running(session_id),
            "checking": session_id in self._checking
            or bool(last and last["state"] == rows.CHECKING and session_id in self._turns),
            "needs_you": bool(last and last["needs_you"]) and not self.running(session_id),
            "check_command": workspace["check_command"],
            # the session is a scheduled run's, on a copy of the project
            "scheduled_run": bool(workspace.get("copy_of")),
            "preview_command": workspace["preview_command"],
            "previewing": bool(
                (shown := self.previews.get(session_id)) and shown.state != previews.ENDED
            ),
            "waiting": bool(
                session_id in self._turns
                and any(not a.done() for a in self._turns[session_id].asks.values())
            ),
            "result": session["result"],
            "turns": len(turns),
            "answer": last["answer"] if last else "",
            "ended": _outward(last)["why"] if last and last["state"] == rows.DONE else "",
            "cost_usd": round(float(session["cost_usd"]), 6),
            # 0 in the row means "the usual limit": say the number that holds
            "cost_limit_usd": float(session["cost_limit_usd"]) or self._usual_limit(),
            "model_calls": int(session["model_calls"]),
            "tokens_in": int(session["tokens_in"]),
            "tokens_out": int(session["tokens_out"]),
            # a model with no known price is counted and limited in tokens, not in dollars
            "counted_in": self._counted_in(session["model"]),
            "token_limit": int(session["token_limit"] or 0) or self._usual_token_limit(),
            "created_at": session["created_at"],
            "updated_at": session["updated_at"],
        }

    def _usual_limit(self) -> float:
        return float(getattr(self.state.coding_gateway, "default_limit_usd", 0.0) or 0.0)

    def _usual_token_limit(self) -> int:
        return int(getattr(self.state.coding_gateway, "default_limit_tokens", 0) or 0)

    def _counted_in(self, model: str) -> str:
        if self.harness_of(model) is not None:
            return "plan"  # paid by the person's own plan; the program's report is shown
        try:
            route = self.state.coding_gateway.model(model or None)
        except Exception:
            return "usd"
        return "tokens" if getattr(route, "counted_in_tokens", False) else "usd"

    def set_token_limit(self, owner: Owner, session_id: str, limit_tokens: int) -> dict[str, Any]:
        """The most tokens a session on a model with no known price may use, from its next call."""
        self._session(owner, session_id)
        self.store.set_session_token_limit(owner, session_id, limit_tokens)
        set_limit = getattr(self.state.coding_gateway, "set_token_limit", None)
        if set_limit is not None:
            set_limit(session_id, limit_tokens)
        return self.view(owner, session_id)

    def set_limit(self, owner: Owner, session_id: str, limit_usd: float) -> dict[str, Any]:
        """The most the session may cost, from its next model call on."""
        self._session(owner, session_id)
        self.store.set_session_limit(owner, session_id, limit_usd)
        set_limit = getattr(self.state.coding_gateway, "set_limit", None)
        if set_limit is not None:
            set_limit(session_id, limit_usd)
        return self.view(owner, session_id)

    def turns(self, owner: Owner, session_id: str) -> list[dict[str, Any]]:
        self._session(owner, session_id)
        keep = (
            "id", "position", "request", "state", "result", "why", "check_why", "answer",
            "steps", "notes", "started_at", "finished_at", "changed", "rounds", "needs_you",
        )  # fmt: skip
        found = [_outward(t) for t in self._turn_rows(owner, session_id)]
        undo, redo = (None, None) if session_id in self._turns else self._marks(found)
        return [
            {
                **{k: t[k] for k in keep},
                "undone": bool(t["undone_at"]),
                "can_undo": t["id"] == undo,
                "can_redo": t["id"] == redo,
            }
            for t in found
        ]

    async def stop_all(self) -> int:
        """Stop every turn in flight, whoever's it is (the coding engine is being stopped).
        Gives how many there were."""
        for flight in list(self._turns.values()):
            flight.stop.set()
        tasks = [f.task for f in self._turns.values() if f.task is not None]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return len(tasks)

    async def close(self) -> None:
        """The engine is closing: every turn in flight is stopped, every terminal closed."""
        if self.scheduled is not None:
            await self.scheduled.close()  # the timer first: nothing new comes due
        await self.stop_all()
        await self.terminals.close_all()
        await self.previews.close_all()
        close = getattr(self.place, "close", None)
        if close is not None:
            await close()

    # ---- one turn ------------------------------------------------------------------------------

    def _session(self, owner: Owner, session_id: str) -> dict[str, Any]:
        try:
            return self.store.get_session(owner, session_id)
        except rows.NotFound:
            raise Refused("not_found", "There is no such coding session.") from None

    async def _turn(
        self,
        owner: Owner,
        session: dict[str, Any],
        workspace: dict[str, Any],
        turn: dict[str, Any],
        flight: _Turn,
    ) -> dict[str, Any]:
        """One turn from the message to its closed row, run by the loop. It never raises."""
        sid = session["id"]
        run = asyncio.ensure_future(
            self.loop.run_turn(
                owner, sid, turn["request"], turn=turn, stop=flight.stop,
                unattended=flight.unattended,
            )
        )  # fmt: skip
        stopping = asyncio.ensure_future(flight.stop.wait())
        try:
            done, _ = await asyncio.wait({run, stopping}, return_when=asyncio.FIRST_COMPLETED)
            if run not in done:
                self.loop.stop(sid)  # a check that runs is ended at once
                for waiting in flight.asks.values():  # a card that waits is closed, unanswered
                    if not waiting.done():
                        waiting.set_result("")
                if flight.where is not None:
                    # the loop interrupts the place and reads on to its "ended"; not for ever
                    await asyncio.wait({run}, timeout=STOP_GRACE_S * 4)
                if not run.done():  # the session is still being made, or nothing answers
                    run.cancel()
            await asyncio.gather(run, return_exceptions=True)
            if not run.cancelled() and run.exception() is not None:
                log.error("a coding turn failed", exc_info=run.exception())
        finally:
            stopping.cancel()
            await asyncio.gather(stopping, return_exceptions=True)
            if not flight.told:
                # the loop was cut off before it said the end: its row is closed, say it here
                self._turns.pop(sid, None)
                closed = self.store.get_turn(owner, turn["id"])
                why = places.STOPPED if flight.stop.is_set() else places.ERROR
                self.feed(sid).add(
                    STATE, sid, turn["id"], state=rows.DONE, why=why, result=closed["result"],
                    detail="" if flight.stop.is_set()
                    else "Something went wrong in the app while the agent worked.",
                    cost_usd=self._cost(sid),
                )  # fmt: skip
        return _outward(self.store.get_turn(owner, turn["id"]))

    def _cost(self, session_id: str) -> float:
        cost = 0.0
        with contextlib.suppress(Exception):
            cost = float(self.state.coding_gateway.spent(session_id)["usd"])
        return round(cost, 6)

    def _on_loop(self, event: dict[str, Any]) -> None:
        """What the loop says, said on the session's feed in the contract's words."""
        sid = str(event["session_id"])
        feed = self.feed(sid)
        if event["kind"] == "check":
            feed.add(
                CHECK, sid, str(event.get("turn_id") or ""), id=event["id"],
                round=int(event["round"]), rounds=self.loop.rounds, command=event["command"],
                result=event["result"], why=event["why"], exit_code=event["exit_code"],
                seconds=float(event["seconds"]), changed_tests=list(event["changed_tests"]),
                tail=str(event.get("tail") or "")[-TAIL_SHOWN:],
            )  # fmt: skip
            return
        state = str(event["state"])
        more: dict[str, Any] = {}
        for key in ("why", "result", "detail", "changed", "needs_you"):
            if event.get(key) not in (None, ""):
                more[key] = event[key]
        if event.get("needs_you") is False:
            more.pop("needs_you", None)
        if "why" in more:
            more["why"], check_why = how_it_ended(str(more["why"]))
            if check_why:
                more["check_why"] = check_why
        if "round" in event or "rounds" in event:
            more["round"] = int(event.get("round") or event.get("rounds") or 0)
        if state == rows.DONE:
            more.setdefault("result", "")
            more.setdefault("why", places.FINISHED)
            flight = self._turns.pop(sid, None)  # closed before it is said: who hears "done"
            if flight is not None:  # and asks at once must not find it still working
                flight.told = True
        feed.add(STATE, sid, str(event["turn_id"]), state=state, cost_usd=self._cost(sid), **more)

    async def _closing(
        self,
        owner: Owner,
        session: dict[str, Any],
        workspace: dict[str, Any],
        turn: dict[str, Any],
        why: str,
        detail: str,
    ) -> dict[str, Any]:
        """The turn is over: its words and steps are written, what it changed is counted, and a
        refusal is said. What is given back goes out with the turn's last state."""
        flight = self._turns.get(session["id"])
        answer, steps = (flight.answer, flight.steps) if flight is not None else ("", 0)
        store, feed = self.store, self.feed(session["id"])
        if why == places.REFUSED:
            # the model's own words, as a plain message: not an error
            answer = detail or answer
            feed.add(REFUSAL, session["id"], turn["id"], message=answer)
        elif why == places.ERROR and detail:
            store.note_turn(owner, turn["id"], detail)
        store.set_turn_answer(owner, turn["id"], answer=answer, steps=steps)
        more: dict[str, Any] = {}
        if why in (places.ERROR, places.REFUSED) and detail:
            more["detail"] = detail
        changed = await self._after(owner, workspace, turn)
        if changed is not None:
            more["changed"] = changed
        return more

    async def _after(
        self, owner: Owner, workspace: dict[str, Any], turn: dict[str, Any]
    ) -> int | None:
        """Keep the project as the turn left it and count what it changed. None for a turn that
        had no checkpoint (Plan, or git could not)."""
        kept = self.store.get_turn(owner, turn["id"])["checkpoint_id"]
        cps = self._cps(workspace)
        if not kept or cps is None:
            return None
        try:
            before = self.store.get_checkpoint(owner, kept)["commit_id"]
            made = await asyncio.to_thread(cps.checkpoint, "after the turn")
            changed = len(await asyncio.to_thread(cps.changes, before, made.id))
        except (CheckpointError, rows.NotFound) as e:
            log.warning("no checkpoint after a coding turn: %s", e)
            self.store.note_turn(owner, turn["id"], "What this turn changed could not be recorded.")
            return None
        self.store.set_turn_changes(owner, turn["id"], after_commit=made.id, changed=changed)
        return changed

    def _request(self, owner: Owner, session: dict[str, Any], turn: dict[str, Any]) -> str:
        """The person's message as the agent gets it: with what the agent cannot know by itself
        (its last turn was undone; the conversation is new because the mode changed)."""
        earlier = [t for t in self.store.list_turns(owner, session["id"]) if t["id"] != turn["id"]]
        text = turn["request"]
        if not earlier:
            return text
        last = earlier[-1]
        if last["undone_at"]:
            text = f"{UNDONE_NOTE}\n\n{text}"
        if not session["place_session"] and session["last_event"] is None and last["answer"]:
            # a new conversation after a change of mode: it goes on from the last answer
            self.store.note_turn(owner, turn["id"], MODE_CHANGED)
            text = (
                "Earlier in this session the person asked:\n"
                f"{last['request'][:RECAP_CHARS]}\n\nYou answered:\n"
                f"{last['answer'][:RECAP_CHARS]}\n\nNow the person says:\n{text}"
            )
        return text

    async def _confirm(
        self,
        owner: Owner,
        session: dict[str, Any],
        workspace: dict[str, Any],
        turn: dict[str, Any],
        flight: _Turn,
        feed: Feed,
        event: Any,
    ) -> None:
        """The coding engine waits before one or more changes. Answer at once, or ask the person
        first (`rules.py`). Nothing has run while it waits."""
        ask_id = str(event.data.get("id") or "")
        steps = [s for s in event.data.get("steps") or [] if isinstance(s, dict)]
        folder = Path(workspace["path"])
        cps = self._cps(workspace)

        def left_out(path: str) -> bool:
            try:
                return cps.is_left_out(path) if cps is not None else True
            except CheckpointError:
                return True  # not known: undo cannot be promised, so it is asked

        kinds = await asyncio.to_thread(
            lambda: [rules.classify(step, folder, left_out) for step in steps]
        )
        mode = self.store.get_session(owner, session["id"])["mode"]  # it may have changed
        allowed = self.store.get_workspace(owner, workspace["id"])["allowed"]
        if flight.unattended:
            # a scheduled run needs no approval for ordinary work, and nobody is there for the
            # rest: whatever a chat in "Ask before changes" would ask about (a delete, an
            # install, a file Undo cannot put back, a picture) is judged as there, and refused
            # unless the person allowed that kind for the project
            mode = rows.ASK
        verdict, kind = rules.decide(mode, allowed, kinds)
        mark = rules.ALLOWED if verdict == rules.ALLOWED else ""
        if verdict == "ask" and flight.unattended:
            # nobody is there to ask (ADR-0105, decision 11): it is refused and written down
            step = steps[kinds.index(kind)]
            what = str(step.get("command") or step.get("path") or step.get("tool") or "")[:300]
            self.store.note_turn(owner, turn["id"], f"Refused, nobody to ask: {what}")
            mark = rules.NO
        elif verdict == "ask":
            step = steps[kinds.index(kind)]
            waiting: asyncio.Future[str] = asyncio.get_running_loop().create_future()
            flight.asks[ask_id] = waiting
            feed.add(
                INTERRUPT, session["id"], turn["id"], interrupt_id=ask_id, kind=ASK_KIND,
                payload={
                    "ask": kind,
                    "step_id": str(step.get("id") or ""),
                    "tool": str(step.get("tool") or ""),
                    "command": str(step.get("command") or ""),
                    "path": rules.path_in(folder, str(step.get("path") or "")) or "",
                    "says": _reason(step),
                    "project": workspace["name"],
                    "undo": kind != rules.NOT_UNDOABLE,
                    "steps": len(steps),
                },
            )  # fmt: skip
            mark = await waiting
            if not mark:  # the turn was stopped while the card waited
                return
            if mark == rules.ALLOW:
                self.store.set_allowed(owner, workspace["id"], [*allowed, kind])
        for step, found in zip(steps, kinds, strict=True):
            if mark and found:
                flight.marks[str(step.get("id") or "")] = mark
        if mark != rules.NO:
            # a picture or speech that was let through is made now, by the app itself and for
            # the person, before the command that asked for it runs and reads how it went
            for step, found in zip(steps, kinds, strict=True):
                if found == rules.MAKE:
                    await self._make(owner, workspace, str(step.get("command") or ""))
        if flight.where is not None:
            # a no is for this one step: said too strongly, a model went on to refuse the
            # person's later requests for the same file by itself (docs/spikes/coding-c2.md)
            no = (
                "This is a scheduled run and nobody is here to answer, so this one step was not "
                "done. Go on without it, and say in your final message what you could not do."
                if flight.unattended
                else "The person was asked and said no to this one step, so it was not done. Do "
                "not repeat this same step now: go on without it, or say what you could not do. "
                "If the person asks for it again later, try it again as usual."
            )
            with contextlib.suppress(PlaceError):
                await self.place.answer(
                    flight.where, ask_id, mark != rules.NO, no if mark == rules.NO else ""
                )

    async def _make(self, owner: Owner, workspace: dict[str, Any], command: str) -> None:
        data = self.state.desktop_dir
        if data is None:
            return
        identity = Identity(owner.tenant_id, owner.user_id)
        notes = Path(data) / "coding-fixed" / assets.NOTES
        await assets.make(self.state, identity, Path(workspace["path"]), notes, command)

    def _relay(
        self, feed: Feed, session: dict[str, Any], turn: dict[str, Any], flight: _Turn, event: Any
    ) -> None:
        """One event of the place, said to whoever follows the session."""
        ids = (session["id"], turn["id"])
        data = event.data
        if event.kind == places.TEXT:
            flight.answer = str(data.get("text") or "")
            feed.add(MESSAGE, *ids, text=flight.answer)
        elif event.kind == places.PIECE:
            kind = REASONING if data.get("thinking") else TOKEN
            feed.add(kind, *ids, node=NODE, text=str(data.get("text") or ""))
        elif event.kind == places.STEP:
            flight.steps += 1
            given = {k: v for k, v in data.items() if k not in ("tool", "id")}
            feed.add(
                TOOL_CALL, *ids, id=str(data.get("id") or ""), name=str(data.get("tool") or ""),
                arguments=given,
            )  # fmt: skip
        elif event.kind == places.RESULT:
            call = str(data.get("id") or "")
            output = {"text": str(data.get("text") or "")}
            if call in flight.marks:  # how its question was answered: yes, allow, no, allowed
                output["answer"] = flight.marks.pop(call)
            status = "refused" if data.get("refused") else "ok" if data.get("ok") else "error"
            feed.add(
                TOOL_RESULT, *ids, id=call, name=str(data.get("tool") or ""), status=status,
                output=output,
            )  # fmt: skip
        elif event.kind == places.SKILLS:
            names = [str(n) for n in data.get("names") or []]
            if names:
                feed.add(SKILLS_USED, *ids, names=names, titles=self._skill_titles(names))
        elif event.kind == places.CONFIRM:
            # a session that only reads has nothing to ask; whatever asks is told no
            asyncio.ensure_future(self._say_no(flight, str(data.get("id") or "")))

    async def _say_no(self, flight: _Turn, confirmation: str) -> None:
        if flight.where is not None:
            with contextlib.suppress(PlaceError):
                await self.place.answer(
                    flight.where, confirmation, False, "This session only reads."
                )

    # ---- cost and search -----------------------------------------------------------------------

    async def _on_call(self, call: Any) -> None:
        """One model call, from the gateway: added to the session's row."""
        await asyncio.to_thread(
            self.store.add_session_cost,
            call.session_id,
            usd=float(call.usd),
            tokens_in=int(call.input_tokens),
            tokens_out=int(call.output_tokens),
        )

    def words(self, owner: Owner, session_id: str) -> str:
        """What a person would remember a session by: its title, its project and what was asked
        first."""
        session = self.store.get_session(owner, session_id)
        workspace = self.store.get_workspace(owner, session["workspace_id"])
        turns = self.store.list_turns(owner, session_id)
        return words_of(session["title"], workspace["name"], turns[0]["request"] if turns else "")

    async def _index(self, owner: Owner, session_id: str) -> None:
        """Make the session findable (ADR-0041): best effort, never fails the request."""
        index = self.state.creation_index
        if index is None:
            return
        try:
            await index.index(
                owner.tenant_id, PRODUCT_ID, owner.user_id, KIND, session_id,
                search_text(self.words(owner, session_id)),
            )  # fmt: skip
        except Exception:
            log.warning("the coding session could not be added to search", exc_info=True)


def _real(folder: str) -> Path:
    """A folder the person named, as its real path."""
    return Path(os.path.realpath(os.path.expanduser(folder.strip())))


def _reason(step: dict[str, Any]) -> str:
    """The agent's own reason for a step, when it gave one. The coding engine fills a missing
    summary with the tool's name and what it was given; that is not a reason, and is left out."""
    said = str(step.get("summary") or "").strip()
    tool = str(step.get("tool") or "")
    return "" if not said or said.startswith((f"{tool}:", f"{tool}(", "{")) else said


def words_of(title: str, project: str, first_request: str) -> str:
    parts = [title, f"Coding session on {project}" if project else "", first_request]
    return ". ".join(p.strip() for p in parts if p and p.strip())


def _title_of(request: str) -> str:
    """A session's name from its first request: its first line, cut at a word."""
    line = request.strip().splitlines()[0].strip() if request.strip() else ""
    if len(line) <= 60:
        return line
    return line[:60].rsplit(" ", 1)[0] + "…"


def _shown(path: str, before: bytes | None, after: bytes | None) -> dict[str, Any]:
    """A changed file for the Changes tab: each side as text, and the two as lines."""
    what = "added" if before is None else "deleted" if after is None else "changed"
    out: dict[str, Any] = {
        "path": path, "what": what, "test": is_test_file(path), "binary": False,
        "too_large": False, "before": None, "after": None, "lines": [],
    }  # fmt: skip
    sides = [b for b in (before, after) if b is not None]
    if any(b"\0" in b[:8000] for b in sides):
        out["binary"] = True
        return out
    if any(len(b) > MAX_SHOWN_BYTES for b in sides):
        out["too_large"] = True
        return out
    old = before.decode("utf-8", "replace") if before is not None else None
    new = after.decode("utf-8", "replace") if after is not None else None
    out["before"], out["after"] = old, new
    a, b = (old or "").splitlines(), (new or "").splitlines()
    if len(a) + len(b) > MAX_SHOWN_LINES * 2:
        out["too_large"] = True
        return out
    lines: list[dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag == "equal":
            lines += [{"t": "same", "text": line, "a": i1 + n + 1, "b": j1 + n + 1}
                      for n, line in enumerate(a[i1:i2])]  # fmt: skip
            continue
        lines += [{"t": "del", "text": line, "a": i1 + n + 1} for n, line in enumerate(a[i1:i2])]
        lines += [{"t": "add", "text": line, "b": j1 + n + 1} for n, line in enumerate(b[j1:j2])]
    out["lines"] = lines
    return out


def _check_row(row: dict[str, Any]) -> dict[str, Any]:
    """A check as the window is given it: never where its output file is."""
    keep = ("id", "turn_id", "round", "command", "result", "why", "exit_code", "seconds",
            "changed_tests", "created_at")  # fmt: skip
    return {k: row[k] for k in keep}
