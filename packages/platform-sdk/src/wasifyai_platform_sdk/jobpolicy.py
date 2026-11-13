"""One job per person (ADR-0088, stage J4 of the 2026-10-27 plan): the one place that decides
whether a new job may enter a line, and the leases it counts.

Every way into a line asks `JobPolicy.admit` before queuing: the media sink (pictures and clips) and
the engine queue (speech, 3D models, Motion graphics and training on the web, which also covers the
products' own job managers there). The rule is "at most `limit` jobs in the line per person, across
everything", with `limit` read from a callable at the moment a job asks (`MAX_JOBS_PER_USER`; 0
means no limit, and the desktop is not limited). Admins and the admin jobs that fetch models are
exempt.

A job in the line holds a lease for its person: a record with an expiry a little longer than the
job's own time-out, taken when the job enters and given back when it ends, fails or is stopped, so a
crashed service cannot lock anyone out for ever. Counting reads the leases, not the queues, so it is
the same for every kind of job. A lease carries the job's kind and a cost class, unused while the
limit is one rule across everything; they are there for the changes ADR-0088 lists (a limit per
kind, a weight per job)."""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from redis.asyncio import Redis

from wasifyai_platform_sdk.context import current_context
from wasifyai_platform_sdk.errors import RunError
from wasifyai_platform_sdk.jobs import JobRequest, JobSink

EXEMPT_KINDS = ("admin.",)  # the jobs an admin starts to fetch a model or set up an engine
SYSTEM = "system"  # the service's own jobs (reading a trainer's words), started by nobody
LEASE_MARGIN_S = 300  # a lease outlives its job's time-out by this much
MEDIA_TIMEOUT_S = 1200  # the media worker's own time-out for a picture or a clip
BUSY = (
    "You already have something being made ({what}). Wait for it to finish, or stop it, then try "
    "again."
)

# words for the job in the way, by the start of its kind
KIND_WORDS: dict[str, str] = {
    "image.": "a picture",
    "video.": "a video",
    "speech.speak": "a speech",
    "speech.music": "a song",
    "speech.": "a voice job",
    "lipsync.": "a lip sync",
    "model3d.": "a 3D model",
    "builder.": "a motion graphics video",
    "train.": "a model being taught",
}


def words_for(kind: str) -> str:
    for prefix, words in sorted(KIND_WORDS.items(), key=lambda kv: -len(kv[0])):
        if kind.startswith(prefix):
            return words
    return "a job"


@dataclass(frozen=True)
class Lease:
    job_id: str
    kind: str
    cost: str
    expires: float


class JobLimitReached(RunError):
    """The person already has as many jobs in the line as they may: the refusal, in words, names the
    job in the way (ADR-0088 decision 5)."""

    def __init__(self, blocking: Lease):
        super().__init__("busy", BUSY.format(what=words_for(blocking.kind)), retryable=True)
        self.blocking = blocking


class LeaseStore(Protocol):
    async def take(self, tenant_id: str, user_id: str, lease: Lease, limit: int) -> Lease | None:
        """Take a lease when the person holds fewer than `limit` live ones (`None` back), else
        return one of those that are in the way and take nothing. Atomic across replicas."""
        ...

    async def give_back(self, tenant_id: str, user_id: str, job_id: str) -> None: ...

    async def held(self, tenant_id: str, user_id: str) -> list[Lease]: ...


class InMemoryLeases:
    """One process (tests, a single API, the desktop's engine)."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._by_person: dict[tuple[str, str], dict[str, Lease]] = {}
        self._clock = clock

    def _live(self, tenant_id: str, user_id: str) -> dict[str, Lease]:
        now = self._clock()
        mine = self._by_person.setdefault((tenant_id, user_id), {})
        for job_id in [j for j, lease in mine.items() if lease.expires <= now]:
            del mine[job_id]
        return mine

    async def take(self, tenant_id: str, user_id: str, lease: Lease, limit: int) -> Lease | None:
        mine = self._live(tenant_id, user_id)
        if lease.job_id in mine:
            return None  # the same job asking again (a retry): already in
        if len(mine) >= limit:
            return min(mine.values(), key=lambda held: held.expires)
        mine[lease.job_id] = lease
        return None

    async def give_back(self, tenant_id: str, user_id: str, job_id: str) -> None:
        self._live(tenant_id, user_id).pop(job_id, None)

    async def held(self, tenant_id: str, user_id: str) -> list[Lease]:
        return list(self._live(tenant_id, user_id).values())


# A sorted set per person (member = job id, score = expiry) and a hash of what each lease is.
# Drop the expired, then take only when under the limit; one script, so two replicas cannot both
# take the last place.
_TAKE = """
local now = tonumber(ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
if redis.call('ZSCORE', KEYS[1], ARGV[2]) then return '' end
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[4]) then
  local first = redis.call('ZRANGE', KEYS[1], 0, 0)[1]
  return redis.call('HGET', KEYS[2], first) or first
