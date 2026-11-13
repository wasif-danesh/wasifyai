# SPDX-License-Identifier: Apache-2.0
"""The voice product's routes (ADR-0066, stage V1), under `/products/wasifyai-voice`.

    GET  /speeches, /speeches/{id}, /speeches/{id}/download      DELETE /speeches/{id}
    POST /transcripts (multipart)                                 GET /transcripts,
    /transcripts/{id}
    GET  /transcripts/{id}/export?format=txt|srt|vtt              PATCH, DELETE /transcripts/{id}
    POST /dictation (multipart, a 16 kHz mono WAV)                text back, nothing kept
    POST /read-aloud (a reply's text, one passage at a time)      sound back, nothing kept

Making a speech is a run of the product's graph (`/products/wasifyai-voice/runs`); transcribing a
recording is one request, because the runtime reads it faster than it plays."""

import asyncio
import base64
import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from wasifyai_platform_sdk import (
    Identity,
    RouteDeps,
    VoiceEngineError,
    VoiceRequestError,
    check_speak,
    check_transcribe,
    process_image,
    search_text,
)
from wasifyai_platform_sdk.uploads import UploadError
from wasifyai_platform_sdk.voice_models import MAX_DESCRIPTION_CHARS, MAX_REFERENCE_TEXT_CHARS

from wasifyai_voice import (
    audio_input,
    audiobook,
    dictation,
    export,
    read_aloud,
    reference,
)
from wasifyai_voice.runtime import PRODUCT_ID, NotAvailable, engine_for, store_for
from wasifyai_voice.store import NotFound, VoiceStore, new_id

log = logging.getLogger(__name__)

TRANSCRIPT_INDEX_CHARS = 2000
MAX_IMPORT_S = 3600.0
PICTURE_MAX_SIDE = 1024  # the engine scales it further to what the model takes
PICTURE_KEEP_S = 24 * 3600  # an added picture that no clip used is removed after a day


class Title(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)


class WordsRequest(BaseModel):
    """A recording of the library to write down: a track or a speech."""

    model_config = ConfigDict(extra="forbid")
    kind: str = Field(pattern="^(track|speech)$")
    id: str = Field(min_length=1, max_length=64)
    model: str | None = Field(default=None, max_length=100)


class ReadAloudRequest(BaseModel):
    """A chat reply, as the model wrote it, and which passage of it to speak (0 is the first)."""

    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=read_aloud.MAX_RAW_CHARS)
    part: int = Field(default=0, ge=0, lt=read_aloud.MAX_PASSAGES)


class PlanBook(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=audiobook.MAX_BOOK_CHARS * 2)
    target: int = Field(
        default=audiobook.TARGET_CHAPTER_CHARS, ge=1000, le=audiobook.MAX_CHAPTER_CHARS // 2
    )


class TrackPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=200)
    favourite: StrictBool | None = None


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

    # ---- the models ------------------------------------------------------------------------

    @router.get("/models")
    async def models(
        task: str | None = Query(None, max_length=20),
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        """The models the engine offers (the web's hosted ones; the desktop lists them, with what is
        on the computer, under `/desktop/audio/models`)."""
        try:
            engine = engine_for(deps.state)
        except NotAvailable as e:
            raise HTTPException(503, str(e)) from None
        return {"models": engine.models(task)}

    @router.get("/runtime")
    async def runtime(identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        """Whether what runs the models is set up. A service whose models are all hosted has nothing
        to set up and says so (`hosted`); one with the local runtime reports its state, which the
        web only reads: setting it up is done in the desktop app that owns the computer."""
        try:
            engine = engine_for(deps.state)
        except NotAvailable as e:
            raise HTTPException(503, str(e)) from None
        state = getattr(engine, "state", None)
        return state() if callable(state) else {"hosted": True}  # type: ignore[no-any-return]

    @router.get("/lipsync-engine")
    async def lipsync_engine(identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        """The lip sync component's state (installed, running), when this service has it."""
        try:
            engine = engine_for(deps.state)
        except NotAvailable as e:
            raise HTTPException(503, str(e)) from None
        sidecar = getattr(engine, "lipsync_sidecar", None)
        if sidecar is None:
            raise HTTPException(404, "Lip sync is not available in this deployment.")
        return sidecar.state()  # type: ignore[no-any-return]

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

    # ---- tracks (music) --------------------------------------------------------------------

    async def track_out(t: dict[str, Any], identity: Identity) -> dict[str, Any]:
        assert deps.storage is not None, "object storage is not configured"
        with deps.acting_as(identity, PRODUCT_ID):
            url = await deps.storage.url(t["audio_key"])
        return {k: v for k, v in t.items() if k not in ("tenant_id", "user_id", "audio_key")} | {
            "audio_url": url
        }

    async def reindex_track(identity: Identity, t: dict[str, Any]) -> None:
        index = deps.state.creation_index
        if index is None:
            return
        try:
            text = search_text(t["title"], t["description"], t["lyrics"][:TRANSCRIPT_INDEX_CHARS])
            await index.index(
                identity.tenant_id, PRODUCT_ID, identity.user_id, "track", t["id"], text
            )
        except Exception:
            log.warning("the track could not be added to search", exc_info=True)

    @router.get("/formats")
    async def formats(identity: Identity = Depends(deps.identity)) -> dict[str, list[str]]:
        """The formats a track or a speech can be saved in: WAV always, and what the tools on this
        computer can make."""
        return {"formats": ["wav", *audio_input.available_encodings()]}

    @router.post("/audiobook/plan")
    async def plan_book(
        body: PlanBook, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """The chapters of a long text, for the person to read and change before anything is spoken.
        Nothing is made or kept."""
        try:
            chapters = audiobook.plan_chapters(body.text, body.target)
        except audiobook.BookError as e:
            raise HTTPException(422, {"code": e.code, "message": str(e)}) from None
        listed = [c.public() for c in chapters]
        return {
            "chapters": listed,
            "chars": sum(int(c["chars"]) for c in listed),  # type: ignore[call-overload]
            "estimated_seconds": sum(int(c["estimated_seconds"]) for c in listed),  # type: ignore[call-overload]
        }

    @router.post("/tracks/import", status_code=201)
    async def import_track(
        file: UploadFile = File(...),  # noqa: B008
        title: str | None = Form(None, max_length=200),
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        """Add a recording from this computer to Your music, so the audio tools can work on it."""
        assert deps.storage is not None, "storage is required"
        name = file.filename or "recording"
        data = await file.read(audio_input.MAX_BYTES + 1)
        try:
            wav, seconds = await audio_input.at_rate(data, name, 44100, 2)
        except audio_input.AudioInputError as e:
            raise HTTPException(422, {"code": e.code, "message": str(e)}) from None
        if seconds > MAX_IMPORT_S:
            raise HTTPException(
                422,
                {"code": "too_long", "message": "That recording is longer than an hour."},
            )
        tid = new_id()
        key = f"music/{tid}.wav"
        with deps.acting_as(identity, PRODUCT_ID):
            await deps.storage.put(key, wav, "audio/wav")
        label = (title or "").strip()[:120] or name.rsplit(".", 1)[0][:120] or "Recording"
        t = await asyncio.to_thread(
            vstore().add_track, identity.tenant_id, identity.user_id, title=label,
            mode="imported", description=f"Added from the file {name[:100]}", lyrics="",
            instrumental=False, model_id="", options={}, seed=None, seconds=round(seconds, 2),
            sample_rate=44100, audio_key=key, load_s=0, elapsed_s=0, track_id=tid,
            edit={"action": "import", "file": name[:200]},
        )  # fmt: skip
        await reindex_track(identity, t)
        return await track_out(t, identity)

    @router.post("/words")
    async def words(
        body: WordsRequest, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """What a recording of the library says, written down (for the person to change in the
        speech editor). Nothing is saved."""
        assert deps.storage is not None, "storage is required"
        try:
            engine = engine_for(deps.state)
        except NotAvailable as e:
            raise HTTPException(503, str(e)) from None
        store = vstore()
        try:
            if body.kind == "track":
                row = await asyncio.to_thread(
                    store.get_track, identity.tenant_id, identity.user_id, body.id
                )
            else:
                row = await asyncio.to_thread(
                    store.get_speech, identity.tenant_id, identity.user_id, body.id
                )
            with deps.acting_as(identity, PRODUCT_ID):
                data = await deps.storage.get(row["audio_key"])
        except (NotFound, FileNotFoundError):
            raise HTTPException(404, "recording not found") from None
        try:
            chosen = engine.resolve("transcribe", body.model or None)
            wav, _ = await audio_input.at_rate(data, "audio.wav", 16000, 1)
            result = await engine.transcribe(chosen, wav, check_transcribe(chosen, None))
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
        return {"text": result.text, "seconds": round(result.seconds, 2), "model": chosen.id}

    @router.post("/dictation")
    async def dictate(
        file: UploadFile = File(...),  # noqa: B008
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        """A short clip from the chat box's microphone, written down. Nothing is saved: the clip is
        held in memory for this request and the answer is the text alone (no creation, no library
        row, no search entry, no log of the words). Only a 16 kHz mono 16-bit WAV of up to five
        minutes is read (`dictation.inspect`); the speech model may stay in memory beside the chat
        model when the two fit (`displaced` names whose model was unloaded when they did not)."""
        try:
            engine = engine_for(deps.state)
        except NotAvailable as e:
            raise HTTPException(503, str(e)) from None
        data = await file.read(dictation.MAX_BYTES + 1)
        try:
            clip = await asyncio.to_thread(dictation.inspect, data)
            chosen = engine.resolve("transcribe", None)
            result = await engine.transcribe(
                chosen, data, check_transcribe(chosen, None), beside=True
            )
        except dictation.DictationError as e:
            raise HTTPException(422, {"code": e.code, "message": str(e)}) from None
        except VoiceRequestError as e:
            raise HTTPException(422, {"code": e.code, "message": e.message}) from None
        except VoiceEngineError as e:
            status = 409 if e.code in ("runtime_missing", "model_missing", "no_model") else 502
            raise HTTPException(status, {"code": e.code, "message": e.message}) from None
        text = result.text.strip()
        if not text:
            raise HTTPException(
                422,
                {
                    "code": "no_speech",
                    "message": "No words were caught. Speak closer to it and try again.",
                },
            )
        return {
            "text": text,
            "seconds": round(clip.seconds, 2),
            "model": chosen.id,
            "displaced": result.displaced,
        }

    @router.post("/read-aloud")
    async def read_aloud_passage(
        body: ReadAloudRequest, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """One passage of a chat reply, spoken. Nothing is saved: the text is held for this request
        and the sound goes back in the answer (a WAV, base64), with no creation, no library row, no
        search entry, no file and no log of the words. The text is turned into plain words and cut
        at sentence ends (`read_aloud.passages`); ask for `part` 0, 1, 2 ... up to `parts`. The
        speech model may stay in memory beside the chat model when the two fit (`displaced` names
        whose model was unloaded when they did not)."""
        try:
            engine = engine_for(deps.state)
        except NotAvailable as e:
            raise HTTPException(503, str(e)) from None
        try:
            found = await asyncio.to_thread(read_aloud.passages, body.text)
            if body.part >= len(found.items):
                raise read_aloud.ReadAloudError("no_such_part", "There is no more to read.")
            chosen = engine.resolve("speak", None)
            text, voice, options = check_speak(chosen, found.items[body.part], None, None)
            result = await engine.speak(chosen, text, voice, options, beside=True)
        except read_aloud.ReadAloudError as e:
            status = 404 if e.code == "no_such_part" else 422
            raise HTTPException(status, {"code": e.code, "message": str(e)}) from None
        except VoiceRequestError as e:
            raise HTTPException(422, {"code": e.code, "message": e.message}) from None
        except VoiceEngineError as e:
            status = 409 if e.code in ("runtime_missing", "model_missing", "no_model") else 502
            raise HTTPException(status, {"code": e.code, "message": e.message}) from None
        return {
            "audio": base64.b64encode(result.wav).decode("ascii"),
            "part": body.part,
            "parts": len(found.items),
            "truncated": found.truncated,
            "seconds": round(result.seconds, 2),
            "model": chosen.id,
            "displaced": result.displaced,
        }

    # ---- lip sync: pictures and clips (V5) -------------------------------------------------

    async def clip_out(c: dict[str, Any], identity: Identity) -> dict[str, Any]:
        assert deps.storage is not None, "object storage is not configured"
        with deps.acting_as(identity, PRODUCT_ID):
            video, picture = (
                await deps.storage.url(c["video_key"]),
                await deps.storage.url(c["picture_key"]),
            )
        hidden = ("tenant_id", "user_id", "video_key", "picture_key")
        return {k: v for k, v in c.items() if k not in hidden} | {
            "video_url": video,
            "picture_url": picture,
        }

    async def forget_stale_pictures(identity: Identity) -> None:
        assert deps.storage is not None
        from datetime import UTC, datetime, timedelta

        before = (datetime.now(UTC) - timedelta(seconds=PICTURE_KEEP_S)).isoformat(
            timespec="milliseconds"
        )
        for p in await asyncio.to_thread(vstore().stale_pictures, before):
            try:
                gone = await asyncio.to_thread(
                    vstore().delete_picture, p["tenant_id"], p["user_id"], p["id"]
                )
                with deps.acting_as(Identity(p["tenant_id"], p["user_id"]), PRODUCT_ID):
                    await deps.storage.delete(gone["key"])
            except (NotFound, FileNotFoundError):
                pass

    @router.post("/pictures", status_code=201)
    async def add_picture(
        file: UploadFile = File(...),  # noqa: B008
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        """A picture to make a talking video from: checked, cleaned of everything but the pixels (no
        location, no camera data), scaled down. It is kept until a clip uses it, or for a day."""
        assert deps.storage is not None, "storage is required"
        data = await file.read(10 * 1024 * 1024 + 1)
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(
                422, {"code": "too_large", "message": "That picture is larger than 10 MB."}
            )
        try:
            clean = await asyncio.to_thread(process_image, data, PICTURE_MAX_SIDE)
        except UploadError as e:
            raise HTTPException(422, {"code": "bad_picture", "message": e.message}) from None
        pid = new_id()
        key = f"lipsync/pictures/{pid}.png"
        with deps.acting_as(identity, PRODUCT_ID):
            await deps.storage.put(key, clean.png, "image/png")
        p = await asyncio.to_thread(
            vstore().add_picture, identity.tenant_id, identity.user_id, key=key,
            width=clean.width, height=clean.height, picture_id=pid,
        )  # fmt: skip
        await forget_stale_pictures(identity)
        with deps.acting_as(identity, PRODUCT_ID):
            url = await deps.storage.url(key)
        return {"id": p["id"], "width": p["width"], "height": p["height"], "url": url}

    @router.get("/clips")
    async def list_clips(
        ids: str | None = Query(None, max_length=2000),
        limit: int = Query(100, ge=1, le=500),
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        wanted = [i for i in (ids or "").split(",") if i] or None
        rows = await asyncio.to_thread(
            vstore().list_clips, identity.tenant_id, identity.user_id, wanted, limit
        )
        return {"items": [await clip_out(c, identity) for c in rows]}

    @router.get("/clips/{cid}")
    async def get_clip(cid: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        try:
            c = await asyncio.to_thread(
                vstore().get_clip, identity.tenant_id, identity.user_id, cid
            )
        except NotFound:
            raise HTTPException(404, "clip not found") from None
        return await clip_out(c, identity)

    @router.get("/clips/{cid}/download")
    async def download_clip(cid: str, identity: Identity = Depends(deps.identity)) -> Response:
        assert deps.storage is not None
        try:
            c = await asyncio.to_thread(
                vstore().get_clip, identity.tenant_id, identity.user_id, cid
            )
            with deps.acting_as(identity, PRODUCT_ID):
                data = await deps.storage.get(c["video_key"])
        except (NotFound, FileNotFoundError):
            raise HTTPException(404, "clip not found") from None
        name = export.file_name(c["title"], "mp4")
        return Response(
            data, media_type="video/mp4",
            headers={"Content-Disposition": f'attachment; filename="{name}"',
                     "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        )  # fmt: skip

    @router.patch("/clips/{cid}")
    async def update_clip(
        cid: str, body: TrackPatch, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        try:
            c = await asyncio.to_thread(
                vstore().update_clip, identity.tenant_id, identity.user_id, cid,
                title=body.title.strip() if body.title else None, favourite=body.favourite,
            )  # fmt: skip
        except NotFound:
            raise HTTPException(404, "clip not found") from None
        index = deps.state.creation_index
        if index is not None:
            try:
                text = search_text(c["title"], c["script"][:TRANSCRIPT_INDEX_CHARS])
                await index.index(
                    identity.tenant_id, PRODUCT_ID, identity.user_id, "lipsync", c["id"], text
                )
            except Exception:
                log.warning("the clip could not be added to search", exc_info=True)
        return await clip_out(c, identity)

    @router.delete("/clips/{cid}", status_code=204)
    async def delete_clip(cid: str, identity: Identity = Depends(deps.identity)) -> Response:
        assert deps.storage is not None
        try:
            c = await asyncio.to_thread(
                vstore().delete_clip, identity.tenant_id, identity.user_id, cid
            )
        except NotFound:
            raise HTTPException(404, "clip not found") from None
        with deps.acting_as(identity, PRODUCT_ID):
            for key in (c["video_key"], c["picture_key"]):
                try:
                    await deps.storage.delete(key)
                except FileNotFoundError:
                    pass
        await deps.unindex(identity, PRODUCT_ID, cid)
        return Response(status_code=204)

    @router.get("/tracks")
    async def list_tracks(
        ids: str | None = Query(None, max_length=2000),
        limit: int = Query(100, ge=1, le=500),
        favourites: bool = False,
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        wanted = [i for i in (ids or "").split(",") if i] or None
        rows = await asyncio.to_thread(
            vstore().list_tracks, identity.tenant_id, identity.user_id, wanted, limit, favourites
        )
        return {"items": [await track_out(t, identity) for t in rows]}

    @router.get("/tracks/{tid}")
    async def get_track(tid: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        try:
            t = await asyncio.to_thread(
                vstore().get_track, identity.tenant_id, identity.user_id, tid
            )
        except NotFound:
            raise HTTPException(404, "track not found") from None
        return await track_out(t, identity)

    @router.get("/tracks/{tid}/download")
    async def download_track(
        tid: str,
        format: str = Query("wav", pattern="^(wav|mp3|m4a)$"),
        identity: Identity = Depends(deps.identity),
    ) -> Response:
        assert deps.storage is not None
        try:
            t = await asyncio.to_thread(
                vstore().get_track, identity.tenant_id, identity.user_id, tid
            )
            with deps.acting_as(identity, PRODUCT_ID):
                data = await deps.storage.get(t["audio_key"])
        except (NotFound, FileNotFoundError):
            raise HTTPException(404, "track not found") from None
        media = "audio/wav"
        if format != "wav":
            try:
                data = await audio_input.encode(data, format)
            except audio_input.AudioInputError as e:
                raise HTTPException(422, {"code": e.code, "message": str(e)}) from None
            media = audio_input.ENCODINGS[format][0]
        name = export.file_name(t["title"], format)
        return Response(
            data, media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{name}"',
                     "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        )  # fmt: skip

    @router.patch("/tracks/{tid}")
    async def update_track(
        tid: str, body: TrackPatch, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        try:
            t = await asyncio.to_thread(
                vstore().update_track, identity.tenant_id, identity.user_id, tid,
                title=body.title.strip() if body.title else None, favourite=body.favourite,
            )  # fmt: skip
        except NotFound:
            raise HTTPException(404, "track not found") from None
        await reindex_track(identity, t)
        return await track_out(t, identity)

    @router.delete("/tracks/{tid}", status_code=204)
    async def delete_track(tid: str, identity: Identity = Depends(deps.identity)) -> Response:
        assert deps.storage is not None
        try:
            t = await asyncio.to_thread(
                vstore().delete_track, identity.tenant_id, identity.user_id, tid
            )
        except NotFound:
            raise HTTPException(404, "track not found") from None
        with deps.acting_as(identity, PRODUCT_ID):
            try:
                await deps.storage.delete(t["audio_key"])
            except FileNotFoundError:
                pass
        await deps.unindex(identity, PRODUCT_ID, tid)
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
        index = deps.state.creation_index
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
        reference_text: str = Form("", max_length=MAX_REFERENCE_TEXT_CHARS),
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        assert deps.storage is not None, "storage is required"
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
            reference_seconds=round(seconds, 2), voice_id=vid,
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
        index = deps.state.creation_index
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
