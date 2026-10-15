"""The product's read API: a user's songs (ADR-0023). Mounted under /products/wasifyai-music/.

Every query is scoped by tenant, product and user, and every audio/cover link is signed fresh, so
a song can be opened any time (the links themselves expire after an hour)."""

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from wasifyai_platform_sdk import Identity, RouteDeps, build_enhance_router, parse_ids

from wasifyai_music import prompts
from wasifyai_music.guardrail import enhance_guard
from wasifyai_music.id3 import small_cover_jpeg, tag_mp3
from wasifyai_music.songs import PostgresSongStore, SongRecord, SongStore
from wasifyai_music.video import VideoError, VideoUnavailable, encode_video

PRODUCT_ID = "wasifyai-music"
ARTIST = "Wasify AI"  # the artist in a downloaded MP3's tag
MAX_PARALLEL_ENCODES = 2

log = logging.getLogger(__name__)


class SongSummary(BaseModel):
    id: str
    title: str
    style: str
    created_at: datetime
    audio_url: str
    cover_url: str | None  # null when the cover job failed


class SongDetail(SongSummary):
    lyrics: str


class SongPage(BaseModel):
    songs: list[SongSummary]
    next_before: datetime | None  # pass as `before` to get the next page; null at the end


def build_routes(
    deps: RouteDeps,
    store: SongStore | None = None,
    encoder: Callable[[bytes, bytes, str], Awaitable[bytes]] | None = None,
) -> APIRouter:
    """`store` and `encoder` are injectable for tests; production reads the shared database and
    runs ffmpeg."""
    router = APIRouter(tags=[PRODUCT_ID])
    router.include_router(build_enhance_router(deps, PRODUCT_ID, prompts.load, enhance_guard))

    def songs() -> SongStore:
        return store or PostgresSongStore(deps.engine)

    async def summary(song: SongRecord) -> dict:
        assert deps.storage is not None, "object storage is not configured"
        return {
            "id": song.id,
            "title": song.title,
            "style": song.style,
            "created_at": song.created_at,
            "audio_url": await deps.storage.url(song.audio_key),
            "cover_url": await deps.storage.url(song.cover_key) if song.cover_key else None,
        }

    @router.get("/songs", response_model=SongPage)
    async def list_songs(
        limit: int = Query(20, ge=1, le=50),
        before: datetime | None = None,
        ids: str | None = Query(None, max_length=2000),
        identity: Identity = Depends(deps.identity),
    ) -> SongPage:
        wanted = parse_ids(ids)  # "these songs, in this order": the cards for search results
        if wanted is not None:
            found = [await songs().get(identity.tenant_id, identity.user_id, i) for i in wanted]
            with deps.acting_as(identity, PRODUCT_ID):
                got = [SongSummary(**await summary(s)) for s in found if s is not None]
            return SongPage(songs=got, next_before=None)
        rows = await songs().list(identity.tenant_id, identity.user_id, limit + 1, before)
        page, more = rows[:limit], len(rows) > limit
        with deps.acting_as(identity, PRODUCT_ID):
            items = [SongSummary(**await summary(s)) for s in page]
        return SongPage(songs=items, next_before=page[-1].created_at if more and page else None)

    @router.get("/songs/{song_id}", response_model=SongDetail)
    async def get_song(song_id: str, identity: Identity = Depends(deps.identity)) -> SongDetail:
        song = await songs().get(identity.tenant_id, identity.user_id, song_id)
        if song is None:  # also what another user's song looks like: no existence leak
            raise HTTPException(404, "song not found")
        with deps.acting_as(identity, PRODUCT_ID):
            return SongDetail(**await summary(song), lyrics=song.lyrics)

    @router.get("/songs/{song_id}/download/{kind}")
    async def download(
        song_id: str,
        kind: Literal["audio", "cover", "video"],
        identity: Identity = Depends(deps.identity),
    ) -> Response:
        """A file the browser saves. Browsers ignore `download` on links to another origin (the
        storage host), so files are served from here with a Content-Disposition. The song is looked
        up for this user only, like every other route.

        `audio` is the MP3 with the title, lyrics and cover art written into its tag, so a music
        player shows the cover. `video` is the cover as a picture with the song playing, made on the
        first request and kept in storage."""
        assert deps.storage is not None, "object storage is not configured"
        song = await songs().get(identity.tenant_id, identity.user_id, song_id)
        if song is None:
            raise HTTPException(404, "file not found")
        key = song.audio_key if kind == "audio" else song.cover_key
        if kind == "video" and song.cover_key is None:
            key = None  # a video needs the cover
        if not key:
            raise HTTPException(404, "file not found")
        try:
            with deps.acting_as(identity, PRODUCT_ID):
                if kind == "audio":
                    data, ext = await tagged_audio(song, key), "mp3"
                elif kind == "video":
                    data, ext = await video_for(song), "mp4"
                else:
                    data, ext = await deps.storage.get(key), key.rsplit(".", 1)[-1].lower()
        except FileNotFoundError:
            raise HTTPException(404, "file not found") from None
        except VideoUnavailable:
            raise HTTPException(503, "Video downloads are not available on this server.") from None
        except VideoError:
            raise HTTPException(
                502, "The video could not be made. Try again in a moment."
            ) from None
        return Response(
            data,
            media_type=CONTENT_TYPES.get(ext, "application/octet-stream"),
            headers={
                "Content-Disposition": f'attachment; filename="{file_name(song.title, ext)}"',
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    async def tagged_audio(song: SongRecord, key: str) -> bytes:
        """The MP3 with its tag. If the cover or tagging fails, the plain MP3 is still served."""
        assert deps.storage is not None
        audio = await deps.storage.get(key)
        try:
            jpeg = None
            if song.cover_key:
                cover = await deps.storage.get(song.cover_key)
                jpeg = await asyncio.to_thread(small_cover_jpeg, cover)
            return tag_mp3(
                audio, title=song.title, artist=ARTIST, lyrics=song.lyrics, cover_jpeg=jpeg,
                comment=f"Made with {ARTIST}",
            )  # fmt: skip
        except Exception:
            log.exception("could not tag the audio of song %s; serving it plain", song.id)
            return audio

    async def video_for(song: SongRecord) -> bytes:
        """The song's video: kept in storage after the first time. One encode at a time per song,
        and a few at once across songs, since it is CPU work."""
        assert deps.storage is not None and song.cover_key
        key = song.audio_key.rsplit("/", 1)[0] + "/video.mp4"
        if await deps.storage.exists(key):
            return await deps.storage.get(key)
        async with _locks.setdefault(song.id, asyncio.Lock()):
            try:
                if await deps.storage.exists(key):  # another request made it while we waited
                    return await deps.storage.get(key)
                audio, cover = (
                    await deps.storage.get(song.audio_key),
                    await deps.storage.get(song.cover_key),
                )
                async with _encodes:
                    video = await (encoder or encode_video)(audio, cover, song.title)
                await deps.storage.put(key, video, "video/mp4")
                return video
            finally:
                _locks.pop(song.id, None)

    _locks: dict[str, asyncio.Lock] = {}
    _encodes = asyncio.Semaphore(MAX_PARALLEL_ENCODES)

    return router


CONTENT_TYPES = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "flac": "audio/flac",
    "ogg": "audio/ogg",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "mp4": "video/mp4",
}


def file_name(title: str, ext: str) -> str:
    """A safe, readable file name from the title: letters, digits and hyphens only."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60].strip("-") or "song"
    return f"{slug}.{ext}" if ext else slug
