"""Run records shared by all API replicas: who owns a run and what it is waiting for."""

from datetime import UTC, datetime
from typing import Any, Protocol, cast

from pydantic import BaseModel, Field
from redis.asyncio import Redis

TTL_SECONDS = 7 * 24 * 3600


class RunRecord(BaseModel):
    run_id: str
    thread_id: str
    product_id: str
    tenant_id: str
    user_id: str
    status: str = "running"  # running | waiting_input | waiting_job | done | error
    awaiting: str | None = None  # interrupt id a user must answer
    waiting_job: str | None = None  # job id the graph is paused on
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class RunStore(Protocol):
    async def create(self, rec: RunRecord) -> None: ...
    async def get(self, tenant_id: str, run_id: str) -> RunRecord | None: ...
    async def set_state(
        self,
        tenant_id: str,
        run_id: str,
        status: str,
        awaiting: str | None = None,
        waiting_job: str | None = None,
    ) -> None: ...
    async def take_awaiting(self, tenant_id: str, run_id: str) -> str | None:
        """Atomically clear and return the pending interrupt id (None if nothing is pending)."""
        ...

    async def take_waiting_job(self, tenant_id: str, run_id: str, job_id: str) -> bool:
        """Atomically clear the wait if the run is paused on exactly this job."""
        ...


class InMemoryRunStore:
    def __init__(self) -> None:
        self._runs: dict[tuple[str, str], RunRecord] = {}

    async def create(self, rec: RunRecord) -> None:
        self._runs[(rec.tenant_id, rec.run_id)] = rec

    async def get(self, tenant_id: str, run_id: str) -> RunRecord | None:
        rec = self._runs.get((tenant_id, run_id))
        return rec.model_copy() if rec else None

    async def set_state(
        self,
        tenant_id: str,
        run_id: str,
        status: str,
        awaiting: str | None = None,
        waiting_job: str | None = None,
    ) -> None:
        rec = self._runs[(tenant_id, run_id)]
        rec.status, rec.awaiting, rec.waiting_job = status, awaiting, waiting_job

    async def take_awaiting(self, tenant_id: str, run_id: str) -> str | None:
        rec = self._runs.get((tenant_id, run_id))
        if rec is None or not rec.awaiting:
            return None
        taken, rec.awaiting, rec.status = rec.awaiting, None, "running"
        return taken

    async def take_waiting_job(self, tenant_id: str, run_id: str, job_id: str) -> bool:
        rec = self._runs.get((tenant_id, run_id))
        if rec is None or rec.waiting_job != job_id:
            return False
        rec.waiting_job, rec.status = None, "running"
        return True


_TAKE = """
local v = redis.call('HGET', KEYS[1], ARGV[1])
if (not v) or v == '' or (ARGV[2] ~= '' and v ~= ARGV[2]) then return nil end
redis.call('HSET', KEYS[1], ARGV[1], '', 'status', 'running')
return v
"""


def run_key(tenant_id: str, run_id: str) -> str:
    return f"wasifyai:{tenant_id}:run:{run_id}:meta"


class RedisRunStore:
    def __init__(self, redis: Redis):
        self._r = redis
        self._take = redis.register_script(_TAKE)

    async def create(self, rec: RunRecord) -> None:
        key = run_key(rec.tenant_id, rec.run_id)
        data = {k: ("" if v is None else v) for k, v in rec.model_dump().items()}
        await self._r.hset(key, mapping=cast(Any, data))
        await self._r.expire(key, TTL_SECONDS)

    async def get(self, tenant_id: str, run_id: str) -> RunRecord | None:
        raw: Any = await self._r.hgetall(run_key(tenant_id, run_id))
        if not raw:
            return None
        d = {
            (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
            for k, v in raw.items()
        }
        d["awaiting"] = d.get("awaiting") or None
        d["waiting_job"] = d.get("waiting_job") or None
        return RunRecord(**d)

    async def set_state(
        self,
        tenant_id: str,
        run_id: str,
        status: str,
        awaiting: str | None = None,
        waiting_job: str | None = None,
    ) -> None:
        await self._r.hset(
            run_key(tenant_id, run_id),
            mapping={
                "status": status,
                "awaiting": awaiting or "",
                "waiting_job": waiting_job or "",
            },
        )

    async def take_awaiting(self, tenant_id: str, run_id: str) -> str | None:
        v = await self._take(keys=[run_key(tenant_id, run_id)], args=["awaiting", ""])
        return (v.decode() if isinstance(v, bytes) else v) if v else None

    async def take_waiting_job(self, tenant_id: str, run_id: str, job_id: str) -> bool:
        v = await self._take(keys=[run_key(tenant_id, run_id)], args=["waiting_job", job_id])
        return bool(v)
