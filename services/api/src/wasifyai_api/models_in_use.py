"""Which models this service uses, for everyone who is signed in (ADR-0086 on the web).

An admin chooses what serves chat, images and video (`/admin/models`, `/admin/media`); a person only
needs to see what that is, so the "Select ... model" button on the web screens can name it. Nothing
here changes anything, and no key, address or setting is returned: only a title, a plain line and
whether it is set up.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from wasifyai_api.identity import Identity, get_identity

log = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["models"])

CHAT_ALIAS = "default-chat"
MEDIA_PRODUCTS = {"images": "wasifyai-image", "video": "wasifyai-video"}


class InUseModel(BaseModel):
    id: str
    title: str
    plain: str
    ready: bool
    licence: str = ""


class InUse(BaseModel):
    chat: list[InUseModel] = []
    images: list[InUseModel] = []
    video: list[InUseModel] = []


def _name(model: str | None) -> str:
    """`ollama_chat/gemma4:e4b` is shown as `gemma4:e4b`."""
    return (model or "").rsplit("/", 1)[-1]


async def _chat(request: Request) -> list[InUseModel]:
    access = getattr(request.app.state, "models", None)
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


def _titles(request: Request, product_id: str) -> list[tuple[str, str]]:
    from wasifyai_api.desktop_models import load_catalogue

    pdir = getattr(request.app.state, "products_dir", None)
    if pdir is None:
        return []
    try:
        return [(e.title, e.licence) for e in load_catalogue(Path(pdir), [product_id])]
    except Exception:
        log.warning("could not read the models of %s", product_id, exc_info=True)
        return []


async def _media(request: Request, who: Identity, group: str) -> list[InUseModel]:
    media = getattr(request.app.state, "media", None)
    if media is None:
        return []
    product_id = MEDIA_PRODUCTS[group]
    try:
        listing = await media.list(who.tenant_id)
    except Exception:
        log.warning("could not read the media setup for the picker", exc_info=True)
        return []
    items = [i for i in listing.items if i.product_id == product_id]
    if not items:
        return []
    labels = {b.id: b.label for b in listing.backends}
    # the product's own workflow runs the catalogue's model; another backend is named by its service
    if all(i.source == "default" for i in items):
        known = _titles(request, product_id)
        if known:
            return [
                InUseModel(
                    id=f"{product_id}:{n}",
                    title=title,
                    plain="Set up on this service by an admin.",
                    ready=True,
                    licence=licence,
                )
                for n, (title, licence) in enumerate(known)
            ]
    first = items[0]
    return [
        InUseModel(
            id=f"{product_id}:{first.backend}",
            title=labels.get(first.backend, first.backend),
            plain="The service an admin chose for this.",
            ready=True,
        )
    ]


@router.get("/in-use", response_model=InUse)
async def in_use(request: Request, who: Identity = Depends(get_identity)) -> InUse:
    return InUse(
        chat=await _chat(request),
        images=await _media(request, who, "images"),
        video=await _media(request, who, "video"),
    )
