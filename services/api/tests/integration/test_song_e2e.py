"""A whole song through the real stack: API + Redis pipeline + media worker (stub) + Postgres,
with the real model (via LiteLLM) writing the guardrail verdicts and the lyrics.

Skipped unless Postgres (migrated), Redis and LiteLLM are reachable. Runs as a throwaway tenant
and user so it cannot touch your dev quota; its rows are deleted afterwards."""

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import text
from wasifyai_api.config import get_settings
from wasifyai_api.main import create_app
from wasifyai_media_worker.consumer import Worker
from wasifyai_media_worker.gpu import RedisGpuLock
from wasifyai_media_worker.processor import JobProcessor, StubRunner
from wasifyai_media_worker.settings import WorkerSettings
from wasifyai_media_worker.state import RedisJobState
from wasifyai_music import register
from wasifyai_platform_sdk import (
    GraphRegistry,
    PostgresUsageRecorder,
    RedisEventLog,
    RedisJobSink,
    RedisRunStore,
    ScopedStorage,
    memory_storage,
)

from .conftest import PRODUCTS_DIR


def parse(text_: str) -> list[tuple[str, dict]]:
    out = []
    for block in text_.strip().split("\n\n"):
        lines = [ln for ln in block.split("\n") if not ln.startswith(":")]
        if lines:
            out.append(
                (lines[1].removeprefix("event: "), json.loads(lines[2].removeprefix("data: ")))
            )
    return out


@pytest.fixture
async def identity(engine, monkeypatch):
    tenant, user = f"it-songs-{uuid4().hex[:8]}", f"user-{uuid4().hex[:8]}"
    monkeypatch.setenv("DEFAULT_TENANT_ID", tenant)
    monkeypatch.setenv("DEV_USER_ID", user)
    monkeypatch.setenv("WASIFYAI_MUSIC__QUOTAS__SONGS_PER_USER_PER_DAY", "1")
    get_settings.cache_clear()
    yield tenant, user
    get_settings.cache_clear()
    async with engine.begin() as conn:
        for table in ("songs", "usage_events"):
            await conn.execute(text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": tenant})


async def test_a_song_end_to_end_then_the_quota_stops_the_next_one(
    engine, redis_conn, litellm_settings, identity
):
    tenant, user = identity
    raw = memory_storage()
    log = RedisEventLog(redis_conn)
    registry = GraphRegistry()
    register(registry)
    app = create_app(
        registry,
        PRODUCTS_DIR,
        InMemorySaver(),
        None,  # usage goes to Postgres
        ScopedStorage(raw),
        engine,
        heartbeat_s=0.2,
        event_log=log,
        run_store=RedisRunStore(redis_conn),
        job_sink=RedisJobSink(redis_conn, log),
        redis=redis_conn,
    )
    worker_usage = PostgresUsageRecorder(engine)
    processor = JobProcessor(
        WorkerSettings(ollama_base_url="", job_timeout_s=60),
        RedisEventLog(redis_conn),
        raw,
        worker_usage,
        StubRunner(),
        RedisGpuLock(redis_conn, "song-e2e"),
        RedisJobState(redis_conn),
    )

    async with app.router.lifespan_context(app):
        worker = asyncio.create_task(Worker(redis_conn, processor).run_forever())
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://t", timeout=300
            ) as c:
                # 1. the request streams lyrics, then waits for the user
                r = await c.post(
                    "/products/wasifyai-music/runs",
                    json={
                        "input": {
                            "idea": "a rainy night in Tokyo",
                            "genre": "indie pop",
                            "mood": "mellow",
                        }
                    },
                )
                first = parse(r.text)
                names = [e for e, _ in first]
                assert names[-1] == "interrupt", first[-1]
                tokens = "".join(d["text"] for e, d in first if e == "token")
                prompt = first[-1][1]["payload"]  # what the UI shows the user
                assert prompt["kind"] == "approve_lyrics" and prompt["error"] == ""
                assert tokens.strip() == prompt["lyrics"].strip()  # the stream IS the lyrics
                assert "[verse]" in prompt["lyrics"] and "[chorus]" in prompt["lyrics"]
                run_id = first[0][1]["run_id"]

                # 2. approve: music job, then cover job, then done
                r = await c.post(f"/runs/{run_id}/resume", json={"value": {"action": "approve"}})
                rest = parse(r.text)
                assert rest[-1][0] == "done", rest[-1]
                jobs = [(d["capability"], d["status"]) for e, d in rest if e == "job_progress"]
                assert jobs.index(("music.generate", "completed")) < jobs.index(
                    ("image.generate", "queued")
                )
                out = rest[-1][1]["outputs"]
                assert out["status"] == "done" and out["audio_url"] and out["cover_url"]
                assert out["audio_key"] == f"{out['song_id']}/audio.wav"  # stub worker makes wav
                seqs = [d["seq"] for _, d in first + rest]
                assert seqs == list(
                    range(1, len(seqs) + 1)
                )  # one ordered stream across both requests

                # 3. quota (1 a day here): the next request is refused before any model runs
                r = await c.post(
                    "/products/wasifyai-music/runs", json={"input": {"idea": "another song"}}
                )
                refused = parse(r.text)[-1]
                assert refused[0] == "done" and refused[1]["outputs"]["status"] == "refused"
                assert refused[1]["outputs"]["refusal"]["code"] == "quota_exceeded"
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

    async with engine.connect() as conn:
        song = (
            await conn.execute(
                text("SELECT title, audio_key, cover_key, user_id FROM songs WHERE tenant_id=:t"),
                {"t": tenant},
            )
        ).one()
        kinds = {
            r[0]
            for r in await conn.execute(
                text("SELECT DISTINCT kind FROM usage_events WHERE tenant_id=:t"), {"t": tenant}
            )
        }
    assert song[3] == user and song[1].endswith("/audio.wav") and song[2].endswith("/cover.png")
    assert {
        "song.created",
        "llm.input_tokens",
        "llm.output_tokens",
        "gpu.seconds",
        "job.completed",
    } <= kinds
