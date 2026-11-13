"""Images and video on the person's own key (ADR-0095, stage K3).

`KeyedMediaRouter` is the desktop worker's router: a job of a product set to a cloud model in the
picker's Cloud tab runs on the cheapest of that model's offers with a key saved in Settings › Your
keys (`OfferRunner`, which sends it through `FalRunner` on fal.ai and `CloudImageRunner` on
WaveSpeed and Runware; ADR-0100 stage CP3); every other job runs where it always did (the
computer's own ComfyUI). It is asked again for every job, so a change in the
picker applies to the next picture or clip."""

from typing import Any

import httpx
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
        if route is None or not route.choices:
            return self._local
        # the media worker is the desktop's (an extra of the API): imported where it runs
        from wasifyai_media_worker.backends import CloudChoice, OfferRunner

        choices = [CloudChoice(c.provider.id, c.key, c.base_url, c.offer) for c in route.choices]
        return OfferRunner(
            route.model, route.title or route.model, choices, self._http, self._timeout,
            self._poll,
        )  # fmt: skip
