# ruff: noqa: E501  (the sentences shown to people are easier to read on one line)
"""Teach it to decide: the runs of a set of decision examples (ADR-0075).

A decision set is one question with texts and their right answers. A run asks the chosen model the
texts it will be checked on first, teaches it (`desktop_decision_training`), asks again, counts words
for comparison, and keeps the model with its card: how often it was right before and after, where it
went wrong, whether its confidence can be trusted, and a mark that says in words whether it learnt.
One run at a time on this computer, and not while a picture or writing model is being taught: all hold
the one big-model slot (ADR-0056)."""

import asyncio
import hashlib
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk import Identity, RouteDeps, RouteGuard, RunContext, set_context
from wasifyai_platform_sdk.context import reset_context

from wasifyai_training import bases, decision
from wasifyai_training.decision import DecisionJob, Question, Row, Said
from wasifyai_training.language import Stopped
from wasifyai_training.runtime import (
    EV_RUN,
    PRODUCT_ID,
    STATEMENTS,
    NotAvailable,
    Refused,
    add_to_search,
    model_folder,
    run_folder,
    run_manager_for,
    store_for,
)

log = logging.getLogger(__name__)

KIND = "decision"


def engine_for(state: Any) -> Any:
    engine = getattr(state, "decision_training", None)
    if engine is None:
        raise NotAvailable("Teaching it to decide is not available here.")
    return engine


def set_hash(q: Question, rows: list[Row]) -> str:
    h = hashlib.sha256()
    h.update(f"{q.kind}\0{q.text}\0{q.levels}\0".encode())
    for r in rows:
        h.update(r.text.encode())
        h.update(b"\0")
        h.update(r.answer.encode())
        h.update(b"\0")
    return h.hexdigest()[:16]


def words_of(row: dict[str, Any]) -> str:
    """What search finds a decision model by: its name, its question and what it is."""
    q = (row.get("card") or {}).get("question", {}).get("text", "")
    return ". ".join(x for x in (row["name"], q, "decision") if x and x.strip())


def said_out(s: Said) -> dict[str, Any]:
    return {"answer": s.answer, "confidence": s.confidence, "shares": s.shares}


def missing(row: dict[str, Any], q: Question, rows: list[Row]) -> str | None:
    """What is missing before a run, in the sentence the person is shown; None when nothing is."""
    if why := decision.blocker(q, rows):
        return why
    if not row["rights"]:
        return "Say whose these texts are first."
    return None


def estimate_words(steps: int, d: bases.Descriptor) -> str:
    """ "About N minutes" from the seconds a step took when the base was measured (loading included)."""
    seconds = steps * d.seconds_per_step + d.overhead_s
    return "Under a minute" if seconds < 60 else f"About {round(seconds / 60)} minutes"


