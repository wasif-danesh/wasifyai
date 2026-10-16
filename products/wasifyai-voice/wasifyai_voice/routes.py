# SPDX-License-Identifier: Apache-2.0
"""The voice product's routes (ADR-0066, stage V1), under `/products/wasifyai-voice`.

    GET  /speeches, /speeches/{id}, /speeches/{id}/download      DELETE /speeches/{id}
    POST /transcripts (multipart)                                 GET /transcripts,
    /transcripts/{id}
    GET  /transcripts/{id}/export?format=txt|srt|vtt              PATCH, DELETE /transcripts/{id}

Making a speech is a run of the product's graph (`/products/wasifyai-voice/runs`); transcribing a
recording is one request, because the runtime reads it faster than it plays."""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from wasifyai_platform_sdk import (
    Identity,
    RouteDeps,
    VoiceEngineError,
    VoiceRequestError,
    check_transcribe,
    search_text,
)
from wasifyai_platform_sdk.voice_models import MAX_DESCRIPTION_CHARS, MAX_REFERENCE_TEXT_CHARS

from wasifyai_voice import audio_input, consent, export, reference
from wasifyai_voice.runtime import PRODUCT_ID, NotAvailable, engine_for, store_for
from wasifyai_voice.store import NotFound, VoiceStore, new_id

log = logging.getLogger(__name__)

TRANSCRIPT_INDEX_CHARS = 2000


class Title(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)


class NewDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=3, max_length=MAX_DESCRIPTION_CHARS)


class VoicePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, min_length=3, max_length=MAX_DESCRIPTION_CHARS)
    reference_text: str | None = Field(default=None, max_length=MAX_REFERENCE_TEXT_CHARS)


