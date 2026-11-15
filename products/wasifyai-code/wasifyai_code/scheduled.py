"""Scheduled runs in the app (ADR-0105; stage C6 of docs/v2-coding-agent-start-plan.md).

`schedules.py` knows when a schedule comes due and holds the one timer. This module is what the
timer is given: what a run *does*, and what the screen asks about schedules and their runs.

**One run.**

    1 a checkpoint of the project as it is now (`checkpoints.py`)
    2 a copy of what that checkpoint holds, in a folder of the coding engine's own
      (`<app data>/coding/copies/<run>/<project>`): inside the sandbox, outside the project
    3 a session on the copy, in "Work on its own", with nobody to ask: the same turn as a chat
      message (`Loop.run_turn`, through `Sessions.send(unattended=True)`), with the project's
      check and the project's skills. Ordinary edits and commands run; what a chat in "Ask
      before changes" would ask about (a delete, an install, a file Undo cannot put back, a
      picture) is refused and written down, unless that kind is allowed for the project
    4 the result word, and how many files the run changed in its copy

**The project is never touched by a run.** What the run changed stays in the copy until the
person looks at it and chooses "Apply to the project" or "Let it go". Applying writes each
changed file into the project only if the project's own file is still what the copy was made
from; a file the person changed meanwhile is left alone and named.

What the project ignores (`.env`, `node_modules`) is not in a checkpoint and so not in the copy:
a run whose check needs such files will say so through its check.
"""

import asyncio
import json
import logging
import shutil
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from wasifyai_code import schedules as rules
from wasifyai_code import store as rows
from wasifyai_code.checkpoints import CheckpointError
from wasifyai_code.runtime import Refused
from wasifyai_code.schedules import BadRule, RunResult, Timer
from wasifyai_code.store import Owner

log = logging.getLogger(__name__)

Row = dict[str, Any]

COPIES = "copies"  # under <app data>/coding, the coding engine's own folder
KEPT_COPIES = 5  # of one schedule: older copies nobody applied are let go
MAX_REQUEST = 20_000
TEMPLATES = Path(__file__).with_name("own") / "templates.json"


def templates() -> list[dict[str, Any]]:
    """Our short list of starting points for a schedule (ADR-0104, decision 9): prompt text and
    a plain rule, each with the rule in words. A template is only where a schedule starts: the
    person can change everything before it is saved."""
    found = json.loads(TEMPLATES.read_text()).get("templates") or []
    return [{**t, "rule_words": rule_words(t["rule"])} for t in found]


