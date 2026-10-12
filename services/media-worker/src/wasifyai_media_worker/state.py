"""Per-job bookkeeping that makes redelivery safe: attempts and the final result."""

from typing import Protocol

from redis.asyncio import Redis
from wasifyai_platform_sdk import JobResult

TTL_SECONDS = 7 * 24 * 3600


class JobState(Protocol):
    async def finished(self, tenant_id: str, job_id: str) -> JobResult | None: ...
    async def begin(self, tenant_id: str, job_id: str) -> int:
        """Record a processing attempt; returns the attempt number (1 = first)."""
        ...

    async def finish(self, tenant_id: str, job_id: str, result: JobResult) -> None: ...


class InMemoryJobState:
    def __init__(self) -> None:
        self._attempts: dict[tuple[str, str], int] = {}
        self._results: dict[tuple[str, str], JobResult] = {}

    async def finished(self, tenant_id: str, job_id: str) -> JobResult | None:
        return self._results.get((tenant_id, job_id))

    async def begin(self, tenant_id: str, job_id: str) -> int:
        self._attempts[(tenant_id, job_id)] = n = self._attempts.get((tenant_id, job_id), 0) + 1
        return n

    async def finish(self, tenant_id: str, job_id: str, result: JobResult) -> None:
        self._results[(tenant_id, job_id)] = result


class RedisJobState:
    def __init__(self, redis: Redis):
        self._r = redis

    @staticmethod
    def _key(tenant_id: str, job_id: str) -> str:
        return f"wasifyai:{tenant_id}:job:{job_id}"

    async def finished(self, tenant_id: str, job_id: str) -> JobResult | None:
        raw = await self._r.hget(self._key(tenant_id, job_id), "result")  # type: ignore[misc]
        return JobResult.model_validate_json(raw) if raw else None

    async def begin(self, tenant_id: str, job_id: str) -> int:
        key = self._key(tenant_id, job_id)
        n = await self._r.hincrby(key, "attempts", 1)  # type: ignore[misc]
        await self._r.expire(key, TTL_SECONDS)
        return int(n)

    async def finish(self, tenant_id: str, job_id: str, result: JobResult) -> None:
        await self._r.hset(self._key(tenant_id, job_id), "result", result.model_dump_json())  # type: ignore[misc]
