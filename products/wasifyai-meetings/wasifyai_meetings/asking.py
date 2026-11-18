"""Asking about meetings (ADR-0108 decision 16, stage MT5): through notebooks, not a second engine.

A meeting goes into a notebook as a source: a note with its title, date, speakers, the transcript
(`[m:ss] Name: words`) and its reports, added with the notebooks' own action `notebook.add_source`.
Then it can be asked about with the notebook's citations, alone or with the other sources there.

A question on a meeting's own page is put to a notebook the meeting is in, with `notebook.ask`
limited to the meeting's source, so the answer cites the meeting's own lines. A meeting in no
notebook yet is added first to a notebook named after it (said so on the page). Both run through the
app's one executor (ADR-0068), as the window would. A question is a job (rule 6), one at a time for
each person, kept with the meeting."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from wasifyai_platform_sdk import Identity, RouteDeps, RunContext, reset_context, set_context

from wasifyai_meetings.reports import transcript_of
from wasifyai_meetings.store import MeetingStore, NotFound

log = logging.getLogger(__name__)

READY_WAIT_S = 180.0  # how long a question waits for a just-added source to be read
READY_POLL_S = 1.0


class Refused(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def note_of(row: dict[str, Any], reports: list[dict[str, Any]]) -> str:
    """The meeting as a notebook source: what a question about it may need, in plain text."""
    when = (row.get("created_at") or "")[:10]
    minutes = round(float(row.get("seconds") or 0) / 60)

    def spoke(s: dict[str, Any]) -> str:
        m = round(float(s.get("seconds") or 0) / 60)
        return f"{s['name']} ({m} min)" if m else s["name"]

    # with how long each spoke, so "who spoke most" is answered from the meeting, not guessed
    names = ", ".join(spoke(s) for s in row["speakers"]) or "nobody named"
    head = [
        f"Meeting: {row['title']}",
        f"Date: {when}" if when else "",
        f"Length: {minutes} minutes" if minutes else "",
        f"Speakers: {names}",
    ]
    written = [
        f"\n{r['title']} (a report written from the transcript)\n\n{r['text']}"
        for r in reports
        if r.get("status") == "done" and r.get("text")
    ]
    return (
        "\n".join(h for h in head if h)
        + "\n\nTranscript\n\n"
        + transcript_of(row)
        + ("\n" + "\n".join(written) if written else "")
    )


def _executor(deps: RouteDeps) -> Any:
    actions = deps.state.actions
    if actions is None:
        raise Refused("unavailable", "Notebooks are not available here.")
    return actions


async def _run(deps: RouteDeps, identity: Identity, action: str, params: dict[str, Any]) -> Any:
    result = await _executor(deps).run_action(action, params, "window", actor=identity)
    if result.status != "ok":
        raise Refused(result.code or result.status, result.text or "That did not work.")
    return result.output


async def notebooks(deps: RouteDeps, identity: Identity) -> list[dict[str, Any]]:
    """The person's notebooks, to choose one to add a meeting to."""
    out = await _run(deps, identity, "notebook.list", {})
    return [{"id": n["notebook_id"], "title": n["title"]} for n in out.get("notebooks", [])]


async def add_to_notebook(
    deps: RouteDeps, store: MeetingStore, identity: Identity, item: str, *,
    notebook_id: str = "", title: str = "",
) -> dict[str, Any]:  # fmt: skip
    """Add the meeting to `notebook_id`, or to a new notebook called `title` (the meeting's title
    when empty). Added again, the newer source is the one its questions use."""
    t, u = identity.tenant_id, identity.user_id
    row = store.get(t, u, item)
    if row["status"] != "done":
        raise Refused("not_ready", "The meeting is not made yet.")
    if not row["lines"]:
        raise Refused("empty", "Nothing was said in this meeting, so there is nothing to add.")
    if notebook_id:
        known = {n["id"]: n["title"] for n in await notebooks(deps, identity)}
        if notebook_id not in known:
            raise Refused("not_found", "That notebook is not there.")
        name = known[notebook_id]
    else:
        made = await _run(
            deps, identity, "notebook.create", {"title": (title or row["title"])[:200]}
        )
        notebook_id, name = made["notebook_id"], made["title"]
    note = note_of(row, store.reports_of(t, u, item))
    added = await _run(deps, identity, "notebook.add_source", {
        "notebook_id": notebook_id, "title": f"Meeting: {row['title']}"[:200], "content": note,
    })  # fmt: skip
    store.add_in_notebook(t, u, item, notebook_id, name, added["document_id"])
    return {"notebook_id": notebook_id, "notebook_title": name, "document_id": added["document_id"]}


def _source_state(deps: RouteDeps, identity: Identity, nid: str, did: str) -> str | None:
    """The notebook source's state ("pending", "processing", "ready", "failed" ...), or None when
    it cannot be told here (then the question is put at once)."""
    try:
        from wasifyai_notebooks.runtime import runtime_for
    except ImportError:
        return None
    try:
        doc = runtime_for(deps.state).store.get_document(
            identity.tenant_id, identity.user_id, nid, did
        )
    except Exception:  # the source was deleted in the notebook: the caller adds it again
        return "missing"
    return str(doc.get("status") or "")