class ScheduleRefused(Exception):
    """A request that cannot be done, with the sentence the person is shown."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def words_of(title: str, project: str, when: str, request: str) -> str:
    """What a person would look a schedule up by (ADR-0041)."""
    parts = (title, "A scheduled run of the coding agent", project, when, request[:600])
    return ". ".join(p.strip().rstrip(".") for p in parts if p and p.strip())


def rule_words(rule: dict[str, Any]) -> str:
    """A rule in plain words: "Every day at 09:00"."""
    kind = rule.get("kind")
    at = str(rule.get("time") or "")
    if kind == "once":
        return f"Once, on {rule.get('date')} at {at}"
    if kind == "every":
        if rule.get("hours"):
            n = int(rule["hours"])
            return "Every hour" if n == 1 else f"Every {n} hours"
        return f"Every {int(rule.get('minutes') or 0)} minutes"
    if kind == "daily":
        return f"Every day at {at}"
    if kind == "weekdays":
        names = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
        days = [names[d] for d in rule.get("days") or [] if 0 <= int(d) <= 6]
        if days == list(names[:5]):
            return f"Every weekday at {at}"
        return f"Every {', '.join(days)} at {at}"
    if kind == "monthly":
        day = int(rule.get("day") or 1)
        last = " (or the month's last day)" if day > 28 else ""
        return f"Every month on day {day} at {at}{last}"
    return "At no time"


class Scheduled:
    """The schedules of the app and their runs. `sessions` is the product's `Sessions`."""

    def __init__(self, sessions: Any, *, clock: rules.Clock | None = None):
        self.sessions = sessions
        self.store = sessions.store
        self.timer = Timer(self.store, self._run, clock=clock)
        self._serving: asyncio.Task[None] | None = None

    # ---- the timer -------------------------------------------------------------------------------

    def start(self) -> None:
        """Begin to serve: from now on a schedule that comes due runs. Once."""
        if self._serving is None or self._serving.done():
            self._serving = asyncio.ensure_future(self.timer.serve())

    async def close(self) -> None:
        task, self._serving = self._serving, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def now(self) -> datetime:
        return self.timer.clock.now()

    # ---- schedules -------------------------------------------------------------------------------

    def _workspace(self, owner: Owner, workspace_id: str) -> dict[str, Any]:
        try:
            found = self.store.get_workspace(owner, workspace_id)
        except rows.NotFound:
            raise ScheduleRefused("not_found", "There is no such project.") from None
        if found.get("copy_of"):
            raise ScheduleRefused("not_found", "There is no such project.")
        return found

    def _schedule(self, owner: Owner, schedule_id: str) -> dict[str, Any]:
        try:
            return self.store.get_schedule(owner, schedule_id)
        except rows.NotFound:
            raise ScheduleRefused("not_found", "There is no such schedule.") from None

    def view(self, owner: Owner, schedule: dict[str, Any]) -> dict[str, Any]:
        try:
            project = self.store.get_workspace(owner, schedule["workspace_id"])["name"]
        except rows.NotFound:
            project = ""
        runs = self.store.list_runs(owner, schedule["id"])
        last = runs[-1] if runs else None
        return {
            "id": schedule["id"],
            "title": schedule["title"] or schedule["request"].strip().splitlines()[0][:60],
            "request": schedule["request"],
            "workspace_id": schedule["workspace_id"],
            "project": project,
            "rule": schedule["rule"],
            "rule_words": rule_words(schedule["rule"]),
            "time_zone": schedule["time_zone"],
            "enabled": bool(schedule["enabled"]),
            "run_when_missed": bool(schedule["run_when_missed"]),
            "model": schedule["model"],
            "next_due": schedule["next_due"] if schedule["enabled"] else None,
            "running": any(r["state"] in (rows.RUN_WAITING, rows.RUN_RUNNING) for r in runs),
            "last": self.run_view(owner, last) if last else None,
            "created_at": schedule["created_at"],
        }

    def list(self, owner: Owner, ids: Sequence[str] | None = None) -> list[dict[str, Any]]:
        found = reversed(self.store.list_schedules(owner))
        return [self.view(owner, s) for s in found if ids is None or s["id"] in ids]

    def get(self, owner: Owner, schedule_id: str) -> dict[str, Any]:
        schedule = self._schedule(owner, schedule_id)
        runs = self.store.list_runs(owner, schedule_id)
        return {
            **self.view(owner, schedule),
            "runs": [self.run_view(owner, r) for r in reversed(runs)][:50],
        }

    def add(
        self,
        owner: Owner,
        *,
        workspace_id: str,
        request: str,
        rule: dict[str, Any],
        time_zone: str,
        title: str = "",
        model: str = "",
        run_when_missed: bool = True,
    ) -> dict[str, Any]:
        self._workspace(owner, workspace_id)
        request = request.strip()
        if not request or len(request) > MAX_REQUEST:
            raise ScheduleRefused("nothing_to_do", "Say what the agent should do at each run.")
        self._model(model)
        try:
            made = rules.add_schedule(
                self.store, owner, workspace_id=workspace_id, request=request,
                rule=self._counted_from_now(rule),
                time_zone=time_zone, now=self.now(), run_when_missed=run_when_missed,
            )  # fmt: skip
        except BadRule as e:
            raise ScheduleRefused("bad_rule", str(e)) from None
        # with no model named, the one the person chose for this project's newest session
        model = model or self._model_of(owner, workspace_id)
        made = self.store.name_schedule(owner, made["id"], title=title.strip(), model=model)
        self.timer.changed()
        return self.view(owner, made)

    def change(self, owner: Owner, schedule_id: str, **given: Any) -> dict[str, Any]:
        """Change what a schedule asks, when it runs, or whether it is on."""
        have = self._schedule(owner, schedule_id)
        title, model = given.pop("title", None), given.pop("model", None)
        request = given.get("request")
        if request is not None and (not request.strip() or len(request) > MAX_REQUEST):
            raise ScheduleRefused("nothing_to_do", "Say what the agent should do at each run.")
        if model is not None:
            self._model(model)
        if given.get("rule") is not None:
            given["rule"] = self._counted_from_now(given["rule"])
        try:
            made = rules.change_schedule(self.store, owner, schedule_id, now=self.now(), **given)
        except BadRule as e:
            raise ScheduleRefused("bad_rule", str(e)) from None
        if title is not None or model is not None:
            made = self.store.name_schedule(
                owner, schedule_id,
                title=have["title"] if title is None else title.strip(),
                model=have["model"] if model is None else model,
            )  # fmt: skip
        self.timer.changed()
        return self.view(owner, made)

    def _counted_from_now(self, rule: dict[str, Any]) -> dict[str, Any]:
        """ "Every so many minutes or hours" is counted from when the schedule is saved, unless
        the rule names its own start."""
        if isinstance(rule, dict) and rule.get("kind") == "every" and not rule.get("start"):
            return {**rule, "start": rows.utc_text(self.now())}
        return rule

    async def index(self, owner: Owner, view: dict[str, Any]) -> None:
        """Make a schedule findable in the Library (ADR-0041): best effort, never fails the
        request."""
        from wasifyai_platform_sdk import search_text

        from wasifyai_code import PRODUCT_ID
        from wasifyai_code.runtime import SCHEDULE_KIND

        index = self.sessions.state.creation_index
        if index is None:
            return
        try:
            words = words_of(view["title"], view["project"], view["rule_words"], view["request"])
            await index.index(
                owner.tenant_id, PRODUCT_ID, owner.user_id, SCHEDULE_KIND, view["id"],
                search_text(words),
            )  # fmt: skip
        except Exception:
            log.warning("the schedule could not be added to search", exc_info=True)

    async def remove(self, owner: Owner, schedule_id: str) -> bool:
        """Forget a schedule and its history. The copies of its runs are let go."""
        self._schedule(owner, schedule_id)
        for run in self.store.list_runs(owner, schedule_id):
            await self._let_go(owner, run)
        done = self.store.delete_schedule(owner, schedule_id)
        self.timer.changed()
        return done

    def run_now(self, owner: Owner, schedule_id: str) -> dict[str, Any]:
        """ "Run now": the same run, with this moment as its due time."""
        self._schedule(owner, schedule_id)
        self.start()
        row = self.timer.run_now(owner, schedule_id)
        if row is None:
            raise ScheduleRefused("busy", "It was started a moment ago.")
        return self.run_view(owner, row)

    def _model_of(self, owner: Owner, workspace_id: str) -> str:
        """The model of the project's newest session: what the person chose to work with there.
        Empty when the project has none (then the gateway's own first choice holds)."""
        mine = [s for s in self.store.list_sessions(owner) if s["workspace_id"] == workspace_id]
        mine.sort(key=lambda s: s["created_at"])
        return str(mine[-1]["model"]) if mine else ""

    def _model(self, model: str) -> None:
        if not model:
            return
        if self.sessions.harness_of(model) is not None:
            # the person's own agent program (ADR-0107): whether it is signed in is asked at the run
            return
        try:
            self.sessions.state.coding_gateway.model(model)
        except Exception as e:  # noqa: BLE001  (the gateway's own, sayable refusal)
            raise ScheduleRefused("no_such_model", str(getattr(e, "message", e))) from None

    # ---- one run ---------------------------------------------------------------------------------

    def _copies(self) -> Path:
        server = self.sessions.state.coding_server
        return Path(server.run_dir) / COPIES

    async def _run(self, schedule: dict[str, Any], run: dict[str, Any]) -> RunResult:
        """What the timer calls when a schedule's time has come. Raising means the run failed,
        and what is raised is written down as why."""
        owner = Owner(schedule["tenant_id"], schedule["user_id"], schedule["product_id"])
        sessions = self.sessions
        project = self.store.get_workspace(owner, schedule["workspace_id"])
        folder = Path(project["path"])
        if not await asyncio.to_thread(folder.is_dir):
            raise RuntimeError(f"The project's folder is not there any more: {folder}")
        gateway = sessions.state.coding_gateway
        chosen = schedule["model"] or self._model_of(owner, project["id"])
        on_harness = sessions.harness_of(chosen) if chosen else None
        if on_harness is not None:
            # the person's own agent program, on their plan (ADR-0107, stage H3): it must be set
            # up and signed in when the run comes due; its words say what to do when it is not
            try:
                await sessions._harness_ready(on_harness[0])
            except Refused as e:
                raise RuntimeError(e.message) from None
            model_id = f"{on_harness[0]}:{on_harness[1] or 'default'}"
        else:
            try:
                route = gateway.model(chosen or None)
            except Exception as e:
                raise RuntimeError(str(getattr(e, "message", e))) from None
            if (why := await gateway.ready(route.id)) is not None:
                raise RuntimeError(why)
            model_id = route.id
        cps = sessions._cps(project)
        if cps is None:
            raise RuntimeError("Scheduled runs are not available here.")
        try:
            base = await asyncio.to_thread(cps.checkpoint, "before a scheduled run")
            target = self._copies() / run["id"] / (folder.name or "project")
            await asyncio.to_thread(cps.copy_to, base.id, target)
        except CheckpointError as e:
            raise RuntimeError(f"The project could not be copied: {e}") from None
        copy = self.store.add_workspace(
            owner, str(target), name=project["name"], check_command=project["check_command"],
            check_from=project["check_from"], check_limit_s=project["check_limit_s"],
            copy_of=project["id"],
        )  # fmt: skip
        self.store.set_allowed(owner, copy["id"], project["allowed"])
        for extension_id, on in self.store.switches(owner, project["id"]).items():
            self.store.set_switch(owner, copy["id"], extension_id, on)  # the project's skills
        self.store.set_run_copy(run["id"], copy_workspace=copy["id"], base_commit=base.id)
        session = self.store.add_session(
            owner, copy["id"], title=self.view(owner, schedule)["title"], model=model_id,
            mode=rows.OWN,
        )  # fmt: skip
        await sessions.send(owner, session["id"], schedule["request"], unattended=True)
        try:
            closed = await sessions.wait(owner, session["id"])
        except asyncio.CancelledError:
            await asyncio.shield(sessions.stop(owner, session["id"]))
            raise
        self.store.set_run_changed(run["id"], int(closed["changed"] or 0))
        await self._tidy(owner, schedule["id"])
        note = ""
        if closed["why"] not in ("finished", ""):
            note = {
                "stopped": "It was stopped.",
                "step_limit": "The agent used every step one turn allows.",
                "refused": "The model declined this request.",
            }.get(closed["why"], (closed["notes"] or ["The coding engine reported an error."])[-1])
        refused = [n for n in closed["notes"] if n.startswith("Refused, nobody to ask")]
        if refused and not note:
            were = "s were" if len(refused) != 1 else " was"
            note = f"{len(refused)} step{were} refused: nobody was there to ask."
        return RunResult(closed["result"], session["id"], note)

    async def _tidy(self, owner: Owner, schedule_id: str) -> None:
        """Keep the copies of a schedule's newest runs; let go of older ones nobody applied."""
        kept = [r for r in self.store.list_runs(owner, schedule_id) if r["copy_workspace"]]
        for run in kept[:-KEPT_COPIES]:
            await self._let_go(owner, run)

    async def _let_go(self, owner: Owner, run: dict[str, Any], *, applied: bool = False) -> None:
        """Remove a run's copy: its folder, its session and its rows. Never the project."""
        copy_id = run.get("copy_workspace")
        if not copy_id:
            return
        try:
            copy = self.store.get_workspace(owner, copy_id)
        except rows.NotFound:
            return
        if run.get("session_id"):
            try:
                await self.sessions.delete(owner, run["session_id"])
            except Exception:  # noqa: BLE001  (it is gone already)
                pass
        folder = Path(copy["path"])
        if copy.get("copy_of") and self._copies() in folder.parents:
            await asyncio.to_thread(shutil.rmtree, folder.parent, True)
        self.store.delete_workspace(owner, copy_id)
        self.store.close_run_copy(owner, run["id"], applied=applied)

    # ---- a run, for the screen -------------------------------------------------------------------

    def run_view(self, owner: Owner, run: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": run["id"],
            "schedule_id": run["schedule_id"],
            "due_at": run["due_at"],
            "state": run["state"],
            "result": run["result"],
            "note": run["note"],
            "stands_for": run["stands_for"],
            "session_id": run["session_id"] if run.get("copy_workspace") else None,
            "changed": int(run.get("changed") or 0),
            # the copy is still there: its changes can be looked at, applied or let go
            "open": bool(run.get("copy_workspace")),
            "applied_at": run.get("applied_at"),
            "discarded_at": run.get("discarded_at"),
            "started_at": run["started_at"],
            "finished_at": run["finished_at"],
        }

    def _open_run(self, owner: Owner, run_id: str) -> tuple[Row, Row, Row]:
        """A run whose copy is still there: the run, its copy's workspace and the project's."""
        try:
            run = self.store.get_run(owner, run_id)
        except rows.NotFound:
            raise ScheduleRefused("not_found", "There is no such run.") from None
        if run["state"] in (rows.RUN_WAITING, rows.RUN_RUNNING):
            raise ScheduleRefused("busy", "The run is still going. Wait for it, or stop it.")
        if not run.get("copy_workspace") or not run.get("base_commit"):
            raise ScheduleRefused("no_copy", "This run's changes are not there any more.")
        try:
            copy = self.store.get_workspace(owner, run["copy_workspace"])
            project = self.store.get_workspace(owner, copy["copy_of"])
        except rows.NotFound:
            raise ScheduleRefused("no_copy", "This run's changes are not there any more.") from None
        return run, copy, project

    async def changes(self, owner: Owner, run_id: str) -> dict[str, Any]:
        """What a run changed in its copy, and for each file whether it can be applied: the
        project's own file must still be what the copy was made from."""
        run, copy, project = self._open_run(owner, run_id)
        return await asyncio.to_thread(self._changes, run, copy, project)

    def _changes(self, run: Row, copy: Row, project: Row) -> Row:
        sessions = self.sessions
        theirs, ours = sessions._cps(copy), sessions._cps(project)
        if theirs is None or ours is None:
            raise ScheduleRefused("no_copy", "This run's changes are not there any more.")
        try:
            # what the run's turn began from in the copy: what the project's checkpoint held
            owner = Owner(run["tenant_id"], run["user_id"], run["product_id"])
            turns = sessions._turn_rows(owner, run["session_id"])
            first = next((t["before_commit"] for t in turns if t["before_commit"]), None)
            if first is None:
                return {"run": run["id"], "project": project["name"], "files": []}
            found = theirs.changes(first)
            files = []
            for change in found:
                was = ours.file_at(run["base_commit"], change.path)
                now = _read(Path(project["path"]) / change.path)
                files.append(
                    {
                        "path": change.path,
                        "what": change.what,
                        # the person changed this file in the project since the copy was made
                        "conflict": was != now,
                    }
                )
        except CheckpointError as e:
            raise ScheduleRefused("no_copy", f"The run's changes could not be read: {e}") from None
        return {"run": run["id"], "project": project["name"], "files": files}

    async def apply(self, owner: Owner, run_id: str) -> dict[str, Any]:
        """Write a run's changes into the project. A file the person changed since the copy was
        made is left as it is and named. The project is checkpointed first."""
        run, copy, project = self._open_run(owner, run_id)
        if self.sessions.running_in(owner, project["id"]):
            raise ScheduleRefused("busy", "The agent is working in this project. Wait or stop it.")
        found = await asyncio.to_thread(self._changes, run, copy, project)
        done = await asyncio.to_thread(self._apply, copy, project, found["files"])
        await self._let_go(owner, run, applied=True)
        return {**done, "run": self.run_view(owner, self.store.get_run(owner, run_id))}

    def _apply(self, copy: Row, project: Row, files: Sequence[Row]) -> Row:
        ours = self.sessions._cps(project)
        if ours is not None:
            try:
                ours.checkpoint("before applying a scheduled run")
            except CheckpointError as e:
                log.warning("no checkpoint before applying a scheduled run: %s", e)
        source, target = Path(copy["path"]), Path(project["path"])
        written, left = [], []
        for file in files:
            if file["conflict"]:
                left.append(file["path"])
                continue
            to = target / file["path"]
            if file["what"] == "deleted":
                to.unlink(missing_ok=True)
            else:
                to.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / file["path"], to)
            written.append(file["path"])
        return {"applied": written, "left": left}

    async def discard(self, owner: Owner, run_id: str) -> dict[str, Any]:
        """Let a run's changes go: its copy is removed, the project is as it was."""
        run, _copy, _project = self._open_run(owner, run_id)
        await self._let_go(owner, run)
        return self.run_view(owner, self.store.get_run(owner, run_id))

    async def stop(self, owner: Owner, run_id: str) -> bool:
        """Stop a run that is going: its turn is stopped, and it ends "not checked"."""
        try:
            run = self.store.get_run(owner, run_id)
        except rows.NotFound:
            raise ScheduleRefused("not_found", "There is no such run.") from None
        if run["state"] != rows.RUN_RUNNING or not run.get("copy_workspace"):
            return False
        for session in self.store.list_sessions(owner):
            if session["workspace_id"] == run["copy_workspace"]:
                return bool(await self.sessions.stop(owner, session["id"]))
        return False


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes() if path.is_file() and not path.is_symlink() else None
    except OSError:
        return None


def time_zone_of_this_computer() -> str:
    """The computer's own time zone, by name; UTC when it cannot be told."""
    try:
        link = Path("/etc/localtime").resolve()
        parts = link.parts
        if "zoneinfo" in parts:
            name = "/".join(parts[parts.index("zoneinfo") + 1 :])
            rules.zone(name)
            return name
    except (OSError, BadRule):
        pass
    return "UTC"
