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

Every session of this stage is in **Plan mode**: the agent only reads, so nothing can change,
nothing is checked and the session's word stays what it was. No checkpoint is taken. The
implement, check, fix loop (`loop.py`) takes over the turn when a mode that edits arrives (C2).

**The relay.** Each session has a `Feed`: the turn's states, the agent's steps, its words and a
refusal, in order, in the shape of the SSE contract's section "A coding session's stream"
(`docs/contracts/sse-events.md`; ADR-0101, amendment of 2026-11-14). The route
`GET /code/sessions/{id}/events` sends it to the window as it is.
"""

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk import search_text

from wasifyai_code import PRODUCT_ID
from wasifyai_code import place as places
from wasifyai_code import store as rows
from wasifyai_code.place import Account, Place, PlaceError, SessionSpec
from wasifyai_code.store import CodeStore, Owner

log = logging.getLogger(__name__)

KIND = "code_session"  # what a session is called in search (ADR-0041)
STEP_LIMIT = 60  # tool steps in one turn of a session that reads
STOP_GRACE_S = 3.0  # after Stop, how long the place's own "ended" is waited for
# the stream's event kinds (the SSE contract, "A coding session's stream")
STATE, MESSAGE, REFUSAL = "code_state", "code_message", "code_refusal"
TOOL_CALL, TOOL_RESULT = "tool_call", "tool_result"
TOKEN, REASONING = "token", "reasoning"  # words as they are written: relayed, never kept
NOT_KEPT = (TOKEN, REASONING)
NODE = "agent"
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

    def add(self, kind: str, session_id: str, turn_id: str, **data: Any) -> dict[str, Any]:
        """One event in the contract's envelope: the session is the thread, the turn the run."""
        self._seq += 1
        event = {
            "event": kind,
            "run_id": turn_id,
            "thread_id": session_id,
            "seq": self._seq,
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            **data,
        }
        if kind not in NOT_KEPT:
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
    ) -> dict[str, Any]:
        """A new session on a folder. Nothing runs yet, and the coding engine is not started."""
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
            mode=rows.PLAN,
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
            "result": session["result"],
            "turns": len(turns),
            "answer": last["answer"] if last else "",
            "ended": last["why"] if last and last["state"] == rows.DONE else "",
            "cost_usd": round(float(session["cost_usd"]), 6),
            "cost_limit_usd": float(session["cost_limit_usd"]),
            "tokens_in": int(session["tokens_in"]),
            "tokens_out": int(session["tokens_out"]),
            "created_at": session["created_at"],
            "updated_at": session["updated_at"],
        }

    def turns(self, owner: Owner, session_id: str) -> list[dict[str, Any]]:
        self._session(owner, session_id)
        keep = ("id", "position", "request", "state", "result", "why", "answer", "steps", "notes",
                "started_at", "finished_at")  # fmt: skip
        return [{k: t[k] for k in keep} for t in self.store.list_turns(owner, session_id)]

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
        return await self._close_turn(owner, session, turn, flight, feed, why, detail)

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
                await self.place.send(where, turn["request"], run=True)
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
            feed.add(
                TOOL_RESULT, *ids, id=str(data.get("id") or ""), name=str(data.get("tool") or ""),
                status="ok" if data.get("ok") else "error",
                output={"text": str(data.get("text") or "")},
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
    ) -> dict[str, Any]:
        """Write how the turn ended. A turn that only read changes no word: what stood, stands."""
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
            self._tell(feed, session, turn, rows.DONE, why=why, result=standing, detail=detail)
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


def words_of(title: str, project: str, first_request: str) -> str:
    parts = [title, f"Coding session on {project}" if project else "", first_request]
    return ". ".join(p.strip() for p in parts if p and p.strip())


def _title_of(request: str) -> str:
    """A session's name from its first request: its first line, cut at a word."""
    line = request.strip().splitlines()[0].strip() if request.strip() else ""
    if len(line) <= 60:
        return line
    return line[:60].rsplit(" ", 1)[0] + "…"
