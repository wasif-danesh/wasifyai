"""Reports of a meeting (ADR-0108 decision 15, stage MT4): written from a template by the person's
chosen chat model (local, or on their key: the `text.chat` binding of `product.yaml`).

A template is a title and what to write. The app has six (a summary, minutes, action items,
decisions, a stand-up and a sales call) and a person can keep their own. A transcript longer than
one
part is written down in overlapping parts first (notes of each part), and the report is written from
the notes, so a long meeting fits a small model; the parts overlap so a point made across a cut is
not lost. A report is written in the language of the meeting. It is a job (rule 6), one at a time,
and says where it is."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from wasifyai_platform_sdk import (
    Identity,
    RouteDeps,
    RunContext,
    RunError,
    reset_context,
    set_context,
)

from wasifyai_meetings.store import MeetingStore, NotFound

log = logging.getLogger(__name__)

PART_CHARS = 12000  # a part of the transcript the model reads at once (about 3,000 words)
OVERLAP_CHARS = 1200  # how much each part repeats of the one before
NOTES_CHARS = 24000  # notes longer than this are written down again, shorter


@dataclass(frozen=True)
class Template:
    id: str
    title: str
    instructions: str


TEMPLATES = (
    Template(
        "summary", "Summary",
        "A short summary for someone who was not there: what the meeting was about in two or three "
        "sentences, then the main points as a list, what was decided, and what happens next.",
    ),
    Template(
        "minutes", "Minutes",
        "Minutes of the meeting: who took part (the speakers' names), each subject discussed with "
        "what was said about it, the decisions made, and the action items with who will do them.",
    ),
    Template(
        "actions", "Action items",
        "Every task someone agreed to do or was asked to do, as a list: what is to be done, who "
        "will do it, and by when if a time was said. Nothing else.",
    ),
    Template(
        "decisions", "Decisions",
        "Every decision made in the meeting, as a list: what was decided, why, and who decided "
        "or agreed. Then what was left open, to decide later.",
    ),
    Template(
        "standup", "Stand-up",
        "For each person: what they did, what they will do next, and anything blocking them. "
        "Then anything the team must follow up.",
    ),
    Template(
        "sales", "Sales call",
        "Notes of a sales call: who the customer is and who was there, what they need, their "
        "questions and objections and how they were answered, budget and timing if said, and "
        "the agreed next steps.",
    ),
)  # fmt: skip
BY_ID = {t.id: t for t in TEMPLATES}

SYSTEM = (
    "You write reports of meetings from their transcripts. Each line of a transcript starts with "
    "when it was said and who said it. Use only what the transcript says: never make up names, "
    'numbers, dates, tasks or decisions. Call people by the names in the transcript ("Speaker 2" '
    "if that is all there is). Write in the language the meeting was held in. Use Markdown: a "
    "heading, short paragraphs and lists. When the transcript has nothing for a part, say so in "
    "one line rather than filling it."
)


def _clock(seconds: float) -> str:
    s = int(max(0, seconds))
    h, m = divmod(s // 60, 60)
    return f"{h}:{m:02d}:{s % 60:02d}" if h else f"{m}:{s % 60:02d}"


def transcript_of(row: dict[str, Any]) -> str:
    """The meeting as the model reads it: one line per turn, `[m:ss] Name: words`."""
    names = {s["key"]: s["name"] for s in row["speakers"]}
    return "\n".join(
        f"[{_clock(x['start'])}] {names.get(x['speaker'], x['speaker'])}: {x['text']}"
        for x in row["lines"]
    )


def parts_of(text: str, size: int = PART_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    """`text` in parts of at most `size` characters, cut at the end of a line, each starting
    `overlap` characters before the last one ended (also at a line)."""
    if len(text) <= size:
        return [text]
    out: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = text.rfind("\n", start + size // 2, end)
            end = cut + 1 if cut > 0 else end
        out.append(text[start:end])
        if end >= len(text):
            break
        back = text.rfind("\n", max(start + 1, end - overlap), end - 1)
        start = back + 1 if back > start else end
    return out


def template_for(store: MeetingStore, identity: Identity, tid: str) -> Template:
    if tid in BY_ID:
        return BY_ID[tid]
    t = store.template(identity.tenant_id, identity.user_id, tid)
    return Template(t["id"], t["title"], t["instructions"])


def all_templates(store: MeetingStore, identity: Identity) -> list[dict[str, Any]]:
    own = store.templates(identity.tenant_id, identity.user_id)
    return [{"id": t.id, "title": t.title, "instructions": t.instructions, "own": False}
            for t in TEMPLATES] + [{**t, "own": True} for t in own]  # fmt: skip


class Refused(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ReportJobs:
    """One report written at a time: on the desktop in all (the chat model is one model in its
    memory), on the web for each person (`per_person`)."""

    def __init__(
        self, deps: RouteDeps, product: str, store_of: Any, on_done: Any, per_person: bool = False
    ):
        self._deps = deps
        self._product = product
        self._store_of = store_of
        self._on_done = on_done  # (identity, meeting id) -> awaitable: search sees the report
        self._per_person = per_person
        self._jobs: dict[tuple[str, str], tuple[str, asyncio.Task[None]]] = {}

    def _slot(self, identity: Identity | None) -> tuple[str, str]:
        if not self._per_person or identity is None:
            return ("", "")
        return (identity.tenant_id, identity.user_id)

    def busy(self, identity: Identity | None = None) -> bool:
        job = self._jobs.get(self._slot(identity))
        return job is not None and not job[1].done()

    def _job_of(self, rid: str) -> asyncio.Task[None] | None:
        for got, task in self._jobs.values():
            if got == rid and not task.done():
                return task
        return None

    def start(
        self, identity: Identity, item: str, template: Template, title: str = ""
    ) -> dict[str, Any]:
        store: MeetingStore = self._store_of(self._deps.state)
        row = store.get(identity.tenant_id, identity.user_id, item)
        if row["status"] != "done":
            raise Refused("not_ready", "The meeting is not made yet.")
        if not row["lines"]:
            raise Refused(
                "empty", "Nothing was said in this meeting, so there is nothing to report."
            )
        if self.busy(identity):
            raise Refused("busy", "A report is being written. Wait for it to finish.")
        report = store.add_report(
            identity.tenant_id, identity.user_id, item, template.id, title or template.title
        )

        async def run() -> None:
            token = set_context(RunContext(identity.tenant_id, self._product, identity.user_id))
            try:
                await self._write(identity, row, report["id"], template)
            finally:
                reset_context(token)

        self._jobs[self._slot(identity)] = (report["id"], asyncio.create_task(run()))
        return report

    async def wait(self, rid: str) -> None:
        task = self._job_of(rid)
        if task is not None:
            await asyncio.shield(task)

    async def cancel(self, rid: str) -> bool:
        task = self._job_of(rid)
        if task is None:
            return False
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return True

    async def _ask(self, system: str, prompt: str) -> str:
        caps = self._deps.state.caps[self._product]
        return (await caps.text.complete("chat", system, prompt)).strip()

    async def _write(
        self, identity: Identity, row: dict[str, Any], rid: str, template: Template
    ) -> None:
        store: MeetingStore = self._store_of(self._deps.state)
        what = f'Write this report of the meeting "{row["title"]}":\n{template.instructions}'
        try:
            parts = parts_of(transcript_of(row))
            if len(parts) == 1:
                store.report_stage(rid, "Writing", 0.1)
                text = await self._ask(SYSTEM, f"{what}\n\nThe transcript:\n\n{parts[0]}")
            else:
                notes = []
                for i, part in enumerate(parts):
                    store.report_stage(
                        rid, f"Reading part {i + 1} of {len(parts)}", 0.85 * i / len(parts)
                    )
                    notes.append(await self._ask(SYSTEM, (
                        f"This is part {i + 1} of {len(parts)} of the transcript of a meeting (the "
                        f"parts overlap a little). Write notes of it to be used for this report "
                        f"later: {template.instructions}\nKeep every name, number, date, task and "
                        f"decision, with who said it. Notes only, no introduction.\n\n{part}"
                    )))  # fmt: skip
                joined = "\n\n".join(f"Notes of part {i + 1}:\n{n}" for i, n in enumerate(notes))
                while len(joined) > NOTES_CHARS:  # many parts: the notes are shortened first
                    store.report_stage(rid, "Shortening the notes", 0.85)
                    joined = "\n\n".join([
                        await self._ask(SYSTEM, (
                            "Shorten these notes of a meeting to half, keeping every name, "
                            f"number, date, task and decision:\n\n{chunk}"
                        ))
                        for chunk in parts_of(joined, PART_CHARS, 0)
                    ])  # fmt: skip
                store.report_stage(rid, "Writing", 0.9)
                text = await self._ask(SYSTEM, (
                    f"{what}\n\nWrite it from these notes of the meeting, taken part by part "
                    f"(the parts overlapped, so a point may be in two notes: say it once):\n\n"
                    f"{joined}"
                ))  # fmt: skip
            if not text:
                raise RunError("empty_reply", "The chat model wrote nothing. Try again.")
            store.finish_report(rid, text)
            caps = self._deps.state.caps[self._product]
            await caps.record_usage("meetings.report", 1, "reports", template=template.id[:16])
            await self._on_done(identity, row["id"])
        except asyncio.CancelledError:
            store.fail_report(rid, "Stopped.", "cancelled")
            raise
        except RunError as e:
            store.fail_report(rid, e.message)
        except Exception:
            log.exception("writing a meeting report failed")
            store.fail_report(
                rid, "The chat model did not answer. Check it in Models and try again."
            )


def report_out(r: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "meeting_id", "template", "title", "status", "stage", "progress", "error",
            "text", "created_at", "finished_at")  # fmt: skip
    return {k: r.get(k) for k in keys}


__all__ = [
    "BY_ID", "NotFound", "ReportJobs", "TEMPLATES", "Template", "all_templates", "parts_of",
    "report_out", "template_for", "transcript_of",
]  # fmt: skip
