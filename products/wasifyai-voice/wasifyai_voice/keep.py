"""A recording of the person's added to Your music: the Import button, and a recording or the
sound of a clip attached in the chat that the person asks to work on
(docs/chat-does-everything-plan.md, CE2).

The file is untrusted: it is decoded to a 44.1 kHz stereo WAV (`audio_input.at_rate`) and kept as
that. The track is put in search at once (ADR-0041)."""

import asyncio
import logging
from typing import Any

from wasifyai_platform_sdk import Identity, search_text

from wasifyai_voice import audio_input
from wasifyai_voice.runtime import PRODUCT_ID
from wasifyai_voice.store import VoiceStore, new_id

log = logging.getLogger(__name__)
MAX_IMPORT_S = 3600.0
INDEX_CHARS = 2000


class TooLong(Exception):
    """A recording longer than an hour. The message is in words for the person."""


async def add_recording(
    deps: Any, store: VoiceStore, identity: Identity, data: bytes, name: str, title: str = ""
) -> dict[str, Any]:
    """Make `data` a track of Your music and return its row. Raises `audio_input.AudioInputError`
    or `TooLong` in words."""
    wav, seconds = await audio_input.at_rate(data, name, 44100, 2)
    if seconds > MAX_IMPORT_S:
        raise TooLong("That recording is longer than an hour.")
    tid = new_id()
    key = f"music/{tid}.wav"
    with deps.acting_as(identity, PRODUCT_ID):
        await deps.storage.put(key, wav, "audio/wav")
    label = title.strip()[:120] or name.rsplit(".", 1)[0][:120] or "Recording"
    t = await asyncio.to_thread(
        store.add_track, identity.tenant_id, identity.user_id, title=label,
        mode="imported", description=f"Added from the file {name[:100]}", lyrics="",
        instrumental=False, model_id="", options={}, seed=None, seconds=round(seconds, 2),
        sample_rate=44100, audio_key=key, load_s=0, elapsed_s=0, track_id=tid,
        edit={"action": "import", "file": name[:200]},
    )  # fmt: skip
    index = deps.state.creation_index
    if index is not None:
        try:
            text = search_text(t["title"], t["description"], t["lyrics"][:INDEX_CHARS])
            await index.index(
                identity.tenant_id, PRODUCT_ID, identity.user_id, "track", t["id"], text
            )
        except Exception:
            log.warning("the track could not be added to search", exc_info=True)
    return t
