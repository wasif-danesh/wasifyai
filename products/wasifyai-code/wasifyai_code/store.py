# ruff: noqa: E501  (the SQL is easier to read on one line)
"""The coding product's rows (ADR-0101 to ADR-0105): on the desktop one small SQLite file in the
app's own data folder; on the web the same tables in their own Postgres schema (`code`). One store
class on either database (stage J2: `wasifyai_platform_sdk.sqlstore`).

Every row carries `tenant_id` and `product_id` (rule 7) and the person it belongs to, and every
query a person can cause is scoped by all three (an `Owner`). The few calls the scheduler's timer
makes for every person at once say so in their names.

- A **workspace** is a folder the person chose, with its check command (ADR-0103, decision 5: the
  command lives here, never in the workspace) and the checkpoint of the last state that passed.
- A **session** is one conversation with the agent on a workspace. Its `result` is the one word in
  its header. Its `mode` says how much the agent may do (`plan`: it only reads). Its counted cost
  and tokens are added by the model gateway, call by call (ADR-0102, decision 4).
- A **turn** is one request and everything done about it, with its state (`loop.py`), the
  agent's last message (`answer`) and how many tool steps it took.
- A **check** is one run of the check command (ADR-0103, decision 8).
- A **checkpoint** names a commit in the workspace's checkpoint store (`checkpoints.py`).
- A **schedule** is a request, a plain rule and a time zone; a **schedule run** is one time it came
  due and what happened (ADR-0105, decision 2). The store allows one run per schedule and due
  time, which is how a due time is claimed (decision 7).

Times are UTC ISO text that sorts as text.
"""

import json
import threading
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk.sqlstore import PostgresStoreDb, SqliteStoreDb, StoreDb

from wasifyai_code import PRODUCT_ID

SCHEMA = 1

# the four result words (ADR-0103, decision 3); "" means nothing has been checked yet
PASSED, FAILED, NOT_CHECKED, COULD_NOT_CHECK = "passed", "failed", "not_checked", "could_not_check"
RESULTS = (PASSED, FAILED, NOT_CHECKED, COULD_NOT_CHECK)

# where a turn is; `done` means it is over and `result` says how
WORKING, TURN_ENDED, CHECKING, DONE = "working", "turn_ended", "checking", "done"
TURN_STATES = (WORKING, TURN_ENDED, CHECKING, DONE)

# what happened to a time a schedule came due
RUN_WAITING, RUN_RUNNING, RUN_DONE = "waiting", "running", "done"
RUN_MISSED, RUN_SKIPPED, RUN_FAILED = "missed", "skipped", "failed"
RUN_STATES = (RUN_WAITING, RUN_RUNNING, RUN_DONE, RUN_MISSED, RUN_SKIPPED, RUN_FAILED)

# how much the agent may do in a session (the plan's three modes; only the first is built)
PLAN = "plan"  # it only reads: no tool that writes a file or runs a command
MODES = (PLAN,)

LEFT_WORKING = "It was stopped when the app closed."
STILL_RUNNING = "still running"


class NotFound(Exception):
    """No such row for this person."""


@dataclass(frozen=True)
class Owner:
    """Whose rows: the tenant, the product and the person."""

    tenant_id: str
    user_id: str
    product_id: str = PRODUCT_ID


@dataclass(frozen=True)
class Missed:
    """A due time that will not run: its time, how many due times the row stands for, and why."""

    due_at: str
    stands_for: int = 1
    note: str = ""


def new_id() -> str:
    return uuid.uuid4().hex


def utc_text(when: datetime) -> str:
    """A moment as the text the store keeps: UTC, to the second, always the same shape, so that two
    writers of one due time write the same key."""
    if when.tzinfo is None:
        raise ValueError("a time without a zone")
    return when.astimezone(UTC).replace(microsecond=0).isoformat()


def from_text(text: str) -> datetime:
    return datetime.fromisoformat(text)


_clock = threading.Lock()
_last = datetime.min.replace(tzinfo=UTC)


def now() -> str:
    """The present moment as text, to the microsecond, and never the same twice in one process:
    rows are listed in the order they were written, and two written in one instant must not
    change places."""
    global _last
    with _clock:
        _last = max(datetime.now(UTC), _last + timedelta(microseconds=1))
        return _last.isoformat(timespec="microseconds")


