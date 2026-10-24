# ruff: noqa: E501  (the SQL is easier to read on one line)
"""The datasets, runs and trained models of a person (ADR-0073, T1): one small SQLite file and the files
beside it, in the app's own data folder.

Every query is scoped by tenant and user. A **dataset** is pictures with a kind, a name, a magic word and
the person's statement of rights; an **item** is one picture with its checks and its written caption; a
**run** is one go at training a dataset; a **model** is what a finished run leaves, with its card. A run
left `working` by a process that is gone is failed when the store opens: a run takes minutes to hours, and
the engine that started it is not there any more."""

import json
import re
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = 1
LEFT_RUNNING = "It was stopped when the app closed. Start it again."
KINDS = ("character", "style", "object")
RIGHTS = ("mine", "permission", "drawing", "artwork")


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
CREATE TABLE IF NOT EXISTS datasets(
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('character', 'style', 'object')),
  name TEXT NOT NULL DEFAULT '', trigger_word TEXT NOT NULL DEFAULT '', rights TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS items(
  id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
  name TEXT NOT NULL DEFAULT '', width INTEGER, height INTEGER, sha256 TEXT NOT NULL, dhash TEXT NOT NULL,
  checks TEXT NOT NULL DEFAULT '[]', caption TEXT NOT NULL DEFAULT '',
  caption_state TEXT NOT NULL DEFAULT 'none' CHECK (caption_state IN ('none', 'writing', 'done', 'edited', 'failed')),
  caption_error TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(
  id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('working', 'done', 'failed', 'cancelled')),
  stage TEXT NOT NULL DEFAULT '', step INTEGER NOT NULL DEFAULT 0, steps INTEGER NOT NULL DEFAULT 0,
  progress REAL NOT NULL DEFAULT 0, error TEXT, base TEXT NOT NULL DEFAULT '', settings TEXT NOT NULL DEFAULT '{}',
  samples TEXT NOT NULL DEFAULT '[]', preview INTEGER NOT NULL DEFAULT 0, model_id TEXT, elapsed_s REAL,
  created_at TEXT NOT NULL, finished_at TEXT);
