"""The chat's plan for the window (ADR-0110): which plan the chat answers on, and the models each
program offers it. Setting up the programs and signing in are Code's routes (ADR-0107,
`/products/wasifyai-code/harnesses`); nothing here reads or keeps a login."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from wasifyai_platform_sdk import Identity

from wasifyai_api.coding_harness import HARNESSES
from wasifyai_api.identity import get_identity
from wasifyai_api.plan_chat import MODELS, PlanChat, valid_choice
from wasifyai_api.services import services_of

router = APIRouter(prefix="/desktop", tags=["desktop"])


class ChatPlanIn(BaseModel):
    harness: str | None = None  # None: the chat answers on its model again
    model: str = ""  # "" is the program's own choice


def _plan(request: Request) -> PlanChat:
    plan = services_of(request).chat_plan
    if plan is None:
        raise HTTPException(404, "not available in this deployment")
    return plan


def _view(plan: PlanChat) -> dict[str, Any]:
    choice = plan.choices.get()
    return {
        "choice": choice.as_dict() if choice else None,
        "programs": [
            {
                "id": h.id,
                "title": h.title,
                "models": [{"id": m, "name": name} for m, name in MODELS.get(h.id, ())],
            }
            for h in HARNESSES.values()
        ],
    }


@router.get("/chat-plan")
async def chat_plan(request: Request, _: Identity = Depends(get_identity)) -> dict[str, Any]:
    return _view(_plan(request))


@router.put("/chat-plan")
async def set_chat_plan(
    body: ChatPlanIn, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    plan = _plan(request)
    if body.harness is None:
        plan.choices.set(None)
    else:
        choice = valid_choice(body.harness, body.model)
        if choice is None:
            raise HTTPException(422, "There is no such program or model.")
        plan.choices.set(choice)
    return _view(plan)
