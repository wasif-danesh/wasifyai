# SPDX-License-Identifier: Apache-2.0
"""An audiobook as a graph task (ADR-0066, stage V7): the chapters a person approved are spoken one
at a time in the voice they chose, each kept as a track as soon as it is done, and, when asked for,
joined into one track of the whole book.

The voice is a built-in one or a saved one (described or cloned); the model is the engine's to
choose or the person's to pick. Nothing here knows a model."""

import asyncio
import logging
import time
from typing import Any

from langgraph.config import get_stream_writer
from wasifyai_platform_sdk import (
    Capabilities,
    RunError,
    VoiceEngineError,
    VoiceRequestError,
    check_clone,
    check_design,
    check_speak,
    require_context,
)

from wasifyai_voice import audiobook
from wasifyai_voice.runtime import store_for
from wasifyai_voice.store import NotFound
from wasifyai_voice.tools import Kit, Refuse
from wasifyai_voice.usage import BOOKS, metered

log = logging.getLogger(__name__)

WHOLE_MAX_CHARS = 100_000  # a track of the whole book is held in memory: about two hours of speech


def build_book(caps: Capabilities, app_state: Any, engine: Any, refuse_with: Refuse, kit: Kit):
    def say(label: str) -> None:
        get_stream_writer()(
            {"type": "node", "node": "audiobook", "status": "started", "label": label}
        )

    async def voice_for(state: dict[str, Any]) -> Any:
        """(model, a label for the record, the call that speaks a piece of text)."""
        eng = engine()
        ctx = require_context()
        options = state.get("options") or None
        if state.get("saved_voice"):
            try:
                saved = store_for(app_state).get_voice(
                    ctx.tenant_id, ctx.user_id, str(state["saved_voice"])
                )
            except NotFound:
                raise audiobook.BookError(
                    "unknown_voice", "That saved voice is no longer there."
                ) from None
            model = eng.resolve(saved["kind"], state.get("model") or None)
            if saved["kind"] == "design":

                async def design(text: str) -> Any:
                    t, d, opts = check_design(model, text, saved["description"], options)
                    return await eng.design(model, t, d, opts)

                return model, saved["name"], design
            reference = store_for(app_state).reference_path(saved["id"])
            if not reference.is_file():
                raise audiobook.BookError(
                    "reference_missing", "The recording of this voice is no longer there."
                )
            lo, hi = model.clone["min_seconds"], model.clone["max_seconds"]
            if not lo <= float(saved["reference_seconds"] or 0) <= hi:
                raise audiobook.BookError(
                    "reference_length",
                    f"{model.title} needs a recording of {lo:g} to {hi:g} seconds.",
                )

            async def clone(text: str) -> Any:
                t, said, opts = check_clone(model, text, saved["reference_text"], options)
                return await eng.clone(model, t, reference, said, opts)

            return model, saved["name"], clone
        model = eng.resolve("speak", state.get("model") or None)
        voice = state.get("voice") or None
        check_speak(model, "Hello.", voice, options)  # the voice and the options, before any work

        async def speak(text: str) -> Any:
            t, v, opts = check_speak(model, text, voice, options)
            return await eng.speak(model, t, v, opts)

        return model, voice or model.default_voice or model.title, speak

    async def audiobook_node(state: dict[str, Any]) -> dict[str, Any]:
        say("Checking")
        assert caps.storage is not None, "storage is required"
        try:
            chapters = audiobook.check_chapters(state.get("chapters"))
            title = " ".join(str(state.get("title", "")).split())[:120] or "Audiobook"
            whole = bool(state.get("whole"))
            if whole and sum(len(c.text) for c in chapters) > WHOLE_MAX_CHARS:
                raise audiobook.BookError(
                    "whole_too_long",
                    "A single track of the whole book is for books up to about two hours. "
                    "Leave it out, and every chapter is kept as its own track.",
                )
            model, label, call = await voice_for(state)
        except audiobook.BookError as e:
            return refuse_with(e.code, str(e))
        except VoiceRequestError as e:
            return refuse_with(e.code, e.message)
        except VoiceEngineError as e:
            raise kit.failed(e) from None

        read_titles = state.get("read_titles", True)
        made: list[dict[str, Any]] = []
        spoken: list[tuple[bytes, float]] = []
        t0 = time.monotonic()
        total = len(chapters)
        rate = 0
        try:
            for n, chapter in enumerate(chapters, 1):
                pieces = audiobook.split_pieces(chapter.text)
                if read_titles:
                    pieces.insert(0, audiobook.Piece(chapter.title.rstrip(".") + ".", 1.0))
                parts: list[tuple[bytes, float]] = []
                for j, piece in enumerate(pieces, 1):
                    say(f"Chapter {n} of {total}, part {j} of {len(pieces)}")
                    result = await call(piece.text)
                    rate = result.sample_rate
                    parts.append((result.wav, piece.pause_s))
                wav, seconds = await asyncio.to_thread(audiobook.join_wavs, parts)
                track = await kit.keep(
                    wav=wav, rate=rate, seconds=seconds,
                    title=f"{title} - {n}. {chapter.title}"[:120], mode="chapter",
                    description=f"Chapter {n} of {total} of {title}", model_id=model.id,
                    options=state.get("options") or {}, seed=None, parent=None,
                    edit={
                        "action": "audiobook", "book": title, "chapter": n, "of": total,
                        "chapter_title": chapter.title, "voice": label, "pieces": len(pieces),
                    },
                    load_s=0.0, elapsed_s=time.monotonic() - t0, lyrics=chapter.text,
                )  # fmt: skip
                made.append(track | {"chapter": n})
                if whole:
                    spoken.append((wav, audiobook.CHAPTER_PAUSE_S))
        except VoiceEngineError as e:
            kept = len(made)
            msg = f"{e.message} " + (
                f"Chapters 1 to {kept} were kept in Your music." if kept else "Nothing was kept."
            )
            raise RunError(e.code, msg, retryable=e.code in ("busy", "engine_stopped")) from None
        except (audiobook.BookError, VoiceRequestError) as e:
            raise RunError(getattr(e, "code", "failed"), str(getattr(e, "message", e))) from None

        book = None
        if whole and spoken:
            say("Joining the chapters")
            wav, seconds = await asyncio.to_thread(audiobook.join_wavs, spoken)
            book = await kit.keep(
                wav=wav, rate=rate, seconds=seconds, title=title, mode="audiobook",
                description=f"The whole of {title}, {total} chapters", model_id=model.id,
                options=state.get("options") or {}, seed=None, parent=None,
                edit={"action": "audiobook", "book": title, "of": total, "voice": label},
                load_s=0.0, elapsed_s=time.monotonic() - t0,
                lyrics="\n\n".join(c.title for c in chapters),
            )  # fmt: skip
        return {
            "tracks": made, "book": book, "chapters": total, "title": title,
            "seconds": round(sum(t["seconds"] for t in made), 2),
            "elapsed_s": round(time.monotonic() - t0, 2), "status": "done",
        }  # fmt: skip

    def characters(state: dict[str, Any]) -> int:
        chapters = state.get("chapters") or []
        return sum(len(str(c.get("text", ""))) for c in chapters if isinstance(c, dict))

    # counted in characters of text, which is what a hosted voice bills by
    return {"audiobook": metered(caps, BOOKS, audiobook_node, amount=characters, unit="characters")}
