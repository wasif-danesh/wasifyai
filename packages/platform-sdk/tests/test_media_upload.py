import io
import struct
import wave

import pytest
from wasifyai_platform_sdk import UploadError, process_audio
from wasifyai_platform_sdk.media_upload import sniff


def tone(seconds: float = 1.0, rate: int = 22050) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<hh", 3000, -3000) * int(rate * seconds))
    return buf.getvalue()


def test_the_container_is_decided_by_the_first_bytes():
    assert sniff(tone()) == "wav"
    assert sniff(b"OggS" + b"\0" * 20) == "ogg"
    assert sniff(b"fLaC" + b"\0" * 20) == "flac"
    assert sniff(b"ID3\x04" + b"\0" * 20) == "mp3"
    assert sniff(b"\xff\xfb\x90\x00" + b"\0" * 20) == "mp3"
    assert sniff(b"\x00\x00\x00\x18ftypM4A " + b"\0" * 20) == "mp4"
    assert sniff(b"\x1a\x45\xdf\xa3" + b"\0" * 20) == "matroska"
    assert sniff(b"RIFF\0\0\0\0AVI " + b"\0" * 20) is None  # RIFF, but not WAVE
    assert sniff(b"just some text, named .mp3") is None
    assert sniff(b"") is None


def test_anything_else_is_refused_whatever_it_is_called():
    with pytest.raises(UploadError) as e:
        process_audio(b"this is not audio, even if it is named song.mp3" * 10)
    assert e.value.status == 415


def test_a_wav_becomes_16k_mono_with_its_length():
    out = process_audio(tone(2.0))
    assert out.container == "wav"
    assert 1.9 < out.seconds < 2.1
    with wave.open(io.BytesIO(out.wav)) as w:  # readable by every reader: the lengths are filled in
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (1, 16000, 2)
        assert abs(w.getnframes() / 16000 - out.seconds) < 0.01


def test_a_file_that_claims_to_be_audio_but_is_not_cannot_be_read():
    fake = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\xff" * 200
    with pytest.raises(UploadError) as e:
        process_audio(fake)
    assert e.value.status == 422


def test_a_recording_over_the_limit_is_refused():
    with pytest.raises(UploadError) as e:
        process_audio(tone(5.0), max_seconds=2)
    assert e.value.status == 422 and "longer than" in e.value.message


def test_a_nearly_empty_recording_is_refused():
    with pytest.raises(UploadError) as e:
        process_audio(tone(0.05))
    assert e.value.status == 422
