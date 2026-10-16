# SPDX-License-Identifier: Apache-2.0
"""The recording a cloned voice is made from: checked, cut to a length the models take, kept as WAV.

The models take 2 to 30 seconds. A longer recording is cut at 30 seconds (the start, where a person
usually speaks most clearly); a shorter one is refused in words. Anything that is not 16-bit PCM
WAV is converted first (ffmpeg or macOS afconvert), because the standard library cannot read it."""

import io
import wave

from wasifyai_voice import audio_input

MIN_SECONDS = 2.0
MAX_SECONDS = 30.0
RATE = 24000


def _cut(wav: bytes) -> tuple[bytes, float]:
    """(WAV of at most MAX_SECONDS, its length). Raises wave.Error for what is not 16-bit PCM."""
    with wave.open(io.BytesIO(wav)) as w:
        rate, width, channels = w.getframerate(), w.getsampwidth(), w.getnchannels()
        if width != 2 or rate <= 0:
            raise wave.Error("not 16-bit")
        seconds = w.getnframes() / rate
        if seconds <= MAX_SECONDS:
            return wav, seconds
        frames = w.readframes(int(MAX_SECONDS * rate))
    out = io.BytesIO()
    with wave.open(out, "wb") as o:
        o.setnchannels(channels)
        o.setsampwidth(width)
        o.setframerate(rate)
        o.writeframes(frames)
    return out.getvalue(), MAX_SECONDS


async def prepare(data: bytes, filename: str) -> tuple[bytes, float]:
    """(mono WAV, seconds) for a recording a person gave, or an AudioInputError in words."""
    wav = await audio_input.to_wav(data, filename, RATE)
    try:
        cut, seconds = _cut(wav)
    except (wave.Error, EOFError):
        # float or 24-bit samples, or a damaged header: let the converter normalise it
        wav = await audio_input.to_wav(data, filename, RATE, force=True)
        try:
            cut, seconds = _cut(wav)
        except (wave.Error, EOFError):
            raise audio_input.AudioInputError(
                "unsupported_audio", "That recording could not be read. Try a WAV or MP3."
            ) from None
    if seconds < MIN_SECONDS:
        raise audio_input.AudioInputError(
            "too_short", f"That recording is under {MIN_SECONDS:.0f} seconds. Use 3 to 30 seconds."
        )
    return cut, seconds
