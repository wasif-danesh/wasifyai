# ruff: noqa: E501  (the SQL is easier to read on one line)
"""The datasets, runs and trained models of a person (ADR-0073, T1): on the desktop one small SQLite file
and the files beside it, in the app's own data folder; on the web the same tables in their own Postgres
schema (`training`) and the files in object storage (`files.py`). One store class on either database
(stage J2: `wasifyai_platform_sdk.sqlstore`).

Every query is scoped by tenant and user. A **dataset** is pictures with a kind, a name and a magic
word; an **item** is one picture with its checks and its written caption; a
**run** is one go at training a dataset; a **model** is what a finished run leaves, with its card. On the
desktop a run left `working` by a process that is gone is paused (or failed) when the store opens; on the
web a restarted service fails it and stops its worker job (`runs_left_working`)."""

import json
import re
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk.sqlstore import PostgresStoreDb, SqliteStoreDb, StoreDb

SCHEMA = 1
LEFT_RUNNING = "It was stopped when the app closed. Start it again."
LEFT_PAUSED = "It was paused when the app closed. You can pick it up where it stopped."
LEFT_RUNNING_WEB = "It was stopped when the service restarted. Start it again."
KINDS = ("character", "style", "object")
FAMILIES = ("image", "video")  # what a set of pictures (and clips) teaches
QUALITIES = ("quick", "better")
DECISION_KINDS = ("yes_no", "category", "score")


class NotFound(Exception):
    """No such item for this person."""


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", text)[:64] or "_"


RUNS_DDL = """
CREATE TABLE IF NOT EXISTS runs(
  id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('working', 'paused', 'done', 'failed', 'cancelled')),
  stage TEXT NOT NULL DEFAULT '', step INTEGER NOT NULL DEFAULT 0, steps INTEGER NOT NULL DEFAULT 0,
  progress DOUBLE PRECISION NOT NULL DEFAULT 0, error TEXT, base TEXT NOT NULL DEFAULT '', settings TEXT NOT NULL DEFAULT '{}',
  samples TEXT NOT NULL DEFAULT '[]', preview INTEGER NOT NULL DEFAULT 0, model_id TEXT, elapsed_s DOUBLE PRECISION,
  created_at TEXT NOT NULL, finished_at TEXT);
"""

DDL = (
    """
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
"""
    + RUNS_DDL
    + """CREATE TABLE IF NOT EXISTS models(
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, run_id TEXT NOT NULL, dataset_id TEXT,
  name TEXT NOT NULL, trigger_word TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'character',
  base TEXT NOT NULL DEFAULT '', card TEXT NOT NULL DEFAULT '{}', preview INTEGER NOT NULL DEFAULT 0,
  adapter_bytes BIGINT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS datasets_owner ON datasets(tenant_id, user_id, created_at);
CREATE INDEX IF NOT EXISTS items_dataset ON items(dataset_id, created_at);
CREATE INDEX IF NOT EXISTS runs_owner ON runs(tenant_id, user_id, created_at);
CREATE INDEX IF NOT EXISTS models_owner ON models(tenant_id, user_id, created_at);
CREATE TABLE IF NOT EXISTS writing_sets(
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
  name TEXT NOT NULL DEFAULT '', quality TEXT NOT NULL DEFAULT 'quick' CHECK (quality IN ('quick', 'better')),
  base TEXT NOT NULL DEFAULT '', rights TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS examples(
  id TEXT PRIMARY KEY, set_id TEXT NOT NULL, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
  position INTEGER NOT NULL, ask TEXT NOT NULL, answer TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS writing_sets_owner ON writing_sets(tenant_id, user_id, created_at);
CREATE INDEX IF NOT EXISTS examples_set ON examples(set_id, position);
CREATE TABLE IF NOT EXISTS decision_sets(
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
  name TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'yes_no' CHECK (kind IN ('yes_no', 'category', 'score')),
  question TEXT NOT NULL DEFAULT '', options TEXT NOT NULL DEFAULT '[]', levels INTEGER NOT NULL DEFAULT 5,
  low TEXT NOT NULL DEFAULT '', high TEXT NOT NULL DEFAULT '',
  quality TEXT NOT NULL DEFAULT 'quick' CHECK (quality IN ('quick', 'better')),
  base TEXT NOT NULL DEFAULT '', rights TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decision_examples(
  id TEXT PRIMARY KEY, set_id TEXT NOT NULL, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
  position INTEGER NOT NULL, text TEXT NOT NULL, answer TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS decision_sets_owner ON decision_sets(tenant_id, user_id, created_at);
CREATE INDEX IF NOT EXISTS decision_examples_set ON decision_examples(set_id, position);
"""
)