def build_routes(deps: RouteDeps, store: VoiceStore | None = None):
    router = APIRouter(tags=[PRODUCT_ID])

    def vstore() -> VoiceStore:
        if store is not None:
            return store
        try:
            return store_for(deps.state)
        except NotAvailable as e:
            raise HTTPException(503, str(e)) from None

    async def speech_out(s: dict[str, Any], identity: Identity) -> dict[str, Any]:
        assert deps.storage is not None, "object storage is not configured"
        with deps.acting_as(identity, PRODUCT_ID):
            url = await deps.storage.url(s["audio_key"])
        return {k: v for k, v in s.items() if k not in ("tenant_id", "user_id", "audio_key")} | {
            "audio_url": url
        }

    # ---- speeches --------------------------------------------------------------------------

    @router.get("/speeches")
    async def list_speeches(
        ids: str | None = Query(None, max_length=2000),
        limit: int = Query(100, ge=1, le=500),
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        wanted = [i for i in (ids or "").split(",") if i] or None
        rows = await asyncio.to_thread(
            vstore().list_speeches, identity.tenant_id, identity.user_id, wanted, limit
        )
        return {"items": [await speech_out(s, identity) for s in rows]}

    @router.get("/speeches/{sid}")
    async def get_speech(sid: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        try:
            s = await asyncio.to_thread(
                vstore().get_speech, identity.tenant_id, identity.user_id, sid
            )
        except NotFound:
            raise HTTPException(404, "speech not found") from None
        return await speech_out(s, identity)

    @router.get("/speeches/{sid}/download")
    async def download_speech(sid: str, identity: Identity = Depends(deps.identity)) -> Response:
        assert deps.storage is not None
        try:
            s = await asyncio.to_thread(
                vstore().get_speech, identity.tenant_id, identity.user_id, sid
            )
            with deps.acting_as(identity, PRODUCT_ID):
                data = await deps.storage.get(s["audio_key"])
        except (NotFound, FileNotFoundError):
            raise HTTPException(404, "speech not found") from None
        name = export.file_name(s["text"][:40], "wav")
        return Response(
            data, media_type="audio/wav",
            headers={"Content-Disposition": f'attachment; filename="{name}"',
                     "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        )  # fmt: skip

    @router.delete("/speeches/{sid}", status_code=204)
    async def delete_speech(sid: str, identity: Identity = Depends(deps.identity)) -> Response:
        assert deps.storage is not None
        try:
            s = await asyncio.to_thread(
                vstore().delete_speech, identity.tenant_id, identity.user_id, sid
            )
        except NotFound:
            raise HTTPException(404, "speech not found") from None
        with deps.acting_as(identity, PRODUCT_ID):
            try:
                await deps.storage.delete(s["audio_key"])
            except FileNotFoundError:
                pass
        await deps.unindex(identity, PRODUCT_ID, sid)
        return Response(status_code=204)

    # ---- saved voices ----------------------------------------------------------------------

    async def voice_out(v: dict[str, Any], identity: Identity) -> dict[str, Any]:
        out = {k: x for k, x in v.items() if k not in ("tenant_id", "user_id", "reference_key")}
        if v["reference_key"]:
            assert deps.storage is not None
            with deps.acting_as(identity, PRODUCT_ID):
                out["reference_url"] = await deps.storage.url(v["reference_key"])
        return out

    async def reindex_voice(identity: Identity, v: dict[str, Any]) -> None:
        index = getattr(deps.state, "creation_index", None)
        if index is None:
            return
        try:
            text = search_text(v["name"], v["description"] or "cloned voice")
            await index.index(
                identity.tenant_id, PRODUCT_ID, identity.user_id, "voice", v["id"], text
            )
        except Exception:
            log.warning("the voice could not be added to search", exc_info=True)

    @router.get("/voices")
    async def list_voices(
        kind: str | None = Query(None, pattern="^(design|clone)$"),
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        rows = await asyncio.to_thread(
            vstore().list_voices, identity.tenant_id, identity.user_id, kind
        )
        return {"items": [await voice_out(v, identity) for v in rows]}

    @router.get("/voices/{vid}")
    async def get_voice(vid: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        try:
            v = await asyncio.to_thread(
                vstore().get_voice, identity.tenant_id, identity.user_id, vid
            )
        except NotFound:
            raise HTTPException(404, "voice not found") from None
        return await voice_out(v, identity)

    @router.post("/voices/design", status_code=201)
    async def create_design(
        body: NewDesign, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        description = " ".join(body.description.split())
        if "(" in description or ")" in description:
            raise HTTPException(
                422,
                {"code": "bad_description", "message": "Leave brackets out of the description."},
            )
        v = await asyncio.to_thread(
            vstore().add_voice, identity.tenant_id, identity.user_id, kind="design",
            name=body.name.strip(), description=description,
        )  # fmt: skip
        await reindex_voice(identity, v)
        return await voice_out(v, identity)

    @router.post("/voices/clone", status_code=201)
    async def create_clone(
        file: UploadFile = File(...),  # noqa: B008
        name: str = Form(..., min_length=1, max_length=100),
        consent_basis: str = Form("", alias="consent"),
        reference_text: str = Form("", max_length=MAX_REFERENCE_TEXT_CHARS),
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        assert deps.storage is not None, "storage is required"
        if consent_basis not in consent.STATEMENTS:
            raise HTTPException(
                422,
                {
                    "code": "consent_required",
                    "message": "Say whose voice this is: yours, or one you have permission to use.",
                },
            )
        data = await file.read(audio_input.MAX_BYTES + 1)
        try:
            wav, seconds = await reference.prepare(data, file.filename or "voice")
        except audio_input.AudioInputError as e:
            raise HTTPException(422, {"code": e.code, "message": str(e)}) from None
        s = vstore()
        vid = new_id()
        key = f"voice/{vid}.wav"
        with deps.acting_as(identity, PRODUCT_ID):
            await deps.storage.put(key, wav, "audio/wav")
        path = s.reference_path(vid)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, wav)
        v = await asyncio.to_thread(
            s.add_voice, identity.tenant_id, identity.user_id, kind="clone", name=name.strip(),
            reference_key=key, reference_text=" ".join(reference_text.split()),
            reference_seconds=round(seconds, 2), consent=consent.record(consent_basis),
            voice_id=vid,
        )  # fmt: skip
        await reindex_voice(identity, v)
        return await voice_out(v, identity)

    @router.patch("/voices/{vid}")
    async def update_voice(
        vid: str, body: VoicePatch, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        if body.description and ("(" in body.description or ")" in body.description):
            raise HTTPException(
                422,
                {"code": "bad_description", "message": "Leave brackets out of the description."},
            )
        try:
            v = await asyncio.to_thread(
                vstore().update_voice, identity.tenant_id, identity.user_id, vid,
                name=body.name.strip() if body.name else None,
                description=" ".join(body.description.split()) if body.description else None,
                reference_text=" ".join(body.reference_text.split())
                if body.reference_text is not None else None,
            )  # fmt: skip
        except NotFound as e:
            raise HTTPException(404, str(e)) from None
        await reindex_voice(identity, v)
        return await voice_out(v, identity)

    @router.delete("/voices/{vid}", status_code=204)
    async def delete_voice(vid: str, identity: Identity = Depends(deps.identity)) -> Response:
        try:
            v = await asyncio.to_thread(
                vstore().delete_voice, identity.tenant_id, identity.user_id, vid
            )
        except NotFound:
            raise HTTPException(404, "voice not found") from None
        if v["reference_key"] and deps.storage is not None:
            with deps.acting_as(identity, PRODUCT_ID):
                try:
                    await deps.storage.delete(v["reference_key"])
                except FileNotFoundError:
                    pass
        await deps.unindex(identity, PRODUCT_ID, vid)
        return Response(status_code=204)

    # ---- transcripts -----------------------------------------------------------------------

    async def reindex(identity: Identity, t: dict[str, Any]) -> None:
        index = getattr(deps.state, "creation_index", None)
        if index is None:
            return
        try:
            text = search_text(t["title"], t["text"][:TRANSCRIPT_INDEX_CHARS])
            await index.index(
                identity.tenant_id, PRODUCT_ID, identity.user_id, "transcript", t["id"], text
            )
        except Exception:  # the periodic check will catch up
            log.warning("the transcript could not be added to search", exc_info=True)

    def brief(t: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in t.items() if k not in ("tenant_id", "user_id")}

    @router.post("/transcripts", status_code=201)
    async def create_transcript(
        file: UploadFile = File(...),  # noqa: B008
        model: str | None = Form(None),
        title: str | None = Form(None),
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        try:
            engine = engine_for(deps.state)
        except NotAvailable as e:
            raise HTTPException(503, str(e)) from None
        name = file.filename or "recording"
        data = await file.read(audio_input.MAX_BYTES + 1)
        try:
            chosen = engine.resolve("transcribe", model or None)
            options = check_transcribe(chosen, None)
            wav = await audio_input.to_wav(data, name)
            result = await engine.transcribe(chosen, wav, options)
        except audio_input.AudioInputError as e:
            raise HTTPException(422, {"code": e.code, "message": str(e)}) from None
        except VoiceRequestError as e:
            raise HTTPException(422, {"code": e.code, "message": e.message}) from None
        except VoiceEngineError as e:
            status = (
                409
                if e.code in ("runtime_missing", "model_missing", "no_model")
                else 422
                if e.code == "unknown_model"
                else 502
            )
            raise HTTPException(status, {"code": e.code, "message": e.message}) from None
        label = (title or "").strip()[:200] or name.rsplit(".", 1)[0][:200] or "Transcript"
        saved = await asyncio.to_thread(
            vstore().add_transcript, identity.tenant_id, identity.user_id, title=label,
            source_name=name[:200], model_id=chosen.id, text=result.text,
            segments=[{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text}
                      for s in result.segments],
            seconds=round(result.seconds, 2), elapsed_s=round(result.elapsed_s, 2),
        )  # fmt: skip
        await reindex(identity, saved)
        return brief(saved)

    @router.get("/transcripts")
    async def list_transcripts(
        ids: str | None = Query(None, max_length=2000),
        limit: int = Query(100, ge=1, le=500),
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        wanted = [i for i in (ids or "").split(",") if i] or None
        rows = await asyncio.to_thread(
            vstore().list_transcripts, identity.tenant_id, identity.user_id, wanted, limit
        )
        return {"items": [brief(t) | {"segments": [], "text": t["text"][:240]} for t in rows]}

    @router.get("/transcripts/{tid}")
    async def get_transcript(
        tid: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        try:
            return brief(
                await asyncio.to_thread(
                    vstore().get_transcript, identity.tenant_id, identity.user_id, tid
                )
            )
        except NotFound:
            raise HTTPException(404, "transcript not found") from None

    @router.get("/transcripts/{tid}/export")
    async def export_transcript(
        tid: str, format: str = Query("txt"), identity: Identity = Depends(deps.identity)
    ) -> Response:
        if format not in export.FORMATS:
            raise HTTPException(422, "format must be txt, srt or vtt")
        try:
            t = await asyncio.to_thread(
                vstore().get_transcript, identity.tenant_id, identity.user_id, tid
            )
        except NotFound:
            raise HTTPException(404, "transcript not found") from None
        ctype, ext = export.FORMATS[format]
        fname = export.file_name(t["title"], ext)
        return Response(
            export.render(t, format), media_type=ctype,
            headers={"Content-Disposition": f'attachment; filename="{fname}"',
                     "Cache-Control": "private, no-store"},
        )  # fmt: skip

    @router.patch("/transcripts/{tid}")
    async def rename_transcript(
        tid: str, body: Title, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        try:
            saved = await asyncio.to_thread(
                vstore().rename_transcript,
                identity.tenant_id,
                identity.user_id,
                tid,
                body.title.strip(),
            )
        except NotFound:
            raise HTTPException(404, "transcript not found") from None
        await reindex(identity, saved)
        return brief(saved)

    @router.delete("/transcripts/{tid}", status_code=204)
    async def delete_transcript(tid: str, identity: Identity = Depends(deps.identity)) -> Response:
        try:
            await asyncio.to_thread(
                vstore().delete_transcript, identity.tenant_id, identity.user_id, tid
            )
        except NotFound:
            raise HTTPException(404, "transcript not found") from None
        await deps.unindex(identity, PRODUCT_ID, tid)
        return Response(status_code=204)

    return router
