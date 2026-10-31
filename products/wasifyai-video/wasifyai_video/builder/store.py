"""What Motion graphics keeps (`builder.db`, in `<app data>/video-builder/`): the compositions (a
title, a template and the words and settings that fill it) and one row for each render that was
started.

The files of a composition are in a folder next to this database (`projects.py`); what a render
makes is a clip in the video product's table (`mode = "composition"`), linked here by `video_id`."""

import json
import secrets
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk.sqlstore import PostgresStoreDb, SqliteStoreDb, StoreDb, ddl_for

SCHEMA_VERSION = 5
KEEP_VERSIONS = 20  # earlier versions of a composition that can be brought back

_VERSIONS = """
CREATE TABLE versions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, composition_id TEXT NOT NULL, title TEXT NOT NULL,
  slots TEXT NOT NULL, saved_at TEXT NOT NULL, template TEXT);
CREATE INDEX versions_composition ON versions(composition_id, id DESC);
"""
_SCHEMA = (
    """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE compositions(
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
  title TEXT NOT NULL, template TEXT NOT NULL, slots TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, conversation_id TEXT);
CREATE INDEX compositions_owner ON compositions(tenant_id, user_id, updated_at DESC);
CREATE TABLE renders(
  id TEXT PRIMARY KEY, composition_id TEXT NOT NULL, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('working', 'done', 'failed', 'cancelled')),
  video_id TEXT, error TEXT, progress DOUBLE PRECISION NOT NULL DEFAULT 0,
  settings TEXT NOT NULL DEFAULT '{}',
  elapsed_s DOUBLE PRECISION, peak_mb INTEGER, blocked INTEGER NOT NULL DEFAULT 0,
  started_at TEXT NOT NULL, finished_at TEXT, check_report TEXT);
CREATE INDEX renders_composition ON renders(composition_id, started_at DESC);
CREATE TABLE brand_kits(
  tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, kit TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, user_id));
"""
    + _VERSIONS
)
# what version 2 adds to a version 1 file: the exact-text check's report, and earlier versions
_V2_UPGRADE = "ALTER TABLE renders ADD COLUMN check_report TEXT;" + _VERSIONS
# what version 3 adds to a version 2 file: a change can turn a template's project into scenes, so a
# version says which template its slots are for (ADR-0096)
_V3_UPGRADE = """
ALTER TABLE versions ADD COLUMN template TEXT;
UPDATE versions SET template =
  (SELECT template FROM compositions c WHERE c.id = versions.composition_id);
"""
# what version 4 adds: the chat with the editor's assistant, one for each project (ADR-0096)
_V4_UPGRADE = "ALTER TABLE compositions ADD COLUMN conversation_id TEXT;"
# what version 5 adds: a person's brand kit, used in all their projects (ADR-0096 MX7)
_V5_UPGRADE = """
CREATE TABLE brand_kits(
  tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, kit TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, user_id));
"""

LEFT_RUNNING = "The app was closed while this video was being made."


class NotFound(Exception):
    pass


class NothingToUndo(Exception):
    pass


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def new_id() -> str:
    return uuid.uuid4().hex


LOCK_KEY = 0x62646C72  # "bdlr": the advisory lock that serialises schema creation on Postgres


