"""The meetings a person has (ADR-0108): on the desktop one small SQLite file and the recordings
beside it, in the app's own data folder; on the web (stage MT6) the same tables in their own
Postgres schema (`meetings`). One store class on either database (`wasifyai_platform_sdk.sqlstore`).

Every query is scoped by tenant and user. A meeting has a state (`working`, `done`, `failed`,
`cancelled`), a stage in words while it is being made, its speakers (`S1`, `S2`, ... with the name a
person gave them) and its lines (a stretch of the transcript, with when it was said and by whom). A
meeting left `working` by a process that is gone is failed when the desktop's store opens.

People (stage MT3): a person has a name, and evidence about their voice: a speaker of a meeting they
were confirmed as (`voice`), and speakers they were confirmed not to be (`confirmed`: another person
of
the same meeting; `rejected`: the person said "not them"). Each piece carries the speaker's
voiceprint
when there is one, and how it was recorded (`in_person`, `remote`, `imported`). Each meeting's
speakers
have one voiceprint each (`speaker_prints`). Reports (stage MT4): a meeting's reports, written from
a
template, and a person's own templates."""

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk.sqlstore import PostgresStoreDb, SqliteStoreDb, StoreDb

SCHEMA = 1
LEFT_RUNNING = "It was stopped when the app closed. Make it again."
STALE = "It was stopped when the service restarted. Try again."
STATES = ("working", "done", "failed", "cancelled")


class NotFound(Exception):
    """No such meeting for this person."""


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", text)[:64] or "_"


DDL = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meetings(
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
  title TEXT NOT NULL, source_name TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'file',
  status TEXT NOT NULL CHECK (status IN ('working', 'done', 'failed', 'cancelled')),
  stage TEXT NOT NULL DEFAULT '', progress DOUBLE PRECISION NOT NULL DEFAULT 0, error TEXT,
  language TEXT NOT NULL DEFAULT '', model_id TEXT NOT NULL DEFAULT '',
  seconds DOUBLE PRECISION, speakers TEXT NOT NULL DEFAULT '[]',
  lines TEXT NOT NULL DEFAULT '[]', text TEXT NOT NULL DEFAULT '',
  timings TEXT NOT NULL DEFAULT '{}', elapsed_s DOUBLE PRECISION,
  created_at TEXT NOT NULL, finished_at TEXT);
