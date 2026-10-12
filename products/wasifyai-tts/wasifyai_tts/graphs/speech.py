# pyright: reportTypedDictNotRequiredAccess=false
# (Graph state is filled in node by node; a node only reads keys that earlier nodes have set.)
"""The text to speech graph: guardrail, one job, finish (ADR-0042).

    check_request -> start_job -> await_job -> finalise
        |
        v
      refuse

Graph code names capabilities (`text.moderate`, `speech.synthesize`), never models or voices: the
voice catalog (`voices.yaml`) turns the user's language and male or female choice into an engine, a
model and a voice. The job is two nodes: one enqueues, one waits, because a paused node re-runs from
its start on resume."""

import logging
import re
from typing import Any, Literal, TypedDict, cast
from uuid import uuid4

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from wasifyai_platform_sdk import Capabilities, RunError, await_job, require_context

from wasifyai_tts import guardrail
from wasifyai_tts.index import index_text
from wasifyai_tts.schemas import MAX_TEXT_CHARS
from wasifyai_tts.speeches import (
    SPEECH_CREATED,
    InMemorySpeechStore,
    PostgresSpeechStore,
    Quota,
    SpeechError,
    SpeechRecord,
    SpeechStore,
    UsageQuota,
    to_mp3,
    wav_seconds,
)
from wasifyai_tts.voices import Catalog, NoVoice, load_catalog

log = logging.getLogger(__name__)

Status = Literal["working", "done", "refused", "failed"]


class SpeechState(TypedDict, total=False):
    # request
    text: str
    language: str
    gender: str
    voice: str  # optional: a catalog voice id; the language's default otherwise
    # the voice chosen
    voice_id: str
    voice_label: str
    # job and result
    job_id: str
    result_key: str
    speech_id: str
    audio_key: str
    audio_url: str
    seconds: float
    characters: int
    # outcome
    status: Status
    refusal: dict[str, str]


def _clean(value: object, limit: int) -> str:
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(value or ""))
    return re.sub(r"[ \t]+", " ", text).strip()[:limit]


def build_speech(caps: Capabilities, checkpointer: Any):
    """Registry entry point: wires the production stores from the capabilities."""
    speeches: SpeechStore = (
        PostgresSpeechStore(caps.db) if caps.db is not None else InMemorySpeechStore()
    )
    quota: Quota | None = UsageQuota(caps.db) if caps.db is not None else None
    return build_speech_graph(caps, checkpointer, speeches, quota, load_catalog())