class BuilderStore:
    """One store class on either database (stage J2: `wasifyai_platform_sdk.sqlstore`): the
    desktop's `builder.db`, or the web's own Postgres schema (`builder`)."""

    def __init__(self, db: StoreDb, root: Path):
        """`root` is where a composition's files are on the desktop (`projects.py`); the web keeps
        none, so it is a temporary folder there."""
        self.db = db
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            self._init_postgres() if db.dialect == "postgres" else self._init_sqlite()
        except BaseException:
            db.close()
            raise

    @classmethod
    def in_folder(cls, root: Path) -> "BuilderStore":
        """The desktop's `builder.db` under `root`. A render that was still working belongs to a
        process that is gone, so it is failed in words."""
        root = Path(root)
        store = cls(SqliteStoreDb(root / "builder.db", shared=False), root)
        with store._connect() as db:
            db.execute(
                "UPDATE renders SET status = 'failed', error = ?, finished_at = ? "
                "WHERE status = 'working'",
                (LEFT_RUNNING, now()),
            )
        return store

    @classmethod
    def on_postgres(
        cls, dsn: str, *, schema: str = "builder", max_connections: int = 8
    ) -> "BuilderStore":
        """The web's store, in its own schema of the deployment's Postgres."""
        db = PostgresStoreDb(dsn, schema, max_connections=max_connections)
        return cls(db, Path(tempfile.gettempdir()))

    @property
    def path(self) -> Path | None:
        return getattr(self.db, "path", None)

    @property
    def schema(self) -> str:
        return str(getattr(self.db, "schema", ""))

    def close(self) -> None:
        self.db.close()

    def drop_schema(self) -> None:
        """Remove every table of this store (tests)."""
        drop = getattr(self.db, "drop", None)
        if drop is not None:
            drop()

    def _init_sqlite(self) -> None:
        with self._connect() as db:
            have = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='meta'"
            ).fetchone()
            if have is None:
                db.executescript("BEGIN;" + _SCHEMA + "COMMIT;")
                db.execute("INSERT INTO meta VALUES ('schema', ?)", (str(SCHEMA_VERSION),))
                return
            row = db.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
            version = int(row[0])
            if version > SCHEMA_VERSION:
                raise RuntimeError("builder.db was made by a newer version of this app")
            if version == 1:
                db.executescript("BEGIN;" + _V2_UPGRADE + "COMMIT;")
            elif version == 2:
                db.executescript("BEGIN;" + _V3_UPGRADE + "COMMIT;")
            if version < 4:
                db.executescript("BEGIN;" + _V4_UPGRADE + "COMMIT;")
            if version < 5:
                db.executescript("BEGIN;" + _V5_UPGRADE + "COMMIT;")
            if version < SCHEMA_VERSION:
                db.execute("UPDATE meta SET value = ? WHERE key = 'schema'", (str(SCHEMA_VERSION),))

    def _init_postgres(self) -> None:
        with self.db.transaction() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(?)", (LOCK_KEY,))
            conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
            fresh = (
                conn.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = ? AND table_name = 'meta'",
                    (self.schema,),
                ).fetchone()
                is None
            )
            if fresh:
                for statement in ddl_for(_SCHEMA, "postgres").split(";"):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute("INSERT INTO meta VALUES ('schema', ?)", (str(SCHEMA_VERSION),))
                return
            row = conn.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
            if not row or int(row["value"]) > SCHEMA_VERSION:
                raise RuntimeError(
                    "the Motion graphics tables were made by a newer version of this app"
                )
            version = int(row["value"])
            upgrades = (_V3_UPGRADE if version == 2 else "") + (_V4_UPGRADE if version < 4 else "")
            upgrades += _V5_UPGRADE if version < 5 else ""
            for statement in upgrades.split(";"):
                if statement.strip():
                    conn.execute(statement)
            if version < SCHEMA_VERSION:
                conn.execute(
                    "UPDATE meta SET value = ? WHERE key = 'schema'", (str(SCHEMA_VERSION),)
                )

    def live_key(self) -> str:
        """The key that signs a preview's address (`live.py`): one for this store, so every copy of
        the service on the web accepts what another signed."""
        with self._connect() as db:
            db.execute(
                "INSERT INTO meta VALUES ('live_key', ?) ON CONFLICT (key) DO NOTHING",
                (secrets.token_hex(32),),
            )
            row = db.execute("SELECT value FROM meta WHERE key = 'live_key'").fetchone()
        return str(row["value"])

    def owned_composition(self, cid: str) -> dict[str, Any] | None:
        """A composition by its id alone: only for a signed preview address, which names no owner
        (the address was signed for the owner, and holds no more than fits in a path segment)."""
        with self._connect() as db:
            row = db.execute("SELECT * FROM compositions WHERE id=?", (cid,)).fetchone()
        return self._composition(row) if row is not None else None

    def fail_stale(self, before: str, message: str) -> int:
        """Fail renders still working since before `before`: nobody is working on them (a service
        that restarted)."""
        with self._connect() as db:
            return int(
                db.execute(
                    "UPDATE renders SET status = 'failed', error = ?, finished_at = ? "
                    "WHERE status = 'working' AND started_at < ?",
                    (message, now(), before),
                ).rowcount
            )

    @contextmanager
    def _connect(self) -> Iterator[Any]:
        with self.db.connect() as db:
            yield db

    @staticmethod
    def _composition(r: Any) -> dict[str, Any]:
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
                "INSERT INTO compositions(id, tenant_id, user_id, title, template, slots, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
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
        self, tenant: str, user: str, cid: str, *, title: str, slots: dict[str, Any],
        template: str | None = None,
    ) -> dict[str, Any]:  # fmt: skip
        """Change a composition; the one before it is kept as a version. `template` turns a
        template's project into a project of scenes (ADR-0096); Undo turns it back."""
        before = self.get_composition(tenant, user, cid)
        with self._connect() as db:
            if before["slots"] != slots:  # a change that changes nothing is not a version
                db.execute(
                    "INSERT INTO versions(composition_id, title, slots, saved_at, template) "
                    "VALUES (?,?,?,?,?)",
                    (cid, before["title"], json.dumps(before["slots"]), now(), before["template"]),
                )
                db.execute(
                    "DELETE FROM versions WHERE composition_id=? AND id NOT IN "
                    "(SELECT id FROM versions WHERE composition_id=? ORDER BY id DESC LIMIT ?)",
                    (cid, cid, KEEP_VERSIONS),
                )
            db.execute(
                "UPDATE compositions SET title=?, template=?, slots=?, updated_at=? "
                "WHERE id=? AND tenant_id=? AND user_id=?",
                (
                    title,
                    template or before["template"],
                    json.dumps(slots),
                    now(),
                    cid,
                    tenant,
                    user,
                ),
            )
        return self.get_composition(tenant, user, cid)

    def set_assets(
        self, tenant: str, user: str, cid: str, assets: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """The files of a project of scenes. Adding one is not a change Undo takes back: the file
        stays with the project, whichever version of the scenes is on the screen."""
        found = self.get_composition(tenant, user, cid)
        slots = {**found["slots"], "assets": assets}
        with self._connect() as db:
            db.execute(
                "UPDATE compositions SET slots=?, updated_at=? WHERE id=?",
                (json.dumps(slots), now(), cid),
            )
        return self.get_composition(tenant, user, cid)

    def begin_with(self, tenant: str, user: str, cid: str, slots: dict[str, Any]) -> dict[str, Any]:
        """How a new project begins, set before anything was done to it: no step for Undo."""
        self.get_composition(tenant, user, cid)
        with self._connect() as db:
            db.execute(
                "UPDATE compositions SET slots=?, updated_at=? WHERE id=?",
                (json.dumps(slots), now(), cid),
            )
        return self.get_composition(tenant, user, cid)

    # ---- the brand kit -----------------------------------------------------------------------

    def get_brand(self, tenant: str, user: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT kit FROM brand_kits WHERE tenant_id=? AND user_id=?", (tenant, user)
            ).fetchone()
        return json.loads(row["kit"]) if row else None

    def set_brand(self, tenant: str, user: str, kit: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as db:
            db.execute(
                "INSERT INTO brand_kits(tenant_id, user_id, kit, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (tenant_id, user_id) DO UPDATE "
                "SET kit = excluded.kit, updated_at = excluded.updated_at",
                (tenant, user, json.dumps(kit), now()),
            )
        return kit

    def set_conversation(self, tenant: str, user: str, cid: str, conversation: str) -> None:
        """The chat that belongs to this project, found again when it is opened."""
        self.get_composition(tenant, user, cid)
        with self._connect() as db:
            db.execute("UPDATE compositions SET conversation_id=? WHERE id=?", (conversation, cid))

    def version_count(self, cid: str) -> int:
        with self._connect() as db:
            row = db.execute(
                "SELECT count(*) AS n FROM versions WHERE composition_id=?", (cid,)
            ).fetchone()
        return int(row["n"])

    def undo_composition(self, tenant: str, user: str, cid: str) -> dict[str, Any]:
        """Bring back the version before this one (the current one is not kept)."""
        current = self.get_composition(tenant, user, cid)
        with self._connect() as db:
            row = db.execute(
                "SELECT id, title, slots, template FROM versions WHERE composition_id=? "
                "ORDER BY id DESC LIMIT 1",
                (cid,),
            ).fetchone()
            if row is None:
                raise NothingToUndo(cid)
            db.execute("DELETE FROM versions WHERE id=?", (row["id"],))
            slots = json.loads(row["slots"])
            if "assets" in current["slots"] and "scenes" in slots:
                slots["assets"] = current["slots"]["assets"]  # the files are today's
            db.execute(
                "UPDATE compositions SET title=?, template=?, slots=?, updated_at=? WHERE id=?",
                (
                    row["title"],
                    row["template"] or current["template"],
                    json.dumps(slots),
                    now(),
                    cid,
                ),
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

    def get_status(self, rid: str) -> str | None:
        with self._connect() as db:
            row = db.execute("SELECT status FROM renders WHERE id=?", (rid,)).fetchone()
        return row["status"] if row else None

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