_OWNED = (
    "id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, product_id TEXT NOT NULL, user_id TEXT NOT NULL"
)
_WORDS = "('', 'passed', 'failed', 'not_checked', 'could_not_check')"

DDL = f"""
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workspaces(
  {_OWNED},
  name TEXT NOT NULL DEFAULT '', path TEXT NOT NULL,
  check_command TEXT NOT NULL DEFAULT '',
  check_from TEXT NOT NULL DEFAULT '' CHECK (check_from IN ('', 'suggested', 'person')),
  check_limit_s INTEGER NOT NULL DEFAULT 600,
  last_pass TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(
  {_OWNED},
  workspace_id TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
  origin TEXT NOT NULL DEFAULT 'chat' CHECK (origin IN ('chat', 'schedule')),
  place TEXT NOT NULL DEFAULT 'this-computer', place_session TEXT, last_event TEXT,
  model TEXT NOT NULL DEFAULT '',
  mode TEXT NOT NULL DEFAULT 'plan',
  result TEXT NOT NULL DEFAULT '' CHECK (result IN {_WORDS}),
  cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0, cost_limit_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
  tokens_in BIGINT NOT NULL DEFAULT 0, tokens_out BIGINT NOT NULL DEFAULT 0, model_calls INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS turns(
  {_OWNED},
  session_id TEXT NOT NULL, workspace_id TEXT NOT NULL, position INTEGER NOT NULL, request TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('working', 'turn_ended', 'checking', 'done')),
  result TEXT NOT NULL DEFAULT '' CHECK (result IN {_WORDS}),
  why TEXT NOT NULL DEFAULT '', rounds INTEGER NOT NULL DEFAULT 0, needs_you INTEGER NOT NULL DEFAULT 0,
  checkpoint_id TEXT, notes TEXT NOT NULL DEFAULT '[]',
  answer TEXT NOT NULL DEFAULT '', steps INTEGER NOT NULL DEFAULT 0,
  started_at TEXT NOT NULL, finished_at TEXT);
CREATE TABLE IF NOT EXISTS checks(
  {_OWNED},
  workspace_id TEXT NOT NULL, session_id TEXT NOT NULL, turn_id TEXT, round INTEGER NOT NULL,
  command TEXT NOT NULL,
  result TEXT NOT NULL CHECK (result IN ('passed', 'failed', 'not_checked', 'could_not_check')),
  why TEXT NOT NULL DEFAULT '', exit_code INTEGER, seconds DOUBLE PRECISION NOT NULL DEFAULT 0,
  output_file TEXT NOT NULL DEFAULT '', changed_tests TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS checkpoints(
  {_OWNED},
  workspace_id TEXT NOT NULL, session_id TEXT, turn_id TEXT,
  kind TEXT NOT NULL CHECK (kind IN ('turn', 'undo', 'pass')),
  commit_id TEXT NOT NULL, tree_id TEXT NOT NULL, label TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS schedules(
  {_OWNED},
  workspace_id TEXT NOT NULL, request TEXT NOT NULL, rule TEXT NOT NULL, time_zone TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1, run_when_missed INTEGER NOT NULL DEFAULT 1,
  next_due TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS schedule_runs(
  {_OWNED},
  schedule_id TEXT NOT NULL, due_at TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('waiting', 'running', 'done', 'missed', 'skipped', 'failed')),
  result TEXT NOT NULL DEFAULT '' CHECK (result IN {_WORDS}),
  note TEXT NOT NULL DEFAULT '', stands_for INTEGER NOT NULL DEFAULT 1, session_id TEXT,
  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
  UNIQUE (schedule_id, due_at));
CREATE INDEX IF NOT EXISTS workspaces_owner ON workspaces(tenant_id, product_id, user_id, created_at);
CREATE INDEX IF NOT EXISTS sessions_owner ON sessions(tenant_id, product_id, user_id, updated_at);
CREATE INDEX IF NOT EXISTS turns_session ON turns(session_id, position);
CREATE INDEX IF NOT EXISTS checks_session ON checks(session_id, created_at);
CREATE INDEX IF NOT EXISTS checkpoints_workspace ON checkpoints(workspace_id, created_at);
CREATE INDEX IF NOT EXISTS schedules_owner ON schedules(tenant_id, product_id, user_id, created_at);
CREATE INDEX IF NOT EXISTS schedule_runs_state ON schedule_runs(schedule_id, state);
"""

