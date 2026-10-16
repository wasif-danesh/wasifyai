# SPDX-License-Identifier: Apache-2.0
"""The notebooks database: one SQLite file (`notebooks.db`) with FTS5 and sqlite-vec (ADR-0065
decision 5). Notebooks, folders, documents and their passages with a keyword index and a vector
index. Synchronous: the engine calls it from a thread.

Ownership (rule 7, ADR-0030): a notebook belongs to a tenant and a user, and every read or write of
a notebook or what is in it is scoped by both. Another person's notebook is simply not found.
"""

import json
import sqlite3
import unicodedata
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlite_vec

from wasifyai_notebooks.chunking import Passage
from wasifyai_notebooks.tokenizer import TOKENIZER

SCHEMA_VERSION = 4
MAX_FOLDER_DEPTH = 8

PENDING, PROCESSING, READY, FAILED, CANCELLED = (
    "pending",
    "processing",
    "ready",
    "failed",
    "cancelled",
)
INTERACTIVE, BULK = 100, 10  # priority: a note written during a long folder copy is read first


class NotFound(Exception):
    pass


class Conflict(Exception):
    """The request is valid but the state does not allow it; `str(e)` is safe to show."""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def new_id() -> str:
    return uuid.uuid4().hex


def name_key(name: str) -> str:
    """NFC and case-folded in Python: SQLite's NOCASE folds ASCII only."""
    return unicodedata.normalize("NFC", name).casefold()


_SCHEMA = f"""
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE notebooks(
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, title TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, opened_at TEXT);
CREATE INDEX notebooks_owner ON notebooks(tenant_id, user_id, updated_at);

CREATE TABLE folders(
  id TEXT PRIMARY KEY,
  notebook_id TEXT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
  parent_id TEXT REFERENCES folders(id) ON DELETE CASCADE,
  name TEXT NOT NULL, name_key TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE UNIQUE INDEX folders_name ON folders(notebook_id, COALESCE(parent_id, ''), name_key);

CREATE TABLE documents(
  id TEXT PRIMARY KEY,
  notebook_id TEXT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
  folder_id TEXT REFERENCES folders(id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('file', 'note')),
  status TEXT NOT NULL,
  error TEXT,
  priority INTEGER NOT NULL DEFAULT {INTERACTIVE},
  mime TEXT, suffix TEXT, size_bytes INTEGER, sha256 TEXT, pages INTEGER,
  content TEXT,
  embedder TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE UNIQUE INDEX documents_dedup
  ON documents(notebook_id, COALESCE(folder_id, ''), sha256) WHERE sha256 IS NOT NULL;
CREATE INDEX documents_notebook ON documents(notebook_id, created_at);
CREATE INDEX documents_queue ON documents(status, priority DESC, created_at);

CREATE TABLE chunks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  position INTEGER NOT NULL, content TEXT NOT NULL, start_line INTEGER, end_line INTEGER,
  UNIQUE(document_id, position));

CREATE VIRTUAL TABLE chunks_fts USING fts5(
  content, content='chunks', content_rowid='id', tokenize="{TOKENIZER}");
CREATE TRIGGER chunks_ai AFTER INSERT ON chunks BEGIN
  INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER chunks_au AFTER UPDATE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES ('delete', old.id, old.content);
  INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
END;
"""


