# SPDX-License-Identifier: Apache-2.0
"""What the voice product keeps (`voice.db`, next to the app's other data): the speeches made, the
transcripts written and the voices saved. The audio of a speech and the recording a cloned voice
came from are files in the app's storage (their keys are kept here); a cloned voice also has a copy
under `voices/` that the speech runtime reads. A transcript keeps its text and its timed segments,
not the recording it came from."""

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 4

_SPEECHES = """
CREATE TABLE speeches(
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
  mode TEXT NOT NULL DEFAULT 'speak', saved_voice_id TEXT,
  text TEXT NOT NULL, model_id TEXT NOT NULL, voice TEXT, options TEXT NOT NULL DEFAULT '{}',
  seconds REAL NOT NULL, sample_rate INTEGER NOT NULL, audio_key TEXT NOT NULL,
  load_s REAL NOT NULL DEFAULT 0, elapsed_s REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE INDEX speeches_owner ON speeches(tenant_id, user_id, created_at DESC);
"""
_TRANSCRIPTS = """
CREATE TABLE transcripts(
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
  title TEXT NOT NULL, source_name TEXT NOT NULL DEFAULT '', model_id TEXT NOT NULL,
  text TEXT NOT NULL, segments TEXT NOT NULL DEFAULT '[]', seconds REAL NOT NULL DEFAULT 0,
  elapsed_s REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX transcripts_owner ON transcripts(tenant_id, user_id, created_at DESC);
"""
_VOICES = """
CREATE TABLE voices(
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
  name TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('design', 'clone')),
  description TEXT NOT NULL DEFAULT '', reference_key TEXT,
  reference_text TEXT NOT NULL DEFAULT '', reference_seconds REAL,
  consent TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX voices_owner ON voices(tenant_id, user_id, created_at DESC);
"""
_TRACKS = """
CREATE TABLE tracks(
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
  title TEXT NOT NULL, mode TEXT NOT NULL, description TEXT NOT NULL,
  lyrics TEXT NOT NULL DEFAULT '', instrumental INTEGER NOT NULL DEFAULT 0,
  model_id TEXT NOT NULL, options TEXT NOT NULL DEFAULT '{}',
  seed INTEGER, seconds REAL NOT NULL, sample_rate INTEGER NOT NULL, audio_key TEXT NOT NULL,
  load_s REAL NOT NULL DEFAULT 0, elapsed_s REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL, favourite INTEGER NOT NULL DEFAULT 0, parent_id TEXT,
  edit TEXT NOT NULL DEFAULT '{}');
CREATE INDEX tracks_owner ON tracks(tenant_id, user_id, created_at DESC);
"""
_SCHEMA = "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);" + (
    _SPEECHES + _TRANSCRIPTS + _VOICES + _TRACKS
)
# what version 2 adds to a version 1 file: how a speech was made, and saved voices
_V2_UPGRADE = (
    "ALTER TABLE speeches ADD COLUMN mode TEXT NOT NULL DEFAULT 'speak';"
    "ALTER TABLE speeches ADD COLUMN saved_voice_id TEXT;" + _VOICES
)
# what version 3 adds: music; version 4: favourites, and what a track was edited from
_V3_UPGRADE = _TRACKS
_V4_UPGRADE = (
    "ALTER TABLE tracks ADD COLUMN favourite INTEGER NOT NULL DEFAULT 0;"
    "ALTER TABLE tracks ADD COLUMN parent_id TEXT;"
    "ALTER TABLE tracks ADD COLUMN edit TEXT NOT NULL DEFAULT '{}';"
)


class NotFound(Exception):
    pass


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def new_id() -> str:
    return uuid.uuid4().hex


class VoiceStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.path = self.root / "voice.db"
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
                version = int(row[0]) if row else 0
                if version > SCHEMA_VERSION or version < 1:
                    raise RuntimeError("voice.db was made by a newer version of this app")
                if version == 1:
                    db.executescript("BEGIN;" + _V2_UPGRADE + "COMMIT;")
                if version <= 2:  # the tracks table is made with its version 4 columns
                    db.executescript("BEGIN;" + _V3_UPGRADE + "COMMIT;")
                elif version == 3:
                    db.executescript("BEGIN;" + _V4_UPGRADE + "COMMIT;")
                if version < SCHEMA_VERSION:
                    db.execute(
                        "UPDATE meta SET value = ? WHERE key = 'schema'", (str(SCHEMA_VERSION),)
                    )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode = WAL")
        try:
            yield db
        finally:
            db.close()

    # ---- speeches ---------------------------------------------------------------------------

    @staticmethod
    def _speech(r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        d["options"] = json.loads(d["options"])
        return d

    def add_speech(
        self, tenant: str, user: str, *, text: str, model_id: str, voice: str | None,
        options: dict[str, Any], seconds: float, sample_rate: int, audio_key: str,
        load_s: float, elapsed_s: float, speech_id: str | None = None,
        mode: str = "speak", saved_voice_id: str | None = None,
    ) -> dict[str, Any]:  # fmt: skip
        sid = speech_id or new_id()
        with self._connect() as db:
            db.execute(
                "INSERT INTO speeches(id, tenant_id, user_id, mode, saved_voice_id, text, "
                "model_id, voice, options, seconds, sample_rate, audio_key, load_s, elapsed_s, "
                "created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (sid, tenant, user, mode, saved_voice_id, text, model_id, voice,
                 json.dumps(options), seconds, sample_rate, audio_key, load_s, elapsed_s, now()),
            )  # fmt: skip
        return self.get_speech(tenant, user, sid)

    def get_speech(self, tenant: str, user: str, sid: str) -> dict[str, Any]:
        with self._connect() as db:
            r = db.execute(
                "SELECT * FROM speeches WHERE id = ? AND tenant_id = ? AND user_id = ?",
                (sid, tenant, user),
            ).fetchone()
        if r is None:
            raise NotFound("speech not found")
        return self._speech(r)

    def list_speeches(
        self, tenant: str, user: str, ids: list[str] | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM speeches WHERE tenant_id = ? AND user_id = ? "
                "ORDER BY created_at DESC, id LIMIT ?",
                (tenant, user, max(1, min(limit, 500))),
            ).fetchall()
        out = [self._speech(r) for r in rows]
        return [s for s in out if ids is None or s["id"] in ids]

    def delete_speech(self, tenant: str, user: str, sid: str) -> dict[str, Any]:
        gone = self.get_speech(tenant, user, sid)
        with self._connect() as db:
            db.execute("DELETE FROM speeches WHERE id = ?", (sid,))
        return gone

    # ---- transcripts ------------------------------------------------------------------------

    @staticmethod
    def _transcript(r: sqlite3.Row, *, body: bool = True) -> dict[str, Any]:
        d = dict(r)
        d["segments"] = json.loads(d["segments"])
        if not body:
            d.pop("segments")
            d.pop("text")
        return d

    def add_transcript(
        self, tenant: str, user: str, *, title: str, source_name: str, model_id: str, text: str,
        segments: list[dict[str, Any]], seconds: float, elapsed_s: float,
        transcript_id: str | None = None,
    ) -> dict[str, Any]:  # fmt: skip
        tid, stamp = transcript_id or new_id(), now()
        with self._connect() as db:
            db.execute(
                "INSERT INTO transcripts(id, tenant_id, user_id, title, source_name, model_id, "
                "text, segments, seconds, elapsed_s, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (tid, tenant, user, title, source_name, model_id, text, json.dumps(segments),
                 seconds, elapsed_s, stamp, stamp),
            )  # fmt: skip
        return self.get_transcript(tenant, user, tid)

    def get_transcript(self, tenant: str, user: str, tid: str) -> dict[str, Any]:
        with self._connect() as db:
            r = db.execute(
                "SELECT * FROM transcripts WHERE id = ? AND tenant_id = ? AND user_id = ?",
                (tid, tenant, user),
            ).fetchone()
        if r is None:
            raise NotFound("transcript not found")
        return self._transcript(r)

    def list_transcripts(
        self, tenant: str, user: str, ids: list[str] | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM transcripts WHERE tenant_id = ? AND user_id = ? "
                "ORDER BY created_at DESC, id LIMIT ?",
                (tenant, user, max(1, min(limit, 500))),
            ).fetchall()
        return [self._transcript(r) for r in rows if ids is None or r["id"] in ids]

    def rename_transcript(self, tenant: str, user: str, tid: str, title: str) -> dict[str, Any]:
        self.get_transcript(tenant, user, tid)
        with self._connect() as db:
            db.execute(
                "UPDATE transcripts SET title = ?, updated_at = ? WHERE id = ?", (title, now(), tid)
            )
        return self.get_transcript(tenant, user, tid)

    def delete_transcript(self, tenant: str, user: str, tid: str) -> None:
        self.get_transcript(tenant, user, tid)
        with self._connect() as db:
            db.execute("DELETE FROM transcripts WHERE id = ?", (tid,))

    # ---- voices -----------------------------------------------------------------------------

    @staticmethod
    def _voice(r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        d["consent"] = json.loads(d["consent"])
        return d

    def reference_path(self, voice_id: str) -> Path:
        """Where the speech runtime reads a cloned voice's recording from (not user-chosen)."""
        if not voice_id.isalnum():
            raise NotFound("voice not found")
        return self.root / "voices" / f"{voice_id}.wav"

    def add_voice(
        self, tenant: str, user: str, *, kind: str, name: str, description: str = "",
        reference_key: str | None = None, reference_text: str = "",
        reference_seconds: float | None = None, consent: dict[str, Any] | None = None,
        voice_id: str | None = None,
    ) -> dict[str, Any]:  # fmt: skip
        vid, stamp = voice_id or new_id(), now()
        with self._connect() as db:
            db.execute(
                "INSERT INTO voices(id, tenant_id, user_id, name, kind, description, "
                "reference_key, reference_text, reference_seconds, consent, created_at, "
                "updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (vid, tenant, user, name, kind, description, reference_key, reference_text,
                 reference_seconds, json.dumps(consent or {}), stamp, stamp),
            )  # fmt: skip
        return self.get_voice(tenant, user, vid)

    def get_voice(self, tenant: str, user: str, vid: str) -> dict[str, Any]:
        with self._connect() as db:
            r = db.execute(
                "SELECT * FROM voices WHERE id = ? AND tenant_id = ? AND user_id = ?",
                (vid, tenant, user),
            ).fetchone()
        if r is None:
            raise NotFound("voice not found")
        return self._voice(r)

    def list_voices(self, tenant: str, user: str, kind: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM voices WHERE tenant_id = ? AND user_id = ? "
                "AND (? IS NULL OR kind = ?) ORDER BY created_at DESC, id",
                (tenant, user, kind, kind),
            ).fetchall()
        return [self._voice(r) for r in rows]

    def update_voice(
        self, tenant: str, user: str, vid: str, *, name: str | None = None,
        description: str | None = None, reference_text: str | None = None,
    ) -> dict[str, Any]:  # fmt: skip
        voice = self.get_voice(tenant, user, vid)
        if description is not None and voice["kind"] != "design":
            raise NotFound("a cloned voice has no description")
        if reference_text is not None and voice["kind"] != "clone":
            raise NotFound("a described voice has no recording")
        with self._connect() as db:
            db.execute(
                "UPDATE voices SET name = ?, description = ?, reference_text = ?, updated_at = ? "
                "WHERE id = ?",
                (name if name is not None else voice["name"],
                 description if description is not None else voice["description"],
                 reference_text if reference_text is not None else voice["reference_text"],
                 now(), vid),
            )  # fmt: skip
        return self.get_voice(tenant, user, vid)

    def delete_voice(self, tenant: str, user: str, vid: str) -> dict[str, Any]:
        gone = self.get_voice(tenant, user, vid)
        with self._connect() as db:
            db.execute("DELETE FROM voices WHERE id = ?", (vid,))
        self.reference_path(vid).unlink(missing_ok=True)
        return gone

    # ---- tracks (music) ---------------------------------------------------------------------

    @staticmethod
    def _track(r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        d["options"] = json.loads(d["options"])
        d["instrumental"] = bool(d["instrumental"])
        d["favourite"] = bool(d["favourite"])
        d["edit"] = json.loads(d["edit"])
        return d

    def add_track(
        self, tenant: str, user: str, *, title: str, mode: str, description: str, lyrics: str,
        instrumental: bool, model_id: str, options: dict[str, Any], seed: int | None,
        seconds: float, sample_rate: int, audio_key: str, load_s: float, elapsed_s: float,
        track_id: str | None = None, parent_id: str | None = None,
        edit: dict[str, Any] | None = None,
    ) -> dict[str, Any]:  # fmt: skip
        tid, stamp = track_id or new_id(), now()
        with self._connect() as db:
            db.execute(
                "INSERT INTO tracks(id, tenant_id, user_id, title, mode, description, lyrics, "
                "instrumental, model_id, options, seed, seconds, sample_rate, audio_key, load_s, "
                "elapsed_s, created_at, updated_at, parent_id, edit) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (tid, tenant, user, title, mode, description, lyrics, int(instrumental), model_id,
                 json.dumps(options), seed, seconds, sample_rate, audio_key, load_s, elapsed_s,
                 stamp, stamp, parent_id, json.dumps(edit or {})),
            )  # fmt: skip
        return self.get_track(tenant, user, tid)

    def get_track(self, tenant: str, user: str, tid: str) -> dict[str, Any]:
        with self._connect() as db:
            r = db.execute(
                "SELECT * FROM tracks WHERE id = ? AND tenant_id = ? AND user_id = ?",
                (tid, tenant, user),
            ).fetchone()
        if r is None:
            raise NotFound("track not found")
        return self._track(r)

    def list_tracks(
        self, tenant: str, user: str, ids: list[str] | None = None, limit: int = 100,
        favourites: bool = False,
    ) -> list[dict[str, Any]]:  # fmt: skip
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM tracks WHERE tenant_id = ? AND user_id = ? "
                "AND (? = 0 OR favourite = 1) ORDER BY created_at DESC, id LIMIT ?",
                (tenant, user, int(favourites), max(1, min(limit, 500))),
            ).fetchall()
        return [self._track(r) for r in rows if ids is None or r["id"] in ids]

    def update_track(
        self, tenant: str, user: str, tid: str, *, title: str | None = None,
        favourite: bool | None = None,
    ) -> dict[str, Any]:  # fmt: skip
        t = self.get_track(tenant, user, tid)
        with self._connect() as db:
            db.execute(
                "UPDATE tracks SET title = ?, favourite = ?, updated_at = ? WHERE id = ?",
                (title if title is not None else t["title"],
                 int(favourite if favourite is not None else t["favourite"]), now(), tid),
            )  # fmt: skip
        return self.get_track(tenant, user, tid)

    def rename_track(self, tenant: str, user: str, tid: str, title: str) -> dict[str, Any]:
        return self.update_track(tenant, user, tid, title=title)

    def delete_track(self, tenant: str, user: str, tid: str) -> dict[str, Any]:
        gone = self.get_track(tenant, user, tid)
        with self._connect() as db:
            db.execute("DELETE FROM tracks WHERE id = ?", (tid,))
        return gone