_MINE = "tenant_id = ? AND product_id = ? AND user_id = ?"


def _who(owner: Owner) -> tuple[str, str, str]:
    return (owner.tenant_id, owner.product_id, owner.user_id)


class CodeStore:
    def __init__(self, db: StoreDb):
        self.db = db
        db.open_tables(DDL)
        db.exec("INSERT INTO meta VALUES ('schema', ?) ON CONFLICT DO NOTHING", (str(SCHEMA),))

    @classmethod
    def in_folder(cls, folder: Path) -> "CodeStore":
        """The desktop's store: `code.db` in the app's data folder. What a closed app left in the
        middle is closed, in words."""
        store = cls(SqliteStoreDb(folder / "code.db"))
        store.close_left_working()
        return store

    @classmethod
    def on_file(cls, path: Path) -> "CodeStore":
        """A second opening of a desktop store that is already in use (another window): the same
        file, a connection of its own, and nothing is closed."""
        return cls(SqliteStoreDb(path))

    @classmethod
    def on_postgres(cls, dsn: str, schema: str = "code") -> "CodeStore":
        """The web's store, in its own schema of the deployment's Postgres."""
        return cls(PostgresStoreDb(dsn, schema))

    def close_left_working(self) -> None:
        """Turns and scheduled runs that a process which is gone left unfinished. A turn becomes
        "not checked" (nothing checked it); a run becomes failed."""
        at = now()
        self.db.exec(
            "UPDATE turns SET state = 'done', result = 'not_checked', why = 'app_closed', finished_at = ? WHERE state <> 'done'",
            (at,),
        )
        self.db.exec(
            "UPDATE schedule_runs SET state = 'failed', note = ?, finished_at = ? WHERE state IN ('waiting', 'running')",
            (LEFT_WORKING, at),
        )

    def close(self) -> None:
        self.db.close()

    def drop_schema(self) -> None:
        """Remove every table of this store (tests on Postgres)."""
        drop = getattr(self.db, "drop", None)
        if drop is not None:
            drop()

    # ---- rows ----------------------------------------------------------------------------------

    def _get(self, table: str, owner: Owner, item: str) -> dict[str, Any]:
        row = self.db.one(f"SELECT * FROM {table} WHERE id = ? AND {_MINE}", (item, *_who(owner)))
        if row is None:
            raise NotFound(f"{table}: {item}")
        return _row(row)

    def _list(
        self, table: str, owner: Owner, where: str = "", args: Sequence[Any] = (), order: str = "created_at, id"
    ) -> list[dict[str, Any]]:  # fmt: skip
        sql = f"SELECT * FROM {table} WHERE {_MINE}{' AND ' + where if where else ''} ORDER BY {order}"
        return [_row(r) for r in self.db.all(sql, (*_who(owner), *args))]

    # ---- workspaces ----------------------------------------------------------------------------

    def add_workspace(
        self, owner: Owner, path: str, *, name: str = "", check_command: str = "",
        check_from: str = "", check_limit_s: int = 600,
    ) -> dict[str, Any]:  # fmt: skip
        item = new_id()
        self.db.exec(
            "INSERT INTO workspaces(id, tenant_id, product_id, user_id, name, path, check_command, check_from, check_limit_s, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item, *_who(owner), name[:200], path, check_command, check_from if check_command else "", check_limit_s, now()),
        )  # fmt: skip
        return self.get_workspace(owner, item)

    def get_workspace(self, owner: Owner, item: str) -> dict[str, Any]:
        return self._get("workspaces", owner, item)

    def list_workspaces(self, owner: Owner) -> list[dict[str, Any]]:
        return self._list("workspaces", owner)

    def find_workspace(self, owner: Owner, path: str) -> dict[str, Any] | None:
        """This person's workspace for a folder, when they have opened it before."""
        found = self._list("workspaces", owner, "path = ?", (path,))
        return found[0] if found else None

    def workspace_paths(self) -> list[str]:
        """Every folder any person has opened as a workspace: what the one coding engine of
        this computer is allowed to reach (its sandbox names them all)."""
        return [
            r["path"] for r in self.db.all("SELECT DISTINCT path FROM workspaces ORDER BY path")
        ]

    def set_check(
        self, owner: Owner, item: str, command: str, *, source: str = "person", limit_s: int | None = None
    ) -> dict[str, Any]:  # fmt: skip
        """The workspace's check command: what was suggested from the project's files, or what the
        person typed. An empty command means nothing is checked, and the turn will say so."""
        n = self.db.exec(
            f"UPDATE workspaces SET check_command = ?, check_from = ?, check_limit_s = COALESCE(?, check_limit_s) WHERE id = ? AND {_MINE}",
            (command, source if command else "", limit_s, item, *_who(owner)),
        )
        if n == 0:
            raise NotFound(f"workspaces: {item}")
        return self.get_workspace(owner, item)

    def set_last_pass(self, owner: Owner, item: str, checkpoint_id: str | None) -> None:
        self.db.exec(
            f"UPDATE workspaces SET last_pass = ? WHERE id = ? AND {_MINE}",
            (checkpoint_id, item, *_who(owner)),
        )

    def delete_workspace(self, owner: Owner, item: str) -> bool:
        """Forget a workspace and every row that hangs on it. The folder itself is the person's and
        is not touched; the checkpoint store on disk is the caller's to remove."""
        who = _who(owner)
        with self.db.transaction() as db:
            n = db.execute(
                f"DELETE FROM workspaces WHERE id = ? AND {_MINE}", (item, *who)
            ).rowcount
            if n == 0:
                return False
            db.execute(
                f"DELETE FROM schedule_runs WHERE {_MINE} AND schedule_id IN (SELECT id FROM schedules WHERE workspace_id = ?)",
                (*who, item),
            )
            for table in ("schedules", "checkpoints", "checks", "turns", "sessions"):
                db.execute(f"DELETE FROM {table} WHERE workspace_id = ? AND {_MINE}", (item, *who))
        return True

    # ---- sessions ------------------------------------------------------------------------------

    def add_session(
        self, owner: Owner, workspace_id: str, *, title: str = "", origin: str = "chat", model: str = "",
        mode: str = PLAN, cost_limit_usd: float = 0.0,
    ) -> dict[str, Any]:  # fmt: skip
        self.get_workspace(owner, workspace_id)  # it must be this person's
        if mode not in MODES:
            raise ValueError(f"no such mode: {mode}")
        item, at = new_id(), now()
        self.db.exec(
            "INSERT INTO sessions(id, tenant_id, product_id, user_id, workspace_id, title, origin, model, mode, cost_limit_usd, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item,
                *_who(owner),
                workspace_id,
                title[:200],
                origin,
                model,
                mode,
                cost_limit_usd,
                at,
                at,
            ),
        )
        return self.get_session(owner, item)

    def set_session_title(self, owner: Owner, item: str, title: str) -> None:
        self.db.exec(
            f"UPDATE sessions SET title = ?, updated_at = ? WHERE id = ? AND {_MINE}",
            (title[:200], now(), item, *_who(owner)),
        )

    def add_session_cost(
        self, item: str, *, usd: float, tokens_in: int, tokens_out: int, calls: int = 1
    ) -> None:
        """One model call of a session, counted by the gateway (which knows the session by its
        token, and so names no person here)."""
        self.db.exec(
            "UPDATE sessions SET cost_usd = cost_usd + ?, tokens_in = tokens_in + ?, tokens_out = tokens_out + ?, "
            "model_calls = model_calls + ? WHERE id = ?",
            (usd, tokens_in, tokens_out, calls, item),
        )

    def delete_session(self, owner: Owner, item: str) -> bool:
        """Forget a session and its turns and checks. The workspace and its checkpoints stay."""
        who = _who(owner)
        with self.db.transaction() as db:
            n = db.execute(f"DELETE FROM sessions WHERE id = ? AND {_MINE}", (item, *who)).rowcount
            if n == 0:
                return False
            for table in ("checks", "turns"):
                db.execute(f"DELETE FROM {table} WHERE session_id = ? AND {_MINE}", (item, *who))
        return True

    def sessions_page(self, after: str | None, limit: int) -> list[dict[str, Any]]:
        """Sessions of every person in the order of their ids, with their workspace's name and
        the first thing that was asked: what search indexes (ADR-0041)."""
        rows = self.db.all(
            "SELECT s.id, s.tenant_id, s.product_id, s.user_id, s.title, w.name AS workspace_name, w.path AS workspace_path, "
            "(SELECT t.request FROM turns t WHERE t.session_id = s.id ORDER BY t.position LIMIT 1) AS first_request "
            "FROM sessions s LEFT JOIN workspaces w ON w.id = s.workspace_id "
            f"{'WHERE s.id > ? ' if after is not None else ''}ORDER BY s.id LIMIT ?",
            (limit,) if after is None else (after, limit),
        )
        return [dict(r) for r in rows]

    def sessions_present(self, ids: Sequence[str]) -> set[str]:
        if not ids:
            return set()
        rows = self.db.all(
            f"SELECT id FROM sessions WHERE id IN ({','.join('?' * len(ids))})", tuple(ids)
        )
        return {_first(r) for r in rows}

    def get_session(self, owner: Owner, item: str) -> dict[str, Any]:
        return self._get("sessions", owner, item)

    def list_sessions(
        self, owner: Owner, workspace_id: str | None = None, ids: list[str] | None = None
    ) -> list[dict[str, Any]]:
        where, args = [], []
        if workspace_id is not None:
            where.append("workspace_id = ?")
            args.append(workspace_id)
        if ids:
            where.append(f"id IN ({','.join('?' * len(ids))})")
            args += ids
        return self._list("sessions", owner, " AND ".join(where), args, "updated_at DESC, id DESC")

    def set_place_session(self, owner: Owner, item: str, place_session: str | None) -> None:
        self.db.exec(
            f"UPDATE sessions SET place_session = ?, updated_at = ? WHERE id = ? AND {_MINE}",
            (place_session, now(), item, *_who(owner)),
        )

    def set_cursor(self, owner: Owner, item: str, last_event: str | None) -> None:
        """The last event of the place that was read for this session: the next turn follows from
        there, so an old turn's end is never taken for the new one's."""
        self.db.exec(
            f"UPDATE sessions SET last_event = ? WHERE id = ? AND {_MINE}",
            (last_event, item, *_who(owner)),
        )

    def set_session_result(self, owner: Owner, item: str, result: str) -> None:
        """The one word in the session's header."""
        self.db.exec(
            f"UPDATE sessions SET result = ?, updated_at = ? WHERE id = ? AND {_MINE}",
            (result, now(), item, *_who(owner)),
        )

    # ---- turns ---------------------------------------------------------------------------------

    def add_turn(self, owner: Owner, session_id: str, request: str) -> dict[str, Any]:
        session = self.get_session(owner, session_id)
        item, at = new_id(), now()
        with self.db.transaction() as db:
            last = db.execute(
                "SELECT COALESCE(MAX(position), 0) AS n FROM turns WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            db.execute(
                "INSERT INTO turns(id, tenant_id, product_id, user_id, session_id, workspace_id, position, request, state, started_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'working', ?)",
                (item, *_who(owner), session_id, session["workspace_id"], _first(last) + 1, request, at),
            )  # fmt: skip
        return self.get_turn(owner, item)

    def get_turn(self, owner: Owner, item: str) -> dict[str, Any]:
        return self._get("turns", owner, item)

    def list_turns(self, owner: Owner, session_id: str) -> list[dict[str, Any]]:
        return self._list("turns", owner, "session_id = ?", (session_id,), "position")

    def set_turn(
        self, owner: Owner, item: str, *, state: str | None = None, rounds: int | None = None,
        checkpoint_id: str | None = None,
    ) -> None:  # fmt: skip
        """Move a turn that is not over to another state."""
        self.db.exec(
            "UPDATE turns SET state = COALESCE(?, state), rounds = COALESCE(?, rounds), checkpoint_id = COALESCE(?, checkpoint_id) "
            f"WHERE id = ? AND {_MINE} AND state <> 'done'",
            (state, rounds, checkpoint_id, item, *_who(owner)),
        )

    def set_turn_answer(self, owner: Owner, item: str, *, answer: str, steps: int) -> None:
        """What the agent said last in the turn, and how many tool steps it has taken."""
        self.db.exec(
            f"UPDATE turns SET answer = ?, steps = ? WHERE id = ? AND {_MINE}",
            (answer, steps, item, *_who(owner)),
        )

    def note_turn(self, owner: Owner, item: str, note: str) -> None:
        """Write down something that happened in the turn (a question that was refused because
        nobody was there to answer)."""
        with self.db.transaction() as db:
            row = db.execute(f"SELECT notes FROM turns WHERE id = ? AND {_MINE}", (item, *_who(owner))).fetchone()  # fmt: skip
            if row is None:
                raise NotFound(f"turns: {item}")
            notes = [*json.loads(_first(row)), note]
            db.execute("UPDATE turns SET notes = ? WHERE id = ?", (json.dumps(notes), item))

    def finish_turn(
        self, owner: Owner, item: str, *, result: str, why: str = "", rounds: int = 0, needs_you: bool = False
    ) -> dict[str, Any]:  # fmt: skip
        """Close a turn. Only a turn that is not over: a late call does not change what was said."""
        self.db.exec(
            "UPDATE turns SET state = 'done', result = ?, why = ?, rounds = ?, needs_you = ?, finished_at = ? "
            f"WHERE id = ? AND {_MINE} AND state <> 'done'",
            (result, why, rounds, int(needs_you), now(), item, *_who(owner)),
        )
        return self.get_turn(owner, item)

    # ---- checks --------------------------------------------------------------------------------

    def add_check(
        self, owner: Owner, *, workspace_id: str, session_id: str, turn_id: str | None, round: int,
        command: str, result: str, why: str = "", exit_code: int | None = None, seconds: float = 0.0,
        output_file: str = "", changed_tests: Sequence[str] = (),
    ) -> dict[str, Any]:  # fmt: skip
        item = new_id()
        self.db.exec(
            "INSERT INTO checks(id, tenant_id, product_id, user_id, workspace_id, session_id, turn_id, round, command, result, why, "
            "exit_code, seconds, output_file, changed_tests, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item, *_who(owner), workspace_id, session_id, turn_id, round, command, result, why,
             exit_code, seconds, output_file, json.dumps(list(changed_tests)), now()),
        )  # fmt: skip
        return self._get("checks", owner, item)

    def list_checks(
        self, owner: Owner, *, session_id: str | None = None, turn_id: str | None = None
    ) -> list[dict[str, Any]]:
        if turn_id is not None:
            return self._list("checks", owner, "turn_id = ?", (turn_id,), "round, created_at, id")
        return self._list("checks", owner, "session_id = ?", (session_id,))

    # ---- checkpoints ---------------------------------------------------------------------------

    def add_checkpoint(
        self, owner: Owner, *, workspace_id: str, kind: str, commit_id: str, tree_id: str,
        label: str = "", session_id: str | None = None, turn_id: str | None = None,
    ) -> dict[str, Any]:  # fmt: skip
        item = new_id()
        self.db.exec(
            "INSERT INTO checkpoints(id, tenant_id, product_id, user_id, workspace_id, session_id, turn_id, kind, commit_id, tree_id, label, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item, *_who(owner), workspace_id, session_id, turn_id, kind, commit_id, tree_id, label[:200], now()),
        )  # fmt: skip
        return self.get_checkpoint(owner, item)

    def get_checkpoint(self, owner: Owner, item: str) -> dict[str, Any]:
        return self._get("checkpoints", owner, item)

    def list_checkpoints(self, owner: Owner, workspace_id: str) -> list[dict[str, Any]]:
        return self._list("checkpoints", owner, "workspace_id = ?", (workspace_id,))

    # ---- schedules -----------------------------------------------------------------------------

    def add_schedule(
        self, owner: Owner, *, workspace_id: str, request: str, rule: dict[str, Any], time_zone: str,
        next_due: str | None, enabled: bool = True, run_when_missed: bool = True,
    ) -> dict[str, Any]:  # fmt: skip
        self.get_workspace(owner, workspace_id)
        item, at = new_id(), now()
        self.db.exec(
            "INSERT INTO schedules(id, tenant_id, product_id, user_id, workspace_id, request, rule, time_zone, enabled, run_when_missed, "
            "next_due, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item, *_who(owner), workspace_id, request, json.dumps(rule), time_zone, int(enabled),
             int(run_when_missed), next_due, at, at),
        )  # fmt: skip
        return self.get_schedule(owner, item)

    def get_schedule(self, owner: Owner, item: str) -> dict[str, Any]:
        return self._get("schedules", owner, item)

    def list_schedules(self, owner: Owner) -> list[dict[str, Any]]:
        return self._list("schedules", owner)

    def update_schedule(
        self, owner: Owner, item: str, *, next_due: str | None, request: str | None = None,
        rule: dict[str, Any] | None = None, time_zone: str | None = None, enabled: bool | None = None,
        run_when_missed: bool | None = None,
    ) -> dict[str, Any]:  # fmt: skip
        """Change a schedule. `next_due` is always given: whoever changes the rule, the zone or the
        switch works out the next time again (`schedules.next_due`)."""
        n = self.db.exec(
            "UPDATE schedules SET request = COALESCE(?, request), rule = COALESCE(?, rule), time_zone = COALESCE(?, time_zone), "
            "enabled = COALESCE(?, enabled), run_when_missed = COALESCE(?, run_when_missed), next_due = ?, updated_at = ? "
            f"WHERE id = ? AND {_MINE}",
            (request, json.dumps(rule) if rule is not None else None, time_zone,
             None if enabled is None else int(enabled),
             None if run_when_missed is None else int(run_when_missed), next_due, now(), item, *_who(owner)),
        )  # fmt: skip
        if n == 0:
            raise NotFound(f"schedules: {item}")
        return self.get_schedule(owner, item)

    def delete_schedule(self, owner: Owner, item: str) -> bool:
        with self.db.transaction() as db:
            n = db.execute(f"DELETE FROM schedules WHERE id = ? AND {_MINE}", (item, *_who(owner))).rowcount  # fmt: skip
            db.execute(f"DELETE FROM schedule_runs WHERE schedule_id = ? AND {_MINE}", (item, *_who(owner)))  # fmt: skip
        return n > 0

    def schedules_on(self) -> list[dict[str, Any]]:
        """Every schedule that is on and has a next time, for every person: what the one timer
        holds (ADR-0105, decision 5)."""
        rows = self.db.all("SELECT * FROM schedules WHERE enabled = 1 AND next_due IS NOT NULL ORDER BY next_due, id")  # fmt: skip
        return [_row(r) for r in rows]

    def schedule_for_timer(self, item: str) -> dict[str, Any] | None:
        """One schedule as it is now, for the timer (any person's)."""
        row = self.db.one("SELECT * FROM schedules WHERE id = ?", (item,))
        return _row(row) if row is not None else None

    # ---- the times a schedule came due -----------------------------------------------------------

    def come_due(
        self, schedule: dict[str, Any], *, next_due: str | None, latest: str, run_latest: bool,
        latest_note: str = "", missed: Sequence[Missed] = (),
    ) -> list[dict[str, Any]] | None:  # fmt: skip
        """A schedule's time has come. In one transaction: move the schedule on to `next_due`,
        write a row for every time that passed (`missed`, then `latest`), and claim the latest one
        to run if `run_latest` and no run of this schedule is still going (otherwise it is written
        as missed, or as skipped: still running).

        Only one caller gets to do this for a given schedule and due time: the schedule is moved on
        only if its next time is still the one the caller saw, and a due time's row can be written
        once (ADR-0105, decision 7). The loser gets `None` and nothing is written. The winner gets
        the rows it wrote; the one to run is in state `waiting`."""
        owner = Owner(schedule["tenant_id"], schedule["user_id"], schedule["product_id"])
        at, written = now(), []
        with self.db.transaction() as db:
            moved = db.execute(
                "UPDATE schedules SET next_due = ?, updated_at = ? WHERE id = ? AND next_due = ? AND enabled = 1",
                (next_due, at, schedule["id"], schedule["next_due"]),
            ).rowcount
            if moved == 0:
                return None
            for m in missed:
                row = self._write_run(
                    db, owner, schedule["id"], m.due_at, RUN_MISSED, m.note, m.stands_for, at
                )
                written += [row] if row else []
            going = self._going(db, schedule["id"])
            if not run_latest:
                state, note = RUN_MISSED, latest_note
            elif going:
                state, note = RUN_SKIPPED, STILL_RUNNING
            else:
                state, note = RUN_WAITING, latest_note
            row = self._write_run(db, owner, schedule["id"], latest, state, note, 1, at)
            written += [row] if row else []
        return [self.get_run(owner, r) for r in written]

    def claim_run(
        self, schedule: dict[str, Any], due_at: str, note: str = ""
    ) -> dict[str, Any] | None:
        """Claim one due time to run now ("Run now", ADR-0105 decision 10). `None` when that due
        time already has a row. If a run of the schedule is still going, the row is written as
        skipped and given back, so the caller can say so."""
        owner = Owner(schedule["tenant_id"], schedule["user_id"], schedule["product_id"])
        with self.db.transaction() as db:
            going = self._going(db, schedule["id"])
            state, note = (RUN_SKIPPED, STILL_RUNNING) if going else (RUN_WAITING, note)
            row = self._write_run(db, owner, schedule["id"], due_at, state, note, 1, now())
        return self.get_run(owner, row) if row else None

    @staticmethod
    def _going(db: Any, schedule_id: str) -> bool:
        row = db.execute(
            "SELECT COUNT(*) AS n FROM schedule_runs WHERE schedule_id = ? AND state IN ('waiting', 'running')",
            (schedule_id,),
        ).fetchone()
        return _first(row) > 0

    @staticmethod
    def _write_run(
        db: Any, owner: Owner, schedule_id: str, due_at: str, state: str, note: str, stands_for: int, at: str
    ) -> str | None:  # fmt: skip
        item = new_id()
        finished = None if state == RUN_WAITING else at
        n = db.execute(
            "INSERT INTO schedule_runs(id, tenant_id, product_id, user_id, schedule_id, due_at, state, note, stands_for, created_at, finished_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (schedule_id, due_at) DO NOTHING",
            (item, *_who(owner), schedule_id, due_at, state, note, stands_for, at, finished),
        ).rowcount
        return item if n == 1 else None

    def get_run(self, owner: Owner, item: str) -> dict[str, Any]:
        return self._get("schedule_runs", owner, item)

    def list_runs(self, owner: Owner, schedule_id: str) -> list[dict[str, Any]]:
        return self._list("schedule_runs", owner, "schedule_id = ?", (schedule_id,), "due_at, id")

    def start_run(self, run: dict[str, Any]) -> bool:
        """A waiting run begins. False when it is not waiting any more (it was closed meanwhile)."""
        n = self.db.exec(
            "UPDATE schedule_runs SET state = 'running', started_at = ? WHERE id = ? AND state = 'waiting'",
            (now(), run["id"]),
        )
        return n == 1

    def finish_run(
        self, run: dict[str, Any], *, state: str = RUN_DONE, result: str = "", note: str = "",
        session_id: str | None = None,
    ) -> None:  # fmt: skip
        """What happened: `done` with one of the four result words, or `failed` with the reason."""
        self.db.exec(
            "UPDATE schedule_runs SET state = ?, result = ?, note = ?, session_id = COALESCE(?, session_id), finished_at = ? "
            "WHERE id = ? AND state IN ('waiting', 'running')",
            (state, result, note, session_id, now(), run["id"]),
        )


def _first(row: Any) -> Any:
    """The one value of a one-column row, whichever database made it (a mapping on both)."""
    return next(iter(dict(row).values()))


def _row(row: Any) -> dict[str, Any]:
    out = dict(row)
    for key in ("rule", "notes", "changed_tests"):
        if key in out:
            out[key] = json.loads(out[key])
    for key in ("enabled", "run_when_missed", "needs_you"):
        if key in out:
            out[key] = bool(out[key])
    return out