CREATE TABLE IF NOT EXISTS models(
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, run_id TEXT NOT NULL, dataset_id TEXT,
  name TEXT NOT NULL, trigger_word TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'character',
  base TEXT NOT NULL DEFAULT '', card TEXT NOT NULL DEFAULT '{}', preview INTEGER NOT NULL DEFAULT 0,
  adapter_bytes INTEGER, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS datasets_owner ON datasets(tenant_id, user_id, created_at);
CREATE INDEX IF NOT EXISTS items_dataset ON items(dataset_id, created_at);
CREATE INDEX IF NOT EXISTS runs_owner ON runs(tenant_id, user_id, created_at);
CREATE INDEX IF NOT EXISTS models_owner ON models(tenant_id, user_id, created_at);
"""


class TrainingStore:
    def __init__(self, folder: Path):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(folder / "training.db", check_same_thread=False, timeout=10)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(DDL)
            self._db.execute("INSERT OR IGNORE INTO meta VALUES ('schema', ?)", (str(SCHEMA),))
            self._db.execute(
                "UPDATE runs SET status = 'failed', error = ?, finished_at = ? WHERE status = 'working'",
                (LEFT_RUNNING, now()),
            )
            self._db.execute(
                "UPDATE items SET caption_state = 'none' WHERE caption_state = 'writing'"
            )
            self._db.commit()

    # ---- where the files are ----------------------------------------------------------------

    def folder_of(self, tenant: str, user: str, kind: str, item_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", item_id):
            raise ValueError("not an id")
        return self.folder / "files" / _slug(tenant) / _slug(user) / kind / item_id

    # ---- the plumbing -----------------------------------------------------------------------

    def _one(self, sql: str, args: tuple[Any, ...]) -> sqlite3.Row | None:
        with self._lock:
            return self._db.execute(sql, args).fetchone()

    def _all(self, sql: str, args: tuple[Any, ...] = ()) -> list[Any]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def _exec(self, sql: str, args: tuple[Any, ...] = ()) -> int:
        with self._lock:
            cur = self._db.execute(sql, args)
            self._db.commit()
            return cur.rowcount

    # ---- datasets -----------------------------------------------------------------------------

    def add_dataset(self, tenant: str, user: str, kind: str, name: str) -> dict[str, Any]:
        if kind not in KINDS:
            raise ValueError("kind")
        item = new_id()
        self._exec(
            "INSERT INTO datasets(id, tenant_id, user_id, kind, name, created_at) VALUES (?,?,?,?,?,?)",
            (item, tenant, user, kind, name.strip()[:60], now()),
        )
        return self.get_dataset(tenant, user, item)

    def get_dataset(self, tenant: str, user: str, item: str) -> dict[str, Any]:
        row = self._one(
            "SELECT * FROM datasets WHERE id = ? AND tenant_id = ? AND user_id = ?",
            (item, tenant, user),
        )
        if row is None:
            raise NotFound(item)
        return dict(row)

    def list_datasets(self, tenant: str, user: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._all(
            "SELECT * FROM datasets WHERE tenant_id = ? AND user_id = ? ORDER BY created_at DESC LIMIT ?",
            (tenant, user, limit),
        )
        return [dict(r) for r in rows]

    def update_dataset(self, tenant: str, user: str, item: str, **fields: str) -> dict[str, Any]:
        allowed = {"kind", "name", "trigger_word", "rights"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if "kind" in sets and sets["kind"] not in KINDS:
            raise ValueError("kind")
        if "rights" in sets and sets["rights"] not in (*RIGHTS, ""):
            raise ValueError("rights")
        if sets:
            cols = ", ".join(f"{k} = ?" for k in sets)
            n = self._exec(
                f"UPDATE datasets SET {cols} WHERE id = ? AND tenant_id = ? AND user_id = ?",
                (*sets.values(), item, tenant, user),
            )
            if n == 0:
                raise NotFound(item)
        return self.get_dataset(tenant, user, item)

    def delete_dataset(self, tenant: str, user: str, item: str) -> bool:
        n = self._exec(
            "DELETE FROM datasets WHERE id = ? AND tenant_id = ? AND user_id = ?",
            (item, tenant, user),
        )
        if n:
            self._exec("DELETE FROM items WHERE dataset_id = ?", (item,))
        return n > 0

    # ---- items --------------------------------------------------------------------------------

    @staticmethod
    def _item(row: sqlite3.Row) -> dict[str, Any]:
        out = dict(row)
        out["checks"] = json.loads(out["checks"])
        return out

    def add_item(
        self, tenant: str, user: str, dataset: str, *, name: str, width: int, height: int,
        sha256: str, dhash: int, checks: list[dict[str, Any]],
    ) -> dict[str, Any]:  # fmt: skip
        self.get_dataset(tenant, user, dataset)  # the owner only
        item = new_id()
        self._exec(
            "INSERT INTO items(id, dataset_id, tenant_id, user_id, name, width, height, sha256, dhash, "
            "checks, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (item, dataset, tenant, user, name[:200], width, height, sha256, format(dhash, "016x"),
             json.dumps(checks), now()),
        )  # fmt: skip
        return self.get_item(tenant, user, item)

    def get_item(self, tenant: str, user: str, item: str) -> dict[str, Any]:
        row = self._one(
            "SELECT * FROM items WHERE id = ? AND tenant_id = ? AND user_id = ?",
            (item, tenant, user),
        )
        if row is None:
            raise NotFound(item)
        return self._item(row)

    def list_items(self, tenant: str, user: str, dataset: str) -> list[dict[str, Any]]:
        rows = self._all(
            "SELECT * FROM items WHERE dataset_id = ? AND tenant_id = ? AND user_id = ? ORDER BY created_at, id",
            (dataset, tenant, user),
        )
        return [self._item(r) for r in rows]

    def set_checks(self, item: str, checks: list[dict[str, Any]]) -> None:
        self._exec("UPDATE items SET checks = ? WHERE id = ?", (json.dumps(checks), item))

    def set_caption(self, item: str, caption: str, state: str, error: str | None = None) -> None:
        self._exec(
            "UPDATE items SET caption = ?, caption_state = ?, caption_error = ? WHERE id = ?",
            (caption[:2000], state, error, item),
        )

    def mark_writing(self, item: str) -> None:
        self._exec(
            "UPDATE items SET caption_state = 'writing', caption_error = NULL WHERE id = ?", (item,)
        )

    def delete_item(self, tenant: str, user: str, item: str) -> bool:
        return (
            self._exec(
                "DELETE FROM items WHERE id = ? AND tenant_id = ? AND user_id = ?",
                (item, tenant, user),
            )
            > 0
        )

    # ---- runs ---------------------------------------------------------------------------------

    @staticmethod
    def _run(row: sqlite3.Row) -> dict[str, Any]:
        out = dict(row)
        out["settings"] = json.loads(out["settings"])
        out["samples"] = json.loads(out["samples"])
        out["preview"] = bool(out["preview"])
        return out

    def add_run(
        self, tenant: str, user: str, dataset: str, *, base: str, steps: int,
        settings: dict[str, Any], preview: bool,
    ) -> dict[str, Any]:  # fmt: skip
        item = new_id()
        self._exec(
            "INSERT INTO runs(id, dataset_id, tenant_id, user_id, status, steps, base, settings, preview, "
            "created_at) VALUES (?,?,?,?, 'working', ?, ?, ?, ?, ?)",
            (item, dataset, tenant, user, steps, base, json.dumps(settings), int(preview), now()),
        )  # fmt: skip
        return self.get_run(tenant, user, item)

    def get_run(self, tenant: str, user: str, item: str) -> dict[str, Any]:
        row = self._one(
            "SELECT * FROM runs WHERE id = ? AND tenant_id = ? AND user_id = ?",
            (item, tenant, user),
        )
        if row is None:
            raise NotFound(item)
        return self._run(row)

    def list_runs(self, tenant: str, user: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._all(
            "SELECT * FROM runs WHERE tenant_id = ? AND user_id = ? ORDER BY created_at DESC LIMIT ?",
            (tenant, user, limit),
        )
        return [self._run(r) for r in rows]

    def set_progress(self, item: str, step: int, stage: str) -> None:
        self._exec(
            "UPDATE runs SET step = ?, stage = ?, progress = CASE WHEN steps > 0 THEN MIN(1.0, ? * 1.0 / steps) "
            "ELSE 0 END WHERE id = ? AND status = 'working'",
            (step, stage, step, item),
        )

    def add_sample(self, item: str, name: str) -> None:
        row = self._one("SELECT samples FROM runs WHERE id = ?", (item,))
        if row is not None:
            samples = [*json.loads(row["samples"]), name]
            self._exec("UPDATE runs SET samples = ? WHERE id = ?", (json.dumps(samples), item))

    def finish_run(
        self, item: str, status: str, *, error: str | None = None, elapsed_s: float | None = None,
        model_id: str | None = None,
    ) -> None:  # fmt: skip
        # only what is still being worked on: a late failure does not undo a finished run
        self._exec(
            "UPDATE runs SET status = ?, error = ?, elapsed_s = ?, model_id = ?, stage = '', "
            "progress = CASE WHEN ? = 'done' THEN 1 ELSE progress END, finished_at = ? "
            "WHERE id = ? AND status = 'working'",
            (status, error, elapsed_s, model_id, status, now(), item),
        )

    # ---- trained models -----------------------------------------------------------------------

    @staticmethod
    def _model(row: sqlite3.Row) -> dict[str, Any]:
        out = dict(row)
        out["card"] = json.loads(out["card"])
        out["preview"] = bool(out["preview"])
        return out

    def add_model(
        self, tenant: str, user: str, *, run_id: str, dataset_id: str | None, name: str,
        trigger_word: str, kind: str, base: str, card: dict[str, Any], preview: bool,
        adapter_bytes: int,
    ) -> dict[str, Any]:  # fmt: skip
        item = new_id()
        self._exec(
            "INSERT INTO models(id, tenant_id, user_id, run_id, dataset_id, name, trigger_word, kind, base, "
            "card, preview, adapter_bytes, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (item, tenant, user, run_id, dataset_id, name[:200], trigger_word, kind, base,
             json.dumps(card), int(preview), adapter_bytes, now()),
        )  # fmt: skip
        return self.get_model(tenant, user, item)

    def get_model(self, tenant: str, user: str, item: str) -> dict[str, Any]:
        row = self._one(
            "SELECT * FROM models WHERE id = ? AND tenant_id = ? AND user_id = ?",
            (item, tenant, user),
        )
        if row is None:
            raise NotFound(item)
        return self._model(row)

    def list_models(self, tenant: str, user: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._all(
            "SELECT * FROM models WHERE tenant_id = ? AND user_id = ? ORDER BY created_at DESC LIMIT ?",
            (tenant, user, limit),
        )
        return [self._model(r) for r in rows]

    def rename_model(self, tenant: str, user: str, item: str, name: str) -> dict[str, Any]:
        n = self._exec(
            "UPDATE models SET name = ? WHERE id = ? AND tenant_id = ? AND user_id = ?",
            (name.strip()[:200], item, tenant, user),
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
