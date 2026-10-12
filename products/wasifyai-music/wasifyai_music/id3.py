"""Put the title, lyrics and cover art inside an MP3, as an ID3v2.3 tag.

Players that show album art (phones, car stereos, desktop players, file thumbnails) then show the
song's cover while it plays, from one ordinary .mp3 file. The audio itself is never re-encoded: the
tag is written in front of the existing audio frames and any older ID3v2 tag is replaced.

Written here, not with a tagging library, because the common ones are GPL-licensed and this needs
only a handful of frames. Tested against ffprobe and against the tag layout directly."""

import io

from PIL import Image

ENC_UTF16 = b"\x01"  # text encoding byte: UTF-16 with a byte order mark
BOM = b"\xff\xfe"  # little endian
LATIN1 = b"\x00"
FRONT_COVER = 3


def syncsafe(n: int) -> bytes:
    """A 28-bit size, seven bits per byte, as ID3 tag headers store it."""
    if not 0 <= n < 1 << 28:
        raise ValueError("tag too large")
    return bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])


def read_syncsafe(b: bytes) -> int:
    return (b[0] << 21) | (b[1] << 14) | (b[2] << 7) | b[3]


def strip_id3v2(data: bytes) -> bytes:
    """The audio without any ID3v2 tag at its start."""
    if len(data) >= 10 and data[:3] == b"ID3" and all(c < 0x80 for c in data[6:10]):
        footer = 10 if data[5] & 0x10 else 0
        return data[10 + read_syncsafe(data[6:10]) + footer :]
    return data


def _utf16(text: str) -> bytes:
    return BOM + text.encode("utf-16-le")


def _frame(frame_id: str, payload: bytes) -> bytes:
    # ID3v2.3 frame sizes are plain big-endian integers (v2.4 made them syncsafe)
    return frame_id.encode("ascii") + len(payload).to_bytes(4, "big") + b"\x00\x00" + payload


def _text_frame(frame_id: str, text: str) -> bytes:
    return _frame(frame_id, ENC_UTF16 + _utf16(text))


def _long_text_frame(frame_id: str, language: str, text: str) -> bytes:
    """USLT (lyrics) and COMM (comment): language, an empty description, then the text."""
    description = BOM + b"\x00\x00"
    return _frame(frame_id, ENC_UTF16 + language.encode("ascii") + description + _utf16(text))


def _picture_frame(jpeg: bytes) -> bytes:
    return _frame(
        "APIC", LATIN1 + b"image/jpeg\x00" + bytes([FRONT_COVER]) + LATIN1 + jpeg
    )  # latin-1 empty description


def small_cover_jpeg(image: bytes, max_px: int = 1000, quality: int = 85) -> bytes:
    """The cover as a modest JPEG, so the tag adds about 150 KB, not the 1.7 MB original PNG."""
    with Image.open(io.BytesIO(image)) as im:
        rgb = im.convert("RGB")
    rgb.thumbnail((max_px, max_px))
    out = io.BytesIO()
    rgb.save(out, "JPEG", quality=quality, optimize=True)
    return out.getvalue()


def tag_mp3(
    audio: bytes,
    *,
    title: str,
    artist: str,
    lyrics: str | None = None,
    cover_jpeg: bytes | None = None,
    comment: str | None = None,
) -> bytes:
    """The same MP3 with an ID3v2.3 tag: title, artist, album, lyrics, comment and cover art."""
    frames = [_text_frame("TIT2", title), _text_frame("TPE1", artist), _text_frame("TALB", title)]
    if lyrics:
        frames.append(_long_text_frame("USLT", "eng", lyrics))
    if comment:
        frames.append(_long_text_frame("COMM", "eng", comment))
    if cover_jpeg:
        frames.append(_picture_frame(cover_jpeg))
    body = b"".join(frames)
    return b"ID3\x03\x00\x00" + syncsafe(len(body)) + body + strip_id3v2(audio)
