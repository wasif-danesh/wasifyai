"""One job at a time per GPU, and free the GPU of LLMs before generating (docs/environments.md)."""

import asyncio
import logging
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol
from uuid import uuid4

import httpx
from redis.asyncio import Redis

log = logging.getLogger(__name__)

# Both act only if this worker still owns the lock.
_RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end
return 0
"""
_RENEW = """
if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('PEXPIRE', KEYS[1], ARGV[2]) end
return 0
"""


class GpuLock(Protocol):
    def hold(self) -> AbstractAsyncContextManager[None]: ...


class LocalGpuLock:
    """Single-process lock, for tests and one-worker setups."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def hold(self):
        async with self._lock:
            yield


class RedisGpuLock:
    """Workers on different machines or pods that share a GPU id take turns. The lock expires on
    its own if a worker dies, and a healthy holder keeps renewing it."""

    def __init__(self, redis: Redis, gpu_id: str, ttl_ms: int = 60_000, poll_s: float = 1.0):
        self._r = redis
        self._key = f"wasifyai:gpu:{gpu_id}"
        self._ttl = ttl_ms
        self._poll = poll_s
        self._release = redis.register_script(_RELEASE)
        self._renew = redis.register_script(_RENEW)

    @asynccontextmanager
    async def hold(self):
        owner = str(uuid4())
        # Polling a Redis lock: there is no notification for it to expire or be released.
        while not await self._r.set(self._key, owner, nx=True, px=self._ttl):  # noqa: ASYNC110
            await asyncio.sleep(self._poll)

        async def keep_alive() -> None:
            while True:
                await asyncio.sleep(self._ttl / 3000)
                await self._renew(keys=[self._key], args=[owner, self._ttl])

        renewer = asyncio.create_task(keep_alive())
        try:
            yield
        finally:
            renewer.cancel()
            await asyncio.gather(renewer, return_exceptions=True)
            await self._release(keys=[self._key], args=[owner])


async def unload_llms(ollama_base_url: str, http: httpx.AsyncClient) -> list[str]:
    """Ask Ollama to drop every loaded model (keep_alive 0) so the image/audio model gets the
    whole GPU. The next chat request reloads its model. Best effort."""
    try:
        r = await http.get(f"{ollama_base_url.rstrip('/')}/api/ps")
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        for name in models:
            await http.post(
                f"{ollama_base_url.rstrip('/')}/api/generate", json={"model": name, "keep_alive": 0}
            )
        if models:
            log.info("unloaded LLMs before generation: %s", models)
        return models
    except (httpx.HTTPError, ValueError):
        log.warning("could not unload LLMs from Ollama", exc_info=True)
        return []