SourceState = Callable[[RouteDeps, Identity, str, str], str | None]


class AskJobs:
    """Questions being answered: one at a time for each person (the chat model is shared)."""

    def __init__(
        self, deps: RouteDeps, product: str, store_of: Callable[[Any], MeetingStore],
        source_state: SourceState = _source_state,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):  # fmt: skip
        self._deps = deps
        self._product = product
        self._store_of = store_of
        self._source_state = source_state
        self._sleep = sleep
        self._jobs: dict[tuple[str, str], tuple[str, asyncio.Task[None]]] = {}

    def busy(self, identity: Identity) -> bool:
        job = self._jobs.get((identity.tenant_id, identity.user_id))
        return job is not None and not job[1].done()

    def start(self, identity: Identity, item: str, question: str) -> dict[str, Any]:
        store = self._store_of(self._deps.state)
        row = store.get(identity.tenant_id, identity.user_id, item)
        if row["status"] != "done":
            raise Refused("not_ready", "The meeting is not made yet.")
        if not row["lines"]:
            raise Refused("empty", "Nothing was said in this meeting, so there is nothing to ask.")
        if self.busy(identity):
            raise Refused("busy", "A question is being answered. Wait for it to finish.")
        q = store.add_question(identity.tenant_id, identity.user_id, item, question.strip())

        async def run() -> None:
            token = set_context(RunContext(identity.tenant_id, self._product, identity.user_id))
            try:
                await self._answer(identity, row, q["id"], question.strip())
            finally:
                reset_context(token)

        self._jobs[(identity.tenant_id, identity.user_id)] = (q["id"], asyncio.create_task(run()))
        return q

    def _job(self, qid: str) -> asyncio.Task[None] | None:
        for got, task in self._jobs.values():
            if got == qid and not task.done():
                return task
        return None

    async def wait(self, qid: str) -> None:
        task = self._job(qid)
        if task is not None:
            await asyncio.shield(task)

    async def cancel(self, qid: str) -> bool:
        task = self._job(qid)
        if task is None:
            return False
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return True

    async def _source(self, identity: Identity, row: dict[str, Any], qid: str) -> dict[str, Any]:
        """The notebook source the question goes to: the newest one the meeting is in that is
        still there, else a new notebook named after it; once it has been read."""
        store = self._store_of(self._deps.state)
        t, u = identity.tenant_id, identity.user_id
        for link in store.in_notebooks(t, u, row["id"]):
            got = await asyncio.to_thread(
                self._source_state, self._deps, identity, link["notebook_id"], link["document_id"]
            )
            if got in (None, "ready"):
                return link
            if got != "missing":
                break
            store.drop_in_notebook(t, u, row["id"], link["notebook_id"])
        else:
            store.question_stage(qid, "Adding the meeting to a notebook")
            link = await add_to_notebook(self._deps, store, identity, row["id"])
        loop = asyncio.get_running_loop()
        until = loop.time() + READY_WAIT_S
        while True:
            got = await asyncio.to_thread(
                self._source_state, self._deps, identity, link["notebook_id"], link["document_id"]
            )
            if got in (None, "ready"):
                return link
            if got in ("failed", "cancelled", "missing"):
                raise Refused("not_read", "The notebook could not read the meeting. Add it again.")
            if loop.time() > until:
                raise Refused("slow", "The notebook is still reading the meeting. Ask again soon.")
            store.question_stage(qid, "The notebook is reading the meeting")
            await self._sleep(READY_POLL_S)

    async def _answer(
        self, identity: Identity, row: dict[str, Any], qid: str, question: str
    ) -> None:
        store = self._store_of(self._deps.state)
        try:
            link = await self._source(identity, row, qid)
            store.question_stage(qid, f"Asking the notebook “{link['notebook_title']}”")
            out = await _run(self._deps, identity, "notebook.ask", {
                "notebook_id": link["notebook_id"], "question": question,
                "document_ids": [link["document_id"]],
            })  # fmt: skip
            store.answer(
                qid, str(out.get("reply") or ""), list(out.get("citations") or []),
                link["notebook_id"], str(out.get("conversation_id") or ""),
            )  # fmt: skip
        except asyncio.CancelledError:
            store.fail_question(qid, "Stopped.", "cancelled")
            raise
        except Refused as e:
            store.fail_question(qid, e.message)
        except NotFound:
            store.fail_question(qid, "The meeting is not there any more.")
        except Exception:
            log.exception("answering a question about a meeting failed")
            store.fail_question(qid, "The question could not be answered. Try again.")


def question_out(q: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "meeting_id", "question", "status", "stage", "error", "reply", "citations",
            "notebook_id", "conversation_id", "created_at", "finished_at")  # fmt: skip
    return {k: q.get(k) for k in keys}


__all__ = ["AskJobs", "Refused", "add_to_notebook", "note_of", "notebooks", "question_out"]
