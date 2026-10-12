"""The product's read API: a user's transcripts (ADR-0023, ADR-0043), under /products/wasifyai-stt/.

Every query is scoped by tenant, product and user. A transcript still being made has a row but no
words yet; the site polls `GET /transcripts?status=working` to show "being made" on any page. The
words are returned only to their owner and are never written to a log."""

import json
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from wasifyai_platform_sdk import Identity, RouteDeps, parse_ids

from wasifyai_stt.formats import content_disposition, to_srt, to_text, to_vtt
from wasifyai_stt.languages import load_languages
from wasifyai_stt.transcripts import PostgresTranscriptStore, TranscriptRecord, TranscriptStore

PRODUCT_ID = "wasifyai-stt"
PREVIEW = 160


class SpokenLanguage(BaseModel):
    id: str
    name: str
    english: str
    quality: Literal["good", "fair", "limited", "unrated"]


class LanguageCatalog(BaseModel):
    languages: list[SpokenLanguage]
    max_seconds: int = 1800
    max_bytes: int = 104857600


class Segment(BaseModel):
    start: float
    end: float
    text: str


class TranscriptSummary(BaseModel):
    id: str
    title: str
    status: Literal["working", "done", "failed"]
    language: str
    language_name: str
    seconds: float
    created_at: datetime
    preview: str
    error: str | None = None  # plain text for the user, only when status is "failed"


class TranscriptDetail(TranscriptSummary):
    text: str
    segments: list[Segment]


class TranscriptPage(BaseModel):
    transcripts: list[TranscriptSummary]
    next_before: datetime | None  # pass as `before` to get the next page; null at the end


def _language_name(code: str) -> str:
    known = load_languages().get(code)
    return known.name if known else code


def _summary(t: TranscriptRecord) -> dict[str, Any]:
    assert t.created_at is not None
    return {
        "id": t.id,
        "title": t.title,
        "status": t.status,
        "language": t.language,
        "language_name": _language_name(t.language),
        "seconds": t.seconds,
        "created_at": t.created_at,
        "preview": " ".join(t.text.split())[:PREVIEW],
        "error": t.error if t.status == "failed" else None,
    }


def build_routes(
    deps: RouteDeps, store: TranscriptStore | None = None, limits: dict[str, int] | None = None
) -> APIRouter:
    """`store` is injectable for tests; production reads the shared database."""
    router = APIRouter(tags=[PRODUCT_ID])

    def transcripts() -> TranscriptStore:
        return store or PostgresTranscriptStore(deps.engine)

    @router.get("/languages", response_model=LanguageCatalog)
    async def languages(identity: Identity = Depends(deps.identity)) -> LanguageCatalog:
        """The languages to choose from, and what an upload may be."""
        return LanguageCatalog(
            languages=[SpokenLanguage(**x) for x in load_languages().public()["languages"]],
            max_seconds=(limits or {}).get("max_seconds", 1800),
            max_bytes=(limits or {}).get("max_bytes", 104857600),
        )

    @router.get("/transcripts", response_model=TranscriptPage)
    async def list_transcripts(
        limit: int = Query(20, ge=1, le=50),
        before: datetime | None = None,
        status: Literal["working", "done", "failed"] | None = None,
        ids: str | None = Query(None, max_length=2000),
        identity: Identity = Depends(deps.identity),
    ) -> TranscriptPage:
        wanted = parse_ids(ids)  # "these transcripts, in this order": the cards for search results
        if wanted is not None:
            found = [
                await transcripts().get(identity.tenant_id, identity.user_id, i) for i in wanted
            ]
            return TranscriptPage(
                transcripts=[TranscriptSummary(**_summary(t)) for t in found if t is not None],
                next_before=None,
            )
        rows = await transcripts().list(
            identity.tenant_id, identity.user_id, limit + 1, before, status
        )
        page, more = rows[:limit], len(rows) > limit
        return TranscriptPage(
            transcripts=[TranscriptSummary(**_summary(t)) for t in page],
            next_before=page[-1].created_at if more and page else None,
        )

    @router.get("/transcripts/{transcript_id}", response_model=TranscriptDetail)
    async def get_transcript(
        transcript_id: str, identity: Identity = Depends(deps.identity)
    ) -> TranscriptDetail:
        t = await transcripts().get(identity.tenant_id, identity.user_id, transcript_id)
        if t is None:  # also what another user's transcript looks like: no existence leak
            raise HTTPException(404, "transcript not found")
        return TranscriptDetail(
            **_summary(t), text=t.text, segments=[Segment(**s) for s in t.segments]
        )

    @router.get("/transcripts/{transcript_id}/download")
    async def download(
        transcript_id: str,
        format: Literal["txt", "srt", "vtt", "json"] = "txt",
        identity: Identity = Depends(deps.identity),
    ) -> Response:
        """The transcript as a file the browser saves: plain text, SRT, WebVTT or JSON."""
        t = await transcripts().get(identity.tenant_id, identity.user_id, transcript_id)
        if t is None or t.status != "done":
            raise HTTPException(404, "transcript not found")
        if format == "srt":
            body, mime = to_srt(t.segments), "application/x-subrip"
        elif format == "vtt":
            body, mime = to_vtt(t.segments), "text/vtt"
        elif format == "json":
            body = json.dumps(
                {
                    "title": t.title,
                    "language": t.language,
                    "seconds": t.seconds,
                    "text": t.text,
                    "segments": t.segments,
                },
                ensure_ascii=False,
                indent=2,
            )
            mime = "application/json"
        else:
            body, mime = to_text(t.text), "text/plain"
        return Response(
            body.encode("utf-8"),
            media_type=f"{mime}; charset=utf-8",
            headers={
                "Content-Disposition": content_disposition(t.title, format),
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.delete("/transcripts/{transcript_id}", status_code=204)
    async def delete_transcript(
        transcript_id: str, identity: Identity = Depends(deps.identity)
    ) -> Response:
        """Delete a transcript (or dismiss a failed one). One still being made cannot be deleted."""
        t = await transcripts().get(identity.tenant_id, identity.user_id, transcript_id)
        if t is None:
            raise HTTPException(404, "transcript not found")
        if t.status == "working":
            raise HTTPException(409, "That recording is still being transcribed.")
        await transcripts().delete(identity.tenant_id, identity.user_id, transcript_id)
        await deps.unindex(identity, PRODUCT_ID, transcript_id)  # out of search too (ADR-0041)
        return Response(status_code=204)

    return router
