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
from wasifyai_api.services import services_of

log = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["models"])

CHAT_ALIAS = "default-chat"
MEDIA_PRODUCTS = {
    "images": "wasifyai-image", "video": "wasifyai-video", "three_d": "wasifyai-model3d",
}  # fmt: skip
# fal.ai's models by the names people know (ADR-0095, K5); another model is shown as it is named
FAL_NAMES = {
    "fal-ai/flux-2": "FLUX.2", "fal-ai/flux-2/edit": "FLUX.2",
    "fal-ai/ltx-2/text-to-video/fast": "LTX-2", "fal-ai/ltx-2/image-to-video/fast": "LTX-2",
    "fal-ai/pixal3d": "Pixal3D", "fal-ai/kokoro": "Kokoro",
}  # fmt: skip
SENT = {
    "images": "What you describe and the pictures you add are sent to fal.ai.",
    "video": "What you describe and the pictures you add are sent to fal.ai.",
    "three_d": "The picture you add is sent to fal.ai.",
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
    three_d: list[InUseModel] = []  # only when an admin put 3D on a provider (fal.ai)


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


def _titles(request: Request, product_id: str) -> list[str]:
    from wasifyai_api.desktop_models import load_catalogue

    pdir = services_of(request).products_dir
    if pdir is None:
        return []
    try:
        return [e.title for e in load_catalogue(Path(pdir), [product_id])]
    except Exception:
        log.warning("could not read the models of %s", product_id, exc_info=True)
        return []


async def _media(request: Request, who: Identity, group: str) -> list[InUseModel]:
    media = services_of(request).media
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
    main = next((i for i in items if i.capability.endswith(".generate")), items[0])
    if main.backend == "fal":
        model = main.config.get("model", "")
        return [
            InUseModel(
                id=f"{product_id}:fal",
                title=f"{FAL_NAMES.get(model, model or 'fal.ai')} · fal.ai",
                plain=f"Chosen by your admin. {SENT[group]}",
                ready=main.key_set,
            )
        ]
    if group == "three_d":  # the engine workers: the 3D screen reads them itself
        return []
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
                )
                for n, title in enumerate(known)
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
        three_d=await _media(request, who, "three_d"),
    )
