"""The coding sessions in flight (stage C1b: a session that only reads).

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
"Ask me" and "Work on its own" (stage C2) it changes files with the file editor and runs nothing:

    before the turn   a checkpoint of the project (`checkpoints.py`), outside the project
    a change          waits in the coding engine; `rules.py` answers at once, or the person is
                      asked with a card (`interrupt`, kind `code_ask`) and may allow the kind
                      for the project
    after the turn    a second checkpoint: what the turn changed is the difference
    Sessions.undo     puts the files back to before the turn; `Sessions.redo` brings it back

No check runs yet: the agent cannot run a command, and neither do we until stage C3, when the
implement, check, fix loop (`loop.py`) takes over the turn. A session's word stays what it was.

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
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk import search_text

from wasifyai_code import PRODUCT_ID, rules
from wasifyai_code import place as places
from wasifyai_code import store as rows
from wasifyai_code.checkpoints import CheckpointError, CheckpointStore
from wasifyai_code.checks import is_test_file
from wasifyai_code.place import Account, Place, PlaceError, SessionSpec
from wasifyai_code.store import CodeStore, Owner

log = logging.getLogger(__name__)

KIND = "code_session"  # what a session is called in search (ADR-0041)
STEP_LIMIT = 60  # tool steps in one turn of a session that reads
STOP_GRACE_S = 3.0  # after Stop, how long the place's own "ended" is waited for
# the stream's event kinds (the SSE contract, "A coding session's stream")
STATE, MESSAGE, REFUSAL = "code_state", "code_message", "code_refusal"
TOOL_CALL, TOOL_RESULT = "tool_call", "tool_result"
INTERRUPT, ASK_KIND = "interrupt", "code_ask"  # the approval card (the contract's `interrupt`)
TOKEN, REASONING = "token", "reasoning"  # words as they are written: relayed, never kept
NOT_KEPT = (TOKEN, REASONING)
NODE = "agent"
MODE_CHANGED = (
    "The session changed between a mode that only reads and one that changes files, so the "
    "agent begins again from this message. It was given the last answer to go on from."
)
UNDONE_NOTE = (
    "(Since your last turn the person undid its changes: the project's files are back to how "
    "they were before that turn.)"
)
CHECKPOINTS_DIR = "checkpoints"
MAX_SHOWN_BYTES = 400_000  # of one side of a changed file, in the Changes tab
MAX_SHOWN_LINES = 4000
RECAP_CHARS = 6000
APP_RESTARTED = (
    "The app was started again since this session's last message, so the agent begins from "
    "this message and does not know the earlier ones."
)


class NotAvailable(Exception):
    """This deployment has no coding engine."""


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


def check_folder(folder: str, *, data_dir: Path | None, home: Path | None = None) -> Path:
    """The folder a session may be opened on, as its real path, or `Refused`.

    The sandbox opens a workspace to the coding engine, so a folder must not hold anything the
    sandbox exists to keep out of reach: the app's own data (its keys file is there), the
    person's whole home folder, their Library, or a hidden folder at the top of their home
    (`.ssh`, `.aws`, `.config`)."""
    if not folder.strip() or not os.path.isabs(os.path.expanduser(folder.strip())):
        raise Refused("bad_folder", "Give the folder's whole path, starting at the top.")
    path = Path(os.path.realpath(os.path.expanduser(folder.strip())))
    if not path.is_dir():
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

    # ---- what the actions and routes call ------------------------------------------------------

    def feed(self, session_id: str) -> Feed:
        return self._feeds.setdefault(session_id, Feed())

    def running(self, session_id: str) -> bool:
        return session_id in self._turns

    async def models(self) -> list[dict[str, Any]]:
        return await self.state.coding_gateway.list_models()

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
        gateway = self.state.coding_gateway
        try:
            route = gateway.model(model or None)
        except Exception as e:
            raise Refused("no_such_model", str(getattr(e, "message", e))) from None
        if (why := await gateway.ready(route.id)) is not None:
            raise Refused("model_not_ready", why)
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
            model=route.id,
            mode=mode,
            cost_limit_usd=cost_limit_usd,
        )
        await self._index(owner, session["id"])
        return self.view(owner, session["id"])

    async def send(self, owner: Owner, session_id: str, text: str) -> dict[str, Any]:
        """Begin a turn and give its row. The turn goes on in the background: follow the feed,
        or `wait` for its end."""
        if not text.strip():
            raise Refused("nothing_to_do", "Say what the agent should look at.")
        session = self._session(owner, session_id)
        if session_id in self._turns:
            raise Refused(
                "busy", "The agent is still working on the last message. Stop it or wait."
            )
        workspace = self.store.get_workspace(owner, session["workspace_id"])
        first = not self.store.list_turns(owner, session_id)
        turn = self.store.add_turn(owner, session_id, text.strip())
        flight = self._turns[session_id] = _Turn(turn["id"])
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
        return turns[-1]

    async def stop(self, owner: Owner, session_id: str) -> bool:
        """Stop the session's turn. False when none is running. Returns once the turn is closed."""
        self._session(owner, session_id)
        flight = self._turns.get(session_id)
        if flight is None:
            return False
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
        if session_id in self._turns:
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
            "state": last["state"] if last else "new",
            "working": session_id in self._turns,
            "waiting": bool(
                session_id in self._turns
                and any(not a.done() for a in self._turns[session_id].asks.values())
            ),
            "result": session["result"],
            "turns": len(turns),
            "answer": last["answer"] if last else "",
            "ended": last["why"] if last and last["state"] == rows.DONE else "",
            "cost_usd": round(float(session["cost_usd"]), 6),
            # 0 in the row means "the usual limit": say the number that holds
            "cost_limit_usd": float(session["cost_limit_usd"]) or self._usual_limit(),
            "model_calls": int(session["model_calls"]),
            "tokens_in": int(session["tokens_in"]),
            "tokens_out": int(session["tokens_out"]),
            "created_at": session["created_at"],
            "updated_at": session["updated_at"],
        }

    def _usual_limit(self) -> float:
        return float(getattr(self.state.coding_gateway, "default_limit_usd", 0.0) or 0.0)

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
        keep = ("id", "position", "request", "state", "result", "why", "answer", "steps", "notes",
                "started_at", "finished_at", "changed")  # fmt: skip
        found = self._turn_rows(owner, session_id)
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
        """The engine is closing: every turn in flight is stopped."""
        await self.stop_all()
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
        """One turn from the message to its closed row. It never raises."""
        feed = self.feed(session["id"])
        self._tell(feed, session, turn, rows.WORKING)
        why, detail = places.ERROR, ""
        work = asyncio.ensure_future(self._work(owner, session, workspace, turn, flight, feed))
        stopping = asyncio.ensure_future(flight.stop.wait())
        try:
            done, _ = await asyncio.wait({work, stopping}, return_when=asyncio.FIRST_COMPLETED)
            if work in done:
                why, detail = work.result()
            else:
                why, detail = places.STOPPED, ""
                for waiting in flight.asks.values():  # a card that waits is closed, unanswered
                    if not waiting.done():
                        waiting.set_result("")
                if flight.where is not None:  # the agent may be working: interrupt it
                    with contextlib.suppress(PlaceError, TimeoutError):
                        await asyncio.wait_for(self.place.stop(flight.where), STOP_GRACE_S)
                    # read on to the place's own "ended", so the next turn begins after it
                    await asyncio.wait({work}, timeout=STOP_GRACE_S)
                    if not work.done():  # it did not end: ask once more, and let go of it
                        with contextlib.suppress(PlaceError, TimeoutError):
                            await asyncio.wait_for(self.place.stop(flight.where), STOP_GRACE_S)
        except Exception:
            log.exception("a coding turn failed")
            detail = "Something went wrong in the app while the agent worked."
        finally:
            for task in (work, stopping):
                task.cancel()
            await asyncio.gather(work, stopping, return_exceptions=True)
        changed = await self._after(owner, workspace, turn)
        return await self._close_turn(owner, session, turn, flight, feed, why, detail, changed)

    async def _before(
        self, owner: Owner, session: dict[str, Any], workspace: dict[str, Any], turn: dict[str, Any]
    ) -> None:
        """Keep the project as it is before a turn that may change it. When git cannot, the turn
        goes on and says that it cannot be undone."""
        cps = self._cps(workspace)
        try:
            if cps is None:
                raise CheckpointError("this deployment keeps no checkpoints")
            made = await asyncio.to_thread(cps.checkpoint, turn["request"][:80])
        except CheckpointError as e:
            log.warning("no checkpoint before a coding turn: %s", e)
            self.store.note_turn(
                owner, turn["id"], "No checkpoint could be taken, so this turn cannot be undone."
            )
            return
        row = self.store.add_checkpoint(
            owner, workspace_id=workspace["id"], kind="turn", commit_id=made.id,
            tree_id=made.tree, label=turn["request"][:80], session_id=session["id"],
            turn_id=turn["id"],
        )  # fmt: skip
        self.store.set_turn(owner, turn["id"], checkpoint_id=row["id"])

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

    async def _work(
        self,
        owner: Owner,
        session: dict[str, Any],
        workspace: dict[str, Any],
        turn: dict[str, Any],
        flight: _Turn,
        feed: Feed,
    ) -> tuple[str, str]:
        """Give the place the message and follow it to the turn's end: why it ended, and the
        detail."""
        spec = SessionSpec(
            Path(workspace["path"]),
            model=session["model"],
            step_limit=STEP_LIMIT,
            read_only=session["mode"] == rows.PLAN,
            account=Account(
                owner.tenant_id, owner.product_id, owner.user_id, session["id"],
                spent_usd=float(session["cost_usd"]), limit_usd=float(session["cost_limit_usd"]),
            ),
        )  # fmt: skip
        try:
            if not spec.read_only:
                await self._before(owner, session, workspace, turn)
            request = self._request(owner, session, turn)
            where, cursor = session["place_session"], session["last_event"]
            adopt = getattr(self.place, "adopt", None)
            if where and adopt is not None and not adopt(where, spec):
                where = None
                self.store.note_turn(owner, turn["id"], APP_RESTARTED)
            if not where:
                where, cursor = await self.place.start(spec), None
                self.store.set_place_session(owner, session["id"], where)
            flight.where = where
            # listen first, then speak: words as they are written go only to who is listening
            opened = asyncio.Event()
            if getattr(self.place, "connects_first", False):
                stream = self.place.follow(where, after=cursor, opened=opened)
            else:
                stream = self.place.follow(where, after=cursor)
                opened.set()
            first = asyncio.ensure_future(anext(stream, None))
            listening = asyncio.ensure_future(opened.wait())
            try:
                await asyncio.wait({first, listening}, return_when=asyncio.FIRST_COMPLETED)
                if flight.stop.is_set():  # stopped before anything was asked
                    return places.STOPPED, ""
                await self.place.send(where, request, run=True)
                if flight.stop.is_set():  # Stop came while the message was on its way
                    await self.place.stop(where)
                event = await first
                while event is not None:
                    if event.kind != places.PIECE:  # a piece is not kept: nothing follows it
                        self.store.set_cursor(owner, session["id"], event.id)
                    if event.kind == places.ENDED:
                        return (
                            str(event.data.get("why") or places.ERROR),
                            str(event.data.get("detail") or ""),
                        )
                    if event.kind == places.CONFIRM and not spec.read_only:
                        await self._confirm(owner, session, workspace, turn, flight, feed, event)
                    else:
                        self._relay(feed, session, turn, flight, event)
                    event = await anext(stream, None)
            finally:
                for task in (first, listening):
                    task.cancel()
                await asyncio.gather(first, listening, return_exceptions=True)
                await stream.aclose()
            return places.ERROR, "The coding engine stopped sending events."
        except PlaceError as e:
            return places.ERROR, str(e) or "The coding engine could not do that."

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
        verdict, kind = rules.decide(mode, allowed, kinds)
        mark = rules.ALLOWED if verdict == rules.ALLOWED else ""
        if verdict == "ask":
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
        if flight.where is not None:
            # a no is for this one step: said too strongly, a model went on to refuse the
            # person's later requests for the same file by itself (docs/spikes/coding-c2.md)
            no = (
                "The person was asked and said no to this one step, so it was not done. Do not "
                "repeat this same step now: go on without it, or say what you could not do. "
                "If the person asks for it again later, try it again as usual."
            )
            with contextlib.suppress(PlaceError):
                await self.place.answer(
                    flight.where, ask_id, mark != rules.NO, no if mark == rules.NO else ""
                )

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
        elif event.kind == places.CONFIRM:
            # a session that only reads has nothing to ask; whatever asks is told no
            asyncio.ensure_future(self._say_no(flight, str(data.get("id") or "")))

    async def _say_no(self, flight: _Turn, confirmation: str) -> None:
        if flight.where is not None:
            with contextlib.suppress(PlaceError):
                await self.place.answer(
                    flight.where, confirmation, False, "This session only reads."
                )

    async def _close_turn(
        self,
        owner: Owner,
        session: dict[str, Any],
        turn: dict[str, Any],
        flight: _Turn,
        feed: Feed,
        why: str,
        detail: str,
        changed: int | None = None,
    ) -> dict[str, Any]:
        """Write how the turn ended. No check runs at this stage, so the session's word stays
        what it was. `changed` is how many files the turn changed (None: no checkpoint)."""
        store = self.store
        try:
            store.set_turn(owner, turn["id"], state=rows.TURN_ENDED)
            self._tell(feed, session, turn, rows.TURN_ENDED, why=why)
            if why == places.REFUSED:
                # the model's own words, as a plain message: not an error
                flight.answer = detail or flight.answer
                feed.add(REFUSAL, session["id"], turn["id"], message=flight.answer)
            elif why == places.ERROR and detail:
                store.note_turn(owner, turn["id"], detail)
            store.set_turn_answer(owner, turn["id"], answer=flight.answer, steps=flight.steps)
            standing = store.get_session(owner, session["id"])["result"]
            closed = store.finish_turn(owner, turn["id"], result=standing, why=why)
            more = {} if changed is None else {"changed": changed}
            self._tell(
                feed, session, turn, rows.DONE, why=why, result=standing, detail=detail, **more
            )
            return closed
        finally:
            self._turns.pop(session["id"], None)

    def _tell(
        self, feed: Feed, session: dict[str, Any], turn: dict[str, Any], state: str, **more: Any
    ) -> None:
        cost = 0.0
        with contextlib.suppress(Exception):
            cost = float(self.state.coding_gateway.spent(session["id"])["usd"])
        feed.add(STATE, session["id"], turn["id"], state=state, cost_usd=round(cost, 6), **more)

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
