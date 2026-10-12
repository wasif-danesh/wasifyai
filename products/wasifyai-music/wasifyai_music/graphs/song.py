# pyright: reportTypedDictNotRequiredAccess=false
# (Graph state is filled in node by node; a node only reads keys that earlier nodes have set.)
"""The song graph: guardrail, lyrics, user approval, music job, cover job, finish.

    check_request -> write_lyrics -> approve_lyrics -> start_music -> await_music
        |                ^                | |
        v                |__ regenerate __| |__ invalid edit: ask again
      refuse
    await_music -> screen_cover -> start_cover -> await_cover -> finalise

Graph code names capabilities (`text.moderate`, `text.lyrics`, `music.generate`,
`image.generate`), never models or workflow node IDs. Music and cover jobs run one after the
other (the worker decides scheduling). Each job is two nodes: one enqueues, one waits, because
a paused node re-runs from its start on resume.
"""

import logging
import re
import secrets
from typing import Any, Literal, TypedDict, cast
from uuid import uuid4

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import ValidationError
from wasifyai_platform_sdk import (
    Capabilities,
    JobFailed,
    RunError,
    await_job,
    require_context,
)

from wasifyai_music import guardrail, prompts
from wasifyai_music.index import index_text
from wasifyai_music.lyrics import (
    DraftInvalid,
    LyricsStreamer,
    lyric_problems,
    merge_tags,
    normalise_lyrics,
    parse_draft,
)
from wasifyai_music.schemas import MAX_IDEA_CHARS, MAX_TAG_CHARS, SONG_SCHEMA, Approval
from wasifyai_music.songs import (
    SONG_CREATED,
    InMemorySongStore,
    PostgresSongStore,
    Quota,
    SongRecord,
    SongStore,
    UsageQuota,
)

log = logging.getLogger(__name__)

MAX_LYRICS_ATTEMPTS = 3
MAX_REGENERATIONS = 5
URL_TTL_HINT = "1 hour"  # presigned links; the song stays in storage and can be re-linked
FALLBACK_COVER = "abstract album cover art in soft gradients, {style}, no text, no people"

Status = Literal["drafting", "awaiting_approval", "generating", "done", "refused", "failed"]


class SongState(TypedDict, total=False):
    # request
    idea: str
    genre: str
    mood: str
    # draft
    title: str
    lyrics: str
    style: str
    cover_prompt: str
    feedback: str  # tells the model what was wrong with its previous attempt
    regenerations: int
    decision: str  # approve | regenerate | invalid
    approval_error: str
    # jobs and results
    music_job_id: str
    cover_job_id: str
    audio_key: str
    cover_key: str
    cover_error: str
    song_id: str
    audio_url: str
    cover_url: str
    # outcome
    status: Status
    refusal: dict[str, str]


def _clean(value: object, limit: int) -> str:
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(value or ""))
    return re.sub(r"[ \t]+", " ", text).strip()[:limit]


def build_song(caps: Capabilities, checkpointer: Any):
    """Registry entry point: wires the production stores from the capabilities."""
    songs: SongStore = PostgresSongStore(caps.db) if caps.db is not None else InMemorySongStore()
    quota: Quota | None = UsageQuota(caps.db) if caps.db is not None else None
    return build_song_graph(caps, checkpointer, songs, quota)


