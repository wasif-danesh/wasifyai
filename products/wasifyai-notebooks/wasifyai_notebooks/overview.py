# SPDX-License-Identifier: Apache-2.0
"""Giving the audio overview its voices (ADR-0066, stage V2): the script of two hosts is spoken
turn by turn by the person's speech model, the pieces are joined with a short pause, and the result
is kept with the output as `overview.wav`. It runs in the background (about a second of work per
turn), and the window asks how far it has got.

The speech engine is reached as `app_state.audio`, as the assistant and the voice product reach it;
nothing here imports the API."""

import asyncio
import io
import logging
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk import VoiceEngineError, VoiceModel, VoiceRequestError, check_speak

log = logging.getLogger(__name__)

AUDIO_FILE = "overview.wav"
PAUSE_S = 0.35  # between two turns of the same host
SWITCH_PAUSE_S = 0.55  # when the other host answers


class NotPossible(Exception):
    """The overview cannot be spoken as asked; `str(e)` is a sentence safe to show."""


@dataclass
class VoiceJob:
    state: str = "working"  # working | ready | failed
    done: int = 0
    total: int = 0
    message: str = ""

    def public(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "done": self.done,
            "total": self.total,
            "message": self.message,
        }


def choose_voices(model: VoiceModel, asked: dict[str, str] | None) -> dict[int, str]:
    """A built-in voice for each host: the ones asked for, else the model's default and the first
    voice of the other gender (so the two hosts are told apart by ear)."""
    if not model.voices:
        raise NotPossible(f"{model.title} has no voices to choose from. Pick a model with voices.")
    out: dict[int, str] = {}
    for host in (1, 2):
        wanted = (asked or {}).get(str(host))
        if wanted:
            if model.voice(wanted) is None:
                raise NotPossible(f"{model.title} has no voice '{wanted}'.")
            out[host] = wanted
    if 1 not in out:
        out[1] = model.default_voice or model.voices[0].id
    if 2 not in out:
        first = model.voice(out[1])
        other = next(
            (v for v in model.voices if v.id != out[1] and first and v.gender != first.gender),
            next((v for v in model.voices if v.id != out[1]), model.voices[0]),
        )
        out[2] = other.id
    return out


def join_wavs(pieces: list[tuple[bytes, float]]) -> bytes:
    """One WAV from `(wav, pause_after_seconds)` pieces that share a rate. Raises ValueError if they
    do not (they come from one model, so they do)."""
    out = io.BytesIO()
    writer: wave.Wave_write | None = None
    rate = 0
    for data, pause in pieces:
        with wave.open(io.BytesIO(data)) as r:
            if writer is None:
                rate = r.getframerate()
                writer = wave.open(out, "wb")
                writer.setnchannels(r.getnchannels())
                writer.setsampwidth(r.getsampwidth())
                writer.setframerate(rate)
            elif r.getframerate() != rate:
                raise ValueError("the pieces were not made at one rate")
            frames = r.readframes(r.getnframes())
            writer.writeframes(frames)
            silence = b"\x00" * (r.getsampwidth() * r.getnchannels())
            writer.writeframes(silence * int(rate * pause))
    if writer is None:
        raise ValueError("nothing to join")
    writer.close()
    return out.getvalue()


class Voicer:
    """The overviews being spoken. State is in memory: a restart forgets a job that was running, and
    the output simply still has no audio."""

    def __init__(self) -> None:
        self._jobs: dict[tuple[str, str], VoiceJob] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def job(self, nid: str, aid: str) -> VoiceJob | None:
        return self._jobs.get((nid, aid))

    def start(
        self,
        *,
        engine: Any,
        model: VoiceModel,
        voices: dict[int, str],
        turns: list[dict[str, Any]],
        out_dir: Path,
        key: tuple[str, str],
        on_done: Any,
    ) -> VoiceJob:
        current = self._jobs.get(key)
        if current and current.state == "working":
            raise NotPossible("The voices are already being made.")
        job = VoiceJob(total=len(turns))
        self._jobs[key] = job
        task = asyncio.create_task(self._run(job, engine, model, voices, turns, out_dir, on_done))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def _run(
        self,
        job: VoiceJob,
        engine: Any,
        model: VoiceModel,
        voices: dict[int, str],
        turns: list[dict[str, Any]],
        out_dir: Path,
        on_done: Any,
    ) -> None:
        pieces: list[tuple[bytes, float]] = []
        try:
            for i, turn in enumerate(turns):
                text, voice, options = check_speak(
                    model, str(turn["text"]), voices[int(turn["speaker"])], None
                )
                result = await engine.speak(model, text, voice, options)
                following = turns[i + 1]["speaker"] if i + 1 < len(turns) else turn["speaker"]
                pieces.append(
                    (result.wav, SWITCH_PAUSE_S if following != turn["speaker"] else PAUSE_S)
                )
                job.done = i + 1
            wav = await asyncio.to_thread(join_wavs, pieces)
            out_dir.mkdir(parents=True, exist_ok=True)
            tmp = out_dir / (AUDIO_FILE + ".part")
            await asyncio.to_thread(tmp.write_bytes, wav)
            tmp.replace(out_dir / AUDIO_FILE)
            await on_done(model.id, voices)
            job.state = "ready"
        except (VoiceEngineError, VoiceRequestError) as e:
            job.state, job.message = "failed", getattr(e, "message", str(e))
        except Exception:
            log.exception("the audio overview could not be spoken")
            job.state, job.message = "failed", "The voices could not be made. Try again."
