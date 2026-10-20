# SPDX-License-Identifier: Apache-2.0
"""Dictation: a short spoken clip from the chat box, written down and thrown away (ADR-0083).

The window records the microphone and averages it down to 16 kHz mono 16-bit PCM WAV itself, so this
side does not convert anything (no ffmpeg) and accepts nothing else: a clip that is not exactly that
is refused in words. The checks run before the speech model is touched, and they are the
hardening of ADR-0035 for sound: a size limit, a length limit, the real header read (not the file
name), the length measured from the samples that are there (not from what the header claims), and a
clip with nothing in it is refused rather than sent to a model that would invent words for it."""

import io
import sys
import wave
from array import array
from dataclasses import dataclass

RATE = 16000
MAX_BYTES = 10 * 1024 * 1024  # five minutes at 16 kHz mono 16-bit is 9.6 MB
MAX_SECONDS = 300.0
MIN_SECONDS = 0.3
SILENCE_PEAK = 0.004  # of full scale (about -48 dB): quieter than a still room's microphone


class DictationError(Exception):
    """`code` is stable; `str(e)` is a sentence safe to show."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Clip:
    seconds: float
    peak: float  # 0 to 1


def inspect(data: bytes) -> Clip:
    """The facts of a clip that may be dictated, or a `DictationError` that says what is wrong."""
    if not data:
        raise DictationError("empty", "That recording is empty. Try again.")
    if len(data) > MAX_BYTES:
        raise DictationError(
            "too_large", "That recording is too long to write down here. Dictate a shorter part."
        )
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise DictationError("not_wav", "That was not a recording this app can read.")
    try:
        with wave.open(io.BytesIO(data)) as w:
            rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
            if (rate, channels, width) != (RATE, 1, 2):
                raise DictationError(
                    "wrong_format", "That recording is not in the form dictation reads. Try again."
                )
            samples = w.readframes(min(w.getnframes(), int(MAX_SECONDS * RATE) + 1))
    except (wave.Error, EOFError):
        raise DictationError("not_wav", "That was not a recording this app can read.") from None
    pcm = array("h")
    pcm.frombytes(samples[: len(samples) - len(samples) % 2])
    if sys.byteorder == "big":  # WAV is little-endian
        pcm.byteswap()
    seconds = len(pcm) / RATE
    if seconds > MAX_SECONDS:
        raise DictationError(
            "too_long", "That recording is longer than five minutes. Dictate a shorter part."
        )
    if seconds < MIN_SECONDS:
        raise DictationError(
            "too_short", "That was too short to write down. Speak for a little longer."
        )
    peak = max(max(pcm), -min(pcm)) / 32768
    if peak < SILENCE_PEAK:
        raise DictationError(
            "silent",
            "Nothing could be heard. Check that the right microphone is chosen and try again.",
        )
    return Clip(seconds, peak)
