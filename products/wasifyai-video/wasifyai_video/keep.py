"""A video file of the person's added to their library: the Videos Import button, and a clip
attached in the chat that the person asks to work on (docs/chat-does-everything-plan.md, CE2).

The file is untrusted: ffmpeg decodes it and makes a clip the engine can carry on
(`import_clip`); the file is never kept as sent. The clip is put in search at once (ADR-0041)."""

import asyncio
import logging
import re
import tempfile
from pathlib import Path
from uuid import uuid4

from wasifyai_platform_sdk import Identity

from wasifyai_video.index import index_text
from wasifyai_video.schemas import FPS
from wasifyai_video.videos import VideoRecord, VideoStore, import_clip, poster_of

PRODUCT_ID = "wasifyai-video"
log = logging.getLogger(__name__)


def title_of(name: str | None) -> str:
    """A clip's name from its file name: no extension, no underscores, at most 120 letters."""
    stem = Path(name or "").stem
    return re.sub(r"\s+", " ", re.sub(r"[_\-\x00-\x1f]+", " ", stem)).strip()[:120] or "My video"


async def add_clip(
    deps, store: VideoStore, identity: Identity, source: Path, title: str
) -> VideoRecord:
    """Make the file at `source` a clip of the library and return its record. Raises `ClipError`
    or `PosterError` in words for a file that cannot be used."""
    with tempfile.TemporaryDirectory(prefix="wasifyai-video-") as tmp:
        out = Path(tmp) / "clip.mp4"
        width, height, frames = await import_clip(source, out)
        data = await asyncio.to_thread(out.read_bytes)
    _, _, poster = await poster_of(data)
    video_id = str(uuid4())
    with deps.acting_as(identity, PRODUCT_ID):
        await deps.storage.put(f"{video_id}/video.mp4", data, "video/mp4")
        await deps.storage.put(f"{video_id}/poster.jpg", poster, "image/jpeg")
    await store.add(
        VideoRecord(
            id=video_id, tenant_id=identity.tenant_id, product_id=PRODUCT_ID,
            user_id=identity.user_id, thread_id=None, run_id=None, mode="import",
            status="working", prompt=title, seconds=max(1, round(frames / FPS)),
            frames=frames, fps=FPS,
        )
    )  # fmt: skip
    await store.finish(
        identity.tenant_id, video_id, width, height, f"{video_id}/video.mp4",
        f"{video_id}/poster.jpg",
    )  # fmt: skip
    index = deps.state.creation_index  # found in search at once (ADR-0041)
    if index is not None:
        try:
            await index.index(
                identity.tenant_id, PRODUCT_ID, identity.user_id, "video", video_id,
                index_text(title),
            )  # fmt: skip
        except Exception:
            log.warning("the added video could not be put in search", exc_info=True)
    made = await store.get(identity.tenant_id, identity.user_id, video_id)
    assert made is not None
    return made