end
redis.call('ZADD', KEYS[1], ARGV[3], ARGV[2])
redis.call('HSET', KEYS[2], ARGV[2], ARGV[5])
redis.call('EXPIREAT', KEYS[1], math.ceil(tonumber(ARGV[3])))
redis.call('EXPIREAT', KEYS[2], math.ceil(tonumber(ARGV[3])))
return ''
"""


class RedisLeases:
    def __init__(self, redis: Redis, namespace: str = "wasifyai:leases"):
        self._r = redis
        self._ns = namespace
        self._script: Any = redis.register_script(_TAKE)

    def _keys(self, tenant_id: str, user_id: str) -> list[str]:
        base = f"{self._ns}:{tenant_id}:{user_id}"
        return [base, base + ":what"]

    async def take(self, tenant_id: str, user_id: str, lease: Lease, limit: int) -> Lease | None:
        what = json.dumps({"job_id": lease.job_id, "kind": lease.kind, "cost": lease.cost,
                           "expires": lease.expires})  # fmt: skip
        got = await self._script(
            keys=self._keys(tenant_id, user_id),
            args=[time.time(), lease.job_id, lease.expires, limit, what],
        )
        if not got:
            return None
        raw = got.decode() if isinstance(got, bytes) else str(got)
        try:
            d = json.loads(raw)
            return Lease(str(d["job_id"]), str(d["kind"]), str(d["cost"]), float(d["expires"]))
        except (ValueError, KeyError, TypeError):
            return Lease(raw, "", "normal", 0.0)  # a lease from before its record was kept

    async def give_back(self, tenant_id: str, user_id: str, job_id: str) -> None:
        zset, what = self._keys(tenant_id, user_id)
        await self._r.zrem(zset, job_id)
        await self._r.hdel(what, job_id)

    async def held(self, tenant_id: str, user_id: str) -> list[Lease]:
        zset, what = self._keys(tenant_id, user_id)
        await self._r.zremrangebyscore(zset, "-inf", time.time())
        out: list[Lease] = []
        for job_id in await self._r.zrange(zset, 0, -1):
            jid = job_id.decode() if isinstance(job_id, bytes) else str(job_id)
            raw = await self._r.hget(what, jid)
            if raw:
                d = json.loads(raw)
                out.append(Lease(jid, d["kind"], d["cost"], float(d["expires"])))
        return out


class JobPolicy:
    """The one place that decides whether a job may enter a line (ADR-0088 decision 2)."""

    def __init__(
        self, leases: LeaseStore, limit: Callable[[], int], clock: Callable[[], float] = time.time
    ):
        self.leases = leases
        self._limit = limit  # read at every admission: a new setting needs no release
        self._clock = clock

    def limit(self) -> int:
        return max(0, int(self._limit()))

    async def admit(
        self,
        tenant_id: str,
        user_id: str,
        job_id: str,
        kind: str,
        timeout_s: float,
        cost: str = "normal",
        role: str | None = None,
    ) -> None:
        """Let the job in (holding a lease for it), or raise `JobLimitReached` naming the job in the
        way. Exempt: no limit, an admin, an admin job."""
        limit = self.limit()
        if role is None:
            ctx = current_context()
            role = ctx.role if ctx is not None else "user"
        if limit == 0 or role == "admin" or user_id == SYSTEM or kind.startswith(EXEMPT_KINDS):
            return
        lease = Lease(job_id, kind, cost, self._clock() + timeout_s + LEASE_MARGIN_S)
        blocking = await self.leases.take(tenant_id, user_id, lease, limit)
        if blocking is not None:
            raise JobLimitReached(blocking)

    async def release(self, tenant_id: str, user_id: str, job_id: str) -> None:
        """The job ended, failed or was stopped: its place is free at once (ADR-0088 decision 5)."""
        await self.leases.give_back(tenant_id, user_id, job_id)


def no_limit() -> JobPolicy:
    """The policy where nobody is limited (the desktop, tests that do not test it)."""
    return JobPolicy(InMemoryLeases(), lambda: 0)


class AdmittedSink:
    """The media sink with the policy in front: a picture or clip enters the line only when its
    person may have one more (and holds a lease until its result comes back or it is stopped)."""

    def __init__(self, sink: JobSink, policy: JobPolicy, timeout_s: float = MEDIA_TIMEOUT_S):
        self.sink = sink
        self.policy = policy
        self._timeout = timeout_s

    async def submit(self, request: JobRequest) -> None:
        await self.policy.admit(
            request.tenant_id, request.user_id, request.job_id, request.capability, self._timeout
        )
        try:
            await self.sink.submit(request)
        except BaseException:
            await self.policy.release(request.tenant_id, request.user_id, request.job_id)
            raise

    def __getattr__(self, name: str) -> Any:
        return getattr(self.sink, name)  # the sink's own calls (the desktop queue's) go through
