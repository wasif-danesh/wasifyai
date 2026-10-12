"""The product's read API: the voice catalog and a user's speech results (ADR-0023, ADR-0042), under
/products/wasifyai-tts/.

Every query is scoped by tenant, product and user, and every link is signed fresh."""

import unicodedata
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from wasifyai_platform_sdk import Identity, RouteDeps, parse_ids

from wasifyai_tts.speeches import PostgresSpeechStore, SpeechRecord, SpeechStore
from wasifyai_tts.voices import Catalog, load_catalog

PRODUCT_ID = "wasifyai-tts"


class VoiceChoice(BaseModel):
    id: str
    label: str
    default: bool
    quality: str  # "good", "fair" or "limited": how the voice's training data compares


class LanguageChoice(BaseModel):
    id: str
    name: str
    english: str
    genders: dict[str, list[VoiceChoice]]  # "female" and "male": empty when there is no voice


class VoiceCatalog(BaseModel):
    languages: list[LanguageChoice]


class SpeechSummary(BaseModel):
    id: str
    text: str
    language: str
    language_name: str
    gender: str
    voice: str  # the voice's label, for example "Heart"
    characters: int
    seconds: float
    created_at: datetime
    audio_url: str


class SpeechPage(BaseModel):
    speeches: list[SpeechSummary]
    next_before: datetime | None  # pass as `before` to get the next page; null at the end


def file_name(text: str, ext: str) -> str:
    """A safe, readable file name from the words: letters, marks and digits of any script, joined by
    hyphens (so a Bengali text gives a Bengali name)."""
    kept = "".join(c if unicodedata.category(c)[0] in "LMN" else " " for c in text.lower())
    slug = "-".join(kept.split())[:48].strip("-") or "speech"
    return f"{slug}.{ext}"


def content_disposition(text: str, ext: str) -> str:
    """The header that makes a browser save the file: an ASCII name for old clients and the real
    name (UTF-8, percent-encoded) for the rest (RFC 6266)."""
    name = file_name(text, ext)
    plain = "".join(c for c in name.rsplit(".", 1)[0] if c.isascii() and (c.isalnum() or c == "-"))
    ascii_name = f"{plain.strip('-') or 'speech'}.{ext}"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


def build_routes(
    deps: RouteDeps, store: SpeechStore | None = None, catalog: Catalog | None = None
) -> APIRouter:
    """`store` and `catalog` are injectable for tests; production reads the shared database."""
    router = APIRouter(tags=[PRODUCT_ID])

    def speeches() -> SpeechStore:
        return store or PostgresSpeechStore(deps.engine)

    def voices() -> Catalog:
        return catalog or load_catalog()

    async def summary(s: SpeechRecord) -> SpeechSummary:
        assert deps.storage is not None, "object storage is not configured"
        assert s.created_at is not None
        lang = voices().language(s.language)
        label = next((v.label for v in voices().voices if v.id == s.voice), s.voice)
        return SpeechSummary(
            id=s.id, text=s.text, language=s.language,
            language_name=lang.name if lang else s.language, gender=s.gender, voice=label,
            characters=s.characters, seconds=s.seconds, created_at=s.created_at,
            audio_url=await deps.storage.url(s.audio_key),
        )  # fmt: skip

    @router.get("/voices", response_model=VoiceCatalog)
    async def list_voices(identity: Identity = Depends(deps.identity)) -> VoiceCatalog:
        """The languages and voices the form offers: a gender with no voice is an empty list."""
        return VoiceCatalog(**voices().public())

    @router.get("/speeches", response_model=SpeechPage)
    async def list_speeches(
        limit: int = Query(20, ge=1, le=50),
        before: datetime | None = None,
        ids: str | None = Query(None, max_length=2000),
        identity: Identity = Depends(deps.identity),
    ) -> SpeechPage:
        wanted = parse_ids(ids)  # "these results, in this order": the cards for search results
        if wanted is not None:
            found = [await speeches().get(identity.tenant_id, identity.user_id, i) for i in wanted]
            with deps.acting_as(identity, PRODUCT_ID):
                got = [await summary(s) for s in found if s is not None]
            return SpeechPage(speeches=got, next_before=None)
        rows = await speeches().list(identity.tenant_id, identity.user_id, limit + 1, before)
        page, more = rows[:limit], len(rows) > limit
        with deps.acting_as(identity, PRODUCT_ID):
            items = [await summary(s) for s in page]
        return SpeechPage(
            speeches=items, next_before=page[-1].created_at if more and page else None
        )

    @router.get("/speeches/{speech_id}", response_model=SpeechSummary)
    async def get_speech(
        speech_id: str, identity: Identity = Depends(deps.identity)
    ) -> SpeechSummary:
        speech = await speeches().get(identity.tenant_id, identity.user_id, speech_id)
        if speech is None:  # also what another user's result looks like: no existence leak
            raise HTTPException(404, "speech not found")
        with deps.acting_as(identity, PRODUCT_ID):
            return await summary(speech)

    @router.get("/speeches/{speech_id}/download")
    async def download(speech_id: str, identity: Identity = Depends(deps.identity)) -> Response:
        """The speech as a file the browser saves (browsers ignore `download` on links to the
        storage host, ADR-0034)."""
        assert deps.storage is not None, "object storage is not configured"
        speech = await speeches().get(identity.tenant_id, identity.user_id, speech_id)
        if speech is None:
            raise HTTPException(404, "speech not found")
        try:
            with deps.acting_as(identity, PRODUCT_ID):
                data = await deps.storage.get(speech.audio_key)
        except FileNotFoundError:
            raise HTTPException(404, "speech not found") from None
        return Response(
            data,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": content_disposition(speech.text, "mp3"),
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.delete("/speeches/{speech_id}", status_code=204)
    async def delete_speech(
        speech_id: str, identity: Identity = Depends(deps.identity)
    ) -> Response:
        """Delete a result: its file first, then the record."""
        assert deps.storage is not None, "object storage is not configured"
        speech = await speeches().get(identity.tenant_id, identity.user_id, speech_id)
        if speech is None:
            raise HTTPException(404, "speech not found")
        with deps.acting_as(identity, PRODUCT_ID):
            try:
                await deps.storage.delete(speech.audio_key)
            except FileNotFoundError:
                pass
        await speeches().delete(identity.tenant_id, identity.user_id, speech_id)
        await deps.unindex(identity, PRODUCT_ID, speech_id)  # out of search too (ADR-0041)
        return Response(status_code=204)

    return router
