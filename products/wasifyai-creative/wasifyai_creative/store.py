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

from wasifyai_platform_sdk.sqlstore import SqliteStoreDb, StoreDb

SCHEMA = 1
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
  created_at TEXT NOT NULL, PRIMARY KEY (project_id, kind, item_id));
"""
LEFT_RUNNING = "It stopped when the app closed. Go on, and it picks up where it stopped."


class NotFound(Exception):
    """No such project for this person."""


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class CreativeStore:
    def __init__(self, db: StoreDb):
        self.db = db
        db.open_tables(DDL)
        db.exec("INSERT INTO meta VALUES ('schema', ?) ON CONFLICT DO NOTHING", (str(SCHEMA),))

    @classmethod
    def in_folder(cls, folder: Path) -> "CreativeStore":
        """The desktop's store: `creative.db`. A plan a closed app left being written can go on."""
        store = cls(SqliteStoreDb(folder / "creative.db"))
        store.db.exec(
            "UPDATE projects SET status = 'interrupted', error = ?, stage = '' WHERE status = 'planning'",
            (LEFT_RUNNING,),
        )
        return store

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
            for table in ("revisions", "checkpoints", "plan_log", "media"):
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
            "UPDATE projects SET stage = ?, progress = ? WHERE id = ? AND status = 'planning'",
            (stage, progress, item),
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

    def clear_checkpoints(self, item: str) -> None:
        self.db.exec("DELETE FROM checkpoints WHERE project_id = ?", (item,))

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

    def add_media(self, item: str, kind: str, media_id: str, shot: str | None) -> None:
        """Tag a thing of the library with this project. The thing itself stays in the library."""
        self.db.exec(
            "INSERT INTO media VALUES (?, ?, ?, ?, ?) ON CONFLICT (project_id, kind, item_id) "
            "DO UPDATE SET shot_id = excluded.shot_id",
            (item, kind, media_id, shot, now()),
        )

    def remove_media(self, item: str, kind: str, media_id: str) -> None:
        self.db.exec(
            "DELETE FROM media WHERE project_id = ? AND kind = ? AND item_id = ?",
            (item, kind, media_id),
        )

    def media_of(self, item: str) -> list[dict[str, Any]]:
        """Newest first, as the rail shows them."""
        rows = self.db.all(
            "SELECT kind, item_id, shot_id, created_at FROM media WHERE project_id = ? "
            "ORDER BY created_at DESC, item_id",
            (item,),
        )
        return [dict(r) for r in rows]

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
