# ruff: noqa: E501  (the sentences shown to people are easier to read on one line)
"""Teach it from examples: the runs of a set of examples (ADR-0074).

A writing set is questions with the answers a person would write. A run asks the chosen model the
test questions first, teaches it (`desktop_language_training`), asks again with the adapter, and keeps
the adapter as a model with its card: the answers before and after, side by side, and a mark that
says in words whether it learnt. One run at a time on this computer, and not while a picture model
is being taught: both hold the one big-model slot (ADR-0056)."""

import asyncio
import hashlib
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk import Identity, RouteDeps, RouteGuard, RunContext, set_context
from wasifyai_platform_sdk.context import reset_context

from wasifyai_training import bases, language
from wasifyai_training.language import LanguageJob, Stopped
from wasifyai_training.runtime import (
    EV_RUN,
    PRODUCT_ID,
    STATEMENTS,
    NotAvailable,
    Refused,
    add_to_search,
    folder_saved,
    model_folder,
    run_folder,
    run_manager_for,
    store_for,
    words_of,
)

log = logging.getLogger(__name__)

KIND = "writing"
# the held-out loss must fall by this share for the check to say it learnt (the spike's run fell by
# half: 5.3 to 2.6); below it the mark is "did not pass", never a block
LEARNT_BY = 0.2


def engine_for(state: Any) -> Any:
    engine = state.language_training
    if engine is None:
        raise NotAvailable("Teaching a writing model is not available here.")
    return engine


def set_hash(examples: list[language.Example]) -> str:
    h = hashlib.sha256()
    for e in examples:
        h.update(e.ask.encode())
        h.update(b"\0")
        h.update(e.answer.encode())
        h.update(b"\0")
    return h.hexdigest()[:16]


def evaluation_of(first: float | None, last: float | None, held: int) -> dict[str, Any]:
    """The mark and its sentence, from the loss on the answers kept back (ADR-0074 decision 7)."""
    if first is None or last is None or first <= 0:
        return {"passed": None, "note": "It could not be checked: no answers were kept back."}
    closer = round(100 * (first - last) / first)
    if last <= first * (1 - LEARNT_BY):
        return {
            "passed": True,
            "note": f"On {held} answers it had not seen, it got {closer} percent closer to your answers.",
        }
    return {
        "passed": False,
        "note": f"On {held} answers it had not seen, it got only {max(0, closer)} percent closer to "
        "your answers. It did not pass: add more examples, or longer ones.",
    }