_CHAT_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations(
  id TEXT PRIMARY KEY,
  notebook_id TEXT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
  title TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS conversations_notebook ON conversations(notebook_id, updated_at);
CREATE TABLE IF NOT EXISTS messages(
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  text TEXT NOT NULL,
  citations TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  UNIQUE(conversation_id, seq));
"""


_STUDIO_SCHEMA = """
CREATE TABLE IF NOT EXISTS artifacts(
  id TEXT PRIMARY KEY,
  notebook_id TEXT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
  format TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  error TEXT,
  prompt TEXT NOT NULL DEFAULT '',
  source_ids TEXT NOT NULL DEFAULT '[]',
  body TEXT,
  data TEXT,
  file_name TEXT,
  file_mime TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS artifacts_notebook ON artifacts(notebook_id, created_at);
"""


_GUIDE_COLUMNS = ("guide", "guide_key")  # added to `notebooks` in schema 4


class NotebookStore:
    def __init__(self, root: Path, *, dimension: int, embedder_id: str):
        """`root` holds `notebooks.db`; `dimension` and `embedder_id` are what the index was built
        with. An index built with another embedder is refused, not mixed (ADR-0065 decision 8)."""
        self.root = Path(root)
        self.path = self.root / "notebooks.db"
        self.dimension = dimension
        self.embedder_id = embedder_id
        self.root.mkdir(parents=True, exist_ok=True)
        self._init()

    # ---- connection -------------------------------------------------------------------------

    def _open(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA journal_mode = WAL")
        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.enable_load_extension(False)
        return db

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = self._open()
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")

    def _init(self) -> None:
        with self.connect() as db:
            have = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='meta'"
            ).fetchone()
            if have is None:
                # executescript is its own transaction; BEGIN/COMMIT make the schema all or nothing
                db.executescript(
                    "BEGIN;"
                    + _SCHEMA
                    + _CHAT_SCHEMA
                    + _STUDIO_SCHEMA
                    + "CREATE VIRTUAL TABLE chunk_vectors USING vec0("
                    + f"embedding float[{self.dimension}]);"
                    "CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN "
                    "INSERT INTO chunks_fts(chunks_fts, rowid, content) "
                    "VALUES ('delete', old.id, old.content);"
                    "DELETE FROM chunk_vectors WHERE rowid = old.id; END;"
                    "COMMIT;"
                )
                self._add_guide_columns(db)
                db.execute(
                    "INSERT INTO meta(key, value) "
                    "VALUES ('schema', ?), ('embedder', ?), ('dimension', ?)",
                    (str(SCHEMA_VERSION), self.embedder_id, str(self.dimension)),
                )
                return
            meta = dict(db.execute("SELECT key, value FROM meta").fetchall())
            self._add_guide_columns(db)
            if meta.get("schema") != str(SCHEMA_VERSION):
                # a file made by an earlier version: add what is new, then record the version
                db.executescript("BEGIN;" + _CHAT_SCHEMA + _STUDIO_SCHEMA + "COMMIT;")
                db.execute("UPDATE meta SET value = ? WHERE key = 'schema'", (str(SCHEMA_VERSION),))
        if meta.get("embedder") != self.embedder_id or meta.get("dimension") != str(self.dimension):
            raise Conflict(
                f"This library was indexed with {meta.get('embedder')}; "
                f"{self.embedder_id} needs the documents read again first."
            )

    @staticmethod
    def _add_guide_columns(db: sqlite3.Connection) -> None:
        have = {r[1] for r in db.execute("PRAGMA table_info(notebooks)")}
        for column in _GUIDE_COLUMNS:
            if column not in have:
                db.execute(f"ALTER TABLE notebooks ADD COLUMN {column} TEXT")

    # ---- notebooks --------------------------------------------------------------------------

    def create_notebook(self, tenant: str, user: str, title: str) -> dict[str, Any]:
        nid, ts = new_id(), now()
        with self._tx() as db:
            db.execute(
                "INSERT INTO notebooks(id, tenant_id, user_id, title, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?)",
                (nid, tenant, user, title, ts, ts),
            )
        return self.get_notebook(tenant, user, nid)

    def _notebook_row(self, db: sqlite3.Connection, tenant: str, user: str, nid: str) -> tuple:
        row = db.execute(
            "SELECT id, title, created_at, updated_at, opened_at FROM notebooks "
            "WHERE id = ? AND tenant_id = ? AND user_id = ?",
            (nid, tenant, user),
        ).fetchone()
        if row is None:
            raise NotFound("notebook not found")
        return row

    def _summary(self, db: sqlite3.Connection, row: tuple) -> dict[str, Any]:
        counts = dict(
            db.execute(
                "SELECT status, COUNT(*) FROM documents WHERE notebook_id = ? GROUP BY status",
                (row[0],),
            ).fetchall()
        )
        return {
            "id": row[0],
            "title": row[1],
            "created_at": row[2],
            "updated_at": row[3],
            "opened_at": row[4],
            "sources": sum(counts.values()),
            "ready": counts.get(READY, 0),
            "reading": counts.get(PENDING, 0) + counts.get(PROCESSING, 0),
            "failed": counts.get(FAILED, 0),
        }

    def get_notebook(self, tenant: str, user: str, nid: str) -> dict[str, Any]:
        with self.connect() as db:
            return self._summary(db, self._notebook_row(db, tenant, user, nid))

    def list_notebooks(self, tenant: str, user: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT id, title, created_at, updated_at, opened_at FROM notebooks "
                "WHERE tenant_id = ? AND user_id = ? "
                "ORDER BY COALESCE(opened_at, created_at) DESC, id",
                (tenant, user),
            ).fetchall()
            return [self._summary(db, r) for r in rows]

    def rename_notebook(self, tenant: str, user: str, nid: str, title: str) -> dict[str, Any]:
        with self._tx() as db:
            self._notebook_row(db, tenant, user, nid)
            db.execute(
                "UPDATE notebooks SET title = ?, updated_at = ? WHERE id = ?", (title, now(), nid)
            )
        return self.get_notebook(tenant, user, nid)

    def open_notebook(self, tenant: str, user: str, nid: str) -> dict[str, Any]:
        with self._tx() as db:
            self._notebook_row(db, tenant, user, nid)
            db.execute("UPDATE notebooks SET opened_at = ? WHERE id = ?", (now(), nid))
        return self.get_notebook(tenant, user, nid)

    def delete_notebook(self, tenant: str, user: str, nid: str) -> None:
        with self._tx() as db:
            self._notebook_row(db, tenant, user, nid)
            busy = db.execute(
                "SELECT COUNT(*) FROM documents WHERE notebook_id = ? AND status = ?",
                (nid, PROCESSING),
            ).fetchone()[0]
            if busy:
                raise Conflict("A source is being read. Stop it or wait, then delete the notebook.")
            db.execute("DELETE FROM notebooks WHERE id = ?", (nid,))

    # ---- folders ----------------------------------------------------------------------------

    def _folder_depth(self, db: sqlite3.Connection, folder_id: str | None) -> int:
        depth = 0
        while folder_id is not None:
            row = db.execute("SELECT parent_id FROM folders WHERE id = ?", (folder_id,)).fetchone()
            if row is None:
                raise NotFound("folder not found")
            depth += 1
            folder_id = row[0]
            if depth > MAX_FOLDER_DEPTH + 1:
                break
        return depth

    def _folder_in(self, db: sqlite3.Connection, nid: str, folder_id: str | None) -> None:
        if folder_id is None:
            return
        row = db.execute(
            "SELECT 1 FROM folders WHERE id = ? AND notebook_id = ?", (folder_id, nid)
        ).fetchone()
        if row is None:
            raise NotFound("folder not found")

    def create_folder(
        self, tenant: str, user: str, nid: str, name: str, parent_id: str | None = None
    ) -> dict[str, Any]:
        fid = new_id()
        with self._tx() as db:
            self._notebook_row(db, tenant, user, nid)
            self._folder_in(db, nid, parent_id)
            if self._folder_depth(db, parent_id) >= MAX_FOLDER_DEPTH:
                raise Conflict(f"Folders can go {MAX_FOLDER_DEPTH} levels deep.")
            try:
                db.execute(
                    "INSERT INTO folders(id, notebook_id, parent_id, name, name_key, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (fid, nid, parent_id, name, name_key(name), now()),
                )
            except sqlite3.IntegrityError as e:
                raise Conflict("A folder with that name is already there.") from e
        return {"id": fid, "notebook_id": nid, "parent_id": parent_id, "name": name}

    def list_folders(self, tenant: str, user: str, nid: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            self._notebook_row(db, tenant, user, nid)
            rows = db.execute(
                "SELECT id, parent_id, name FROM folders WHERE notebook_id = ? ORDER BY name_key",
                (nid,),
            ).fetchall()
        return [{"id": r[0], "notebook_id": nid, "parent_id": r[1], "name": r[2]} for r in rows]

    def rename_folder(self, tenant: str, user: str, nid: str, fid: str, name: str) -> None:
        with self._tx() as db:
            self._notebook_row(db, tenant, user, nid)
            self._folder_in(db, nid, fid)
            try:
                db.execute(
                    "UPDATE folders SET name = ?, name_key = ? WHERE id = ?",
                    (name, name_key(name), fid),
                )
            except sqlite3.IntegrityError as e:
                raise Conflict("A folder with that name is already there.") from e

    def delete_folder(self, tenant: str, user: str, nid: str, fid: str) -> list[str]:
        """Delete a folder, its subfolders and every document in them; returns their ids so the
        caller can remove the stored files."""
        with self._tx() as db:
            self._notebook_row(db, tenant, user, nid)
            self._folder_in(db, nid, fid)
            tree = [
                r[0]
                for r in db.execute(
                    "WITH RECURSIVE t(id) AS (SELECT ? UNION ALL "
                    "SELECT f.id FROM folders f JOIN t ON f.parent_id = t.id) SELECT id FROM t",
                    (fid,),
                )
            ]
            marks = ",".join("?" * len(tree))
            docs = [
                r[0]
                for r in db.execute(
                    f"SELECT id FROM documents WHERE notebook_id = ? AND folder_id IN ({marks})",
                    (nid, *tree),
                )
            ]
            if db.execute(
                f"SELECT 1 FROM documents WHERE folder_id IN ({marks}) AND status = ? LIMIT 1",
                (*tree, PROCESSING),
            ).fetchone():
                raise Conflict("A source in this folder is being read. Stop it or wait.")
            db.execute(
                f"DELETE FROM documents WHERE id IN ({','.join('?' * len(docs))})", docs
            ) if docs else None
            db.execute("DELETE FROM folders WHERE id = ?", (fid,))
        return docs

    # ---- documents --------------------------------------------------------------------------

    _DOC_COLS = (
        "id, notebook_id, folder_id, title, kind, status, error, mime, suffix, size_bytes, "
        "sha256, pages, embedder, created_at, updated_at"
    )

    @staticmethod
    def _doc(row: Sequence[Any], content: str | None = None) -> dict[str, Any]:
        keys: Sequence[str] = (
            "id notebook_id folder_id title kind status error mime suffix size_bytes "
            "sha256 pages embedder created_at updated_at"
        ).split()
        out: dict[str, Any] = dict(zip(keys, row, strict=True))
        if content is not None:
            out["content"] = content
        return out

    def add_file(
        self,
        tenant: str,
        user: str,
        nid: str,
        *,
        title: str,
        suffix: str,
        mime: str,
        size_bytes: int,
        sha256: str,
        folder_id: str | None = None,
        priority: int = INTERACTIVE,
        doc_id: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Returns the document and whether it was already there (the same bytes in the same
        folder are one document)."""
        did, ts = doc_id or new_id(), now()
        with self._tx() as db:
            self._notebook_row(db, tenant, user, nid)
            self._folder_in(db, nid, folder_id)
            dup = db.execute(
                f"SELECT {self._DOC_COLS} FROM documents "
                "WHERE notebook_id = ? AND COALESCE(folder_id, '') = ? AND sha256 = ?",
                (nid, folder_id or "", sha256),
            ).fetchone()
            if dup is not None:
                return self._doc(dup), True
            db.execute(
                "INSERT INTO documents(id, notebook_id, folder_id, title, kind, status, "
                "priority, mime, "
                "suffix, size_bytes, sha256, created_at, updated_at) "
                "VALUES (?,?,?,?, 'file', ?, ?, ?,?,?,?,?,?)",
                (
                    did,
                    nid,
                    folder_id,
                    title,
                    PENDING,
                    priority,
                    mime,
                    suffix,
                    size_bytes,
                    sha256,
                    ts,
                    ts,
                ),
            )
            db.execute("UPDATE notebooks SET updated_at = ? WHERE id = ?", (ts, nid))
        return self.get_document(tenant, user, nid, did), False

    def add_note(
        self,
        tenant: str,
        user: str,
        nid: str,
        *,
        title: str,
        content: str,
        folder_id: str | None = None,
    ) -> dict[str, Any]:
        did, ts = new_id(), now()
        with self._tx() as db:
            self._notebook_row(db, tenant, user, nid)
            self._folder_in(db, nid, folder_id)
            db.execute(
                "INSERT INTO documents(id, notebook_id, folder_id, title, kind, status, priority, "
                "content, size_bytes, created_at, updated_at) "
                "VALUES (?,?,?,?, 'note', ?, ?, ?,?,?,?)",
                (
                    did,
                    nid,
                    folder_id,
                    title,
                    PENDING,
                    INTERACTIVE,
                    content,
                    len(content.encode()),
                    ts,
                    ts,
                ),
            )
            db.execute("UPDATE notebooks SET updated_at = ? WHERE id = ?", (ts, nid))
        return self.get_document(tenant, user, nid, did)

    def list_documents(
        self,
        tenant: str,
        user: str,
        nid: str,
        *,
        statuses: Sequence[str] | None = None,
        folder_id: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = f"SELECT {self._DOC_COLS} FROM documents WHERE notebook_id = ?"
        args: list[Any] = [nid]
        if statuses:
            sql += f" AND status IN ({','.join('?' * len(statuses))})"
            args += list(statuses)
        if folder_id is not None:
            sql += " AND folder_id = ?"
            args.append(folder_id)
        with self.connect() as db:
            self._notebook_row(db, tenant, user, nid)
            rows = db.execute(sql + " ORDER BY created_at DESC, id", args).fetchall()
        return [self._doc(r) for r in rows]

    def get_document(
        self, tenant: str, user: str, nid: str, did: str, *, content: bool = False
    ) -> dict[str, Any]:
        with self.connect() as db:
            self._notebook_row(db, tenant, user, nid)
            row = db.execute(
                f"SELECT {self._DOC_COLS}, content FROM documents WHERE id = ? AND notebook_id = ?",
                (did, nid),
            ).fetchone()
        if row is None:
            raise NotFound("source not found")
        return self._doc(row[:-1], row[-1] if content else None)

    def rename_document(self, tenant: str, user: str, nid: str, did: str, title: str) -> None:
        with self._tx() as db:
            self._notebook_row(db, tenant, user, nid)
            n = db.execute(
                "UPDATE documents SET title = ?, updated_at = ? WHERE id = ? AND notebook_id = ?",
                (title, now(), did, nid),
            ).rowcount
            if not n:
                raise NotFound("source not found")

    def edit_note(self, tenant: str, user: str, nid: str, did: str, content: str) -> None:
        """A note's text changes: it goes back to pending so the index is rebuilt."""
        with self._tx() as db:
            self._notebook_row(db, tenant, user, nid)
            row = db.execute(
                "SELECT kind, status FROM documents WHERE id = ? AND notebook_id = ?", (did, nid)
            ).fetchone()
            if row is None:
                raise NotFound("source not found")
            if row[0] != "note":
                raise Conflict("Only a note can be edited.")
            db.execute(
                "UPDATE documents SET content = ?, size_bytes = ?, status = ?, error = NULL, "
                "priority = ?, updated_at = ? WHERE id = ?",
                (content, len(content.encode()), PENDING, INTERACTIVE, now(), did),
            )

    def move_documents(
        self, tenant: str, user: str, nid: str, ids: Sequence[str], folder_id: str | None
    ) -> int:
        with self._tx() as db:
            self._notebook_row(db, tenant, user, nid)
            self._folder_in(db, nid, folder_id)
            moved = 0
            for did in ids:
                try:
                    moved += db.execute(
                        "UPDATE documents SET folder_id = ?, updated_at = ? "
                        "WHERE id = ? AND notebook_id = ?",
                        (folder_id, now(), did, nid),
                    ).rowcount
                except sqlite3.IntegrityError:
                    pass  # the same bytes already sit in that folder
        return moved

    def delete_document(self, tenant: str, user: str, nid: str, did: str) -> None:
        with self._tx() as db:
            self._notebook_row(db, tenant, user, nid)
            row = db.execute(
                "SELECT status FROM documents WHERE id = ? AND notebook_id = ?", (did, nid)
            ).fetchone()
            if row is None:
                raise NotFound("source not found")
            if row[0] == PROCESSING:
                raise Conflict("This source is being read. Stop it first.")
            db.execute("DELETE FROM documents WHERE id = ?", (did,))

    def retry_document(self, tenant: str, user: str, nid: str, did: str) -> None:
        with self._tx() as db:
            self._notebook_row(db, tenant, user, nid)
            row = db.execute(
                "SELECT status FROM documents WHERE id = ? AND notebook_id = ?", (did, nid)
            ).fetchone()
            if row is None:
                raise NotFound("source not found")
            if row[0] not in (FAILED, CANCELLED):
                raise Conflict("Only a source that failed or was stopped can be read again.")
            db.execute(
                "UPDATE documents SET status = ?, error = NULL, updated_at = ? WHERE id = ?",
                (PENDING, now(), did),
            )

    def cancel_document(self, tenant: str, user: str, nid: str, did: str) -> None:
        with self._tx() as db:
            self._notebook_row(db, tenant, user, nid)
            row = db.execute(
                "SELECT status FROM documents WHERE id = ? AND notebook_id = ?", (did, nid)
            ).fetchone()
            if row is None:
                raise NotFound("source not found")
            if row[0] not in (PENDING, PROCESSING):
                raise Conflict("This source is not being read.")
            db.execute(
                "UPDATE documents SET status = ?, error = NULL, updated_at = ? WHERE id = ?",
                (CANCELLED, now(), did),
            )

    def file_documents(self, tenant: str, user: str, nid: str) -> list[str]:
        """Every document id of a notebook, for removing their stored files."""
        with self.connect() as db:
            self._notebook_row(db, tenant, user, nid)
            return [
                r[0] for r in db.execute("SELECT id FROM documents WHERE notebook_id = ?", (nid,))
            ]

    # ---- the ingest worker's side (not scoped by user: it works through the queue) -----------

    def reset_interrupted(self) -> int:
        """A source the app quit in the middle of reading is failed at start, so Retry offers it."""
        with self._tx() as db:
            n = db.execute(
                "UPDATE documents SET status = ?, error = ?, updated_at = ? WHERE status = ?",
                (FAILED, "Reading was interrupted when the app closed.", now(), PROCESSING),
            ).rowcount
            db.execute(
                "UPDATE artifacts SET status = ?, error = ?, updated_at = ? WHERE status = ?",
                (FAILED, "Making this was interrupted when the app closed.", now(), PROCESSING),
            )
        return n

    def next_pending(self) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                f"SELECT {self._DOC_COLS} FROM documents WHERE status = ? "
                "ORDER BY priority DESC, created_at LIMIT 1",
                (PENDING,),
            ).fetchone()
        return self._doc(row) if row else None

    def begin(self, did: str) -> dict[str, Any] | None:
        """pending -> processing, unless it was cancelled or deleted meanwhile."""
        with self._tx() as db:
            n = db.execute(
                "UPDATE documents SET status = ?, error = NULL, updated_at = ? "
                "WHERE id = ? AND status = ?",
                (PROCESSING, now(), did, PENDING),
            ).rowcount
            if not n:
                return None
            row = db.execute(
                f"SELECT {self._DOC_COLS}, content FROM documents WHERE id = ?", (did,)
            ).fetchone()
        return self._doc(row[:-1], row[-1])

    def is_processing(self, did: str) -> bool:
        with self.connect() as db:
            row = db.execute("SELECT status FROM documents WHERE id = ?", (did,)).fetchone()
        return row is not None and row[0] == PROCESSING

    def finish(
        self,
        did: str,
        *,
        markdown: str | None,
        pages: int | None,
        passages: Sequence[Passage],
        vectors: Sequence[Sequence[float]],
        embedder: str,
    ) -> bool:
        """Replace the document's passages and mark it ready, unless a cancel or delete won.
        A note's own text is never overwritten (`markdown` is None for it)."""
        if len(passages) != len(vectors):
            raise ValueError("a vector for every passage")
        with self._tx() as db:
            row = db.execute("SELECT status, kind FROM documents WHERE id = ?", (did,)).fetchone()
            if row is None or row[0] != PROCESSING:
                return False
            db.execute("DELETE FROM chunks WHERE document_id = ?", (did,))
            for position, (p, v) in enumerate(zip(passages, vectors, strict=True)):
                cid = db.execute(
                    "INSERT INTO chunks(document_id, position, content, start_line, end_line) "
                    "VALUES (?,?,?,?,?)",
                    (did, position, p.text, p.start_line, p.end_line),
                ).lastrowid
                db.execute(
                    "INSERT INTO chunk_vectors(rowid, embedding) VALUES (?, ?)",
                    (cid, sqlite_vec.serialize_float32(list(v))),
                )
            if markdown is not None:
                db.execute("UPDATE documents SET content = ? WHERE id = ?", (markdown, did))
            db.execute(
                "UPDATE documents SET status = ?, error = NULL, pages = ?, embedder = ?, "
                "updated_at = ? "
                "WHERE id = ?",
                (READY, pages, embedder, now(), did),
            )
        return True

    def fail(self, did: str, message: str) -> None:
        with self._tx() as db:
            db.execute(
                "UPDATE documents SET status = ?, error = ?, updated_at = ? "
                "WHERE id = ? AND status = ?",
                (FAILED, message[:500], now(), did, PROCESSING),
            )

    # ---- conversations -----------------------------------------------------------------------

    def create_conversation(
        self, tenant: str, user: str, nid: str, title: str = ""
    ) -> dict[str, Any]:
        cid, ts = new_id(), now()
        with self._tx() as db:
            self._notebook_row(db, tenant, user, nid)
            db.execute(
                "INSERT INTO conversations(id, notebook_id, title, created_at, updated_at) "
                "VALUES (?,?,?,?,?)",
                (cid, nid, title, ts, ts),
            )
        return {"id": cid, "notebook_id": nid, "title": title, "created_at": ts, "updated_at": ts}

    _CONV_KEYS = ("id", "notebook_id", "title", "created_at", "updated_at")

    def get_conversation(self, tenant: str, user: str, nid: str, cid: str) -> dict[str, Any]:
        with self.connect() as db:
            self._notebook_row(db, tenant, user, nid)
            row = db.execute(
                "SELECT id, notebook_id, title, created_at, updated_at FROM conversations "
                "WHERE id = ? AND notebook_id = ?",
                (cid, nid),
            ).fetchone()
        if row is None:
            raise NotFound("conversation not found")
        return dict(zip(self._CONV_KEYS, row, strict=True))

    def list_conversations(self, tenant: str, user: str, nid: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            self._notebook_row(db, tenant, user, nid)
            rows = db.execute(
                "SELECT id, notebook_id, title, created_at, updated_at FROM conversations "
                "WHERE notebook_id = ? ORDER BY updated_at DESC, id",
                (nid,),
            ).fetchall()
        return [dict(zip(self._CONV_KEYS, r, strict=True)) for r in rows]

    def rename_conversation(self, tenant: str, user: str, nid: str, cid: str, title: str) -> None:
        with self._tx() as db:
            self._notebook_row(db, tenant, user, nid)
            n = db.execute(
                "UPDATE conversations SET title = ? WHERE id = ? AND notebook_id = ?",
                (title, cid, nid),
            ).rowcount
            if not n:
                raise NotFound("conversation not found")

    def delete_conversation(self, tenant: str, user: str, nid: str, cid: str) -> None:
        with self._tx() as db:
            self._notebook_row(db, tenant, user, nid)
            n = db.execute(
                "DELETE FROM conversations WHERE id = ? AND notebook_id = ?", (cid, nid)
            ).rowcount
            if not n:
                raise NotFound("conversation not found")

    def add_message(
        self,
        tenant: str,
        user: str,
        nid: str,
        cid: str,
        role: str,
        text: str,
        citations: Sequence[dict[str, Any]] = (),
    ) -> dict[str, Any]:
        mid, ts = new_id(), now()
        with self._tx() as db:
            self._notebook_row(db, tenant, user, nid)
            found = db.execute(
                "SELECT 1 FROM conversations WHERE id = ? AND notebook_id = ?", (cid, nid)
            ).fetchone()
            if found is None:
                raise NotFound("conversation not found")
            seq = db.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM messages WHERE conversation_id = ?", (cid,)
            ).fetchone()[0]
            db.execute(
                "INSERT INTO messages(id, conversation_id, seq, role, text, citations, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (mid, cid, seq, role, text, json.dumps(list(citations), ensure_ascii=False), ts),
            )
            db.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (ts, cid))
        return {
            "id": mid, "seq": seq, "role": role, "text": text, "citations": list(citations),
            "created_at": ts,
        }  # fmt: skip

    def messages(self, tenant: str, user: str, nid: str, cid: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            self._notebook_row(db, tenant, user, nid)
            found = db.execute(
                "SELECT 1 FROM conversations WHERE id = ? AND notebook_id = ?", (cid, nid)
            ).fetchone()
            if found is None:
                raise NotFound("conversation not found")
            rows = db.execute(
                "SELECT id, seq, role, text, citations, created_at FROM messages "
                "WHERE conversation_id = ? ORDER BY seq",
                (cid,),
            ).fetchall()
        return [
            {
                "id": r[0], "seq": r[1], "role": r[2], "text": r[3],
                "citations": json.loads(r[4]), "created_at": r[5],
            }
            for r in rows
        ]  # fmt: skip

    def source_counts(self, tenant: str, user: str, nid: str) -> dict[str, int]:
        """How many sources are in each state: what a question can be asked of."""
        with self.connect() as db:
            self._notebook_row(db, tenant, user, nid)
            return dict(
                db.execute(
                    "SELECT status, COUNT(*) FROM documents WHERE notebook_id = ? GROUP BY status",
                    (nid,),
                ).fetchall()
            )

    # ---- the guide to a notebook ---------------------------------------------------------------

    def sources_key(self, tenant: str, user: str, nid: str) -> str:
        """Names the set of sources a guide was written from: it changes when one is added, removed
        or read again."""
        import hashlib

        with self.connect() as db:
            self._notebook_row(db, tenant, user, nid)
            rows = db.execute(
                "SELECT id, updated_at FROM documents WHERE notebook_id = ? AND status = ? "
                "ORDER BY id",
                (nid, READY),
            ).fetchall()
        return hashlib.sha256(json.dumps(rows).encode()).hexdigest()[:16] if rows else ""

    def get_guide(self, tenant: str, user: str, nid: str) -> dict[str, Any]:
        """The saved guide (or None), and whether the sources have changed since it was written."""
        key = self.sources_key(tenant, user, nid)
        with self.connect() as db:
            self._notebook_row(db, tenant, user, nid)
            row = db.execute(
                "SELECT guide, guide_key FROM notebooks WHERE id = ?", (nid,)
            ).fetchone()
        guide = json.loads(row[0]) if row and row[0] else None
        return {"guide": guide, "stale": bool(guide) and row[1] != key, "ready": bool(key)}

    def save_guide(self, tenant: str, user: str, nid: str, guide: dict[str, Any], key: str) -> None:
        with self._tx() as db:
            self._notebook_row(db, tenant, user, nid)
            db.execute(
                "UPDATE notebooks SET guide = ?, guide_key = ? WHERE id = ?",
                (json.dumps(guide, ensure_ascii=False), key, nid),
            )

    # ---- studio outputs ----------------------------------------------------------------------

    _ART_COLS = (
        "id, notebook_id, format, title, status, error, prompt, source_ids, file_name, "
        "file_mime, created_at, updated_at"
    )

    @staticmethod
    def _art(row: Sequence[Any], body: str | None = None, data: Any = None) -> dict[str, Any]:
        keys = (
            "id notebook_id format title status error prompt source_ids file_name file_mime "
            "created_at updated_at"
        ).split()
        out: dict[str, Any] = dict(zip(keys, row, strict=True))
        out["source_ids"] = json.loads(out["source_ids"] or "[]")
        out["has_file"] = bool(out["file_name"])
        if body is not None:
            out["body"] = body
        if data is not None:
            out["data"] = data
        return out

    def create_artifact(
        self,
        tenant: str,
        user: str,
        nid: str,
        *,
        fmt: str,
        prompt: str,
        source_ids: Sequence[str],
        title: str = "",
    ) -> dict[str, Any]:
        aid, ts = new_id(), now()
        with self._tx() as db:
            self._notebook_row(db, tenant, user, nid)
            db.execute(
                "INSERT INTO artifacts(id, notebook_id, format, title, status, prompt, source_ids, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (aid, nid, fmt, title, PROCESSING, prompt, json.dumps(list(source_ids)), ts, ts),
            )
            db.execute("UPDATE notebooks SET updated_at = ? WHERE id = ?", (ts, nid))
        return self.get_artifact(tenant, user, nid, aid)

    def get_artifact(
        self, tenant: str, user: str, nid: str, aid: str, *, content: bool = False
    ) -> dict[str, Any]:
        with self.connect() as db:
            self._notebook_row(db, tenant, user, nid)
            row = db.execute(
                f"SELECT {self._ART_COLS}, body, data FROM artifacts "
                "WHERE id = ? AND notebook_id = ?",
                (aid, nid),
            ).fetchone()
        if row is None:
            raise NotFound("output not found")
        data = json.loads(row[-1]) if row[-1] else None
        return self._art(row[:-2], row[-2] if content else None, data if content else None)

    def list_artifacts(self, tenant: str, user: str, nid: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            self._notebook_row(db, tenant, user, nid)
            rows = db.execute(
                f"SELECT {self._ART_COLS} FROM artifacts WHERE notebook_id = ? "
                "ORDER BY created_at DESC, id",
                (nid,),
            ).fetchall()
        return [self._art(r) for r in rows]

    def finish_artifact(
        self,
        tenant: str,
        user: str,
        nid: str,
        aid: str,
        *,
        title: str,
        body: str,
        data: dict[str, Any] | None,
        file_name: str | None,
        file_mime: str | None,
    ) -> bool:
        """processing -> ready, unless the output was deleted or stopped meanwhile."""
        with self._tx() as db:
            self._notebook_row(db, tenant, user, nid)
            n = db.execute(
                "UPDATE artifacts SET status = ?, error = NULL, title = ?, body = ?, data = ?, "
                "file_name = ?, file_mime = ?, updated_at = ? "
                "WHERE id = ? AND notebook_id = ? AND status = ?",
                (
                    READY, title, body, json.dumps(data) if data is not None else None,
                    file_name, file_mime, now(), aid, nid, PROCESSING,
                ),
            ).rowcount  # fmt: skip
        return bool(n)

    def set_artifact_data(
        self, tenant: str, user: str, nid: str, aid: str, data: dict[str, Any]
    ) -> None:
        """Replace the structured data of a ready output (the audio overview gains its voices)."""
        with self._tx() as db:
            self._notebook_row(db, tenant, user, nid)
            n = db.execute(
                "UPDATE artifacts SET data = ?, updated_at = ? WHERE id = ? AND notebook_id = ? "
                "AND status = ?",
                (json.dumps(data), now(), aid, nid, READY),
            ).rowcount
            if not n:
                raise NotFound("output not found")

    def fail_artifact(self, tenant: str, user: str, nid: str, aid: str, message: str) -> None:
        with self._tx() as db:
            self._notebook_row(db, tenant, user, nid)
            db.execute(
                "UPDATE artifacts SET status = ?, error = ?, updated_at = ? "
                "WHERE id = ? AND notebook_id = ? AND status = ?",
                (FAILED, message[:500], now(), aid, nid, PROCESSING),
            )

    def cancel_artifact(self, tenant: str, user: str, nid: str, aid: str) -> None:
        with self._tx() as db:
            self._notebook_row(db, tenant, user, nid)
            found = db.execute(
                "SELECT 1 FROM artifacts WHERE id = ? AND notebook_id = ?", (aid, nid)
            ).fetchone()
            if found is None:
                raise NotFound("output not found")
            n = db.execute(
                "UPDATE artifacts SET status = ?, error = NULL, updated_at = ? "
                "WHERE id = ? AND notebook_id = ? AND status = ?",
                (CANCELLED, now(), aid, nid, PROCESSING),
            ).rowcount
            if not n:
                raise Conflict("This output is not being made.")

    def rename_artifact(self, tenant: str, user: str, nid: str, aid: str, title: str) -> None:
        with self._tx() as db:
            self._notebook_row(db, tenant, user, nid)
            n = db.execute(
                "UPDATE artifacts SET title = ?, updated_at = ? WHERE id = ? AND notebook_id = ?",
                (title, now(), aid, nid),
            ).rowcount
            if not n:
                raise NotFound("output not found")

    def delete_artifact(self, tenant: str, user: str, nid: str, aid: str) -> None:
        with self._tx() as db:
            self._notebook_row(db, tenant, user, nid)
            n = db.execute(
                "DELETE FROM artifacts WHERE id = ? AND notebook_id = ?", (aid, nid)
            ).rowcount
            if not n:
                raise NotFound("output not found")

    def reset_interrupted_artifacts(self) -> int:
        """An output being made when the app quit is failed at start, so it can be made again."""
        with self._tx() as db:
            return db.execute(
                "UPDATE artifacts SET status = ?, error = ?, updated_at = ? WHERE status = ?",
                (FAILED, "Making this was interrupted when the app closed.", now(), PROCESSING),
            ).rowcount

    # ---- passages ---------------------------------------------------------------------------

    def get_chunk(
        self, tenant: str, user: str, nid: str, chunk_id: int, around: int = 1
    ) -> dict[str, Any]:
        """A passage and its neighbours in the same document, for opening a citation."""
        with self.connect() as db:
            self._notebook_row(db, tenant, user, nid)
            row = db.execute(
                "SELECT c.document_id, c.position, d.title FROM chunks c "
                "JOIN documents d ON d.id = c.document_id WHERE c.id = ? AND d.notebook_id = ?",
                (chunk_id, nid),
            ).fetchone()
            if row is None:
                raise NotFound("passage not found")
            near = db.execute(
                "SELECT id, position, content, start_line, end_line FROM chunks "
                "WHERE document_id = ? AND position BETWEEN ? AND ? ORDER BY position",
                (row[0], row[1] - around, row[1] + around),
            ).fetchall()
        return {
            "document_id": row[0],
            "title": row[2],
            "chunk_id": chunk_id,
            "passages": [
                {
                    "id": r[0],
                    "position": r[1],
                    "content": r[2],
                    "start_line": r[3],
                    "end_line": r[4],
                }
                for r in near
            ],
        }

    def ready_document_ids(self, nid: str) -> list[str]:
        with self.connect() as db:
            return [
                r[0]
                for r in db.execute(
                    "SELECT id FROM documents WHERE notebook_id = ? AND status = ?", (nid, READY)
                )
            ]

    def owns(self, tenant: str, user: str, nid: str) -> bool:
        with self.connect() as db:
            try:
                self._notebook_row(db, tenant, user, nid)
            except NotFound:
                return False
        return True

    def stats(self) -> dict[str, Any]:
        with self.connect() as db:
            n = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            m = db.execute("SELECT value FROM meta WHERE key = 'embedder'").fetchone()[0]
        return {"chunks": n, "embedder": m, "dimension": self.dimension}


__all__ = [
    "BULK",
    "CANCELLED",
    "FAILED",
    "INTERACTIVE",
    "PENDING",
    "PROCESSING",
    "READY",
    "Conflict",
    "NotFound",
    "NotebookStore",
]
