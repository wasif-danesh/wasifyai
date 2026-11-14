"""The implement, check, fix loop (ADR-0103, decisions 1 to 10; section 6 of the start plan).

The agent implements, in its place. We check, here. One function, `Loop.run_turn`, serves a chat
turn and a scheduled run alike (decision 10).

    working -> turn ended -> did the turn change files?
                 no  -> done (the last result stands)
                 yes -> checking -> passed            -> done
                                 -> failed, round < 3 -> the output goes back -> working
                                 -> failed, round = 3 -> done: needs you
                                 -> could not check   -> done: needs you
    stopped by the person, or at the step limit -> not checked

What the rules come to in this code:

- The place's "finished" only moves the turn to `turn_ended`. Done is the row we write.
- **When the check runs.** After the agent finished, if the files differ from what they were the
  last time we looked (before the turn, or straight after the check of the round before) and from
  the last state that passed. A turn that changed nothing runs no check and changes no word: a
  question costs nothing. (`docs/spikes/coding-cores.md`, "Open points", says why "since the last
  pass" alone is not enough.)
- A turn that ended any other way than "finished" (stopped, the step limit, an error, a refusal)
  is "not checked", whatever it changed.
- No command set for the workspace is "not checked". A command that cannot run, a time limit or a
  crash is "could not check". Neither is ever "passed" (`checks._judge`).
- Three rounds. After the third failure the turn is over and says what still fails. The person's
  next message starts a new count.
- Stop works in every state: it interrupts the place, ends a running check at once (the whole
  process group) and the turn is "not checked".
- Every check is a row, with the test files the agent changed or deleted during the turn.
- A scheduled run has nobody to ask: a confirmation is refused and written down (ADR-0105, 11).

The product's sessions (`runtime.py`) run every turn through this function since stage C3. What
the loop does not know (how a session is opened in the place, what is said to whoever follows
it, how a question is answered) it asks of its `Hooks`. The check runs inside a sandbox of our
own when `sandbox` is given (`client.ThisComputer.sandbox`).
"""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wasifyai_code import checks
from wasifyai_code import place as places
from wasifyai_code import store as rows
from wasifyai_code.checkpoints import CheckpointError, CheckpointStore
from wasifyai_code.checks import Check, CheckResult, is_test_file
from wasifyai_code.place import Place, PlaceError, PlaceEvent, SessionSpec
from wasifyai_code.store import CodeStore, Owner

ROUNDS = 3
NOBODY_TO_ASK = "Nobody is here to answer: this is a scheduled run."

# why a turn ended the way it did, beside the reasons of `place` and `checks`
NO_CHANGE = "no_change"  # the turn changed no file: no check, the last result stands
SAME_AS_LAST_PASS = "same_as_last_pass"  # the files are again exactly what passed
NO_CHANGE_AFTER_FAILURE = "no_change_after_failure"  # sent the failure, the agent changed nothing
ROUNDS_USED = "rounds_used"  # the check failed on the last allowed round
CUT_OFF = "cut_off"  # the turn was ended from outside before it could say how it ended


class TurnRunning(Exception):
    """The session is in the middle of a turn."""


@dataclass(frozen=True)
class TurnOutcome:
    turn_id: str
    result: str  # one of the four words; "" when nothing was ever checked in this session
    why: str = ""
    rounds: int = 0  # how many times the check ran
    needs_you: bool = False
    says: str = ""  # what still fails: the end of the last check's output, or the error
    changed_tests: tuple[str, ...] = ()
    checks: tuple[dict[str, Any], ...] = ()  # the check rows of this turn, in order

    @property
    def checked(self) -> bool:
        return self.rounds > 0


@dataclass
class _Run:
    """One turn in flight."""

    stop: asyncio.Event = field(default_factory=asyncio.Event)
    check: Check | None = None
    cursor: str | None = None  # the last event of the place that was read


