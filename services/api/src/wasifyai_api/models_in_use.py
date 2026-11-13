"""Which models this service uses, for everyone who is signed in (ADR-0086 on the web).

An admin chooses what serves chat (`/admin/models`) and the cloud model of images, video and 3D
(`/admin/media`, ADR-0100 CP11); a person only needs to see what that is, so the "Select ... model"
button on the web screens can name it. Nothing here changes anything, and no key, address or
setting is returned: only a title, a plain line and whether it is set up.
"""

import logging

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from wasifyai_api.identity import Identity, get_identity
from wasifyai_api.services import services_of

log = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["models"])

CHAT_ALIAS = "default-chat"
# the picker's groups that run on the service's cloud models (ADR-0099; ADR-0100, CP11), by the
# product of the keys service
MEDIA_PRODUCTS = {"images": "images", "video": "video", "three_d": "model3d"}
SENT = {
    "images": "What you describe and the pictures you add are sent to the provider that runs it.",
    "video": "What you describe and the pictures you add are sent to the provider that runs it.",
    "three_d": "The picture you add is sent to the provider that runs it.",
}


class InUseModel(BaseModel):
    id: str
    title: str
    plain: str
    ready: bool


class InUse(BaseModel):
    chat: list[InUseModel] = []
    images: list[InUseModel] = []
    video: list[InUseModel] = []
    three_d: list[InUseModel] = []


def _name(model: str | None) -> str:
    """`ollama_chat/gemma4:e4b` is shown as `gemma4:e4b`."""
    return (model or "").rsplit("/", 1)[-1]


async def _chat(request: Request) -> list[InUseModel]:
    access = services_of(request).models
    if access is None:
        return []
    try:
        views = await access.list()
    except Exception:  # the model gateway is down: say nothing rather than a wrong thing
        log.warning("could not read the chat model for the picker", exc_info=True)
        return []
    view = next((v for v in views if v.alias == CHAT_ALIAS), None)
    if view is None:
        return []
    ready = view.source != "missing"
    name = _name(view.model) or _name(
        (getattr(access, "_defaults", {}).get(CHAT_ALIAS, {}).get("litellm_params") or {}).get(
            "model"
        )
    )
    return [
        InUseModel(
            id=CHAT_ALIAS,
            title=name or "Chat model",
            plain="The model that answers in chat. An admin chooses it.",
            ready=ready,
        )
    ]


async def _media(request: Request, who: Identity, group: str) -> list[InUseModel]:
    """The cloud model the service runs the group on: the one the admin chose, else the first a
    key can run; with no key, the button says an admin has to add one."""
    providers = services_of(request).admin_providers
    if providers is None:
        return []
    try:
        route = await providers.for_tenant(who.tenant_id).route(MEDIA_PRODUCTS[group])
    except Exception:
        log.warning("could not read the cloud model for the picker", exc_info=True)
        return []
    if route is None:
        return [
            InUseModel(
                id=f"{group}:none", title="No cloud model yet",
                plain="An admin adds a Runware, WaveSpeed or fal.ai key in Admin › Media.",
                ready=False,
            )
        ]  # fmt: skip
    return [
        InUseModel(
            id=f"{group}:{route.model}", title=route.title or route.model,
            plain=f"Chosen by your admin. {SENT[group]}", ready=True,
        )
    ]  # fmt: skip


@router.get("/in-use", response_model=InUse)
async def in_use(request: Request, who: Identity = Depends(get_identity)) -> InUse:
    return InUse(
        chat=await _chat(request),
        images=await _media(request, who, "images"),
        video=await _media(request, who, "video"),
        three_d=await _media(request, who, "three_d"),
    )