CREATE INDEX IF NOT EXISTS meetings_owner ON meetings(tenant_id, user_id, created_at);
CREATE TABLE IF NOT EXISTS people(
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, name TEXT NOT NULL,
  created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS people_owner ON people(tenant_id, user_id);
CREATE TABLE IF NOT EXISTS speaker_prints(
  meeting_id TEXT NOT NULL, speaker TEXT NOT NULL, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
  kind TEXT NOT NULL, vector TEXT NOT NULL, seconds DOUBLE PRECISION NOT NULL,
  turns INTEGER NOT NULL, PRIMARY KEY (meeting_id, speaker));
CREATE TABLE IF NOT EXISTS prints_made(
  meeting_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, made_at TEXT NOT
  NULL);
CREATE TABLE IF NOT EXISTS evidence(
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, person_id TEXT NOT NULL,
  meeting_id TEXT NOT NULL, speaker TEXT NOT NULL,
  reason TEXT NOT NULL CHECK (reason IN ('voice', 'confirmed', 'rejected')),
  kind TEXT NOT NULL, vector TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS evidence_person ON evidence(tenant_id, user_id, person_id);
CREATE INDEX IF NOT EXISTS evidence_meeting ON evidence(meeting_id);
CREATE TABLE IF NOT EXISTS reports(
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, meeting_id TEXT NOT NULL,
  template TEXT NOT NULL, title TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('working', 'done', 'failed', 'cancelled')),
  stage TEXT NOT NULL DEFAULT '', progress DOUBLE PRECISION NOT NULL DEFAULT 0, error TEXT,
  text TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, finished_at TEXT);
CREATE INDEX IF NOT EXISTS reports_meeting ON reports(tenant_id, user_id, meeting_id);
CREATE TABLE IF NOT EXISTS templates(
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, title TEXT NOT NULL,
  instructions TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS templates_owner ON templates(tenant_id, user_id);
CREATE TABLE IF NOT EXISTS in_notebooks(
  meeting_id TEXT NOT NULL, notebook_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
  user_id TEXT NOT NULL, notebook_title TEXT NOT NULL, document_id TEXT NOT NULL,
  added_at TEXT NOT NULL, PRIMARY KEY (meeting_id, notebook_id));
CREATE TABLE IF NOT EXISTS questions(
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, meeting_id TEXT NOT NULL,
  question TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('working', 'done', 'failed', 'cancelled')),
  stage TEXT NOT NULL DEFAULT '', error TEXT, reply TEXT NOT NULL DEFAULT '',
  citations TEXT NOT NULL DEFAULT '[]', notebook_id TEXT NOT NULL DEFAULT '',
  conversation_id TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, finished_at TEXT);
CREATE INDEX IF NOT EXISTS questions_meeting ON questions(tenant_id, user_id, meeting_id);
"""

_JSON = ("speakers", "lines", "timings")


class MeetingStore:
    def __init__(self, db: StoreDb, folder: Path | None = None):
        """The store on `db`. `folder` is where the recordings are on the desktop."""
        self.db = db
        self.folder = folder
        db.open_tables(DDL)
        db.exec("INSERT INTO meta VALUES ('schema', ?) ON CONFLICT DO NOTHING", (str(SCHEMA),))

    @classmethod
    def in_folder(cls, folder: Path) -> "MeetingStore":
        """The desktop's store: `meetings.db` and the recordings beside it. What a closed app left
        being made is failed, in words."""
        store = cls(SqliteStoreDb(folder / "meetings.db"), folder)
        store.fail_left_running()
        return store

    @classmethod
    def on_postgres(cls, dsn: str, schema: str = "meetings") -> "MeetingStore":
        return cls(PostgresStoreDb(dsn, schema))

    def fail_left_running(self) -> None:
        for table in ("meetings", "reports", "questions"):
            self.db.exec(
                f"UPDATE {table} SET status = 'failed', error = ?, stage = '', finished_at = ? "
                "WHERE status = 'working'",
                (LEFT_RUNNING, now()),
            )

    def close(self) -> None:
        self.db.close()

    def drop_schema(self) -> None:
        drop = getattr(self.db, "drop", None)
        if drop is not None:
            drop()

    def folder_of(self, tenant: str, user: str, item_id: str) -> Path:
        """Where one meeting's files are on the desktop (its recording)."""
        if self.folder is None:
            raise NotImplementedError("the web keeps these files in object storage")
        if not re.fullmatch(r"[0-9a-f]{32}", item_id):
            raise ValueError("not an id")
        return self.folder / "files" / _slug(tenant) / _slug(user) / item_id

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        out = dict(row)
        for k in _JSON:
            out[k] = json.loads(out[k]) if out.get(k) else ({} if k == "timings" else [])
        return out

    # ---- meetings -------------------------------------------------------------------------------

    def add(
        self,
        tenant: str,
        user: str,
        *,
        title: str,
        source_name: str = "",
        language: str = "",
        source: str = "file",
    ) -> dict[str, Any]:
        """A meeting being made. `source` is "file" or "recorded" (in the app, two channels)."""
        item = new_id()
        self.db.exec(
            "INSERT INTO meetings(id, tenant_id, user_id, title, source_name, source, status, "
            "stage, language, created_at) VALUES (?, ?, ?, ?, ?, ?, 'working', ?, ?, ?)",
            (item, tenant, user, title[:200], source_name[:200], source, "Waiting",
             language[:20], now()),
        )  # fmt: skip
        return self.get(tenant, user, item)

    def get(self, tenant: str, user: str, item: str) -> dict[str, Any]:
        row = self.db.one(
            "SELECT * FROM meetings WHERE id = ? AND tenant_id = ? AND user_id = ?",
            (item, tenant, user),
        )
        if row is None:
            raise NotFound(item)
        return self._row(row)

    def list_meetings(
        self, tenant: str, user: str, ids: list[str] | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Newest first; without the lines and the full text (`text` is cut to a preview)."""
        cols = (
            "id, title, source_name, source, status, stage, progress, error, language, model_id, "
            "seconds, speakers, substr(text, 1, 240) AS text, elapsed_s, created_at, finished_at"
        )
        if ids:
            marks = ",".join("?" * len(ids))
            rows = self.db.all(
                f"SELECT {cols} FROM meetings WHERE tenant_id = ? AND user_id = ? "
                f"AND id IN ({marks}) ORDER BY created_at DESC LIMIT ?",
                (tenant, user, *ids, limit),
            )
        else:
            rows = self.db.all(
                f"SELECT {cols} FROM meetings WHERE tenant_id = ? AND user_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (tenant, user, limit),
            )
        out = []
        for r in rows:
            d = dict(r)
            d["speakers"] = json.loads(d["speakers"] or "[]")
            out.append(d)
        return out

    def set_stage(self, item: str, stage: str, progress: float) -> None:
        self.db.exec(
            "UPDATE meetings SET stage = ?, progress = ? WHERE id = ? AND status = 'working'",
            (stage[:120], max(0.0, min(progress, 1.0)), item),
        )

    def finish(
        self, item: str, *, seconds: float, model_id: str, speakers: list[dict[str, Any]],
        lines: list[dict[str, Any]], text: str, timings: dict[str, float], elapsed_s: float,
    ) -> None:  # fmt: skip
        self.db.exec(
            "UPDATE meetings SET status = 'done', stage = '', progress = 1, error = NULL, "
            "seconds = ?, model_id = ?, speakers = ?, lines = ?, text = ?, timings = ?, "
            "elapsed_s = ?, finished_at = ? WHERE id = ? AND status = 'working'",
            (
                seconds, model_id, json.dumps(speakers), json.dumps(lines), text,
                json.dumps(timings), elapsed_s, now(), item,
            ),
        )  # fmt: skip

    def fail(self, item: str, error: str, status: str = "failed") -> None:
        assert status in ("failed", "cancelled")
        self.db.exec(
            "UPDATE meetings SET status = ?, stage = '', error = ?, finished_at = ? "
            "WHERE id = ? AND status = 'working'",
            (status, error[:500], now(), item),
        )

    def rename(self, tenant: str, user: str, item: str, title: str) -> dict[str, Any]:
        n = self.db.exec(
            "UPDATE meetings SET title = ? WHERE id = ? AND tenant_id = ? AND user_id = ?",
            (title.strip()[:200], item, tenant, user),
        )
        if not n:
            raise NotFound(item)
        return self.get(tenant, user, item)

    def set_speakers(
        self, tenant: str, user: str, item: str, speakers: list[dict[str, Any]]
    ) -> None:
        self.db.exec(
            "UPDATE meetings SET speakers = ? WHERE id = ? AND tenant_id = ? AND user_id = ?",
            (json.dumps(speakers), item, tenant, user),
        )

    def with_person(self, tenant: str, user: str, person: str) -> list[dict[str, Any]]:
        """The meetings with a speaker who is `person` or was said not to be."""
        rows = self.db.all(
            "SELECT * FROM meetings WHERE tenant_id = ? AND user_id = ? AND speakers LIKE ?",
            (tenant, user, f"%{person}%"),
        )
        return [self._row(r) for r in rows]

    def delete(self, tenant: str, user: str, item: str) -> bool:
        """A meeting, its reports, its voiceprints and what was learned of people from it."""
        gone = (
            self.db.exec(
                "DELETE FROM meetings WHERE id = ? AND tenant_id = ? AND user_id = ?",
                (item, tenant, user),
            )
            > 0
        )
        if gone:
            for table in (
                "speaker_prints",
                "prints_made",
                "evidence",
                "reports",
                "in_notebooks",
                "questions",
            ):
                self.db.exec(
                    f"DELETE FROM {table} WHERE meeting_id = ? AND tenant_id = ? AND user_id = ?",
                    (item, tenant, user),
                )
        return gone

    # ---- voiceprints of a meeting's speakers (MT3) ----------------------------------------------

    def save_prints(self, tenant: str, user: str, item: str, prints: list[dict[str, Any]]) -> None:
        self.db.exec("DELETE FROM speaker_prints WHERE meeting_id = ?", (item,))
        for p in prints:
            self.db.exec(
                "INSERT INTO speaker_prints(meeting_id, speaker, tenant_id, user_id, kind, vector, "
                "seconds, turns) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (item, p["speaker"], tenant, user, p["kind"], p["vector"], p["seconds"],
                 p["turns"]),
            )  # fmt: skip
        self.db.exec(
            "INSERT INTO prints_made VALUES (?, ?, ?, ?) ON CONFLICT (meeting_id) DO UPDATE SET "
            "made_at = excluded.made_at",
            (item, tenant, user, now()),
        )

    def prints_made(self, tenant: str, user: str, item: str) -> bool:
        return (
            self.db.one(
                "SELECT 1 FROM prints_made WHERE meeting_id = ? AND tenant_id = ? AND user_id = ?",
                (item, tenant, user),
            )
            is not None
        )

    def prints_of(self, tenant: str, user: str, item: str) -> dict[str, dict[str, Any]]:
        rows = self.db.all(
            "SELECT speaker, kind, vector, seconds, turns FROM speaker_prints "
            "WHERE meeting_id = ? AND tenant_id = ? AND user_id = ?",
            (item, tenant, user),
        )
        return {r["speaker"]: dict(r) for r in rows}

    # ---- people (MT3) ---------------------------------------------------------------------------

    def add_person(self, tenant: str, user: str, name: str) -> dict[str, Any]:
        pid = new_id()
        self.db.exec(
            "INSERT INTO people VALUES (?, ?, ?, ?, ?)",
            (pid, tenant, user, name.strip()[:80], now()),
        )
        return self.person(tenant, user, pid)

    def person(self, tenant: str, user: str, pid: str) -> dict[str, Any]:
        row = self.db.one(
            "SELECT id, name, created_at FROM people "
            "WHERE id = ? AND tenant_id = ? AND user_id = ?",
            (pid, tenant, user),
        )
        if row is None:
            raise NotFound(pid)
        return dict(row)

    def person_named(self, tenant: str, user: str, name: str) -> dict[str, Any] | None:
        want = name.strip().casefold()
        for r in self.db.all(
            "SELECT id, name, created_at FROM people WHERE tenant_id = ? AND user_id = ?",
            (tenant, user),
        ):
            if r["name"].casefold() == want:
                return dict(r)
        return None

    def people(self, tenant: str, user: str) -> list[dict[str, Any]]:
        """Each person with how many meetings they were named in, how many voiceprints of them
        are kept, and when they were last named."""
        rows = self.db.all(
            "SELECT p.id, p.name, p.created_at, "
            "COUNT(DISTINCT CASE WHEN e.reason = 'voice' THEN e.meeting_id END) AS meetings, "
            "COALESCE(SUM(CASE WHEN e.reason = 'voice' AND e.vector != '' THEN 1 ELSE 0 END), 0) "
            "AS voices, MAX(CASE WHEN e.reason = 'voice' THEN e.created_at END) AS last_named "
            "FROM people p LEFT JOIN evidence e ON e.person_id = p.id "
            "AND e.tenant_id = p.tenant_id AND e.user_id = p.user_id "
            "WHERE p.tenant_id = ? AND p.user_id = ? GROUP BY p.id, p.name, p.created_at",
            (tenant, user),
        )
        return sorted((dict(r) for r in rows), key=lambda r: r["name"].casefold())

    def rename_person(self, tenant: str, user: str, pid: str, name: str) -> None:
        n = self.db.exec(
            "UPDATE people SET name = ? WHERE id = ? AND tenant_id = ? AND user_id = ?",
            (name.strip()[:80], pid, tenant, user),
        )
        if not n:
            raise NotFound(pid)

    def delete_person(self, tenant: str, user: str, pid: str) -> bool:
        self.db.exec(
            "DELETE FROM evidence WHERE person_id = ? AND tenant_id = ? AND user_id = ?",
            (pid, tenant, user),
        )
        return (
            self.db.exec(
                "DELETE FROM people WHERE id = ? AND tenant_id = ? AND user_id = ?",
                (pid, tenant, user),
            )
            > 0
        )

    def add_evidence(
        self, tenant: str, user: str, *, person: str, item: str, speaker: str, reason: str,
        kind: str, vector: str,
    ) -> None:  # fmt: skip
        self.db.exec(
            "INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id(), tenant, user, person, item, speaker, reason, kind, vector, now()),
        )

    def drop_evidence(
        self, tenant: str, user: str, item: str, *, speaker: str | None = None,
        person: str | None = None, reasons: tuple[str, ...] = ("voice", "confirmed"),
    ) -> None:  # fmt: skip
        """What a confirmation in meeting `item` added: by the speaker it was about, or for a
        person."""
        where = ["tenant_id = ?", "user_id = ?", "meeting_id = ?"]
        args: list[Any] = [tenant, user, item]
        if speaker is not None:
            where.append("speaker = ?")
            args.append(speaker)
        if person is not None:
            where.append("person_id = ?")
            args.append(person)
        marks = ",".join("?" * len(reasons))
        self.db.exec(
            f"DELETE FROM evidence WHERE {' AND '.join(where)} AND reason IN ({marks})",
            (*args, *reasons),
        )

    def evidence(self, tenant: str, user: str) -> list[dict[str, Any]]:
        rows = self.db.all(
            "SELECT person_id, meeting_id, speaker, reason, kind, vector FROM evidence "
            "WHERE tenant_id = ? AND user_id = ?",
            (tenant, user),
        )
        return [dict(r) for r in rows]

    # ---- reports and templates (MT4) ------------------------------------------------------------

    def add_report(
        self, tenant: str, user: str, item: str, template: str, title: str
    ) -> dict[str, Any]:
        rid = new_id()
        self.db.exec(
            "INSERT INTO reports(id, tenant_id, user_id, meeting_id, template, title, status, "
            "stage, created_at) VALUES (?, ?, ?, ?, ?, ?, 'working', 'Waiting', ?)",
            (rid, tenant, user, item, template[:64], title[:200], now()),
        )
        return self.report(tenant, user, rid)

    def report(self, tenant: str, user: str, rid: str) -> dict[str, Any]:
        row = self.db.one(
            "SELECT * FROM reports WHERE id = ? AND tenant_id = ? AND user_id = ?",
            (rid, tenant, user),
        )
        if row is None:
            raise NotFound(rid)
        return dict(row)

    def reports_of(self, tenant: str, user: str, item: str) -> list[dict[str, Any]]:
        rows = self.db.all(
            "SELECT * FROM reports WHERE meeting_id = ? AND tenant_id = ? AND user_id = ? "
            "ORDER BY created_at",
            (item, tenant, user),
        )
        return [dict(r) for r in rows]

    def report_stage(self, rid: str, stage: str, progress: float) -> None:
        self.db.exec(
            "UPDATE reports SET stage = ?, progress = ? WHERE id = ? AND status = 'working'",
            (stage[:120], max(0.0, min(progress, 1.0)), rid),
        )

    def finish_report(self, rid: str, text: str) -> None:
        self.db.exec(
            "UPDATE reports SET status = 'done', stage = '', progress = 1, error = NULL, text = ?, "
            "finished_at = ? WHERE id = ? AND status = 'working'",
            (text, now(), rid),
        )

    def fail_report(self, rid: str, error: str, status: str = "failed") -> None:
        assert status in ("failed", "cancelled")
        self.db.exec(
            "UPDATE reports SET status = ?, stage = '', error = ?, finished_at = ? "
            "WHERE id = ? AND status = 'working'",
            (status, error[:500], now(), rid),
        )

    def delete_report(self, tenant: str, user: str, rid: str) -> bool:
        return (
            self.db.exec(
                "DELETE FROM reports WHERE id = ? AND tenant_id = ? AND user_id = ?",
                (rid, tenant, user),
            )
            > 0
        )

    def add_template(self, tenant: str, user: str, title: str, instructions: str) -> dict[str, Any]:
        tid = "own-" + new_id()
        self.db.exec(
            "INSERT INTO templates VALUES (?, ?, ?, ?, ?, ?)",
            (tid, tenant, user, title.strip()[:80], instructions.strip()[:4000], now()),
        )
        return self.template(tenant, user, tid)

    def template(self, tenant: str, user: str, tid: str) -> dict[str, Any]:
        row = self.db.one(
            "SELECT id, title, instructions, created_at FROM templates "
            "WHERE id = ? AND tenant_id = ? AND user_id = ?",
            (tid, tenant, user),
        )
        if row is None:
            raise NotFound(tid)
        return dict(row)

    def templates(self, tenant: str, user: str) -> list[dict[str, Any]]:
        rows = self.db.all(
            "SELECT id, title, instructions, created_at FROM templates "
            "WHERE tenant_id = ? AND user_id = ? ORDER BY created_at",
            (tenant, user),
        )
        return [dict(r) for r in rows]

    def delete_template(self, tenant: str, user: str, tid: str) -> bool:
        return (
            self.db.exec(
                "DELETE FROM templates WHERE id = ? AND tenant_id = ? AND user_id = ?",
                (tid, tenant, user),
            )
            > 0
        )

    # ---- notebooks and questions (MT5) ---------------------------------------------------------

    def add_in_notebook(
        self, tenant: str, user: str, item: str, notebook_id: str, title: str, document_id: str
    ) -> None:
        """The meeting was added to a notebook as the source `document_id` (again: the newer
        one)."""
        self.db.exec(
            "DELETE FROM in_notebooks WHERE meeting_id = ? AND notebook_id = ?", (item, notebook_id)
        )
        self.db.exec(
            "INSERT INTO in_notebooks VALUES (?, ?, ?, ?, ?, ?, ?)",
            (item, notebook_id, tenant, user, title[:200], document_id, now()),
        )

    def in_notebooks(self, tenant: str, user: str, item: str) -> list[dict[str, Any]]:
        """The notebooks the meeting is a source of, the last added first."""
        rows = self.db.all(
            "SELECT notebook_id, notebook_title, document_id, added_at FROM in_notebooks "
            "WHERE meeting_id = ? AND tenant_id = ? AND user_id = ? ORDER BY added_at DESC",
            (item, tenant, user),
        )
        return [dict(r) for r in rows]

    def drop_in_notebook(self, tenant: str, user: str, item: str, notebook_id: str) -> None:
        self.db.exec(
            "DELETE FROM in_notebooks WHERE meeting_id = ? AND notebook_id = ? AND tenant_id = ? "
            "AND user_id = ?",
            (item, notebook_id, tenant, user),
        )

    def add_question(self, tenant: str, user: str, item: str, question: str) -> dict[str, Any]:
        qid = new_id()
        self.db.exec(
            "INSERT INTO questions(id, tenant_id, user_id, meeting_id, question, status, stage, "
            "created_at) VALUES (?, ?, ?, ?, ?, 'working', 'Waiting', ?)",
            (qid, tenant, user, item, question[:4000], now()),
        )
        return self.question(tenant, user, qid)

    @staticmethod
    def _question(row: Any) -> dict[str, Any]:
        out = dict(row)
        out["citations"] = json.loads(out["citations"] or "[]")
        return out

    def question(self, tenant: str, user: str, qid: str) -> dict[str, Any]:
        row = self.db.one(
            "SELECT * FROM questions WHERE id = ? AND tenant_id = ? AND user_id = ?",
            (qid, tenant, user),
        )
        if row is None:
            raise NotFound(qid)
        return self._question(row)

    def questions_of(self, tenant: str, user: str, item: str) -> list[dict[str, Any]]:
        rows = self.db.all(
            "SELECT * FROM questions WHERE meeting_id = ? AND tenant_id = ? AND user_id = ? "
            "ORDER BY created_at",
            (item, tenant, user),
        )
        return [self._question(r) for r in rows]

    def question_stage(self, qid: str, stage: str) -> None:
        self.db.exec(
            "UPDATE questions SET stage = ? WHERE id = ? AND status = 'working'", (stage[:120], qid)
        )

    def answer(
        self, qid: str, reply: str, citations: list[dict[str, Any]], notebook_id: str,
        conversation_id: str,
    ) -> None:  # fmt: skip
        self.db.exec(
            "UPDATE questions SET status = 'done', stage = '', error = NULL, reply = ?, "
            "citations = ?, notebook_id = ?, conversation_id = ?, finished_at = ? "
            "WHERE id = ? AND status = 'working'",
            (reply, json.dumps(citations), notebook_id, conversation_id, now(), qid),
        )

    def fail_question(self, qid: str, error: str, status: str = "failed") -> None:
        assert status in ("failed", "cancelled")
        self.db.exec(
            "UPDATE questions SET status = ?, stage = '', error = ?, finished_at = ? "
            "WHERE id = ? AND status = 'working'",
            (status, error[:500], now(), qid),
        )

    def delete_question(self, tenant: str, user: str, qid: str) -> bool:
        return (
            self.db.exec(
                "DELETE FROM questions WHERE id = ? AND tenant_id = ? AND user_id = ?",
                (qid, tenant, user),
            )
            > 0
        )

    def fail_stale(self, minutes: float) -> int:
        """On the web: what was left `working` longer than `minutes` without a word (its replica
        is gone) is failed, in words. Each step of a job says where it is well within that."""
        cutoff = datetime.fromtimestamp(datetime.now(UTC).timestamp() - minutes * 60, UTC)
        mark = cutoff.isoformat(timespec="milliseconds")
        n = 0
        for table in ("meetings", "reports", "questions"):
            n += self.db.exec(
                f"UPDATE {table} SET status = 'failed', error = ?, stage = '', finished_at = ? "
                "WHERE status = 'working' AND created_at < ?",
                (STALE, now(), mark),
            )
        return n


__all__ = ["LEFT_RUNNING", "MeetingStore", "NotFound", "STATES", "new_id", "now"]
