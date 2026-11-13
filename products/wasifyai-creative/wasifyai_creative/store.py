# ruff: noqa: E501  (prose and test data are easier to read on one line)
"""Creative Studio's projects (ADR-0090): one small SQLite file in the app's data folder (desktop first; one store
class on either database, stage J2, for when the web comes). A project holds its brief, what was found in its song and
its plan. Every plan is kept as a numbered revision, the writer's finished steps as checkpoints, and what it was
asked and answered as the planning log. Every query is scoped by tenant and user.

A plan left `planning` by a process that is gone becomes `interrupted` when the store opens: its checkpoints are kept,
so the person can go on from where it stopped."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk.sqlstore import PostgresStoreDb, SqliteStoreDb, StoreDb, ddl_for

SCHEMA = 3
KEEP_REVISIONS = 30
KEEP_LOG = 400

DDL = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS projects(
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, title TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('draft', 'planning', 'planned', 'failed', 'stopped', 'interrupted')),
  brief TEXT NOT NULL, facts TEXT NOT NULL DEFAULT '{}', plan TEXT, revision INTEGER NOT NULL DEFAULT 0,
  stage TEXT NOT NULL DEFAULT '', progress DOUBLE PRECISION NOT NULL DEFAULT 0, error TEXT,
  elapsed_s DOUBLE PRECISION, conversation_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS projects_owner ON projects(tenant_id, user_id, updated_at);
CREATE TABLE IF NOT EXISTS revisions(
  project_id TEXT NOT NULL, revision INTEGER NOT NULL, plan TEXT NOT NULL, note TEXT NOT NULL,
  created_at TEXT NOT NULL, PRIMARY KEY (project_id, revision));
CREATE TABLE IF NOT EXISTS checkpoints(
  project_id TEXT NOT NULL, step TEXT NOT NULL, data TEXT NOT NULL,
  PRIMARY KEY (project_id, step));
CREATE TABLE IF NOT EXISTS plan_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, step TEXT NOT NULL,
  asked TEXT NOT NULL, said TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS plan_log_project ON plan_log(project_id, id);
CREATE TABLE IF NOT EXISTS media(
  project_id TEXT NOT NULL, kind TEXT NOT NULL, item_id TEXT NOT NULL, shot_id TEXT,
  made INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
  PRIMARY KEY (project_id, kind, item_id));
CREATE TABLE IF NOT EXISTS takes(
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, shot_id TEXT NOT NULL, kind TEXT NOT NULL,
  item_id TEXT NOT NULL, inputs TEXT NOT NULL, prompt TEXT NOT NULL, mode TEXT NOT NULL,
  seconds DOUBLE PRECISION, revision INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS takes_shot ON takes(project_id, shot_id, created_at);
CREATE TABLE IF NOT EXISTS chosen(
  project_id TEXT NOT NULL, shot_id TEXT NOT NULL, take_id TEXT NOT NULL,
  PRIMARY KEY (project_id, shot_id));
CREATE TABLE IF NOT EXISTS runs(
  project_id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL,
  finished INTEGER NOT NULL, total INTEGER NOT NULL, failed INTEGER NOT NULL DEFAULT 0,
  error TEXT, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS previews(
  project_id TEXT PRIMARY KEY, rel TEXT NOT NULL, mark TEXT NOT NULL, seconds DOUBLE PRECISION NOT NULL,
  empty_shots INTEGER NOT NULL, took_s DOUBLE PRECISION NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS characters(
  tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, name TEXT NOT NULL, look TEXT NOT NULL,
  pictures TEXT NOT NULL, photos_only INTEGER NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, user_id, name));
CREATE TABLE IF NOT EXISTS cuts(
  project_id TEXT PRIMARY KEY, at INTEGER NOT NULL, top INTEGER NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cut_revisions(
  project_id TEXT NOT NULL, n INTEGER NOT NULL, cut TEXT NOT NULL, note TEXT NOT NULL,
  created_at TEXT NOT NULL, PRIMARY KEY (project_id, n));
CREATE TABLE IF NOT EXISTS renders(
  project_id TEXT PRIMARY KEY, rel TEXT NOT NULL, mark TEXT NOT NULL, shape TEXT NOT NULL,
  seconds DOUBLE PRECISION NOT NULL, bytes INTEGER NOT NULL, took_s DOUBLE PRECISION NOT NULL,
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS exports(
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, video_id TEXT NOT NULL, mark TEXT NOT NULL,
  title TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS exports_project ON exports(project_id, created_at);
"""
LEFT_RUNNING = "It stopped when the app closed. Go on, and it picks up where it stopped."
LEFT_RUNNING_WEB = "It stopped when the service restarted. Go on, and it picks up where it stopped."


