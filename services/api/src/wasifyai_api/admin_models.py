"""Admin routes for model access (ADR-0025): see, change, test and reset what serves each alias.

API keys are write-only: they arrive in a request body, go to LiteLLM, and appear nowhere else,
not in responses, the audit log or the logs."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from wasifyai_platform_sdk import need

from wasifyai_api.admin import AuditEntry
from wasifyai_api.identity import Identity, require_admin
from wasifyai_api.litellm_admin import BackendError
from wasifyai_api.model_access import (
    Binding,
    ModelAccess,
    ModelAccessError,
    ModelView,
    ProviderView,
    TestOutcome,
)
from wasifyai_api.services import services_of

router = APIRouter(prefix="/admin/models", tags=["admin"])


class ModelList(BaseModel):
    models: list[ModelView]
    providers: list[ProviderView]


class ModelUpdated(BaseModel):
    model: ModelView


def _models(request: Request) -> ModelAccess:
    return need(services_of(request).models, "model access")


async def _audit(request: Request, who: Identity, action: str, alias: str, **detail) -> None:
    await need(services_of(request).admin, "the admin store").audit(
        who.tenant_id,
        AuditEntry(
            id="", actor_user_id=who.user_id, action=action, target_type="model_alias",
            target_id=alias, detail=detail,
        ),
    )  # fmt: skip


def _describe(b: Binding) -> dict:
    """What goes in the audit log: never the key itself."""
    return {
        "provider": b.provider, "model": b.model, "api_base": b.api_base,
        "key_provided": bool(b.api_key),
    }  # fmt: skip


@router.get("", response_model=ModelList)
async def list_models(request: Request, who: Identity = Depends(require_admin)) -> ModelList:
    models = _models(request)
    try:
        return ModelList(models=await models.list(), providers=models.providers())
    except BackendError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.put("/{alias}", response_model=ModelUpdated)
async def set_model(
    alias: str, binding: Binding, request: Request, who: Identity = Depends(require_admin)
) -> ModelUpdated:
    try:
        view = await _models(request).set(alias, binding, who.user_id)
    except ModelAccessError as exc:
        raise HTTPException(422, str(exc)) from exc
    except BackendError as exc:
        raise HTTPException(502, str(exc)) from exc
    await _audit(request, who, "admin.model.update", alias, **_describe(binding))
    return ModelUpdated(model=view)


@router.post("/{alias}/test", response_model=TestOutcome)
async def test_model(
    alias: str,
    request: Request,
    binding: Binding | None = None,
    who: Identity = Depends(require_admin),
) -> TestOutcome:
    try:
        outcome = await _models(request).test(alias, binding)
    except ModelAccessError as exc:
        raise HTTPException(422, str(exc)) from exc
    except BackendError as exc:
        raise HTTPException(502, str(exc)) from exc
    await _audit(
        request, who, "admin.model.test", alias,
        ok=outcome.ok, candidate=_describe(binding) if binding else None,
    )  # fmt: skip
    return outcome


@router.post("/{alias}/reset", response_model=ModelView)
async def reset_model(
    alias: str, request: Request, who: Identity = Depends(require_admin)
) -> ModelView:
    try:
        view = await _models(request).reset(alias, who.user_id)
    except ModelAccessError as exc:
        raise HTTPException(422, str(exc)) from exc
    except BackendError as exc:
        raise HTTPException(502, str(exc)) from exc
    await _audit(request, who, "admin.model.reset", alias)
    return view