def build_song_graph(caps: Capabilities, checkpointer: Any, songs: SongStore, quota: Quota | None):
    limit = (caps.config.quotas.get("songs_per_user_per_day") if caps.config else None) or None

    async def over_quota() -> bool:
        if not await caps.safeguards_on():  # ADR-0047: quotas apply only with safeguards
            return False
        return bool(limit and quota and await quota.used_today(require_context()) >= limit)

    def quota_message() -> str:
        return f"You've reached today's limit of {limit} songs. Please try again tomorrow."

    def refuse_with(code: str, message: str) -> SongState:
        return {"status": "refused", "refusal": {"code": code, "message": message}}

    # ---- guardrail ----------------------------------------------------------------------

    async def check_request(state: SongState) -> SongState:
        write = get_stream_writer()
        write(
            {
                "type": "node",
                "node": "check_request",
                "status": "started",
                "label": "Checking your request",
            }
        )
        idea = _clean(state.get("idea"), MAX_IDEA_CHARS + 1)
        if not idea:
            return refuse_with("invalid_request", "Please describe the song you would like.")
        if len(idea) > MAX_IDEA_CHARS:
            return refuse_with(
                "invalid_request", f"Please keep the idea under {MAX_IDEA_CHARS} characters."
            )
        genre, mood = (
            _clean(state.get("genre"), MAX_TAG_CHARS),
            _clean(state.get("mood"), MAX_TAG_CHARS),
        )

        if await over_quota():  # before any LLM or GPU work
            return refuse_with("quota_exceeded", quota_message())

        if await caps.safeguards_on():  # ADR-0047
            verdict = await guardrail.judge(
                caps, "song request", "\n".join(filter(None, [idea, genre, mood]))
            )
            if not verdict.allowed:
                return refuse_with(verdict.category, guardrail.refusal_message(verdict.category))
        return {
            "idea": idea,
            "genre": genre,
            "mood": mood,
            "status": "drafting",
            "regenerations": 0,
        }

    def after_check(state: SongState) -> str:
        return "refuse" if state.get("status") == "refused" else "write_lyrics"

    async def refuse(state: SongState) -> SongState:
        return {}

    # ---- lyrics -------------------------------------------------------------------------

    async def write_lyrics(state: SongState) -> SongState:
        write = get_stream_writer()
        feedback = state.get("feedback", "")
        system = prompts.load("lyrics")
        for attempt in range(1, MAX_LYRICS_ATTEMPTS + 1):
            # A repeated "started" tells the UI to clear what it has streamed so far.
            label = "Writing lyrics" if attempt == 1 else "Rewriting lyrics"
            write({"type": "node", "node": "write_lyrics", "status": "started", "label": label})
            user = prompts.render(
                "lyrics_request",
                idea=state.get("idea", ""),
                genre=state.get("genre") or "(your choice)",
                mood=state.get("mood") or "(your choice)",
                feedback=f"Fix this from your previous attempt: {feedback}" if feedback else "",
            )
            streamer, raw = LyricsStreamer(), []
            async for delta in caps.text.stream("lyrics", system, user, schema=SONG_SCHEMA):
                raw.append(delta)
                if shown := streamer.feed(delta):
                    write({"type": "token", "node": "write_lyrics", "text": shown})
            try:
                draft = parse_draft("".join(raw))
            except DraftInvalid as e:
                log.info("lyrics attempt %d rejected: %s", attempt, e)
                feedback = e.feedback
                continue
            return {
                "title": draft.title,
                "lyrics": draft.lyrics,
                "style": draft.style,
                "cover_prompt": draft.cover_prompt,
                "feedback": "",
                "approval_error": "",
                "status": "awaiting_approval",
            }
        raise RunError(
            "lyrics_failed",
            "We couldn't write usable lyrics for that idea. Try rephrasing it.",
            retryable=True,
        )

    # ---- approval -----------------------------------------------------------------------

    async def approve_lyrics(state: SongState) -> SongState:
        answer = interrupt(
            {
                "kind": "approve_lyrics",
                "title": state["title"],
                "lyrics": state["lyrics"],
                "style": state["style"],
                "regenerations_left": MAX_REGENERATIONS - state.get("regenerations", 0),
                "error": state.get("approval_error", ""),
            }
        )
        try:
            approval = Approval.model_validate(answer)
        except ValidationError:
            return {
                "decision": "invalid",
                "approval_error": "Please approve the lyrics or ask for new ones.",
            }

        if approval.action == "regenerate":
            used = state.get("regenerations", 0)
            if used >= MAX_REGENERATIONS:
                return {
                    "decision": "invalid",
                    "approval_error": "You've reached the limit of new drafts for this song.",
                }
            return {
                "decision": "regenerate",
                "regenerations": used + 1,
                "feedback": "",
                "approval_error": "",
            }

        title = _clean(approval.title, 80) if approval.title is not None else state["title"]
        style = _clean(approval.style, 200) if approval.style is not None else state["style"]
        lyrics = (
            normalise_lyrics(approval.lyrics) if approval.lyrics is not None else state["lyrics"]
        )
        if not title or not style:
            return {"decision": "invalid", "approval_error": "The title and style cannot be empty."}
        if len(lyrics) > 3000:
            return {
                "decision": "invalid",
                "approval_error": "The lyrics are too long (limit 3000 characters).",
            }
        if problems := lyric_problems(lyrics):
            return {
                "decision": "invalid",
                "approval_error": "The lyrics must " + " and ".join(problems) + ".",
            }

        # The text that will be sung is screened once, whether generated or edited.
        verdict = await guardrail.judge(caps, "lyrics", lyrics)
        if not verdict.allowed:
            return {
                "decision": "invalid",
                "approval_error": guardrail.refusal_message(verdict.category),
            }
        return {
            "decision": "approve",
            "title": title,
            "lyrics": lyrics,
            "style": style,
            "approval_error": "",
            "status": "generating",
        }

    def after_approval(state: SongState) -> str:
        return {"approve": "start_music", "regenerate": "write_lyrics"}.get(
            state.get("decision", ""), "approve_lyrics"
        )

    # ---- music --------------------------------------------------------------------------

    async def start_music(state: SongState) -> SongState:
        if await over_quota():  # again, right before the GPU is used
            raise RunError("quota_exceeded", quota_message())
        write = get_stream_writer()
        write(
            {
                "type": "node",
                "node": "generate_music",
                "status": "started",
                "label": "Making the music",
            }
        )
        tags = merge_tags(state.get("genre"), state.get("mood"), state["style"])
        handle = await caps.music.generate(
            lyrics=state["lyrics"], style=tags, seed=secrets.randbelow(2**31)
        )
        return {"music_job_id": handle.job_id}

    def await_music(state: SongState) -> SongState:
        result = await_job(state["music_job_id"])  # JobFailed ends the run with the job's error
        return {"audio_key": result.outputs["audio"].key}

    # ---- cover --------------------------------------------------------------------------

    async def screen_cover(state: SongState) -> SongState:
        write = get_stream_writer()
        write(
            {
                "type": "node",
                "node": "screen_cover",
                "status": "started",
                "label": "Preparing the cover art",
            }
        )
        verdict = await guardrail.judge(caps, "cover art description", state["cover_prompt"])
        if verdict.allowed:
            return {}
        # The song is already made; use a neutral cover rather than losing it.
        log.warning("cover prompt refused (%s); using the fallback", verdict.category)
        return {"cover_prompt": FALLBACK_COVER.format(style=state["style"].split(",")[0])}

    async def start_cover(state: SongState) -> SongState:
        write = get_stream_writer()
        write(
            {
                "type": "node",
                "node": "generate_cover",
                "status": "started",
                "label": "Painting the cover",
            }
        )
        handle = await caps.image.generate(
            prompt=state["cover_prompt"], seed=secrets.randbelow(2**31)
        )
        return {"cover_job_id": handle.job_id}

    def await_cover(state: SongState) -> SongState:
        try:
            result = await_job(state["cover_job_id"])
        except JobFailed as e:
            # Keep the song: the music is the product, the cover is a bonus.
            return {"cover_error": e.result.error.message if e.result.error else "cover failed"}
        return {"cover_key": result.outputs["image"].key}

    # ---- finish -------------------------------------------------------------------------

    async def finalise(state: SongState) -> SongState:
        assert caps.storage is not None, "object storage is required"
        ctx = require_context()
        song_id = str(uuid4())
        # Final layout {tenant}/wasifyai-music/{user}/{song_id}/audio.*; the worker's jobs/ paths
        # are
        # temporary.
        audio_key = await caps.storage.move(
            state["audio_key"], f"{song_id}/audio.{state['audio_key'].rsplit('.', 1)[-1]}"
        )
        cover_key = None
        if state.get("cover_key"):
            cover_key = await caps.storage.move(
                state["cover_key"], f"{song_id}/cover.{state['cover_key'].rsplit('.', 1)[-1]}"
            )
        await songs.add(
            SongRecord(
                id=song_id,
                tenant_id=ctx.tenant_id,
                product_id=ctx.product_id,
                user_id=ctx.user_id,
                thread_id=ctx.thread_id,
                run_id=ctx.run_id,
                title=state["title"],
                lyrics=state["lyrics"],
                style=state["style"],
                audio_key=audio_key,
                cover_key=cover_key,
            )
        )
        await caps.index_creation(
            "song", song_id, index_text(state["title"], state["style"], state["lyrics"])
        )  # searchable at once (ADR-0041); never fails the run
        await caps.record_usage(SONG_CREATED, 1, "songs", song_id=song_id)
        return {
            "song_id": song_id,
            "audio_key": audio_key,
            "cover_key": cover_key or "",
            "audio_url": await caps.storage.url(audio_key),
            "cover_url": await caps.storage.url(cover_key) if cover_key else "",
            "status": "done",
        }

    g = StateGraph(SongState)
    for name, fn in [
        ("check_request", check_request),
        ("refuse", refuse),
        ("write_lyrics", write_lyrics),
        ("approve_lyrics", approve_lyrics),
        ("start_music", start_music),
        ("await_music", await_music),
        ("screen_cover", screen_cover),
        ("start_cover", start_cover),
        ("await_cover", await_cover),
        ("finalise", finalise),
    ]:
        g.add_node(name, cast(Any, fn))
    g.add_edge(START, "check_request")
    g.add_conditional_edges(
        "check_request", after_check, {"refuse": "refuse", "write_lyrics": "write_lyrics"}
    )
    g.add_edge("refuse", END)
    g.add_edge("write_lyrics", "approve_lyrics")
    g.add_conditional_edges(
        "approve_lyrics",
        after_approval,
        {
            "start_music": "start_music",
            "write_lyrics": "write_lyrics",
            "approve_lyrics": "approve_lyrics",
        },
    )
    g.add_edge("start_music", "await_music")
    g.add_edge("await_music", "screen_cover")
    g.add_edge("screen_cover", "start_cover")
    g.add_edge("start_cover", "await_cover")
    g.add_edge("await_cover", "finalise")
    g.add_edge("finalise", END)
    return g.compile(checkpointer=checkpointer)