class Hooks:
    """What the loop asks of whoever runs it. The defaults are what a plain run needs (a
    scheduled run, a test); the product's sessions give their own (`runtime.Sessions`)."""

    # True: `event` is given the questions of an unattended turn too, and answers them itself
    # by rules (nobody is asked). False: the loop refuses every question of an unattended turn.
    answers_unattended = False

    def spec(
        self, owner: Owner, session: dict[str, Any], workspace: dict[str, Any], unattended: bool
    ) -> SessionSpec:
        """What the place needs to start this session."""
        return SessionSpec(Path(workspace["path"]), model=session["model"], unattended=unattended)

    async def open(
        self,
        owner: Owner,
        session: dict[str, Any],
        workspace: dict[str, Any],
        turn: dict[str, Any],
        spec: SessionSpec,
        place: Place,
    ) -> tuple[str, str | None]:
        """The place's session for this turn and the last event already read from it."""
        if session["place_session"]:
            return session["place_session"], session["last_event"]
        return await place.start(spec), None

    def request(self, owner: Owner, session: dict[str, Any], turn: dict[str, Any]) -> str:
        """The person's message as the agent gets it."""
        return turn["request"]

    async def event(
        self,
        owner: Owner,
        session: dict[str, Any],
        workspace: dict[str, Any],
        turn: dict[str, Any],
        where: str,
        event: PlaceEvent,
    ) -> None:
        """One event of the place, but the turn's end. A `confirm` of an attended turn is
        answered here."""

    async def ended(
        self,
        owner: Owner,
        session: dict[str, Any],
        workspace: dict[str, Any],
        turn: dict[str, Any],
        why: str,
        detail: str,
    ) -> dict[str, Any]:
        """The turn is over and its row is about to be closed. What is given back is said with
        the turn's last state."""
        return {}


def failure_message(result: CheckResult, round: int, rounds: int) -> str:
    """What goes back to the agent after a failed check: the command, its exit code and the end of
    its output (decision 3)."""
    return (
        f"The project's check did not pass (try {round} of {rounds}).\n\n"
        f"Command: {result.command}\n"
        f"Exit code: {result.exit_code}\n\n"
        f"The end of its output:\n{result.tail}\n\n"
        "Fix what fails. The check is run again when you finish."
    )


