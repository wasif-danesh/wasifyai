"""The action catalogue as this engine serves it (ADR-0068 decision 8).

    SDK built-ins     library.*, app.status, job.*        (they belong to no product)
    this module       models.*                            (the desktop's model library)
    each product      image.*, video.*, speech.* ...      (`actions.py`, registered like routes)

`build_registry` gathers them for the products this deployment serves, so a product that is not
served exposes nothing. `build_executor` adds the stores and the host. Run the module to write
or check `docs/contracts/actions.json`:

    uv run python -m wasifyai_api.actions_engine --write
    uv run python -m wasifyai_api.actions_engine --check
"""

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import GraphRegistry, UsageRecorder
from wasifyai_platform_sdk.actions import (
    Action,
    ActionContext,
    ActionExecutor,
    ActionHost,
    ActionRefused,
    ActionRegistry,
    CallBinding,
    InMemoryApprovalStore,
    InMemoryAuditStore,
    LibraryKind,
    Outcome,
    SqlApprovalStore,
    SqlAuditStore,
    builtin_actions,
    need_runtime,
    render,
)

from wasifyai_api.desktop_fit import assess_fit, need_declared
from wasifyai_api.mcp_client.actions import external_actions

ROOT = Path(__file__).resolve().parents[4]
CONTRACT = ROOT / "docs" / "contracts" / "actions.json"
MODELS_RUNTIME = "models"
CONSENT_DOWNLOAD = (
    "I agree to download this model to this computer. The files and their size are shown in the "
    "window before I approve."
)
MODELS = need_runtime(MODELS_RUNTIME)
SAMPLE_MODEL = "kokoro-82m"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _svc(ctx: ActionContext) -> Any:
    svc = getattr(getattr(ctx.deps, "state", None), "desktop_models", None)
    if svc is None:
        raise ActionRefused("unavailable", "Models are managed in the desktop app.")
    return svc


class ModelRow(BaseModel):
    model_id: str
    title: str
    status: str  # ready | partial | missing
    product_id: str
    bytes_missing: int = 0
    memory_warning: str | None = None


def _row(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "model_id": state["id"], "title": state["title"], "status": state["status"],
        "product_id": state["product_id"], "bytes_missing": state["bytes_missing"],
        "memory_warning": state.get("memory_warning"),
    }  # fmt: skip


# ---- models.list ------------------------------------------------------------------------------


class ListIn(Strict):
    task: str | None = Field(
        None, max_length=30, description="Only models for a task: speak, music, transcribe ..."
    )


class ListOut(BaseModel):
    models: list[ModelRow]


async def _list(p: ListIn, ctx: ActionContext) -> Outcome:
    svc = _svc(ctx)
    machine = await svc.machine()
    rows = [
        _row(svc.entry_state(e, machine))
        for e in svc.catalogue.values()
        if p.task is None or (e.voice is not None and p.task in e.voice.tasks)
    ]
    ready = [r for r in rows if r["status"] == "ready"]
    lines = [f"- {r['title']} ({r['status']}) id {r['model_id']}" for r in rows[:25]]
    return Outcome.ok(
        {"models": rows},
        f"{len(ready)} of {len(rows)} models are on this computer:\n" + "\n".join(lines),
    )


# ---- models.status ----------------------------------------------------------------------------


class StatusIn(Strict):
    model_id: str | None = Field(
        None, max_length=100, description="One model; omit for the downloads."
    )


class DownloadRow(BaseModel):
    download_id: str
    model_id: str
    status: str
    bytes_done: int
    bytes_total: int


class StatusOut(BaseModel):
    model: ModelRow | None = None
    download: DownloadRow | None = None
    disk_free_bytes: int


def _download(d: Any) -> dict[str, Any]:
    pub = d.public()
    return {
        "download_id": pub["id"], "model_id": pub["entry_id"], "status": pub["status"],
        "bytes_done": pub["bytes_done"], "bytes_total": pub["bytes_total"],
    }  # fmt: skip


async def _status(p: StatusIn, ctx: ActionContext) -> Outcome:
    from wasifyai_api.desktop_models import free_disk_bytes

    svc = _svc(ctx)
    out: dict[str, Any] = {"disk_free_bytes": free_disk_bytes(svc.models_dir)}
    text = []
    if p.model_id:
        entry = svc.catalogue.get(p.model_id)
        if entry is None:
            return Outcome.refused("This app does not know that model.", "unknown_model")
        row = _row(svc.entry_state(entry, await svc.machine()))
        out["model"] = row
        text.append(f"{row['title']} is {row['status']}.")
    active = svc.downloads.active or svc.downloads.latest()
    if active is not None and (p.model_id is None or active.entry_id == p.model_id):
        out["download"] = _download(active)
        done, total = active.bytes_done, active.bytes_total
        text.append(f"Download {active.status}: {done} of {total} bytes.")
    return Outcome.ok(out, " ".join(text) or "No download is running.")


# ---- models.download --------------------------------------------------------------------------


class DownloadIn(Strict):
    model_id: str = Field(min_length=1, max_length=100, description="From models.list.")


class DownloadOut(BaseModel):
    download_id: str
    model_id: str
    bytes_total: int