# what a later version added to a table an older one made (video sets, 2026-10-26)
COLUMNS = (
    ("datasets", "family", "TEXT NOT NULL DEFAULT 'image'"),
    ("items", "media", "TEXT NOT NULL DEFAULT 'picture'"),
    ("items", "seconds", "DOUBLE PRECISION"),
    ("items", "frames", "INTEGER"),
)


def _rebuild_runs(db: Any) -> None:
    """A run can be paused (2026-10-25): the status check of a desktop file made before does not
    allow it, so that table is made again with its rows (SQLite cannot change a check)."""
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'runs'"
    ).fetchone()
    if row is None or "'paused'" in row["sql"]:
        return
    db.execute("ALTER TABLE runs RENAME TO runs_old")
    db.execute("DROP INDEX IF EXISTS runs_owner")
    db.executescript(RUNS_DDL)
    db.execute("INSERT INTO runs SELECT * FROM runs_old")
    db.execute("DROP TABLE runs_old")
    db.commit()


class TrainingStore:
    def __init__(self, db: StoreDb, folder: Path):
        """The store on `db`. `folder` holds the files on the desktop; on the web it is a working
        folder only, the files being in object storage."""
        self.db = db
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        db.open_tables(DDL, COLUMNS, before=_rebuild_runs)
        db.exec("INSERT INTO meta VALUES ('schema', ?) ON CONFLICT DO NOTHING", (str(SCHEMA),))

    @classmethod
    def in_folder(cls, folder: Path) -> "TrainingStore":
        """The desktop's store: `training.db` and the files beside it. A run the app left going is
        paused when a checkpoint was kept, else stopped, in words."""
        store = cls(SqliteStoreDb(folder / "training.db"), folder)
        store.settle_left_running()
        return store

    @classmethod
    def on_postgres(
        cls, dsn: str, schema: str = "training", cache: Path | None = None
    ) -> "TrainingStore":
        """The web's store, in its own schema of the deployment's Postgres; `cache` is the API's
        working folder (the files themselves are in object storage)."""
        folder = cache or Path(tempfile.gettempdir()) / "wasifyai-training"
        return cls(PostgresStoreDb(dsn, schema), folder)

    def settle_left_running(self) -> None:
        for row in self._all("SELECT id, tenant_id, user_id FROM runs WHERE status = 'working'"):
            kept = self._has_checkpoint(row["tenant_id"], row["user_id"], row["id"])
            self._exec(
                "UPDATE runs SET status = ?, error = ?, finished_at = ? WHERE id = ?",
                (
                    "paused" if kept else "failed",
                    LEFT_PAUSED if kept else LEFT_RUNNING,
                    None if kept else now(),
                    row["id"],
                ),
            )
        self._exec("UPDATE items SET caption_state = 'none' WHERE caption_state = 'writing'")

    def runs_left_working(self) -> list[dict[str, Any]]:
        """Runs a service that is gone left going: the web has no checkpoint to pick up (a worker's
        job is cancelled by the caller), so each is failed with a sentence."""
        rows = self._all("SELECT id, tenant_id, user_id FROM runs WHERE status = 'working'")
        for r in rows:
            self._exec(
                "UPDATE runs SET status = 'failed', error = ?, finished_at = ? WHERE id = ?",
                (LEFT_RUNNING_WEB, now(), r["id"]),
            )
        self._exec("UPDATE items SET caption_state = 'none' WHERE caption_state = 'writing'")
        return [dict(r) for r in rows]

    def close(self) -> None:
        self.db.close()

    def drop_schema(self) -> None:
        """Remove every table of this store (tests on Postgres)."""
        drop = getattr(self.db, "drop", None)
        if drop is not None:
            drop()

    def _has_checkpoint(self, tenant: str, user: str, run: str) -> bool:
        try:
            folder = self.folder_of(tenant, user, "runs", run) / "out" / "checkpoints"
        except ValueError:
            return False
        return folder.is_dir() and any(folder.glob("*_checkpoint.zip"))

    # ---- where the files are ----------------------------------------------------------------

    def folder_of(self, tenant: str, user: str, kind: str, item_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", item_id):
            raise ValueError("not an id")
        return self.folder / "files" / _slug(tenant) / _slug(user) / kind / item_id

    # ---- the plumbing -----------------------------------------------------------------------

    def _one(self, sql: str, args: tuple[Any, ...]) -> Any:
        return self.db.one(sql, args)

    def _all(self, sql: str, args: tuple[Any, ...] = ()) -> list[Any]:
        return self.db.all(sql, args)

    def _exec(self, sql: str, args: tuple[Any, ...] = ()) -> int:
        return self.db.exec(sql, args)

    def _replace_rows(
        self,
        delete_sql: str,
        delete_args: tuple[Any, ...],
        insert_sql: str,
        rows: list[tuple[Any, ...]],
    ) -> None:
        """Delete some rows and insert others, together: the examples of a set are replaced whole."""
        with self.db.transaction() as db:
            db.execute(delete_sql, delete_args)
            for row in rows:
                db.execute(insert_sql, row)

    # ---- datasets -----------------------------------------------------------------------------

    def add_dataset(
        self, tenant: str, user: str, kind: str, name: str, family: str = "image"
    ) -> dict[str, Any]:
        if kind not in KINDS:
            raise ValueError("kind")
        if family not in FAMILIES:
            raise ValueError("family")
        item = new_id()
        self._exec(
            "INSERT INTO datasets(id, tenant_id, user_id, kind, name, family, created_at) VALUES (?,?,?,?,?,?,?)",
            (item, tenant, user, kind, name.strip()[:60], family, now()),
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

    def list_datasets(
        self, tenant: str, user: str, limit: int = 50, family: str | None = None
    ) -> list[dict[str, Any]]:
        rows = self._all(
            "SELECT * FROM datasets WHERE tenant_id = ? AND user_id = ? AND (CAST(? AS TEXT) IS NULL OR family = ?) "
            "ORDER BY created_at DESC LIMIT ?",
            (tenant, user, family, family, limit),
        )
        return [dict(r) for r in rows]

    def update_dataset(self, tenant: str, user: str, item: str, **fields: str) -> dict[str, Any]:
        allowed = {"kind", "name", "trigger_word"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if "kind" in sets and sets["kind"] not in KINDS:
            raise ValueError("kind")
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
    def _item(row: Any) -> dict[str, Any]:
        out = dict(row)
        out["checks"] = json.loads(out["checks"])
        return out

    def add_item(
        self, tenant: str, user: str, dataset: str, *, name: str, width: int, height: int,
        sha256: str, dhash: int, checks: list[dict[str, Any]], media: str = "picture",
        seconds: float | None = None, frames: int | None = None,
    ) -> dict[str, Any]:  # fmt: skip
        self.get_dataset(tenant, user, dataset)  # the owner only
        item = new_id()
        self._exec(
            "INSERT INTO items(id, dataset_id, tenant_id, user_id, name, width, height, sha256, dhash, "
            "checks, media, seconds, frames, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (item, dataset, tenant, user, name[:200], width, height, sha256, format(dhash, "016x"),
             json.dumps(checks), media, seconds, frames, now()),
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
    def _run(row: Any) -> dict[str, Any]:
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
            "UPDATE runs SET step = ?, stage = ?, progress = CASE WHEN steps <= 0 THEN 0 "
            "WHEN CAST(? AS INTEGER) >= steps THEN 1.0 ELSE CAST(? AS INTEGER) * 1.0 / steps END WHERE id = ? AND status = 'working'",
            (step, stage, step, step, item),
        )

    def add_sample(self, item: str, name: str) -> None:
        row = self._one("SELECT samples FROM runs WHERE id = ?", (item,))
        if row is not None:
            samples = [*json.loads(row["samples"]), name]
            self._exec("UPDATE runs SET samples = ? WHERE id = ?", (json.dumps(samples), item))

    def pause_run(self, item: str, stage: str = "Paused") -> None:
        """Stopped for now, with a checkpoint kept: it can be picked up where it stopped."""
        self._exec(
            "UPDATE runs SET status = 'paused', stage = ?, error = NULL, finished_at = NULL "
            "WHERE id = ? AND status = 'working'",
            (stage, item),
        )

    def resume_run(self, item: str) -> bool:
        return (
            self._exec(
                "UPDATE runs SET status = 'working', stage = 'Starting again', error = NULL "
                "WHERE id = ? AND status = 'paused'",
                (item,),
            )
            > 0
        )

    def finish_run(
        self, item: str, status: str, *, error: str | None = None, elapsed_s: float | None = None,
        model_id: str | None = None,
    ) -> None:  # fmt: skip
        # only what is still being worked on: a late failure does not undo a finished run
        self._exec(
            "UPDATE runs SET status = ?, error = ?, elapsed_s = ?, model_id = ?, stage = '', "
            "progress = CASE WHEN CAST(? AS TEXT) = 'done' THEN 1 ELSE progress END, finished_at = ? "
            "WHERE id = ? AND status IN ('working', 'paused')",
            (status, error, elapsed_s, model_id, status, now(), item),
        )

    # ---- trained models -----------------------------------------------------------------------

    @staticmethod
    def _model(row: Any) -> dict[str, Any]:
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

    def taught_in_run(self, run_prefix: str) -> dict[str, str] | None:
        """What a run taught (`kind`: character, object, style ...) and its magic `word`, from the
        start of its id: the image screens' styles name Train's runs by its first 8 characters."""
        if not run_prefix or not all(c in "0123456789abcdef-" for c in run_prefix):
            return None
        row = self._one(
            "SELECT kind, trigger_word FROM models WHERE run_id LIKE ? "
            "ORDER BY created_at DESC LIMIT 1",
            (f"{run_prefix}%",),
        )
        return {"kind": str(row["kind"]), "word": str(row["trigger_word"] or "")} if row else None

    def rename_model(self, tenant: str, user: str, item: str, name: str) -> dict[str, Any]:
        n = self._exec(
            "UPDATE models SET name = ? WHERE id = ? AND tenant_id = ? AND user_id = ?",
            (name.strip()[:200], item, tenant, user),
        )
        if n == 0:
            raise NotFound(item)
        return self.get_model(tenant, user, item)

    def set_evaluation(
        self, tenant: str, user: str, item: str, evaluation: dict[str, Any]
    ) -> dict[str, Any]:
        """What the check found, kept on the model's card (ADR-0073 decision 10)."""
        card = self.get_model(tenant, user, item)["card"]
        card["evaluation"] = evaluation
        n = self._exec(
            "UPDATE models SET card = ? WHERE id = ? AND tenant_id = ? AND user_id = ?",
            (json.dumps(card), item, tenant, user),
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

    # ---- writing sets: examples of how a person writes (ADR-0074) -----------------------------

    def add_writing_set(self, tenant: str, user: str, name: str) -> dict[str, Any]:
        item = new_id()
        self._exec(
            "INSERT INTO writing_sets(id, tenant_id, user_id, name, created_at) VALUES (?,?,?,?,?)",
            (item, tenant, user, name.strip()[:60], now()),
        )
        return self.get_writing_set(tenant, user, item)

    def get_writing_set(self, tenant: str, user: str, item: str) -> dict[str, Any]:
        row = self._one(
            "SELECT * FROM writing_sets WHERE id = ? AND tenant_id = ? AND user_id = ?",
            (item, tenant, user),
        )
        if row is None:
            raise NotFound(item)
        return dict(row)

    def list_writing_sets(self, tenant: str, user: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._all(
            "SELECT * FROM writing_sets WHERE tenant_id = ? AND user_id = ? ORDER BY created_at DESC LIMIT ?",
            (tenant, user, limit),
        )
        return [dict(r) for r in rows]

    def update_writing_set(
        self, tenant: str, user: str, item: str, **fields: str
    ) -> dict[str, Any]:
        sets = {k: v for k, v in fields.items() if k in {"name", "quality", "base"}}
        if "quality" in sets and sets["quality"] not in QUALITIES:
            raise ValueError("quality")
        if "name" in sets:
            sets["name"] = sets["name"].strip()[:60]
        if sets:
            cols = ", ".join(f"{k} = ?" for k in sets)
            n = self._exec(
                f"UPDATE writing_sets SET {cols} WHERE id = ? AND tenant_id = ? AND user_id = ?",
                (*sets.values(), item, tenant, user),
            )
            if n == 0:
                raise NotFound(item)
        return self.get_writing_set(tenant, user, item)

    def delete_writing_set(self, tenant: str, user: str, item: str) -> bool:
        n = self._exec(
            "DELETE FROM writing_sets WHERE id = ? AND tenant_id = ? AND user_id = ?",
            (item, tenant, user),
        )
        if n:
            self._exec("DELETE FROM examples WHERE set_id = ?", (item,))
        return n > 0

    def set_examples(self, tenant: str, user: str, item: str, rows: list[dict[str, str]]) -> int:
        """Replace the examples of a set with `rows` (`ask` and `answer`), in order."""
        self.get_writing_set(tenant, user, item)  # the owner's, or NotFound
        self._replace_rows(
            "DELETE FROM examples WHERE set_id = ?",
            (item,),
            "INSERT INTO examples(id, set_id, tenant_id, user_id, position, ask, answer) VALUES (?,?,?,?,?,?,?)",
            [(new_id(), item, tenant, user, n, r["ask"], r["answer"]) for n, r in enumerate(rows)],
        )
        return len(rows)

    def list_examples(self, tenant: str, user: str, item: str) -> list[dict[str, str]]:
        rows = self._all(
            "SELECT ask, answer FROM examples WHERE set_id = ? AND tenant_id = ? AND user_id = ? ORDER BY position",
            (item, tenant, user),
        )
        return [{"ask": r["ask"], "answer": r["answer"]} for r in rows]

    # ---- decision sets: texts with the right answers to one question (ADR-0075) -----------------

    def add_decision_set(self, tenant: str, user: str, name: str) -> dict[str, Any]:
        item = new_id()
        self._exec(
            "INSERT INTO decision_sets(id, tenant_id, user_id, name, created_at) VALUES (?,?,?,?,?)",
            (item, tenant, user, name.strip()[:60], now()),
        )
        return self.get_decision_set(tenant, user, item)

    @staticmethod
    def _decision_set(row: Any) -> dict[str, Any]:
        out = dict(row)
        out["options"] = json.loads(out["options"] or "[]")
        return out

    def get_decision_set(self, tenant: str, user: str, item: str) -> dict[str, Any]:
        row = self._one(
            "SELECT * FROM decision_sets WHERE id = ? AND tenant_id = ? AND user_id = ?",
            (item, tenant, user),
        )
        if row is None:
            raise NotFound(item)
        return self._decision_set(row)

    def list_decision_sets(self, tenant: str, user: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._all(
            "SELECT * FROM decision_sets WHERE tenant_id = ? AND user_id = ? ORDER BY created_at DESC LIMIT ?",
            (tenant, user, limit),
        )
        return [self._decision_set(r) for r in rows]

    def update_decision_set(
        self, tenant: str, user: str, item: str, **fields: Any
    ) -> dict[str, Any]:
        keys = {
            "name",
            "kind",
            "question",
            "options",
            "levels",
            "low",
            "high",
            "quality",
            "base",
        }
        sets = {k: v for k, v in fields.items() if k in keys}
        if "quality" in sets and sets["quality"] not in QUALITIES:
            raise ValueError("quality")
        if "kind" in sets and sets["kind"] not in DECISION_KINDS:
            raise ValueError("kind")
        for k, limit in (("name", 60), ("question", 300), ("low", 200), ("high", 200)):
            if k in sets:
                sets[k] = str(sets[k]).strip()[:limit]
        if "options" in sets:
            sets["options"] = json.dumps(
                [
                    {
                        "label": str(o.get("label", "")).strip()[:60],
                        "about": str(o.get("about", "")).strip()[:200],
                    }
                    for o in sets["options"]
                ][:30]
            )
        if sets:
            cols = ", ".join(f"{k} = ?" for k in sets)
            n = self._exec(
                f"UPDATE decision_sets SET {cols} WHERE id = ? AND tenant_id = ? AND user_id = ?",
                (*sets.values(), item, tenant, user),
            )
            if n == 0:
                raise NotFound(item)
        return self.get_decision_set(tenant, user, item)

    def delete_decision_set(self, tenant: str, user: str, item: str) -> bool:
        n = self._exec(
            "DELETE FROM decision_sets WHERE id = ? AND tenant_id = ? AND user_id = ?",
            (item, tenant, user),
        )
        if n:
            self._exec("DELETE FROM decision_examples WHERE set_id = ?", (item,))
        return n > 0

    def set_decision_examples(
        self, tenant: str, user: str, item: str, rows: list[dict[str, str]]
    ) -> int:
        """Replace the examples of a set with `rows` (`text` and `answer`), in order."""
        self.get_decision_set(tenant, user, item)  # the owner's, or NotFound
        self._replace_rows(
            "DELETE FROM decision_examples WHERE set_id = ?",
            (item,),
            "INSERT INTO decision_examples(id, set_id, tenant_id, user_id, position, text, answer) VALUES (?,?,?,?,?,?,?)",
            [(new_id(), item, tenant, user, n, r["text"], r["answer"]) for n, r in enumerate(rows)],
        )
        return len(rows)

    def list_decision_examples(self, tenant: str, user: str, item: str) -> list[dict[str, str]]:
        rows = self._all(
            "SELECT text, answer FROM decision_examples WHERE set_id = ? AND tenant_id = ? AND user_id = ? ORDER BY position",
            (item, tenant, user),
        )
        return [{"text": r["text"], "answer": r["answer"]} for r in rows]