class NotFound(Exception):
    """No such project for this person."""


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class CreativeStore:
    def __init__(self, db: StoreDb):
        self.db = db
        db.open_tables(ddl_for(DDL, db.dialect))
        found = db.one("SELECT value FROM meta WHERE key = 'schema'")
        if found is None:
            db.exec("INSERT INTO meta VALUES ('schema', ?)", (str(SCHEMA),))
        elif int(found["value"]) < SCHEMA:  # the cut's tables (CS3) are made above, as new tables
            if (
                int(found["value"]) < 2
            ):  # a project of CS1: what was added to it was not made for it
                db.exec("ALTER TABLE media ADD COLUMN made INTEGER NOT NULL DEFAULT 0")
            db.exec("UPDATE meta SET value = ? WHERE key = 'schema'", (str(SCHEMA),))

    @classmethod
    def in_folder(cls, folder: Path) -> "CreativeStore":
        """The desktop's store: `creative.db`. A plan a closed app left being written can go on."""
        store = cls(SqliteStoreDb(folder / "creative.db"))
        store.db.exec(
            "UPDATE projects SET status = 'interrupted', error = ?, stage = '' WHERE status = 'planning'",
            (LEFT_RUNNING,),
        )
        store.db.exec(
            "UPDATE runs SET status = 'interrupted', error = ?, stage = '' WHERE status = 'running'",
            (LEFT_RUNNING,),
        )
        return store

    @classmethod
    def on_postgres(
        cls, dsn: str, *, schema: str = "creative", max_connections: int = 8
    ) -> "CreativeStore":
        """The web's store, in its own schema of the deployment's Postgres. Work left going by a
        stopped service is swept by `fail_stale`, not here: other replicas may be working."""
        return cls(PostgresStoreDb(dsn, schema, max_connections=max_connections))

    def fail_stale(self, before: str) -> int:
        """Plans and runs not touched since `before` belong to a service that is gone: they become
        `interrupted` and can go on from their checkpoints. Returns how many."""
        n = self.db.exec(
            "UPDATE projects SET status = 'interrupted', error = ?, stage = '' WHERE status = 'planning' AND updated_at < ?",
            (LEFT_RUNNING_WEB, before),
        )
        return n + self.db.exec(
            "UPDATE runs SET status = 'interrupted', error = ?, stage = '' WHERE status = 'running' AND updated_at < ?",
            (LEFT_RUNNING_WEB, before),
        )

    @property
    def schema(self) -> str:
        return str(getattr(self.db, "schema", ""))

    def drop_schema(self) -> None:
        """Remove the web store's schema (tests)."""
        drop = getattr(self.db, "drop", None)
        if drop is not None:
            drop()

    def close(self) -> None:
        self.db.close()

    @staticmethod
    def _project(row: Any) -> dict[str, Any]:
        out = dict(row)
        out["brief"] = json.loads(out["brief"])
        out["facts"] = json.loads(out["facts"])
        out["plan"] = json.loads(out["plan"]) if out["plan"] else None
        return out

    def add(self, tenant: str, user: str, title: str, brief: dict[str, Any]) -> dict[str, Any]:
        item, at = new_id(), now()
        self.db.exec(
            "INSERT INTO projects(id, tenant_id, user_id, title, status, brief, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'draft', ?, ?, ?)",
            (item, tenant, user, title[:200], json.dumps(brief), at, at),
        )
        return self.get(tenant, user, item)

    def get(self, tenant: str, user: str, item: str) -> dict[str, Any]:
        row = self.db.one(
            "SELECT * FROM projects WHERE id = ? AND tenant_id = ? AND user_id = ?",
            (item, tenant, user),
        )
        if row is None:
            raise NotFound(item)
        return self._project(row)

    def list_projects(
        self, tenant: str, user: str, ids: list[str] | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM projects WHERE tenant_id = ? AND user_id = ?", [tenant, user]
        if ids:
            sql += f" AND id IN ({','.join('?' * len(ids))})"
            args += ids
        sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
        return [self._project(r) for r in self.db.all(sql, (*args, limit))]

    def set_brief(self, item: str, title: str, brief: dict[str, Any]) -> None:
        self.db.exec(
            "UPDATE projects SET title = ?, brief = ?, updated_at = ? WHERE id = ?",
            (title[:200], json.dumps(brief), now(), item),
        )

    def rename(self, tenant: str, user: str, item: str, title: str) -> dict[str, Any]:
        n = self.db.exec(
            "UPDATE projects SET title = ?, updated_at = ? WHERE id = ? AND tenant_id = ? AND user_id = ?",
            (title[:200], now(), item, tenant, user),
        )
        if n == 0:
            raise NotFound(item)
        return self.get(tenant, user, item)

    def delete(self, tenant: str, user: str, item: str) -> bool:
        n = self.db.exec(
            "DELETE FROM projects WHERE id = ? AND tenant_id = ? AND user_id = ?",
            (item, tenant, user),
        )
        if n:
            for table in (
                "revisions",
                "checkpoints",
                "plan_log",
                "media",
                "takes",
                "chosen",
                "runs",
                "previews",
                "cuts",
                "cut_revisions",
                "renders",
                "exports",
            ):
                self.db.exec(f"DELETE FROM {table} WHERE project_id = ?", (item,))
        return n > 0

    # ---- a plan being written ---------------------------------------------------------------------

    def begin(self, item: str, stage: str) -> None:
        self.db.exec(
            "UPDATE projects SET status = 'planning', stage = ?, progress = 0, error = NULL, "
            "updated_at = ? WHERE id = ?",
            (stage, now(), item),
        )

    def set_progress(self, item: str, stage: str, progress: float) -> None:
        self.db.exec(
            "UPDATE projects SET stage = ?, progress = ?, updated_at = ? WHERE id = ? AND status = 'planning'",
            (stage, progress, now(), item),
        )

    def set_facts(self, item: str, facts: dict[str, Any]) -> None:
        self.db.exec("UPDATE projects SET facts = ? WHERE id = ?", (json.dumps(facts), item))

    def finish(
        self, item: str, status: str, error: str | None, elapsed_s: float | None = None
    ) -> None:
        self.db.exec(
            "UPDATE projects SET status = ?, error = ?, stage = '', elapsed_s = COALESCE(?, elapsed_s), "
            "updated_at = ? WHERE id = ? AND status = 'planning'",
            (status, error, elapsed_s, now(), item),
        )

    def checkpoints(self, item: str) -> dict[str, Any]:
        rows = self.db.all("SELECT step, data FROM checkpoints WHERE project_id = ?", (item,))
        return {r["step"]: json.loads(r["data"]) for r in rows}

    def keep_checkpoint(self, item: str, step: str, data: Any) -> None:
        self.db.exec("DELETE FROM checkpoints WHERE project_id = ? AND step = ?", (item, step))
        self.db.exec(
            "INSERT INTO checkpoints(project_id, step, data) VALUES (?, ?, ?)",
            (item, step, json.dumps(data)),
        )

    def clear_checkpoints(self, item: str, keep: tuple[str, ...] = ()) -> None:
        """Forget the finished steps, except those whose name starts with one of `keep`."""
        for step in self.checkpoints(item):
            if not (keep and step.startswith(keep)):
                self.db.exec(
                    "DELETE FROM checkpoints WHERE project_id = ? AND step = ?", (item, step)
                )

    def drop_checkpoints(self, item: str, *prefixes: str) -> None:
        """Forget the finished steps whose name starts with one of `prefixes`."""
        for step in self.checkpoints(item):
            if step.startswith(prefixes):
                self.db.exec(
                    "DELETE FROM checkpoints WHERE project_id = ? AND step = ?", (item, step)
                )

    def add_log(self, item: str, step: str, asked: str, said: str) -> None:
        self.db.exec(
            "INSERT INTO plan_log(project_id, step, asked, said, created_at) VALUES (?, ?, ?, ?, ?)",
            (item, step, asked[:4000], said[:4000], now()),
        )
        self.db.exec(
            "DELETE FROM plan_log WHERE project_id = ? AND id NOT IN "
            "(SELECT id FROM plan_log WHERE project_id = ? ORDER BY id DESC LIMIT ?)",
            (item, item, KEEP_LOG),
        )

    def log_of(self, item: str) -> list[dict[str, Any]]:
        rows = self.db.all(
            "SELECT step, asked, said, created_at FROM plan_log WHERE project_id = ? ORDER BY id",
            (item,),
        )
        return [dict(r) for r in rows]

    # ---- the plan and its revisions -----------------------------------------------------------------

    def save_plan(self, item: str, plan: dict[str, Any], note: str) -> int:
        """A new revision of the plan; the older ones stay, for Undo."""
        row = self.db.one("SELECT revision FROM projects WHERE id = ?", (item,))
        if row is None:
            raise NotFound(item)
        revision = int(row["revision"]) + 1
        text, at = json.dumps(plan), now()
        self.db.exec(
            "INSERT INTO revisions(project_id, revision, plan, note, created_at) VALUES (?, ?, ?, ?, ?)",
            (item, revision, text, note[:200], at),
        )
        self.db.exec(
            "UPDATE projects SET plan = ?, revision = ?, updated_at = ? WHERE id = ?",
            (text, revision, at, item),
        )
        self.db.exec(
            "DELETE FROM revisions WHERE project_id = ? AND revision <= ?",
            (item, revision - KEEP_REVISIONS),
        )
        return revision

    def set_status(self, item: str, status: str, error: str | None = None) -> None:
        self.db.exec(
            "UPDATE projects SET status = ?, error = ?, updated_at = ? WHERE id = ?",
            (status, error, now(), item),
        )

    def keep_conversation(self, item: str, conversation: str) -> None:
        self.db.exec("UPDATE projects SET conversation_id = ? WHERE id = ?", (conversation, item))

    def add_media(
        self, item: str, kind: str, media_id: str, shot: str | None, made: bool = False
    ) -> None:
        """Tag a thing of the library with this project. The thing itself stays in the library;
        `made` says it was made for this project, so deleting the project can offer to delete it."""
        self.db.exec(
            "INSERT INTO media(project_id, kind, item_id, shot_id, made, created_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (project_id, kind, item_id) DO UPDATE SET shot_id = excluded.shot_id",
            (item, kind, media_id, shot, int(made), now()),
        )

    def remove_media(self, item: str, kind: str, media_id: str) -> None:
        self.db.exec(
            "DELETE FROM media WHERE project_id = ? AND kind = ? AND item_id = ?",
            (item, kind, media_id),
        )

    def media_of(self, item: str) -> list[dict[str, Any]]:
        """Newest first, as the rail shows them."""
        rows = self.db.all(
            "SELECT kind, item_id, shot_id, made, created_at FROM media WHERE project_id = ? "
            "ORDER BY created_at DESC, item_id",
            (item,),
        )
        return [dict(r) for r in rows]

    # ---- takes: the stills and clips of a shot ---------------------------------------------------

    def add_take(
        self, item: str, shot: str, kind: str, media_id: str, inputs: str, prompt: str, mode: str,
        seconds: float | None, revision: int, *, choose: bool,
    ) -> str:  # fmt: skip
        """A new take, saved at once. The first take of a shot is its chosen one; another becomes
        chosen only when `choose` says the person asked for it."""
        take = new_id()
        self.db.exec(
            "INSERT INTO takes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (take, item, shot, kind, media_id, inputs, prompt, mode, seconds, revision, now()),
        )
        had = self.db.one(
            "SELECT take_id FROM chosen WHERE project_id = ? AND shot_id = ?", (item, shot)
        )
        if choose or had is None:
            self.choose_take(item, shot, take)
        return take

    def choose_take(self, item: str, shot: str, take: str) -> None:
        self.db.exec(
            "INSERT INTO chosen VALUES (?, ?, ?) ON CONFLICT (project_id, shot_id) "
            "DO UPDATE SET take_id = excluded.take_id",
            (item, shot, take),
        )

    def takes_of(self, item: str) -> list[dict[str, Any]]:
        """Every take of the project, oldest first."""
        rows = self.db.all(
            "SELECT id, shot_id, kind, item_id, inputs, prompt, mode, seconds, revision, created_at "
            "FROM takes WHERE project_id = ? ORDER BY created_at, id",
            (item,),
        )
        return [dict(r) for r in rows]

    def chosen_of(self, item: str) -> dict[str, str]:
        rows = self.db.all("SELECT shot_id, take_id FROM chosen WHERE project_id = ?", (item,))
        return {r["shot_id"]: r["take_id"] for r in rows}

    def remove_takes_of_media(self, item: str, kind: str, media_id: str) -> None:
        """A thing taken out of the project is no longer a take; its shot falls back to its newest."""
        rows = self.db.all(
            "SELECT id, shot_id FROM takes WHERE project_id = ? AND kind = ? AND item_id = ?",
            (item, kind, media_id),
        )
        for row in rows:
            self.db.exec("DELETE FROM takes WHERE id = ?", (row["id"],))
            was = self.chosen_of(item).get(row["shot_id"])
            if was == row["id"]:
                self.db.exec(
                    "DELETE FROM chosen WHERE project_id = ? AND shot_id = ?",
                    (item, row["shot_id"]),
                )
                left = self.db.one(
                    "SELECT id FROM takes WHERE project_id = ? AND shot_id = ? ORDER BY created_at DESC LIMIT 1",
                    (item, row["shot_id"]),
                )
                if left:
                    self.choose_take(item, row["shot_id"], left["id"])

    # ---- the run: one person's stills or preview, as one job -------------------------------------

    def begin_run(self, item: str, kind: str, stage: str, total: int) -> None:
        self.db.exec(
            "INSERT INTO runs VALUES (?, ?, 'running', ?, 0, ?, 0, NULL, ?) ON CONFLICT (project_id) DO UPDATE SET "
            "kind = excluded.kind, status = 'running', stage = excluded.stage, finished = 0, "
            "total = excluded.total, failed = 0, error = NULL, updated_at = excluded.updated_at",
            (item, kind, stage, total, now()),
        )

    def run_progress(self, item: str, stage: str, finished: int, failed: int) -> None:
        self.db.exec(
            "UPDATE runs SET stage = ?, finished = ?, failed = ?, updated_at = ? WHERE project_id = ?",
            (stage, finished, failed, now(), item),
        )

    def end_run(self, item: str, status: str, error: str | None) -> None:
        self.db.exec(
            "UPDATE runs SET status = ?, error = ?, stage = '', updated_at = ? WHERE project_id = ?",
            (status, error, now(), item),
        )

    def run_of(self, item: str) -> dict[str, Any] | None:
        row = self.db.one(
            "SELECT kind, status, stage, finished, total, failed, error FROM runs WHERE project_id = ?",
            (item,),
        )
        return dict(row) if row else None

    def set_preview(
        self, item: str, rel: str, mark: str, seconds: float, empty: int, took: float
    ) -> None:
        self.db.exec(
            "INSERT INTO previews VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (project_id) DO UPDATE SET "
            "rel = excluded.rel, mark = excluded.mark, seconds = excluded.seconds, "
            "empty_shots = excluded.empty_shots, took_s = excluded.took_s, created_at = excluded.created_at",
            (item, rel, mark, seconds, empty, took, now()),
        )

    def preview_of(self, item: str) -> dict[str, Any] | None:
        row = self.db.one(
            "SELECT rel, mark, seconds, empty_shots, took_s, created_at FROM previews WHERE project_id = ?",
            (item,),
        )
        return dict(row) if row else None

    # ---- the cut: its revisions for undo and redo, its video and what was kept (CS3) ------------

    def cut_of(self, item: str) -> dict[str, Any] | None:
        """The cut now, with whether there is something to undo or redo; None before the first."""
        head = self.db.one("SELECT at, top FROM cuts WHERE project_id = ?", (item,))
        if head is None:
            return None
        row = self.db.one(
            "SELECT cut FROM cut_revisions WHERE project_id = ? AND n = ?", (item, head["at"])
        )
        oldest = self.db.one("SELECT MIN(n) AS n FROM cut_revisions WHERE project_id = ?", (item,))
        return {
            "cut": json.loads(row["cut"]) if row else None,
            "can_undo": oldest is not None and oldest["n"] is not None and oldest["n"] < head["at"],
            "can_redo": head["top"] > head["at"],
        }

    def save_cut(self, item: str, cut: dict[str, Any], note: str) -> None:
        """A new revision of the cut. What was undone before it cannot be redone any more."""
        head = self.db.one("SELECT at FROM cuts WHERE project_id = ?", (item,))
        n = int(head["at"]) + 1 if head else 1
        at = now()
        self.db.exec("DELETE FROM cut_revisions WHERE project_id = ? AND n >= ?", (item, n))
        self.db.exec(
            "INSERT INTO cut_revisions VALUES (?, ?, ?, ?, ?)",
            (item, n, json.dumps(cut), note[:200], at),
        )
        self.db.exec(
            "INSERT INTO cuts VALUES (?, ?, ?, ?) ON CONFLICT (project_id) DO UPDATE SET "
            "at = excluded.at, top = excluded.top, updated_at = excluded.updated_at",
            (item, n, n, at),
        )
        self.db.exec(
            "DELETE FROM cut_revisions WHERE project_id = ? AND n <= ?", (item, n - KEEP_REVISIONS)
        )

    def step_cut(self, item: str, by: int) -> str | None:
        """Undo (-1) or redo (+1): what was undone or redone, or None when there is nothing."""
        head = self.db.one("SELECT at, top FROM cuts WHERE project_id = ?", (item,))
        if head is None:
            return None
        to = int(head["at"]) + by
        target = self.db.one(
            "SELECT n FROM cut_revisions WHERE project_id = ? AND n = ?", (item, to)
        )
        if target is None or to > head["top"]:
            return None
        named = self.db.one(
            "SELECT note FROM cut_revisions WHERE project_id = ? AND n = ?",
            (item, head["at"] if by < 0 else to),
        )
        self.db.exec(
            "UPDATE cuts SET at = ?, updated_at = ? WHERE project_id = ?", (to, now(), item)
        )
        return str(named["note"]) if named else ""

    def set_render(
        self, item: str, rel: str, mark: str, shape: str, seconds: float, size: int, took: float
    ) -> None:
        self.db.exec(
            "INSERT INTO renders VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (project_id) DO UPDATE SET "
            "rel = excluded.rel, mark = excluded.mark, shape = excluded.shape, seconds = excluded.seconds, "
            "bytes = excluded.bytes, took_s = excluded.took_s, created_at = excluded.created_at",
            (item, rel, mark, shape, seconds, size, took, now()),
        )

    def render_of(self, item: str) -> dict[str, Any] | None:
        row = self.db.one(
            "SELECT rel, mark, shape, seconds, bytes, took_s, created_at FROM renders WHERE project_id = ?",
            (item,),
        )
        return dict(row) if row else None

    def add_export(self, item: str, video_id: str, mark: str, title: str) -> None:
        self.db.exec(
            "INSERT INTO exports VALUES (?, ?, ?, ?, ?, ?)",
            (new_id(), item, video_id, mark, title[:120], now()),
        )

    def exports_of(self, item: str) -> list[dict[str, Any]]:
        rows = self.db.all(
            "SELECT video_id, mark, title, created_at FROM exports WHERE project_id = ? "
            "ORDER BY created_at DESC",
            (item,),
        )
        return [dict(r) for r in rows]

    # ---- people: kept across projects (ADR-0090 decision 10) ------------------------------------

    def keep_characters(self, tenant: str, user: str, cast: list[dict[str, Any]]) -> None:
        for p in cast:
            self.db.exec(
                "INSERT INTO characters VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (tenant_id, user_id, name) DO UPDATE SET "
                "look = excluded.look, pictures = excluded.pictures, photos_only = excluded.photos_only, "
                "updated_at = excluded.updated_at",
                (tenant, user, p["name"], p.get("look", ""), json.dumps(p.get("pictures") or []),
                 int(bool(p.get("photos_only"))), now()),
            )  # fmt: skip

    def characters(self, tenant: str, user: str) -> list[dict[str, Any]]:
        rows = self.db.all(
            "SELECT name, look, pictures, photos_only FROM characters WHERE tenant_id = ? AND user_id = ? "
            "ORDER BY updated_at DESC",
            (tenant, user),
        )
        return [
            {"name": r["name"], "look": r["look"], "pictures": json.loads(r["pictures"]),
             "photos_only": bool(r["photos_only"])}
            for r in rows
        ]  # fmt: skip

    def undo(self, item: str) -> str | None:
        """Back to the revision before this one; what the undone change was, or None if there is none."""
        row = self.db.one("SELECT revision FROM projects WHERE id = ?", (item,))
        if row is None:
            raise NotFound(item)
        now_at = int(row["revision"])
        before = self.db.one(
            "SELECT revision, plan FROM revisions WHERE project_id = ? AND revision < ? "
            "ORDER BY revision DESC LIMIT 1",
            (item, now_at),
        )
        if before is None:
            return None
        gone = self.db.one(
            "SELECT note FROM revisions WHERE project_id = ? AND revision = ?", (item, now_at)
        )
        self.db.exec(
            "UPDATE projects SET plan = ?, revision = ?, updated_at = ? WHERE id = ?",
            (before["plan"], before["revision"], now(), item),
        )
        self.db.exec("DELETE FROM revisions WHERE project_id = ? AND revision = ?", (item, now_at))
        return str(gone["note"]) if gone else ""
