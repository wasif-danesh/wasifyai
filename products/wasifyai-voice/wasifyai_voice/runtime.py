# SPDX-License-Identifier: Apache-2.0
"""What the voice product needs at run time: its store, and the engine's speech runtime.

Both come from the engine's app state (the data folder; `state.audio`), as the notebooks reach their
library, so this package imports nothing from the API."""

from pathlib import Path
from typing import Any

from wasifyai_platform_sdk import SpeechEngine

from wasifyai_voice.store import VoiceStore

PRODUCT_ID = "wasifyai-voice"


class NotAvailable(Exception):
    """Speech is not served by this deployment (no desktop engine)."""


def engine_for(state: Any) -> SpeechEngine:
    engine = state.audio
    if engine is None:
        raise NotAvailable("Speech is not available in this deployment yet.")
    return engine  # type: ignore[no-any-return]


def store_for(state: Any) -> VoiceStore:
    existing = state.voice_store
    if existing is not None:
        return existing  # type: ignore[no-any-return]
    data = state.desktop_dir
    if not data:
        raise NotAvailable("Speech is not available in this deployment yet.")
    store = VoiceStore(Path(data) / "voice")
    state.voice_store = store
    return store
