"""The 3D models a person made, and the pictures they are made from (ADR-0080, TD1): one small
SQLite file and the files beside it, in the app's own data folder.

Every query is scoped by tenant and user. A model has a state (`working`, `done`, `failed`,
`cancelled`); a picture waiting to become a model is an *input* (its cut-out and the checks of it).
A model or an input left `working` by a process that is gone is failed when the store opens: a 3D
run takes minutes, and the engine that started it is not there any more."""

import json
import re
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = 1
LEFT_RUNNING = "It was stopped when the app closed. Make it again."


class NotFound(Exception):
    """No such item for this person."""


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", text)[:64] or "_"


DDL = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS inputs(
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('checking', 'ready', 'failed')),
  name TEXT NOT NULL DEFAULT '', width INTEGER, height INTEGER,
  checks TEXT NOT NULL DEFAULT '[]', error TEXT, stage TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS models(
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
  title TEXT NOT NULL, prompt TEXT NOT NULL DEFAULT '', input_id TEXT,
  status TEXT NOT NULL CHECK (status IN ('working', 'done', 'failed', 'cancelled')),
  stage TEXT NOT NULL DEFAULT '', progress REAL NOT NULL DEFAULT 0, error TEXT,
  detail TEXT NOT NULL DEFAULT 'standard', seed INTEGER NOT NULL DEFAULT 42,
  recipe TEXT NOT NULL DEFAULT '{}', elapsed_s REAL, peak_gb REAL, glb_bytes INTEGER,
  created_at TEXT NOT NULL, finished_at TEXT);
