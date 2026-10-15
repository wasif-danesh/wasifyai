import pytest
from media_samples import FAKE_FRAMES, HAVE_FFMPEG, decodes_cleanly, png, probe, real_mp3
from PIL import Image
from wasifyai_music.id3 import read_syncsafe, small_cover_jpeg, strip_id3v2, syncsafe, tag_mp3

JPEG = b"\xff\xd8\xff\xe0" + b"jpegbytes" * 20


def frames_of(tagged: bytes) -> dict[str, bytes]:
    """Read the tag back the way a player would, without our writer's help."""
    assert tagged[:5] == b"ID3\x03\x00"
    assert tagged[5] == 0 and all(b < 0x80 for b in tagged[6:10])  # no flags, syncsafe size
    size, found, pos = read_syncsafe(tagged[6:10]), {}, 10
    while pos < 10 + size:
        fid = tagged[pos : pos + 4].decode("ascii")
        length = int.from_bytes(tagged[pos + 4 : pos + 8], "big")
        assert tagged[pos + 8 : pos + 10] == b"\x00\x00"  # no frame flags
        found[fid] = tagged[pos + 10 : pos + 10 + length]
        pos += 10 + length
    assert pos == 10 + size  # frames fill the tag exactly
    return found


def text_of(frame: bytes) -> str:
    assert frame[:3] == b"\x01\xff\xfe"
    return frame[3:].decode("utf-16-le")


def test_sizes_are_syncsafe():
    for n in (0, 1, 127, 128, 16383, 16384, 2**28 - 1):
        packed = syncsafe(n)
        assert all(b < 0x80 for b in packed) and read_syncsafe(packed) == n
    with pytest.raises(ValueError):
        syncsafe(2**28)


def test_the_tag_holds_the_song_and_the_audio_is_untouched():
    tagged = tag_mp3(
        FAKE_FRAMES,
        title="Neon Rain Walk",
        artist="Wasify AI",
        lyrics="[verse]\nrain",
        cover_jpeg=JPEG,
        comment="Made with Wasify AI",
    )
    f = frames_of(tagged)
    assert list(f) == ["TIT2", "TPE1", "TALB", "USLT", "COMM", "APIC"]
    assert (text_of(f["TIT2"]), text_of(f["TPE1"]), text_of(f["TALB"])) == (
        "Neon Rain Walk",
        "Wasify AI",
        "Neon Rain Walk",
    )
    # lyrics: encoding, language, an empty description, then the text
    assert f["USLT"][:4] == b"\x01eng" and f["USLT"].endswith("[verse]\nrain".encode("utf-16-le"))
    # picture: latin-1, mime, type 3 (front cover), empty description, then the JPEG
    assert f["APIC"] == b"\x00image/jpeg\x00\x03\x00" + JPEG
    assert tagged.endswith(FAKE_FRAMES)  # the audio frames are byte-for-byte what they were


def test_text_survives_other_scripts_and_symbols():
    title = "Café 日本語 ☂ — “quoted”"
    assert text_of(frames_of(tag_mp3(FAKE_FRAMES, title=title, artist="x"))["TIT2"]) == title


def test_an_older_tag_is_replaced_not_stacked():
    once = tag_mp3(FAKE_FRAMES, title="Old", artist="x")
    twice = tag_mp3(once, title="New", artist="x")
    assert frames_of(twice).keys() == {"TIT2", "TPE1", "TALB"}
    assert text_of(frames_of(twice)["TIT2"]) == "New"
    assert twice.endswith(FAKE_FRAMES) and twice.count(b"ID3\x03") == 1


def test_a_foreign_tag_with_a_footer_is_stripped_cleanly():
    old = b"ID3\x04\x00\x10" + syncsafe(30) + b"x" * 30 + b"3DI\x04\x00\x10" + syncsafe(30)
    assert strip_id3v2(old + FAKE_FRAMES) == FAKE_FRAMES


def test_audio_that_only_looks_like_a_tag_is_left_alone():
    looks = b"ID3" + bytes([4, 0, 0, 0xFF, 0xFF, 0xFF, 0xFF]) + b"audio"  # a size with high bits
    assert strip_id3v2(looks) == looks
    assert strip_id3v2(FAKE_FRAMES) == FAKE_FRAMES and strip_id3v2(b"") == b""


def test_optional_parts_can_be_left_out():
    f = frames_of(tag_mp3(FAKE_FRAMES, title="t", artist="a"))
    assert set(f) == {"TIT2", "TPE1", "TALB"}


def test_the_cover_becomes_a_small_jpeg():
    big = Image.new("RGBA", (2000, 1500), (10, 200, 120, 128))
    import io

    buf = io.BytesIO()
    big.save(buf, "PNG")
    jpeg = small_cover_jpeg(buf.getvalue())
    assert jpeg[:3] == b"\xff\xd8\xff"
    with Image.open(io.BytesIO(jpeg)) as out:
        assert out.format == "JPEG" and max(out.size) == 1000 and out.size == (1000, 750)
    assert len(jpeg) < len(buf.getvalue())
    with pytest.raises(OSError):  # Pillow's UnidentifiedImageError
        small_cover_jpeg(b"not an image")


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg is not available")
def test_ffmpeg_reads_the_tag_and_sees_the_cover():
    audio = real_mp3()
    tagged = tag_mp3(
        audio,
        title="Neon Rain Walk",
        artist="Wasify AI",
        lyrics="[verse]\nrain falls",
        cover_jpeg=small_cover_jpeg(png(1200, 900)),
        comment="Made with Wasify AI",
    )
    info = probe(tagged, ".mp3")
    assert info["tags"]["title"] == "Neon Rain Walk" and info["tags"]["artist"] == "Wasify AI"
    assert info["tags"]["album"] == "Neon Rain Walk"
    assert "rain falls" in info["report"]  # the lyrics tag
    audio_stream = next(s for s in info["streams"] if s["kind"] == "audio")
    picture = next(s for s in info["streams"] if s["kind"] == "video")
    assert audio_stream["codec"] == "mp3" and picture["codec"] == "mjpeg"
    assert picture["attached_pic"] and max(picture["size"]) <= 1000
    assert decodes_cleanly(tagged, ".mp3")  # still plays, with nothing wrong in the stream
    assert info["duration"] == pytest.approx(probe(audio, ".mp3")["duration"], abs=0.1)
