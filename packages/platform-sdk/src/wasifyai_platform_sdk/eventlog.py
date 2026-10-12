"""Per-run event log. Every run's SSE events are appended here by whoever produces them (the API
replica running the graph, or the media worker reporting job progress) and read by whichever API
replica serves the browser's stream. That is what lets any replica resume a run and any replica
serve its events (ADR-0021).

Events are plain dicts with an `event` type; the log assigns a monotonic `seq` per run, which is
also the SSE id, so `Last-Event-ID` reconnects work across replicas.
"""

import asyncio
import json
from collections import defaultdict
from typing import Any, Protocol

from redis.asyncio import Redis

TTL_SECONDS = 7 * 24 * 3600

# Atomically allocate the next seq and append the entry with that id. Writers on different
# processes can interleave safely: Redis stream ids must increase, and INCR guarantees it.
_APPEND = """
local seq = redis.call('INCR', KEYS[2])
redis.call('XADD', KEYS[1], seq .. '-0', 'd', ARGV[1])
redis.call('EXPIRE', KEYS[1], ARGV[2])
redis.call('EXPIRE', KEYS[2], ARGV[2])
return seq
"""


def events_key(tenant_id: str, run_id: str) -> str:
    return f"wasifyai:{tenant_id}:run:{run_id}:events"


def seq_key(tenant_id: str, run_id: str) -> str:
    return f"wasifyai:{tenant_id}:run:{run_id}:seq"


class EventLog(Protocol):
    async def append(self, tenant_id: str, run_id: str, event: dict[str, Any]) -> int: ...

    async def read(
        self, tenant_id: str, run_id: str, after: int, block_ms: int
    ) -> list[dict[str, Any]]:
        """Events with seq > `after`. Waits up to `block_ms` for one if none exist yet."""
        ...

    async def last_seq(self, tenant_id: str, run_id: str) -> int: ...


class InMemoryEventLog:
    """Single-process log for tests and Redis-less runs."""

    def __init__(self) -> None:
        self._events: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        self._cond: dict[tuple[str, str], asyncio.Condition] = defaultdict(asyncio.Condition)

    async def append(self, tenant_id: str, run_id: str, event: dict[str, Any]) -> int:
        key = (tenant_id, run_id)
        async with self._cond[key]:
            seq = len(self._events[key]) + 1
            self._events[key].append({**event, "seq": seq})
            self._cond[key].notify_all()
            return seq

    async def read(
        self, tenant_id: str, run_id: str, after: int, block_ms: int
    ) -> list[dict[str, Any]]:
        key = (tenant_id, run_id)
        async with self._cond[key]:
            if len(self._events[key]) <= after:
                try:
                    await asyncio.wait_for(self._cond[key].wait(), timeout=block_ms / 1000)
                except TimeoutError:
                    return []
            return list(self._events[key][after:])

    async def last_seq(self, tenant_id: str, run_id: str) -> int:
        return len(self._events[(tenant_id, run_id)])


class RedisEventLog:
    def __init__(self, redis: Redis):
        self._r = redis
        self._append = redis.register_script(_APPEND)

    async def append(self, tenant_id: str, run_id: str, event: dict[str, Any]) -> int:
        return int(
            await self._append(
                keys=[events_key(tenant_id, run_id), seq_key(tenant_id, run_id)],
                args=[json.dumps(event), TTL_SECONDS],
            )
        )

    async def read(
        self, tenant_id: str, run_id: str, after: int, block_ms: int
    ) -> list[dict[str, Any]]:
        res: Any = await self._r.xread(
            {events_key(tenant_id, run_id): f"{after}-0"}, count=200, block=max(block_ms, 1)
        )
        out: list[dict[str, Any]] = []
        for _stream, entries in res or []:
            for entry_id, fields in entries:
                data = fields[b"d"] if b"d" in fields else fields["d"]
                seq = int(
                    str(entry_id.decode() if isinstance(entry_id, bytes) else entry_id).split("-")[
                        0
                    ]
                )
                out.append({**json.loads(data), "seq": seq})
        return out

    async def last_seq(self, tenant_id: str, run_id: str) -> int:
        v: Any = await self._r.get(seq_key(tenant_id, run_id))
        return int(v) if v else 0
