"""The 3D models a person made, and the pictures they are made from (ADR-0080, TD1): on the desktop
one small SQLite file and the files beside it, in the app's own data folder; on the web the same
tables in their own Postgres schema (`model3d`) and the files in object storage (ADR-0087, P3). One
store class on either database (stage J2: `wasifyai_platform_sdk.sqlstore`).

Every query is scoped by tenant and user. A model has a state (`working`, `done`, `failed`,
`cancelled`); a picture waiting to become a model is an *input* (its cut-out and the checks of it).
On the desktop a model or an input left `working` by a process that is gone is failed when the store
opens (`in_folder`): a 3D run takes minutes, and the engine that started it is not there any more.
The web's service follows such a job again on its worker instead."""

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk.sqlstore import PostgresStoreDb, SqliteStoreDb, StoreDb

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
  stage TEXT NOT NULL DEFAULT '', progress DOUBLE PRECISION NOT NULL DEFAULT 0, error TEXT,
  detail TEXT NOT NULL DEFAULT 'standard', seed INTEGER NOT NULL DEFAULT 42,
  recipe TEXT NOT NULL DEFAULT '{}', elapsed_s DOUBLE PRECISION, peak_gb DOUBLE PRECISION,
  glb_bytes BIGINT,
  created_at TEXT NOT NULL, finished_at TEXT);
CREATE INDEX IF NOT EXISTS models_owner ON models(tenant_id, user_id, created_at);
CREATE INDEX IF NOT EXISTS inputs_owner ON inputs(tenant_id, user_id, created_at);
"""


class Model3dStore:
    def __init__(self, db: StoreDb, folder: Path | None = None):
        """The store on `db`. `folder` is where the files are on the desktop; on the web they are in
        object storage and there is none."""
        self.db = db
        self.folder = folder
        db.open_tables(DDL)
        db.exec("INSERT INTO meta VALUES ('schema', ?) ON CONFLICT DO NOTHING", (str(SCHEMA),))

    @classmethod
    def in_folder(cls, folder: Path) -> "Model3dStore":
        """The desktop's store: `model3d.db` and the files beside it. What a closed app left being
        made is failed, in words."""
        store = cls(SqliteStoreDb(folder / "model3d.db"), folder)
        store.fail_left_running()
        return store

    @classmethod
    def on_postgres(cls, dsn: str, schema: str = "model3d") -> "Model3dStore":
        """The web's store, in its own schema of the deployment's Postgres."""
        return cls(PostgresStoreDb(dsn, schema))

    def fail_left_running(self) -> None:
        self.db.exec(
            "UPDATE models SET status = 'failed', error = ?, finished_at = ? "
            "WHERE status = 'working'",
            (LEFT_RUNNING, now()),
        )
        self.db.exec(
            "UPDATE inputs SET status = 'failed', error = ? WHERE status = 'checking'",
            ("It was stopped when the app closed. Add the picture again.",),
        )

    def close(self) -> None:
        self.db.close()

    def drop_schema(self) -> None:
        """Remove every table of this store (tests on Postgres)."""
        drop = getattr(self.db, "drop", None)
        if drop is not None:
            drop()

    # ---- where the files are ----------------------------------------------------------------

    def folder_of(self, tenant: str, user: str, kind: str, item_id: str) -> Path:
        if self.folder is None:
            raise NotImplementedError("the web keeps these files in object storage")
        if not re.fullmatch(r"[0-9a-f]{32}", item_id):
            raise ValueError("not an id")
        return self.folder / "files" / _slug(tenant) / _slug(user) / kind / item_id

    # ---- the three calls every query goes through -----------------------------------------------

    def _one(self, sql: str, args: tuple[Any, ...]) -> Any:
        return self.db.one(sql, args)

    def _all(self, sql: str, args: tuple[Any, ...] = ()) -> list[Any]:
        return self.db.all(sql, args)

    def _exec(self, sql: str, args: tuple[Any, ...] = ()) -> int:
        return self.db.exec(sql, args)

    # ---- pictures -----------------------------------------------------------------------------

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
    def _input(row: Any) -> dict[str, Any]:
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
            "stage = COALESCE(?, stage) WHERE id = ? AND status = 'checking'",
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
        rows = self._all(
            "SELECT id, tenant_id, user_id FROM inputs WHERE created_at < ? "
            "AND id NOT IN (SELECT input_id FROM models WHERE input_id IS NOT NULL)",
            (before,),
        )
        for r in rows:
            self._exec("DELETE FROM inputs WHERE id = ?", (r["id"],))
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
    def _model(row: Any) -> dict[str, Any]:
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
        return [self._model(r) for r in self._all(sql, (*args, limit))]

    def working_models(self) -> list[dict[str, Any]]:
        """Models being made now, for any person: what a restarted service picks up again."""
        return [self._model(r) for r in self._all("SELECT * FROM models WHERE status = 'working'")]

    def working_inputs(self) -> list[dict[str, Any]]:
        return [self._input(r) for r in self._all("SELECT * FROM inputs WHERE status = 'checking'")]

    def fail_stale(self, before: str, message: str) -> int:
        """Fail what has been working since before `before`: nobody is working on it."""
        n = self._exec(
            "UPDATE models SET status = 'failed', error = ?, finished_at = ? "
            "WHERE status = 'working' AND created_at < ?",
            (message, now(), before),
        )
        n += self._exec(
            "UPDATE inputs SET status = 'failed', error = ? "
            "WHERE status = 'checking' AND created_at < ?",
            (message, before),
        )
        return n

    def set_progress(self, item: str, progress: float, stage: str) -> None:
        self._exec(
            "UPDATE models SET progress = ?, stage = ? WHERE id = ? AND status = 'working'",
            (progress, stage, item),
        )

    def finish_model(
        self, item: str, status: str, *, error: str | None = None, elapsed_s: float | None = None,
        peak_gb: float | None = None, glb_bytes: int | None = None,
    ) -> None:  # fmt: skip
        # only what is still being made: a late failure does not undo a model that finished
        self._exec(
            "UPDATE models SET status = ?, error = ?, elapsed_s = ?, peak_gb = ?, glb_bytes = ?, "
            "progress = CASE WHEN ? = 'done' THEN 1 ELSE progress END, stage = '', "
            "finished_at = ? WHERE id = ? AND status = 'working'",
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
