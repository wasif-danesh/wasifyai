"""Images and video on the person's own key (ADR-0095, stage K3).

`KeyedMediaRouter` is the desktop worker's router: a job of a product set to "With my key" in
Settings › Your keys runs on that provider (fal.ai, `FalRunner`) with that key; every other job runs
where it always did (the computer's own ComfyUI). It is asked again for every job, so a change in
Settings applies to the next picture or clip."""

from typing import Any

import httpx
from wasifyai_media_worker.backends import FalRunner
from wasifyai_platform_sdk import JobRequest

from wasifyai_api.own_keys import OwnKeysService

# which product's key a job follows (images and video here; speaking and 3D run outside this worker
# and follow theirs in `own_keys_engines.py`, K4)
PRODUCT_OF = {"wasifyai-image": "images", "wasifyai-video": "video"}


class KeyedMediaRouter:
    def __init__(
        self,
        local: Any,
        keys: OwnKeysService,
        http: httpx.AsyncClient,
        timeout_s: float,
        poll_s: float = 2.0,
    ):
        self._local = local  # the runner of this computer (ComfyUI, with its guards)
        self._keys = keys
        self._http = http
        self._timeout = timeout_s
        self._poll = poll_s

    async def resolve(self, job: JobRequest) -> Any:
        product = PRODUCT_OF.get(job.product_id)
        route = await self._keys.route(product) if product else None
        if route is None or route.provider.id != "fal":
            return self._local
        return FalRunner(
            route.key, route.model, self._http, self._timeout, self._poll, route.base_url
        )