class WritingRunManager:
    """Starts and cancels the runs of writing sets."""

    def __init__(self, deps: RouteDeps):
        self._deps = deps
        self._task: asyncio.Task[None] | None = None
        self._run_id: str | None = None
        # teaching, not what comes after it (the usage record, the search index): the next run or
        # a question may start as soon as the model is kept
        self._teaching = False

    def busy(self) -> bool:
        return self._teaching

    def active(self) -> str | None:
        return self._run_id if self._teaching else None

    def plan(self, identity: Identity, set_id: str) -> dict[str, Any]:
        """What a run of this set would take, and what stops it: the words of the Check step."""
        store = store_for(self._deps.state)
        row = store.get_writing_set(identity.tenant_id, identity.user_id, set_id)
        examples, said = language.clean(
            store.list_examples(identity.tenant_id, identity.user_id, set_id)
        )
        train, valid = language.split(examples) if len(examples) >= 2 else (examples, [])
        steps = language.steps_for(len(train), row["quality"])
        d = bases.descriptor(row["base"]) or bases.descriptors("language")[0]
        return {
            "examples": len(examples), "dropped": said, "checks": language.checks(examples),
            "steps": steps, "estimate": estimate_words(steps, d), "base": d.id, "base_title": d.title,
            "base_note": d.note, "held_back": len(valid),
            "missing": missing(row, examples) or self._base_missing(d),
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
        row = store.get_writing_set(identity.tenant_id, identity.user_id, set_id)
        try:
            chosen, how = bases.resolve(KIND, row["base"] or None, None)
        except bases.Unavailable as e:
            raise Refused("cannot_teach", str(e)) from None
        if why := engine.problem(chosen.id):
            if "not on this computer" in why:
                why = f"{chosen.title} is not on this computer yet. Get it first, next to its name."
            raise Refused("not_ready", why)
        if self.busy() or run_manager_for(self._deps).busy() or decision_busy(self._deps):
            raise Refused("busy", "A model is being taught. Wait for it to finish.")
        examples, _ = language.clean(
            store.list_examples(identity.tenant_id, identity.user_id, set_id)
        )
        if why := missing(row, examples):
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
        train, valid = language.split(examples)
        steps = language.steps_for(len(train), row["quality"])
        run = store.add_run(
            identity.tenant_id, identity.user_id, set_id, base=chosen.id, steps=steps,
            settings={"family": "language", "kind": KIND, "steps": steps, "method": how,
                      "engine": chosen.engine, "quality": row["quality"], "examples": len(examples)},
            preview=False,
        )  # fmt: skip
        self._run_id = run["id"]
        self._teaching = True
        self._task = asyncio.create_task(self._run(identity, row, examples, run, engine))
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
        self, identity: Identity, row: dict[str, Any], examples: list[language.Example],
        run: dict[str, Any], engine: Any,
    ) -> None:  # fmt: skip
        store = store_for(self._deps.state)
        run_id, base = run["id"], run["base"]
        token = set_context(RunContext(identity.tenant_id, PRODUCT_ID, identity.user_id))
        folder = run_folder(store, identity, run_id)
        try:
            await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
            train, valid = language.split(examples)
            questions = language.test_questions(train, valid)
            job = LanguageJob(
                [language.record(e) for e in train], [language.record(e) for e in valid],
                run["steps"], questions, settings=run["settings"],
            )  # fmt: skip
            store.set_progress(run_id, 0, "Asking the model first")
            before = await engine.answer(base, questions)
            result = await engine.train(
                job, base, folder, lambda step, stage: store.set_progress(run_id, step, stage)
            )
            store.set_progress(run_id, run["steps"], "Asking it again")
            after = await engine.answer(base, questions, result.adapter)
            model = await self._keep(identity, row, examples, run, result, questions, before, after)
            store.finish_run(run_id, "done", elapsed_s=result.seconds, model_id=model["id"])
            self._teaching = False
            await RouteGuard(self._deps.state, PRODUCT_ID).record(
                identity,
                EV_RUN,
                1,
                "runs",
                steps=run["steps"],
                seconds=result.seconds,
                preview=False,
            )
            await add_to_search(self._deps.state, identity, model["id"], words_of(model))
        except Stopped as e:
            store.finish_run(run_id, "cancelled", error=str(e))
        except asyncio.CancelledError:
            store.finish_run(run_id, "cancelled", error="Stopped.")
            raise
        except Exception:
            log.exception("a writing run failed")
            store.finish_run(run_id, "failed", error="The model could not be taught. Try again.")
        finally:
            self._teaching = False
            reset_context(token)

    async def _keep(
        self, identity: Identity, row: dict[str, Any], examples: list[language.Example],
        run: dict[str, Any], result: Any, questions: list[str], before: list[str], after: list[str],
    ) -> dict[str, Any]:  # fmt: skip
        store = store_for(self._deps.state)
        d = bases.descriptor(run["base"])
        _, valid = language.split(examples)
        adapter = result.adapter / "adapters.safetensors"
        card = {
            "kind": KIND, "base": run["base"], "base_title": d.title if d else run["base"],
            "licence": d.licence if d else "", "engine": result.engine, "preview": False,
            "dataset": {"name": row["name"], "kind": KIND, "examples": len(examples),
                        "hash": set_hash(examples)},
            "settings": run["settings"], "steps": run["steps"], "seconds": round(result.seconds, 1),
            "peak_memory_gb": round(result.peak_bytes / 1024**3, 1) if result.peak_bytes else None,
            "loss": {"first_held_back": result.first_val, "last_held_back": result.last_val,
                     "last_train": result.last_train},
            "answers": [{"question": q, "before": b, "after": a}
                        for q, b, a in zip(questions, before, after, strict=True)],
            "statement": STATEMENTS.get(row["rights"], ""),
            "evaluation": evaluation_of(result.first_val, result.last_val, len(valid)),
            "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }  # fmt: skip
        size = (await asyncio.to_thread(adapter.stat)).st_size
        model = store.add_model(
            identity.tenant_id, identity.user_id, run_id=run["id"], dataset_id=row["id"],
            name=row["name"] or "My model", trigger_word="", kind=KIND, base=run["base"],
            card=card, preview=False, adapter_bytes=size,
        )  # fmt: skip
        target = model_folder(store, identity, model["id"]) / "adapter"
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.move, str(result.adapter), str(target))
        await folder_saved(self._deps.state, identity, "models", model["id"])
        return model


def decision_busy(deps: RouteDeps) -> bool:
    """Whether a decision or a video model is being taught (they share the one big-model slot)."""
    found = (getattr(deps.state, name, None) for name in ("decision_runs", "video_runs"))
    return any(f is not None and f.busy() for f in found)


def adapter_of(store: Any, identity: Identity, model_id: str) -> Path:
    return model_folder(store, identity, model_id) / "adapter"


def missing(row: dict[str, Any], examples: list[language.Example]) -> str | None:
    """What is missing before a run, in the sentence the person is shown; None when nothing is."""
    if why := language.blocker(examples):
        return why
    if not row["rights"]:
        return "Say whose these examples are first."
    return None


def estimate_words(steps: int, d: bases.Descriptor) -> str:
    """ "About N minutes" from the seconds a step took when the base was measured (loading included)."""
    seconds = steps * d.seconds_per_step + d.overhead_s
    return "Under a minute" if seconds < 60 else f"About {round(seconds / 60)} minutes"


def manager_for(deps: RouteDeps) -> WritingRunManager:
    existing = deps.state.writing_runs
    if existing is None:
        existing = WritingRunManager(deps)
        deps.state.writing_runs = existing
    return existing