async def _download_check(p: DownloadIn, ctx: ActionContext) -> None:
    svc = _svc(ctx)
    entry = svc.catalogue.get(p.model_id)
    if entry is None:
        raise ActionRefused("unknown_model", "This app does not know that model.")
    if all(svc.locate(f) is not None for f in entry.files):
        raise ActionRefused("already_here", "Everything this model needs is already here.")
    if entry.approx_ram_gb:
        fit = assess_fit(need_declared(entry.approx_ram_gb), await svc.machine())
        if fit.verdict == "too_big":
            raise ActionRefused(
                "too_big", f"This model will not fit on this computer. {fit.reason}"
            )


async def _download_start(p: DownloadIn, ctx: ActionContext) -> Outcome:
    from wasifyai_api.desktop_models import DownloadError

    svc = _svc(ctx)
    entry = svc.catalogue[p.model_id]
    missing = [f for f in entry.files if svc.locate(f) is None]
    try:
        d = svc.downloads.start(entry, missing, svc.models_dir)
    except DownloadError as e:
        raise ActionRefused("busy", str(e)) from None
    total = sum(f.size for f in missing)
    return Outcome.ok(
        {"download_id": d.id, "model_id": p.model_id, "bytes_total": total},
        f"The download of {entry.title} started ({total // 1_000_000} MB). Check models.status.",
    )


def engine_actions() -> list[Action]:
    return [
        Action(
            id="models.list", title="Models on this computer",
            summary="Which models are here, partly here or missing.",
            description=(
                "List the models this app knows, with whether each is on this computer (ready), "
                "partly downloaded or missing, and how much is missing. Filter by task (speak, "
                "music, transcribe ...)."
            ),
            input=ListIn, output=ListOut, examples=({}, {"task": "speak"}),
            effect="read", requires=(MODELS,), bind=CallBinding(_list), ui="models",
        ),
        Action(
            id="models.status", title="Model and download status",
            summary="State of one model and of the running download.",
            description=(
                "The state of one model (ready, partial, missing), the progress of the download "
                "that runs now, and the free disk space."
            ),
            input=StatusIn, output=StatusOut, examples=({}, {"model_id": SAMPLE_MODEL}),
            effect="read", requires=(MODELS,), bind=CallBinding(_status), ui="models",
        ),
        Action(
            id="models.download", title="Get a model",
            summary="Download a model to this computer.",
            description=(
                "Start downloading a model that is missing. The person is always shown the files "
                "and their size in the app window and must approve. One download runs at a time; "
                "follow it with models.status."
            ),
            input=DownloadIn, output=DownloadOut, examples=({"model_id": SAMPLE_MODEL},),
            effect="make", flags=("needs_consent", "costly"), requires=(MODELS,),
            consent=CONSENT_DOWNLOAD,
            bind=CallBinding(_download_start, check=_download_check), ui="models",
        ),
    ]  # fmt: skip


# ---- the catalogue of this engine -------------------------------------------------------------


def build_registry(reg: GraphRegistry, served: Iterable[str] | None = None) -> ActionRegistry:
    """Every action of the products this deployment serves, plus the platform's own. A product
    that declares none exposes nothing (ADR-0057)."""
    ok = None if served is None else set(served)
    out = ActionRegistry([*builtin_actions(), *engine_actions(), *external_actions()])
    for product_id, provider in sorted(reg.action_providers().items()):
        if ok is None or product_id in ok:
            out.add_all(provider())
    return out


def library_kinds(
    reg: GraphRegistry, served: Iterable[str] | None = None
) -> dict[str, LibraryKind]:
    ok = None if served is None else set(served)
    kinds: dict[str, LibraryKind] = {}
    for product_id, provider in sorted(reg.library_providers().items()):
        if ok is None or product_id in ok:
            for kind in provider():
                kinds[kind.kind] = kind
    return kinds


def build_executor(
    reg: GraphRegistry,
    host: ActionHost,
    *,
    served: Iterable[str] | None = None,
    db: AsyncEngine | None = None,
    usage: UsageRecorder | None = None,
) -> ActionExecutor:
    """The executor of this engine. Audit and approvals live in the database the engine already
    has (Postgres on the web, the SQLite file on the desktop); without one, in memory."""
    return ActionExecutor(
        build_registry(reg, served),
        host,
        audit=SqlAuditStore(db) if db is not None else InMemoryAuditStore(),
        approvals=SqlApprovalStore(db) if db is not None else InMemoryApprovalStore(),
        usage=usage,
        library=library_kinds(reg, served),
    )


def default_catalogue() -> ActionRegistry:
    """Everything every installed product declares: what `docs/contracts/actions.json` holds."""
    from wasifyai_api.graphs import default_registry

    return build_registry(default_registry())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Write or check docs/contracts/actions.json")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    text = render(default_catalogue())
    if args.write:
        CONTRACT.parent.mkdir(parents=True, exist_ok=True)
        CONTRACT.write_text(text, encoding="utf-8")
        print(f"wrote {CONTRACT.relative_to(ROOT)}")
        return 0
    if not CONTRACT.is_file() or CONTRACT.read_text(encoding="utf-8") != text:
        print("docs/contracts/actions.json is out of date: run --write", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
