"""The speaker model's own code: features made a chunk at a time equal the whole recording's, the
WAV reader takes only what the model reads, and chances become turns as NeMo makes them."""

import struct
import wave
from pathlib import Path

import numpy as np
import pytest
from wasifyai_meetings import sortformer as sf


def _wav(path: Path, samples: np.ndarray, rate: int = 16000, channels: int = 1) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.astype("<i2").tobytes())
    return path


def _whole(x: np.ndarray) -> np.ndarray:
    """The spike's way: pre-emphasis, then zeros at both ends, then every frame at once."""
    e = np.empty_like(x)
    e[0] = x[0]
    e[1:] = x[1:] - sf.PREEMPH * x[:-1]
    padded = np.pad(e, (sf.NFFT // 2, sf.NFFT // 2))
    frames = np.lib.stride_tricks.sliding_window_view(padded, sf.NFFT)[:: sf.HOP]
    s = np.fft.rfft(frames * sf.WINDOW, n=sf.NFFT, axis=-1)
    power = (s.real**2 + s.imag**2).astype(np.float32)
    return np.log(power @ sf.FB_T + sf.LOG_GUARD).astype(np.float32)


def test_features_made_a_chunk_at_a_time_equal_the_whole_recordings():
    rng = np.random.default_rng(1)
    x = (rng.standard_normal(16000 * 23 + 77) * 0.1).astype(np.float32)
    whole = _whole(x)
    assert whole.shape == (sf.frame_count(len(x)), sf.NMELS)
    for a, b in [(0, sf.STRIDE), (sf.STRIDE, 2 * sf.STRIDE), (len(whole) - 300, len(whole))]:
        assert np.array_equal(sf.log_mel(x, a, b), whole[a:b])


def test_int16_samples_read_from_disk_are_scaled_as_floats():
    rng = np.random.default_rng(2)
    i16 = (rng.standard_normal(16000 * 3) * 3000).astype(np.int16)
    assert np.allclose(sf.log_mel(i16, 0, 100), _whole(i16.astype(np.float32) / 32768)[:100])


def test_the_wav_reader_takes_16khz_mono_16bit_only(tmp_path):
    ok = sf.Wav(_wav(tmp_path / "ok.wav", np.arange(32000) % 100))
    assert ok.seconds == 2.0 and ok.samples[5] == 5
    ok.close()
    with pytest.raises(sf.BadAudio, match="16 kHz"):
        sf.Wav(_wav(tmp_path / "44k.wav", np.zeros(4410), rate=44100))
    with pytest.raises(sf.BadAudio, match="one channel"):
        sf.Wav(_wav(tmp_path / "st.wav", np.zeros(3200), channels=2))
    (tmp_path / "x.wav").write_bytes(b"ID3" + bytes(100))
    with pytest.raises(sf.BadAudio, match="not a WAV"):
        sf.Wav(tmp_path / "x.wav")
    (tmp_path / "e.wav").write_bytes(b"")
    with pytest.raises(sf.BadAudio, match="empty"):
        sf.Wav(tmp_path / "e.wav")


def test_a_wav_with_an_extra_chunk_before_its_sound_is_read(tmp_path):
    data = (np.arange(1600) % 50).astype("<i2").tobytes()
    fmt = struct.pack("<HHIIHH", 1, 1, 16000, 32000, 2, 16)
    body = b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"LIST" + struct.pack("<I", 3)
    body += b"abc\x00" + b"data" + struct.pack("<I", len(data)) + data
    path = tmp_path / "list.wav"
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    w = sf.Wav(path)
    assert len(w.samples) == 1600 and w.samples[7] == 7
    w.close()


def test_the_running_median_matches_a_plain_one_at_the_ends_too():
    rng = np.random.default_rng(3)
    p = rng.random((40, 4)).astype(np.float32)
    plain = np.array(
        [[np.median(p[max(t - 5, 0) : t + 6, k]) for k in range(4)] for t in range(40)]
    )
    assert np.allclose(sf.median(p), plain)
    short = rng.random((6, 4)).astype(np.float32)
    assert np.allclose(sf.median(short), [np.median(short[0:6], axis=0)] * 1 + [
        np.median(short[max(t - 5, 0) : t + 6], axis=0) for t in range(1, 6)])  # fmt: skip


def test_chances_become_padded_turns_and_short_ones_are_dropped():
    p = np.zeros((200, 4), np.float32)
    p[10:60, 0] = 0.9  # 4 s of speaker 0
    p[63:90, 0] = 0.9  # after a gap of 0.24 s: joined to the first
    p[100:101, 1] = 0.9  # 0.08 s, 0.39 s once padded: shorter than the shortest turn (0.51 s)
    p[120:180, 2] = 0.9
    turns = sf.turns_of(p)
    assert [t.speaker for t in turns] == [0, 2]
    first = turns[0]
    assert first.start == round(10 * sf.FRAME - sf.PAD_ON, 3)
    assert first.end == round(90 * sf.FRAME + sf.PAD_OFF, 3)


def test_a_turn_still_open_at_the_end_is_closed_there():
    p = np.zeros((50, 4), np.float32)
    p[30:, 3] = 0.95
    (turn,) = sf.turns_of(p)
    assert turn.speaker == 3 and turn.end == round(50 * sf.FRAME + sf.PAD_OFF, 3)


def test_a_piece_of_a_recording_is_a_wav_of_its_own(tmp_path):
    w = sf.Wav(_wav(tmp_path / "a.wav", np.arange(48000) % 1000))
    piece = tmp_path / "piece.wav"
    piece.write_bytes(sf.wav_bytes(w.samples, 1.0, 2.5))
    w.close()
    p = sf.Wav(piece)
    assert p.seconds == 1.5 and p.samples[0] == 16000 % 1000
    p.close()