def build_speech_graph(
    caps: Capabilities,
    checkpointer: Any,
    speeches: SpeechStore,
    quota: Quota | None,
    catalog: Catalog,
):
    limit = (caps.config.quotas.get("speeches_per_user_per_day") if caps.config else None) or None

    async def over_quota() -> bool:
        if not await caps.safeguards_on():  # ADR-0047: quotas apply only with safeguards
            return False
        return bool(limit and quota and await quota.used_today(require_context()) >= limit)

    def quota_message() -> str:
        return f"You've reached today's limit of {limit} speeches. Please try again tomorrow."

    def refuse_with(code: str, message: str) -> SpeechState:
        return {"status": "refused", "refusal": {"code": code, "message": message}}

    # ---- guardrail ----------------------------------------------------------------------

    async def check_request(state: SpeechState) -> SpeechState:
        write = get_stream_writer()
        write(
            {
                "type": "node",
                "node": "check_request",
                "status": "started",
                "label": "Checking your text",
            }
        )
        text = _clean(state.get("text"), MAX_TEXT_CHARS + 1)
        if not text:
            return refuse_with("invalid_request", "Please type the text you want to hear.")
        if len(text) > MAX_TEXT_CHARS:
            return refuse_with(
                "invalid_request", f"Please keep it under {MAX_TEXT_CHARS} characters."
            )
        try:
            voice = catalog.resolve(
                str(state.get("language") or ""),
                str(state.get("gender") or ""),
                state.get("voice") or None,
            )
        except NoVoice as exc:
            return refuse_with("no_voice", exc.message)
        if await over_quota():  # before any LLM or model work
            return refuse_with("quota_exceeded", quota_message())
        if await caps.safeguards_on():  # ADR-0047
            verdict = await guardrail.judge_text(caps, text)
            if not verdict.allowed:
                return refuse_with(verdict.category, guardrail.refusal_message(verdict.category))
        return {
            "text": text,
            "language": state["language"],
            "gender": state["gender"],
            "voice_id": voice.id,
            "voice_label": voice.label,
            "characters": len(text),
            "status": "working",
        }

    def after_check(state: SpeechState) -> str:
        return "refuse" if state.get("status") == "refused" else "start_job"

    async def refuse(state: SpeechState) -> SpeechState:
        return {}

    # ---- the job ------------------------------------------------------------------------

    async def start_job(state: SpeechState) -> SpeechState:
        if await over_quota():  # again, right before the model is used
            raise RunError("quota_exceeded", quota_message())
        get_stream_writer()(
            {
                "type": "node",
                "node": "generate_speech",
                "status": "started",
                "label": "Making your speech",
            }
        )
        voice = catalog.resolve(state["language"], state["gender"], state["voice_id"])
        engine = catalog.engines[voice.engine]
        handle = await caps.speech.synthesize(
            text=state["text"],
            language=state["language"],
            engine=voice.engine,
            model=engine.model,
            voice=voice.engine_voice,
            max_chars=engine.max_chars,
        )
        return {"job_id": handle.job_id}

    async def await_job_node(state: SpeechState) -> SpeechState:
        result = await_job(state["job_id"])
        return {"result_key": result.outputs["audio"].key}

    # ---- finish -------------------------------------------------------------------------

    async def finalise(state: SpeechState) -> SpeechState:
        assert caps.storage is not None, "object storage is required"
        ctx = require_context()
        speech_id = str(uuid4())
        wav = await caps.storage.get(state["result_key"])
        try:
            seconds = wav_seconds(wav)
            mp3 = await to_mp3(wav, state["text"])
        except SpeechError:
            raise RunError(
                "speech_failed", "The speech couldn't be saved. Please try again.", retryable=True
            ) from None
        audio_key = f"{speech_id}/speech.mp3"
        await caps.storage.put(audio_key, mp3, "audio/mpeg")
        try:
            await caps.storage.delete(state["result_key"])  # the worker's temporary WAV
        except FileNotFoundError:
            pass
        await speeches.add(
            SpeechRecord(
                id=speech_id,
                tenant_id=ctx.tenant_id,
                product_id=ctx.product_id,
                user_id=ctx.user_id,
                thread_id=ctx.thread_id,
                run_id=ctx.run_id,
                text=state["text"],
                language=state["language"],
                gender=state["gender"],
                voice=state["voice_id"],
                characters=state["characters"],
                seconds=round(seconds, 2),
                audio_key=audio_key,
            )
        )
        language = catalog.language(state["language"])
        await caps.index_creation(
            "speech", speech_id, index_text(state["text"], language.english if language else "")
        )  # ADR-0041
        await caps.record_usage(
            SPEECH_CREATED, 1, "speeches",  # one per result: the daily quota counts these
            speech_id=speech_id, characters=state["characters"],
            seconds=round(seconds, 2), language=state["language"],
        )  # fmt: skip
        return {
            "speech_id": speech_id,
            "audio_key": audio_key,
            "audio_url": await caps.storage.url(audio_key),
            "seconds": round(seconds, 2),
            "status": "done",
        }

    g = StateGraph(SpeechState)
    for name, fn in [
        ("check_request", check_request),
        ("refuse", refuse),
        ("start_job", start_job),
        ("await_job", await_job_node),
        ("finalise", finalise),
    ]:
        g.add_node(name, cast(Any, fn))
    g.add_edge(START, "check_request")
    g.add_conditional_edges(
        "check_request", after_check, {"refuse": "refuse", "start_job": "start_job"}
    )
    g.add_edge("refuse", END)
    g.add_edge("start_job", "await_job")
    g.add_edge("await_job", "finalise")
    g.add_edge("finalise", END)
    return g.compile(checkpointer=checkpointer)
