# ruff: noqa: E501
"""The looks (video) and styles (pictures) a person taught, for the web (docs/train-web-plan.md).

On the desktop a look is a file in the shared `loras` folder and a request names it. On the web it is the person's own file in
object storage and is never shared: a request names it, this finds the storage key of **that person's** look by that name (or says
it is not theirs), and the media worker fetches the file for that one job."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from wasifyai_api.remote_train import look_key


def person_looks(
    state: Any, video: bool = True
) -> Callable[[str, str, list[str]], Awaitable[dict[str, str] | None]]:
    async def resolve(tenant: str, user: str, names: list[str]) -> dict[str, str] | None:
        store = getattr(state, "training_store", None)
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
