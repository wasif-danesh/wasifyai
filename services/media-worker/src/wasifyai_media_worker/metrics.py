"""Prometheus metrics for the media worker (ADR-0048). Labels are the capability and the status."""

import asyncio
import logging
from typing import Any

from prometheus_client import Counter, Gauge, Histogram, start_http_server
from wasifyai_platform_sdk.jobqueue import JOBS_GROUP, JOBS_STREAM

log = logging.getLogger(__name__)

JOBS = Counter("wdai_jobs_total", "Media jobs that finished", ["capability", "status"])
JOB_SECONDS = Histogram(
    "wdai_job_seconds",
    "Time a media job took on the worker",
    ["capability"],
    buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600, 5400),
)
GPU_SECONDS = Counter("wdai_job_gpu_seconds_total", "GPU seconds used by jobs", ["capability"])
QUEUED = Gauge("wdai_jobs_queued", "Jobs waiting for a worker")
IN_FLIGHT = Gauge("wdai_jobs_in_flight", "Jobs a worker has taken and not finished")
WORKER_UP = Gauge("wdai_worker_up", "1 while the worker loop is running")


def record_job(capability: str, status: str, seconds: float, gpu_seconds: float) -> None:
    JOBS.labels(capability, status).inc()
    JOB_SECONDS.labels(capability).observe(max(seconds, 0.0))
    if gpu_seconds > 0:
        GPU_SECONDS.labels(capability).inc(gpu_seconds)


async def watch_queue(redis: Any, every_s: float = 5.0) -> None:
    """Keep the queue gauges current: waiting (given to no worker) and in flight."""
    while True:
        try:
            groups: Any = await redis.xinfo_groups(JOBS_STREAM)
            group = next((g for g in groups if g["name"] == JOBS_GROUP), None)
            if group is not None:
                QUEUED.set(float(group.get("lag") or 0))
                IN_FLIGHT.set(float(group.get("pending") or 0))
        except Exception:  # the queue may not exist yet; the gauges keep their last value
            pass
        await asyncio.sleep(every_s)


def serve(port: int) -> None:
    if port <= 0:
        return
    try:
        start_http_server(port)
        log.info("metrics on :%d", port)
    except OSError:
        log.warning("metrics port %d is busy", port)