class DecisionRunManager:
    """Starts and cancels the runs of decision sets."""

    def __init__(self, deps: RouteDeps):
        self._deps = deps
        self._task: asyncio.Task[None] | None = None
        self._run_id: str | None = None
        # teaching, not what comes after it (the usage record, the search index)
        self._teaching = False

    def busy(self) -> bool:
        return self._teaching

    def active(self) -> str | None:
        return self._run_id if self._teaching else None

    def others_busy(self) -> bool:
        writing = getattr(self._deps.state, "writing_runs", None)
        return run_manager_for(self._deps).busy() or bool(writing is not None and writing.busy())

    def parts(
        self, identity: Identity, set_id: str
    ) -> tuple[dict[str, Any], Question, list[Row], list[str]]:
        store = store_for(self._deps.state)
        row = store.get_decision_set(identity.tenant_id, identity.user_id, set_id)
        q = decision.question_from(row)
        rows, said = decision.clean(
            q, store.list_decision_examples(identity.tenant_id, identity.user_id, set_id)
        )
        return row, q, rows, said

    def plan(self, identity: Identity, set_id: str) -> dict[str, Any]:
        """What a run of this set would take, and what stops it: the words of the Check step."""
        row, q, rows, said = self.parts(identity, set_id)
        train, held = decision.split(rows) if len(rows) >= 2 else (rows, [])
        epochs, steps = decision.plan_steps(len(train), row["quality"])
        d = bases.descriptor(row["base"]) or bases.descriptors("decision")[0]
        return {
            "examples": len(rows), "dropped": said, "checks": decision.checks(q, rows),
            "counts": {a: sum(r.answer == a for r in rows) for a in q.answers()},
            "steps": steps, "passes": epochs, "estimate": estimate_words(steps, d),
            "base": d.id, "base_title": d.title, "base_note": d.note, "held_back": len(held),
            "missing": missing(row, q, rows) or self._base_missing(d),
        }  # fmt: skip

    def _base_missing(self, d: bases.Descriptor) -> str | None:
        """Why the chosen base cannot be taught from yet: it is not on this computer."""
        try:
            why = engine_for(self._deps.state).problem(d.id)
        except NotAvailable:
            return None
        if why and "not on this computer" in why:
            return f"{d.title} is not on this computer yet. Get it first, next to its name."
        return None

    async def start(self, identity: Identity, set_id: str) -> dict[str, Any]:
        state = self._deps.state
        engine, store = engine_for(state), store_for(state)
        row, q, rows, _ = self.parts(identity, set_id)
        try:
            chosen, how = bases.resolve(KIND, row["base"] or None, None)
        except bases.Unavailable as e:
            raise Refused("cannot_teach", str(e)) from None
        if why := engine.problem(chosen.id):
            if "not on this computer" in why:
                why = f"{chosen.title} is not on this computer yet. Get it first, next to its name."
            raise Refused("not_ready", why)
        if self.busy() or self.others_busy():
            raise Refused("busy", "A model is being taught. Wait for it to finish.")
        if why := missing(row, q, rows):
            raise Refused("not_ready_to_train", why)
        guard = RouteGuard(state, PRODUCT_ID)
        if refusal := await guard.over_quota(
            identity, EV_RUN, "train_runs_per_user_per_day", "training runs"
        ):
            raise Refused(*refusal)
        fit = engine.fit(chosen.need_gb)
        if fit["verdict"] == "too_big":
            raise Refused("too_big", fit["reason"])
        if blockers := engine.preflight_blockers():
            raise Refused("not_now", blockers[0])
        train, _held = decision.split(rows)
        epochs, steps = decision.plan_steps(len(train), row["quality"])
        run = store.add_run(
            identity.tenant_id, identity.user_id, set_id, base=chosen.id, steps=steps,
            settings={"family": "decision", "kind": KIND, "question": q.kind, "steps": steps,
                      "passes": epochs, "method": how, "engine": chosen.engine,
                      "quality": row["quality"], "examples": len(rows)},
            preview=False,
        )  # fmt: skip
        self._run_id = run["id"]
        self._teaching = True
        self._task = asyncio.create_task(self._run(identity, row, q, rows, run, epochs, engine))
        return run

    async def cancel(self, identity: Identity, run_id: str) -> bool:
        store_for(self._deps.state).get_run(identity.tenant_id, identity.user_id, run_id)
        if self._task is None or self._task.done() or self._run_id != run_id or not self._teaching:
            return False
        await engine_for(self._deps.state).stop()
        await asyncio.gather(self._task, return_exceptions=True)
        return True

    async def wait(self, run_id: str) -> None:
        if self._task is not None and self._run_id == run_id:
            await asyncio.gather(self._task, return_exceptions=True)

    async def _run(
        self, identity: Identity, row: dict[str, Any], q: Question, rows: list[Row],
        run: dict[str, Any], epochs: int, engine: Any,
    ) -> None:  # fmt: skip
        store = store_for(self._deps.state)
        run_id, base = run["id"], run["base"]
        token = set_context(RunContext(identity.tenant_id, PRODUCT_ID, identity.user_id))
        folder = run_folder(store, identity, run_id)
        try:
            await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
            train, held = decision.split(rows)
            job = DecisionJob(
                q,
                train,
                held,
                epochs,
                run["steps"],
                decision.test_texts(train, held),
                run["settings"],
            )
            result = await engine.train(
                job, base, folder, lambda step, stage: store.set_progress(run_id, step, stage)
            )
            store.set_progress(run_id, run["steps"], "Counting words to compare")
            counter = decision.WordCounter(train)
            baseline = [counter.predict(r.text) for r in held]
            model = await self._keep(identity, row, q, rows, train, held, run, result, baseline)
            store.finish_run(run_id, "done", elapsed_s=result.seconds, model_id=model["id"])
            self._teaching = False
            await RouteGuard(self._deps.state, PRODUCT_ID).record(
                identity, EV_RUN, 1, "runs", steps=run["steps"], seconds=result.seconds, preview=False,
            )  # fmt: skip
            await add_to_search(self._deps.state, identity, model["id"], words_of(model))
        except Stopped as e:
            store.finish_run(run_id, "cancelled", error=str(e))
        except asyncio.CancelledError:
            store.finish_run(run_id, "cancelled", error="Stopped.")
            raise
        except Exception:
            log.exception("a decision run failed")
            store.finish_run(run_id, "failed", error="The model could not be taught. Try again.")
        finally:
            self._teaching = False
            reset_context(token)

    async def _keep(
        self, identity: Identity, row: dict[str, Any], q: Question, rows: list[Row],
        train: list[Row], held: list[Row], run: dict[str, Any], result: Any, baseline: list[str],
    ) -> dict[str, Any]:  # fmt: skip
        store = store_for(self._deps.state)
        d = bases.descriptor(run["base"])
        rep = decision.report(q, held, result.before, result.after, baseline)
        card = {
            "kind": KIND, "base": run["base"], "base_title": d.title if d else run["base"],
            "licence": d.licence if d else "", "engine": result.engine, "preview": False,
            "question": q.public(),
            "dataset": {"name": row["name"], "kind": KIND, "examples": len(rows),
                        "hash": set_hash(q, rows)},
            "settings": run["settings"], "steps": run["steps"], "seconds": round(result.seconds, 1),
            "peak_memory_gb": round(result.peak_bytes / 1024**3, 1) if result.peak_bytes else None,
            "loss": result.loss,
            "peek": [{"text": t, "before": said_out(b), "after": said_out(a)}
                     for t, b, a in zip(decision.test_texts(train, held), result.peek_before, result.peek_after, strict=False)],
            "report": rep, "statement": STATEMENTS.get(row["rights"], ""),
            "evaluation": {"passed": rep["passed"], "note": rep["note"]},
            "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }  # fmt: skip
        model = store.add_model(
            identity.tenant_id, identity.user_id, run_id=run["id"], dataset_id=row["id"],
            name=row["name"] or "My decision model", trigger_word="", kind=KIND, base=run["base"],
            card=card, preview=False, adapter_bytes=result.bytes,
        )  # fmt: skip
        target = model_folder(store, identity, model["id"]) / "model"
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.move, str(result.folder), str(target))
        return model


