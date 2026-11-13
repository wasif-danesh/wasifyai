# ruff: noqa: E501
"""The looks (video) and styles (pictures) a person taught, for the web (docs/train-web-plan.md).

On the desktop a look is a file in the shared `loras` folder and a request names it. On the web it is the person's own file in
object storage and is never shared: a request names it, this finds the storage key of **that person's** look by that name (or says
it is not theirs), and the media worker fetches the file for that one job."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from wasifyai_api.remote_train import look_key

FIRST_VIDEO_MODEL = "ltx-video-2b"  # every look taught before looks recorded their model


def person_looks(
    state: Any, video: bool = True
) -> Callable[[str, str, list[str]], Awaitable[dict[str, str] | None]]:
    async def resolve(tenant: str, user: str, names: list[str]) -> dict[str, str] | None:
        store = state.training_store
        if store is None:
            return {}
        models = await asyncio.to_thread(store.list_models, tenant, user, 500)
        mine = {
            (m["card"].get("published") or {}).get("lora_name"): m
            for m in models
            if (m["card"].get("family") == "video") == video
        }
        out: dict[str, str] = {}
        for name in names:
            model = mine.get(name)
            if model is None:
                return None
            out[name] = look_key(tenant, user, model["run_id"], name)
        return out

    return resolve


def look_models(state: Any) -> Callable[[str, str, list[str]], Awaitable[dict[str, str]]]:
    """Which video model each of a person's looks was taught on, by the look's file name (desktop and web):
    a look works only with that model (ADR-0097). A look this cannot find is left out, and the request goes
    on to the other checks (the web's says it is not theirs; the desktop's file may be one put there by hand)."""

    async def resolve(tenant: str, user: str, names: list[str]) -> dict[str, str]:
        store = state.training_store
        if store is None:
            try:  # the desktop opens the training store when the training product first needs it
                from wasifyai_training.runtime import store_for
            except ImportError:  # a build without training: no looks were taught here
                return {}
            store = store_for(state)
        models = await asyncio.to_thread(store.list_models, tenant, user, 500)
        out: dict[str, str] = {}
        for m in models:
            card = m["card"]
            name = (card.get("published") or {}).get("lora_name")
            if card.get("family") == "video" and name in names:
                out[name] = str(m.get("base") or card.get("base") or FIRST_VIDEO_MODEL)
        return out

    return resolve