class Loop:
    def __init__(
        self,
        place: Place,
        store: CodeStore,
        *,
        checkpoints: Callable[[dict[str, Any]], CheckpointStore | None],
        outputs: Path,
        rounds: int = ROUNDS,
        wrapper: Sequence[str] = (),
        env: Mapping[str, str] | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        stop_wait_s: float = 5.0,
        hooks: Hooks | None = None,
        sandbox: Callable[[Path], Awaitable[tuple[Sequence[str], Mapping[str, str] | None]]]
        | None = None,
    ):
        """`checkpoints` gives a workspace row's checkpoint store (None: this deployment keeps
        none). `outputs` is the folder the checks' full outputs are written under. `wrapper` and
        `env` go to every check (`checks.Check`), unless `sandbox` gives them for the project's
        folder. `on_event` is told each state of a turn and each check as it happens."""
        self.place, self.store = place, store
        self._checkpoints, self.outputs = checkpoints, Path(outputs)
        self.rounds, self.wrapper, self.env = rounds, tuple(wrapper), env
        self._on_event, self.stop_wait_s = on_event, stop_wait_s
        self.hooks, self._sandbox = hooks or Hooks(), sandbox
        self._runs: dict[str, _Run] = {}

    # ---- what the product calls ------------------------------------------------------------------

    def running(self, session_id: str) -> bool:
        return session_id in self._runs

    def stop(self, session_id: str) -> bool:
        """Stop the session's turn, whatever state it is in. False when none is running."""
        run = self._runs.get(session_id)
        if run is None:
            return False
        run.stop.set()
        if run.check is not None:
            run.check.stop()
        return True

    async def run_turn(
        self,
        owner: Owner,
        session_id: str,
        request: str,
        *,
        unattended: bool = False,
        turn: dict[str, Any] | None = None,
        stop: asyncio.Event | None = None,
    ) -> TurnOutcome:
        """One turn of a session, from the request to its result. The same function for a chat
        message and for a scheduled run (`unattended`). `turn` is the turn's row when the
        caller has already written it; `stop` is the caller's own stop signal, which may be set
        before this begins."""
        if session_id in self._runs:
            raise TurnRunning(session_id)
        session = self.store.get_session(owner, session_id)
        workspace = self.store.get_workspace(owner, session["workspace_id"])
        run = self._runs[session_id] = _Run(cursor=session["last_event"])
        if stop is not None:
            run.stop = stop
        if turn is None:
            turn = self.store.add_turn(owner, session_id, request)
        try:
            return await self._turn(owner, session, workspace, turn, run, unattended)
        except PlaceError as e:
            return await self._finish(
                owner, session, workspace, turn, run, rows.NOT_CHECKED, places.ERROR,
                says=str(e) or "The coding engine could not do that.",
            )  # fmt: skip
        finally:
            del self._runs[session_id]
            # a turn that is still open here was cut off (the engine is closing, or a fault of ours)
            self.store.finish_turn(
                owner, turn["id"], result=rows.NOT_CHECKED,
                why=places.STOPPED if run.stop.is_set() else CUT_OFF,
            )  # fmt: skip

    async def check_now(self, owner: Owner, session_id: str) -> dict[str, Any]:
        """Run the workspace's check outside a turn (the person asked for it). The row is written
        and the session's word is set, like any other check. Gives the check row."""
        if session_id in self._runs:
            raise TurnRunning(session_id)
        session = self.store.get_session(owner, session_id)
        workspace = self.store.get_workspace(owner, session["workspace_id"])
        run = self._runs[session_id] = _Run()
        try:
            result, row = await self._check(owner, session, workspace, None, run, 0, None)
            if result.passed:
                await self._passed(owner, session, workspace, None)
            self.store.set_session_result(owner, session_id, result.result)
            return row
        finally:
            del self._runs[session_id]

    # ---- one turn --------------------------------------------------------------------------------

    async def _turn(
        self,
        owner: Owner,
        session: dict[str, Any],
        workspace: dict[str, Any],
        turn: dict[str, Any],
        run: _Run,
        unattended: bool,
    ) -> TurnOutcome:
        spec = self.hooks.spec(owner, session, workspace, unattended)
        reads = spec.read_only  # it cannot change a file: no checkpoint, no check
        cps = None if reads else self._checkpoints(workspace)
        self._tell(session, turn, rows.WORKING)
        before = None
        if not reads:
            before = await self._keep(owner, cps, session, turn, "turn", turn["request"][:80])
        if before is not None:
            self.store.set_turn(owner, turn["id"], checkpoint_id=before["id"])
        looked = before["tree_id"] if before else None  # the files, the last time we looked
        passed_tree = self._last_pass_tree(owner, workspace)

        done: list[dict[str, Any]] = []
        last: CheckResult | None = None
        tests: tuple[str, ...] = ()

        async def finish(result: str, why: str = "", **more: Any) -> TurnOutcome:
            return await self._finish(
                owner, session, workspace, turn, run, result, why, checks=done,
                changed_tests=tests, **more,
            )  # fmt: skip

        message = self.hooks.request(owner, session, turn)
        if run.stop.is_set():  # stopped before anything was asked
            self._ended(owner, session, turn, places.STOPPED)
            return await finish(
                session["result"] if reads else rows.NOT_CHECKED, places.STOPPED, stands=reads
            )
        where, run.cursor = await self.hooks.open(owner, session, workspace, turn, spec, self.place)
        if where != session["place_session"]:
            self.store.set_place_session(owner, session["id"], where)

        while True:
            why, detail = await self._work(
                owner, session, workspace, turn, where, run, unattended, message
            )
            self._ended(owner, session, turn, why)
            if reads:  # a session that only reads has nothing to check: its word stands
                return await finish(
                    session["result"], NO_CHANGE if why == places.FINISHED else why,
                    stands=True, says=detail,
                )  # fmt: skip
            if why != places.FINISHED:  # stopped, the step limit, an error, a refusal
                return await finish(rows.NOT_CHECKED, why, says=detail)
            if run.stop.is_set():
                await self.place.stop(where)
                return await finish(rows.NOT_CHECKED, places.STOPPED)
            tree = await self._tree(cps)
            if tree is not None and tree == looked:
                if last is None:  # the turn changed nothing: what stood, stands
                    return await finish(session["result"], NO_CHANGE, stands=True)
                return await finish(
                    rows.FAILED, NO_CHANGE_AFTER_FAILURE, needs_you=True, says=last.tail
                )
            if tree is not None and tree == passed_tree:
                return await finish(rows.PASSED, SAME_AS_LAST_PASS)
            if not workspace["check_command"].strip():
                return await finish(rows.NOT_CHECKED, checks.NO_COMMAND)

            round = len(done) + 1
            self.store.set_turn(owner, turn["id"], state=rows.CHECKING, rounds=round)
            self._tell(
                session, turn, rows.CHECKING, round=round, command=workspace["check_command"]
            )
            last, row = await self._check(owner, session, workspace, turn, run, round, before)
            done.append(row)
            tests = tuple(row["changed_tests"])
            if last.result == rows.PASSED:
                await self._passed(owner, session, workspace, turn)
                return await finish(rows.PASSED)
            if last.result == rows.NOT_CHECKED:  # stopped while it ran
                await self.place.stop(where)  # Stop also interrupts the place (decision 7)
                return await finish(rows.NOT_CHECKED, last.why)
            if last.result == rows.COULD_NOT_CHECK:
                return await finish(rows.COULD_NOT_CHECK, last.why, needs_you=True, says=last.tail)
            if round >= self.rounds:
                return await finish(rows.FAILED, ROUNDS_USED, needs_you=True, says=last.tail)
            if run.stop.is_set():  # it failed, and the person does not want another try
                await self.place.stop(where)
                return await finish(rows.FAILED, places.STOPPED, says=last.tail)

            looked = await self._tree(cps)  # a check may write files itself
            self.store.set_turn(owner, turn["id"], state=rows.WORKING)
            self._tell(session, turn, rows.WORKING, round=round)
            message = failure_message(last, round, self.rounds)

    def _ended(self, owner: Owner, session: dict[str, Any], turn: dict[str, Any], why: str) -> None:
        self.store.set_turn(owner, turn["id"], state=rows.TURN_ENDED)
        self._tell(session, turn, rows.TURN_ENDED, why=why)

    async def _work(
        self,
        owner: Owner,
        session: dict[str, Any],
        workspace: dict[str, Any],
        turn: dict[str, Any],
        where: str,
        run: _Run,
        unattended: bool,
        message: str,
    ) -> tuple[str, str]:
        """Give the place the message and follow it until the agent's turn ends, or stop it.
        Gives why it ended, and the detail."""

        async def follow() -> tuple[str, str]:
            # listen first, then speak: words as they are written go only to who is listening
            opened = asyncio.Event()
            if getattr(self.place, "connects_first", False):
                stream: Any = self.place.follow(where, after=run.cursor, opened=opened)  # type: ignore[call-arg]
            else:
                stream = self.place.follow(where, after=run.cursor)
                opened.set()
            first = asyncio.ensure_future(anext(stream, None))
            listening = asyncio.ensure_future(opened.wait())
            try:
                await asyncio.wait({first, listening}, return_when=asyncio.FIRST_COMPLETED)
                if run.stop.is_set():
                    return places.STOPPED, ""
                await self.place.send(where, message, run=True)
                event = await first
                while event is not None:
                    if event.kind != places.PIECE:  # a piece is not kept: nothing follows it
                        run.cursor = event.id
                    if event.kind == places.ENDED:
                        return (
                            str(event.data.get("why") or places.ERROR),
                            str(event.data.get("detail") or ""),
                        )
                    if (
                        event.kind == places.CONFIRM
                        and unattended
                        and not self.hooks.answers_unattended
                    ):
                        await self.place.answer(where, event.data["id"], False, NOBODY_TO_ASK)
                        what = str(event.data.get("what", ""))[:500]
                        self.store.note_turn(owner, turn["id"], f"Refused, nobody to ask: {what}")
                    else:
                        await self.hooks.event(owner, session, workspace, turn, where, event)
                    event = await anext(stream, None)
                return places.ERROR, "The place stopped sending events."
            finally:
                for task in (first, listening):
                    task.cancel()
                await asyncio.gather(first, listening, return_exceptions=True)
                close = getattr(stream, "aclose", None)
                if close is not None:
                    await close()

        following = asyncio.ensure_future(follow())
        stopping = asyncio.ensure_future(run.stop.wait())
        try:
            done, _ = await asyncio.wait({following, stopping}, return_when=asyncio.FIRST_COMPLETED)
            if following in done:
                return following.result()
            with contextlib.suppress(PlaceError, TimeoutError):
                await asyncio.wait_for(self.place.stop(where), self.stop_wait_s)
            # read on to the place's own "ended", so the next turn starts after it; not for ever
            await asyncio.wait({following}, timeout=self.stop_wait_s)
            if not following.done():  # it did not end: ask once more, and let go of it
                with contextlib.suppress(PlaceError, TimeoutError):
                    await asyncio.wait_for(self.place.stop(where), self.stop_wait_s)
            failed = following.exception() if following.done() else None
            if failed is not None and not isinstance(failed, PlaceError):
                raise failed
            return places.STOPPED, ""
        finally:
            for task in (following, stopping):
                task.cancel()
            await asyncio.gather(following, stopping, return_exceptions=True)

    async def _check(
        self,
        owner: Owner,
        session: dict[str, Any],
        workspace: dict[str, Any],
        turn: dict[str, Any] | None,
        run: _Run,
        round: int,
        before: dict[str, Any] | None,
    ) -> tuple[CheckResult, dict[str, Any]]:
        """Run the check once and write its row."""
        name = f"{turn['id'] if turn else rows.new_id()}-{round}.txt"
        wrapper, env = self.wrapper, self.env
        if self._sandbox is not None:
            try:
                wrapper, env = await self._sandbox(Path(workspace["path"]))
            except PlaceError as e:  # no sandbox, no check: never run it outside one
                wrapper, env = ("/usr/bin/false", f"no sandbox: {e}"), env
        check = run.check = Check(
            workspace["check_command"],
            Path(workspace["path"]),
            output=self.outputs / session["id"] / name,
            time_limit_s=workspace["check_limit_s"],
            wrapper=tuple(wrapper),
            env=env,
        )
        if run.stop.is_set():
            check.stop()
        try:
            result = await check.run()
        finally:
            run.check = None
        tests: list[str] = []
        cps = self._checkpoints(workspace) if before is not None else None
        if before is not None and cps is not None:
            # which tests the agent changed or deleted during the turn
            try:
                changes = await asyncio.to_thread(cps.changes, before["commit_id"])
                tests = sorted(
                    c.path for c in changes if c.what != "added" and is_test_file(c.path)
                )
            except CheckpointError:
                pass
        row = self.store.add_check(
            owner,
            workspace_id=workspace["id"],
            session_id=session["id"],
            turn_id=turn["id"] if turn else None,
            round=round,
            command=result.command,
            result=result.result,
            why=result.why,
            exit_code=result.exit_code,
            seconds=result.seconds,
            output_file=str(result.output_file or ""),
            changed_tests=tests,
        )
        self._say({"kind": "check", "session_id": session["id"], "tail": result.tail, **row})
        return result, row

    async def _passed(
        self,
        owner: Owner,
        session: dict[str, Any],
        workspace: dict[str, Any],
        turn: dict[str, Any] | None,
    ) -> None:
        """Keep the state that passed: it is what "since the last pass" is measured against."""
        cps = self._checkpoints(workspace)
        kept = await self._keep(owner, cps, session, turn, "pass", "passed")
        if kept is not None:
            self.store.set_last_pass(owner, workspace["id"], kept["id"])

    async def _finish(
        self,
        owner: Owner,
        session: dict[str, Any],
        workspace: dict[str, Any],
        turn: dict[str, Any],
        run: _Run,
        result: str,
        why: str,
        *,
        needs_you: bool = False,
        says: str = "",
        stands: bool = False,
        checks: Sequence[dict[str, Any]] = (),
        changed_tests: tuple[str, ...] = (),
    ) -> TurnOutcome:
        """Write the turn's end. `stands` means no new word: the session keeps the one it had."""
        more = await self.hooks.ended(owner, session, workspace, turn, why, says)
        self.store.finish_turn(
            owner, turn["id"], result=result, why=why, rounds=len(checks), needs_you=needs_you
        )
        if not stands:
            self.store.set_session_result(owner, session["id"], result)
        self.store.set_cursor(owner, session["id"], run.cursor)
        self._tell(
            session, turn, rows.DONE, result=result, why=why, needs_you=needs_you,
            rounds=len(checks), **more,
        )  # fmt: skip
        return TurnOutcome(
            turn["id"], result, why, len(checks), needs_you, says, changed_tests, tuple(checks)
        )

    # ---- the checkpoint store, which may fail without stopping a turn ----------------------------

    async def _keep(
        self,
        owner: Owner,
        cps: CheckpointStore | None,
        session: dict[str, Any],
        turn: dict[str, Any] | None,
        kind: str,
        label: str,
    ) -> dict[str, Any] | None:
        """Take a checkpoint and write its row. When git cannot, the turn goes on without one and
        says so: it cannot be undone, and its check runs whatever changed."""
        try:
            if cps is None:
                raise CheckpointError("this deployment keeps no checkpoints")
            made = await asyncio.to_thread(cps.checkpoint, label)
        except CheckpointError as e:
            if turn is not None:
                self.store.note_turn(
                    owner, turn["id"], f"No checkpoint could be taken ({kind}): {e}"
                )
            return None
        return self.store.add_checkpoint(
            owner,
            workspace_id=session["workspace_id"],
            kind=kind,
            commit_id=made.id,
            tree_id=made.tree,
            label=label,
            session_id=session["id"],
            turn_id=turn["id"] if turn else None,
        )

    @staticmethod
    async def _tree(cps: CheckpointStore | None) -> str | None:
        if cps is None:
            return None
        try:
            return await asyncio.to_thread(cps.tree)
        except CheckpointError:
            return None  # not known: treated as changed

    def _last_pass_tree(self, owner: Owner, workspace: dict[str, Any]) -> str | None:
        if not workspace["last_pass"]:
            return None
        try:
            return self.store.get_checkpoint(owner, workspace["last_pass"])["tree_id"]
        except rows.NotFound:
            return None

    # ---- telling whoever listens -----------------------------------------------------------------

    def _tell(self, session: dict[str, Any], turn: dict[str, Any], state: str, **more: Any) -> None:
        self._say(
            {
                "kind": "turn",
                "session_id": session["id"],
                "turn_id": turn["id"],
                "state": state,
                **more,
            }
        )

    def _say(self, event: dict[str, Any]) -> None:
        if self._on_event is not None:
            self._on_event(event)