CREATE INDEX IF NOT EXISTS models_owner ON models(tenant_id, user_id, created_at);
CREATE INDEX IF NOT EXISTS inputs_owner ON inputs(tenant_id, user_id, created_at);
"""


class Model3dStore:
    def __init__(self, folder: Path):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(folder / "model3d.db", check_same_thread=False, timeout=10)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(DDL)
            self._db.execute("INSERT OR IGNORE INTO meta VALUES ('schema', ?)", (str(SCHEMA),))
            self._db.execute(
                "UPDATE models SET status = 'failed', error = ?, finished_at = ? "
                "WHERE status = 'working'",
                (LEFT_RUNNING, now()),
            )
            self._db.execute(
                "UPDATE inputs SET status = 'failed', error = ? WHERE status = 'checking'",
                ("It was stopped when the app closed. Add the picture again.",),
            )
            self._db.commit()

    # ---- where the files are ----------------------------------------------------------------

    def folder_of(self, tenant: str, user: str, kind: str, item_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", item_id):
            raise ValueError("not an id")
        return self.folder / "files" / _slug(tenant) / _slug(user) / kind / item_id

    # ---- pictures -----------------------------------------------------------------------------

    def _one(self, sql: str, args: tuple[Any, ...]) -> sqlite3.Row | None:
        with self._lock:
            return self._db.execute(sql, args).fetchone()

    def _exec(self, sql: str, args: tuple[Any, ...] = ()) -> int:
        with self._lock:
            cur = self._db.execute(sql, args)
            self._db.commit()
            return cur.rowcount

    def add_input(
        self, tenant: str, user: str, name: str, width: int, height: int
    ) -> dict[str, Any]:
        item = new_id()
        self._exec(
            "INSERT INTO inputs(id, tenant_id, user_id, status, name, width, height, created_at) "
            "VALUES (?, ?, ?, 'checking', ?, ?, ?, ?)",
            (item, tenant, user, name[:200], width, height, now()),
        )
        return self.get_input(tenant, user, item)

    @staticmethod
    def _input(row: sqlite3.Row) -> dict[str, Any]:
        out = dict(row)
        out["checks"] = json.loads(out["checks"])
        return out

    def get_input(self, tenant: str, user: str, item: str) -> dict[str, Any]:
        row = self._one(
            "SELECT * FROM inputs WHERE id = ? AND tenant_id = ? AND user_id = ?",
            (item, tenant, user),
        )
        if row is None:
            raise NotFound(item)
        return self._input(row)

    def set_input(
        self, item: str, *, status: str, checks: list[dict[str, str]] | None = None,
        error: str | None = None, stage: str | None = None,
    ) -> None:  # fmt: skip
        self._exec(
            "UPDATE inputs SET status = ?, checks = COALESCE(?, checks), error = ?, "
            "stage = COALESCE(?, stage) WHERE id = ?",
            (status, json.dumps(checks) if checks is not None else None, error, stage, item),
        )

    def set_input_stage(self, item: str, stage: str) -> None:
        self._exec("UPDATE inputs SET stage = ? WHERE id = ?", (stage, item))

    def delete_input(self, tenant: str, user: str, item: str) -> bool:
        return (
            self._exec(
                "DELETE FROM inputs WHERE id = ? AND tenant_id = ? AND user_id = ?",
                (item, tenant, user),
            )
            > 0
        )

    def purge_inputs(self, before: str) -> list[tuple[str, str, str]]:
        """Forget pictures older than `before` that no model was made from; their ids, to remove
        the files of."""
        with self._lock:
            rows = self._db.execute(
                "SELECT id, tenant_id, user_id FROM inputs WHERE created_at < ? "
                "AND id NOT IN (SELECT input_id FROM models WHERE input_id IS NOT NULL)",
                (before,),
            ).fetchall()
            self._db.executemany("DELETE FROM inputs WHERE id = ?", [(r["id"],) for r in rows])
            self._db.commit()
        return [(r["tenant_id"], r["user_id"], r["id"]) for r in rows]

    # ---- models -------------------------------------------------------------------------------

    def add_model(
        self, tenant: str, user: str, *, title: str, prompt: str, input_id: str | None,
        detail: str, seed: int, recipe: dict[str, Any],
    ) -> dict[str, Any]:  # fmt: skip
        item = new_id()
        self._exec(
            "INSERT INTO models(id, tenant_id, user_id, title, prompt, input_id, status, stage, "
            "detail, seed, recipe, created_at) VALUES (?, ?, ?, ?, ?, ?, 'working', ?, ?, ?, ?, ?)",
            (item, tenant, user, title[:200], prompt[:1000], input_id, "Starting", detail, seed,
             json.dumps(recipe), now()),
        )  # fmt: skip
        return self.get_model(tenant, user, item)

    @staticmethod
    def _model(row: sqlite3.Row) -> dict[str, Any]:
        out = dict(row)
        out["recipe"] = json.loads(out["recipe"])
        return out

    def get_model(self, tenant: str, user: str, item: str) -> dict[str, Any]:
        row = self._one(
            "SELECT * FROM models WHERE id = ? AND tenant_id = ? AND user_id = ?",
            (item, tenant, user),
        )
        if row is None:
            raise NotFound(item)
        return self._model(row)

    def list_models(
        self, tenant: str, user: str, ids: list[str] | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM models WHERE tenant_id = ? AND user_id = ?", [tenant, user]
        if ids:
            sql += f" AND id IN ({','.join('?' * len(ids))})"
            args += ids
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        with self._lock:
            rows = self._db.execute(sql, (*args, limit)).fetchall()
        return [self._model(r) for r in rows]

    def set_progress(self, item: str, progress: float, stage: str) -> None:
        self._exec(
            "UPDATE models SET progress = ?, stage = ? WHERE id = ? AND status = 'working'",
            (progress, stage, item),
        )

    def finish_model(
        self, item: str, status: str, *, error: str | None = None, elapsed_s: float | None = None,
        peak_gb: float | None = None, glb_bytes: int | None = None,
    ) -> None:  # fmt: skip
        self._exec(
            "UPDATE models SET status = ?, error = ?, elapsed_s = ?, peak_gb = ?, glb_bytes = ?, "
            "progress = CASE WHEN ? = 'done' THEN 1 ELSE progress END, stage = '', "
            "finished_at = ? WHERE id = ?",
            (status, error, elapsed_s, peak_gb, glb_bytes, status, now(), item),
        )

    def rename_model(self, tenant: str, user: str, item: str, title: str) -> dict[str, Any]:
        n = self._exec(
            "UPDATE models SET title = ? WHERE id = ? AND tenant_id = ? AND user_id = ?",
            (title[:200], item, tenant, user),
        )
        if n == 0:
            raise NotFound(item)
        return self.get_model(tenant, user, item)

    def delete_model(self, tenant: str, user: str, item: str) -> bool:
        return (
            self._exec(
                "DELETE FROM models WHERE id = ? AND tenant_id = ? AND user_id = ?",
                (item, tenant, user),
            )
            > 0
        )