def folder_of(store: Any, identity: Identity, model_id: str) -> Path:
    return model_folder(store, identity, model_id) / "model"


def manager_for(deps: RouteDeps) -> DecisionRunManager:
    existing = getattr(deps.state, "decision_runs", None)
    if existing is None:
        existing = DecisionRunManager(deps)
        deps.state.decision_runs = existing
    return existing


class CannotDecide(Exception):
    """A text cannot be decided now; `str(e)` is the sentence to show and `code` says why."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


async def decide(
    deps: RouteDeps, identity: Identity, model_id: str, texts: list[str], original: bool = False
) -> dict[str, Any]:
    """The taught model's answer to each text (and, when asked, the untaught model's answer to the
    same texts), with how sure it is. Raises `CannotDecide`."""
    try:
        engine = engine_for(deps.state)
    except NotAvailable as e:
        raise CannotDecide("not_available", str(e)) from None
    store = store_for(deps.state)
    from wasifyai_training.store import NotFound

    try:
        row = store.get_model(identity.tenant_id, identity.user_id, model_id)
    except NotFound:
        raise CannotDecide("not_found", "That decision model does not exist.") from None
    if row["kind"] != KIND:
        raise CannotDecide("not_found", "That is not a decision model.")
    if manager_for(deps).busy() or manager_for(deps).others_busy():
        raise CannotDecide("busy", "A model is being taught. Wait for it to finish.")
    folder = folder_of(store, identity, model_id)
    if not await asyncio.to_thread((folder / "model.safetensors").is_file):
        raise CannotDecide("gone", "The taught model's files are gone.")
    c = row["card"]["question"]
    q = Question(
        c["kind"], c["text"], tuple(decision.Option(o["label"], o["about"]) for o in c["options"]),
        int(c["levels"]), c["low"], c["high"],
    )  # fmt: skip
    try:
        mine = await engine.answer(folder, q, texts)
        first = None
        if original:
            base = engine.base_folder(row["base"])
            first = await engine.answer(base, q, texts) if base else None
    except RuntimeError as e:
        raise CannotDecide("not_ready", str(e)) from None
    out: dict[str, Any] = {
        "question": q.text, "kind": q.kind, "answers": q.answers(),
        "results": [said_out(s) for s in mine],
    }  # fmt: skip
    if first is not None:
        out["original"] = [said_out(s) for s in first]
    return out
