"""What Motion graphics keeps (`builder.db`, in `<app data>/video-builder/`): the compositions (a
title, a template and the words and settings that fill it) and one row for each render that was
started.

The files of a composition are in a folder next to this database (`projects.py`); what a render
makes is a clip in the video product's table (`mode = "composition"`), linked here by `video_id`."""

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2
KEEP_VERSIONS = 20  # earlier versions of a composition that can be brought back

_VERSIONS = """
CREATE TABLE versions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, composition_id TEXT NOT NULL, title TEXT NOT NULL,
  slots TEXT NOT NULL, saved_at TEXT NOT NULL);
CREATE INDEX versions_composition ON versions(composition_id, id DESC);
"""
_SCHEMA = (
    """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE compositions(
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
  title TEXT NOT NULL, template TEXT NOT NULL, slots TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX compositions_owner ON compositions(tenant_id, user_id, updated_at DESC);
CREATE TABLE renders(
  id TEXT PRIMARY KEY, composition_id TEXT NOT NULL, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('working', 'done', 'failed', 'cancelled')),
  video_id TEXT, error TEXT, progress REAL NOT NULL DEFAULT 0, settings TEXT NOT NULL DEFAULT '{}',
  elapsed_s REAL, peak_mb INTEGER, blocked INTEGER NOT NULL DEFAULT 0,
  started_at TEXT NOT NULL, finished_at TEXT, check_report TEXT);
CREATE INDEX renders_composition ON renders(composition_id, started_at DESC);
"""
    + _VERSIONS
)
# what version 2 adds to a version 1 file: the exact-text check's report, and earlier versions
_V2_UPGRADE = "ALTER TABLE renders ADD COLUMN check_report TEXT;" + _VERSIONS

LEFT_RUNNING = "The app was closed while this video was being made."


class NotFound(Exception):
    pass


class NothingToUndo(Exception):
    pass


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def new_id() -> str:
    return uuid.uuid4().hex


class BuilderStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.path = self.root / "builder.db"
        self.root.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            have = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='meta'"
            ).fetchone()
            if have is None:
                db.executescript("BEGIN;" + _SCHEMA + "COMMIT;")
                db.execute("INSERT INTO meta VALUES ('schema', ?)", (str(SCHEMA_VERSION),))
            else:
                row = db.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
                version = int(row[0])
                if version > SCHEMA_VERSION:
                    raise RuntimeError("builder.db was made by a newer version of this app")
                if version == 1:
                    db.executescript("BEGIN;" + _V2_UPGRADE + "COMMIT;")
                    db.execute(
                        "UPDATE meta SET value = ? WHERE key = 'schema'", (str(SCHEMA_VERSION),)
                    )
            # a render that was still working belongs to a process that is gone
            db.execute(
                "UPDATE renders SET status = 'failed', error = ?, finished_at = ? "
                "WHERE status = 'working'",
                (LEFT_RUNNING, now()),
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    @staticmethod
    def _composition(r: sqlite3.Row) -> dict[str, Any]:
        out = dict(r)
        out["slots"] = json.loads(out["slots"])
        return out

    # ---- compositions -------------------------------------------------------------------------

    def add_composition(
        self, tenant: str, user: str, *, title: str, template: str, slots: dict[str, Any]
    ) -> dict[str, Any]:
        cid, stamp = new_id(), now()
        with self._connect() as db:
            db.execute(
                "INSERT INTO compositions VALUES (?,?,?,?,?,?,?,?)",
                (cid, tenant, user, title, template, json.dumps(slots), stamp, stamp),
            )
        return self.get_composition(tenant, user, cid)

    def get_composition(self, tenant: str, user: str, cid: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM compositions WHERE id=? AND tenant_id=? AND user_id=?",
                (cid, tenant, user),
            ).fetchone()
        if row is None:
            raise NotFound(cid)
        return self._composition(row)

    def list_compositions(
        self, tenant: str, user: str, ids: list[str] | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self._connect() as db:
            if ids is not None:
                marks = ",".join("?" * len(ids))
                rows = db.execute(
                    "SELECT * FROM compositions WHERE tenant_id=? AND user_id=? "
                    f"AND id IN ({marks})",
                    (tenant, user, *ids),
                ).fetchall()
                by_id = {r["id"]: r for r in rows}
                return [self._composition(by_id[i]) for i in ids if i in by_id]
            rows = db.execute(
                "SELECT * FROM compositions WHERE tenant_id=? AND user_id=? "
                "ORDER BY updated_at DESC LIMIT ?",
                (tenant, user, limit),
            ).fetchall()
        return [self._composition(r) for r in rows]

    def update_composition(
        self, tenant: str, user: str, cid: str, *, title: str, slots: dict[str, Any]
    ) -> dict[str, Any]:
        before = self.get_composition(tenant, user, cid)
        with self._connect() as db:
            if before["slots"] != slots:  # a change that changes nothing is not a version
                db.execute(
                    "INSERT INTO versions(composition_id, title, slots, saved_at) VALUES (?,?,?,?)",
                    (cid, before["title"], json.dumps(before["slots"]), now()),
                )
                db.execute(
                    "DELETE FROM versions WHERE composition_id=? AND id NOT IN "
                    "(SELECT id FROM versions WHERE composition_id=? ORDER BY id DESC LIMIT ?)",
                    (cid, cid, KEEP_VERSIONS),
                )
            db.execute(
                "UPDATE compositions SET title=?, slots=?, updated_at=? "
                "WHERE id=? AND tenant_id=? AND user_id=?",
                (title, json.dumps(slots), now(), cid, tenant, user),
            )
        return self.get_composition(tenant, user, cid)

    def version_count(self, cid: str) -> int:
        with self._connect() as db:
            row = db.execute(
                "SELECT count(*) AS n FROM versions WHERE composition_id=?", (cid,)
            ).fetchone()
        return int(row["n"])

    def undo_composition(self, tenant: str, user: str, cid: str) -> dict[str, Any]:
        """Bring back the version before this one (the current one is not kept)."""
        self.get_composition(tenant, user, cid)
        with self._connect() as db:
            row = db.execute(
                "SELECT id, title, slots FROM versions WHERE composition_id=? "
                "ORDER BY id DESC LIMIT 1",
                (cid,),
            ).fetchone()
            if row is None:
                raise NothingToUndo(cid)
            db.execute("DELETE FROM versions WHERE id=?", (row["id"],))
            db.execute(
                "UPDATE compositions SET title=?, slots=?, updated_at=? WHERE id=?",
                (row["title"], row["slots"], now(), cid),
            )
        return self.get_composition(tenant, user, cid)

    def delete_composition(self, tenant: str, user: str, cid: str) -> list[dict[str, Any]]:
        """Remove the composition and its render rows; the renders (rows of the video product) that
        were made from it are returned, so the caller can delete those clips too."""
        found = self.get_composition(tenant, user, cid)  # NotFound if it is not this person's
        renders = self.list_renders(tenant, user, found["id"])
        with self._connect() as db:
            db.execute("DELETE FROM renders WHERE composition_id=?", (cid,))
            db.execute("DELETE FROM versions WHERE composition_id=?", (cid,))
            db.execute("DELETE FROM compositions WHERE id=?", (cid,))
        return renders

    # ---- renders ------------------------------------------------------------------------------

    def add_render(
        self, tenant: str, user: str, cid: str, settings: dict[str, Any]
    ) -> dict[str, Any]:
        rid = new_id()
        with self._connect() as db:
            db.execute(
                "INSERT INTO renders(id, composition_id, tenant_id, user_id, status, settings, "
                "started_at) VALUES (?,?,?,?,'working',?,?)",
                (rid, cid, tenant, user, json.dumps(settings), now()),
            )
        return self.get_render(tenant, user, rid)

    def get_render(self, tenant: str, user: str, rid: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM renders WHERE id=? AND tenant_id=? AND user_id=?",
                (rid, tenant, user),
            ).fetchone()
        if row is None:
            raise NotFound(rid)
        out = dict(row)
        out["settings"] = json.loads(out["settings"])
        report = out.pop("check_report", None)
        out["check"] = json.loads(report) if report else None
        return out

    def list_renders(self, tenant: str, user: str, cid: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT id FROM renders WHERE composition_id=? AND tenant_id=? AND user_id=? "
                "ORDER BY started_at DESC",
                (cid, tenant, user),
            ).fetchall()
        return [self.get_render(tenant, user, r["id"]) for r in rows]

    def working_renders(self) -> list[dict[str, Any]]:
        """Renders being made now, for any person: what a restarted service picks up again."""
        with self._connect() as db:
            rows = db.execute("SELECT id, tenant_id, user_id FROM renders WHERE status='working'")
            ids = [(r["tenant_id"], r["user_id"], r["id"]) for r in rows.fetchall()]
        return [self.get_render(*one) for one in ids]

    def set_check(self, rid: str, report: dict[str, Any]) -> None:
        with self._connect() as db:
            db.execute("UPDATE renders SET check_report=? WHERE id=?", (json.dumps(report), rid))

    def set_progress(self, rid: str, progress: float) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE renders SET progress=? WHERE id=? AND status='working'",
                (max(0.0, min(1.0, progress)), rid),
            )

    def finish_render(
        self, rid: str, status: str, *, video_id: str | None = None, error: str | None = None,
        elapsed_s: float | None = None, peak_mb: int | None = None, blocked: int = 0,
    ) -> None:  # fmt: skip
        with self._connect() as db:
            db.execute(
                "UPDATE renders SET status=?, video_id=?, error=?, elapsed_s=?, peak_mb=?, "
                "blocked=?, finished_at=?, progress=CASE WHEN ?='done' THEN 1 ELSE progress END "
                "WHERE id=? AND status='working'",
                (status, video_id, error, elapsed_s, peak_mb, blocked, now(), status, rid),
            )
