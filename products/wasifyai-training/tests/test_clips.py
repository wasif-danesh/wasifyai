# ruff: noqa: E501  (the sentences shown to people, and made-up media in a test, are easier to read on one line)
"""What is said about a clip: read with ffmpeg, checked in words. Real ffmpeg, made-up clips."""

import subprocess
from pathlib import Path

import pytest
from PIL import Image
from wasifyai_training import clips, pictures

FFMPEG = clips.ffmpeg_path()


def make(path: Path, source: str, seconds: float = 2.0, size: str = "320x240") -> Path:
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"{source}{':' if '=' in source else '='}s={size}:r=24:d={seconds}",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    return path


def test_the_report_of_ffmpeg_is_read_for_size_length_and_rate():
    report = (
        "  Duration: 00:00:02.04, start: 0.000000, bitrate: 1234 kb/s\n"
        "  Stream #0:0[0x1](und): Video: h264 (High), yuv420p(progressive), 1920x1080 [SAR 1:1 DAR 16:9], 1200 kb/s, 25 fps, 25 tbr\n"
    )
    info = clips.parse_info(report)
    assert (info.width, info.height, info.seconds, info.fps, info.frames) == (
        1920,
        1080,
        2.04,
        25.0,
        51,
    )
    with pytest.raises(clips.BadClip, match="could not be read as a video"):
        clips.parse_info("Invalid data found when processing input")
    with pytest.raises(clips.BadClip):
        clips.parse_info("  Duration: N/A\n  Stream #0:0: Audio: aac")


async def test_a_real_clip_is_read_and_a_frame_taken(tmp_path: Path):
    path = make(tmp_path / "c.mp4", "testsrc2", 2.0, "640x480")
    info = await clips.probe(path)
    assert (info.width, info.height) == (640, 480) and 1.9 < info.seconds < 2.2 and info.fps == 24.0
    frame = await clips.frame_at(path, 1.0)
    assert frame.size == (640, 480) and clips.brightness(frame) > clips.DARK_BELOW


async def test_a_file_that_is_not_a_video_or_is_tiny_is_refused_in_words(tmp_path: Path):
    junk = tmp_path / "x.mp4"
    junk.write_bytes(b"not a video at all")
    with pytest.raises(clips.BadClip, match="could not be read as a video"):
        await clips.probe(junk)
    tiny = make(tmp_path / "t.mp4", "testsrc2", 2.0, "48x48")
    with pytest.raises(clips.BadClip, match="too small"):
        await clips.probe(tiny)


async def test_the_checks_say_in_words_what_is_wrong(tmp_path: Path):
    good = make(tmp_path / "g.mp4", "testsrc2", 3.0, "640x480")
    info = await clips.probe(good)
    mid = await clips.frame_at(good, 1.5)
    early = await clips.frame_at(good, 0.3)
    late = await clips.frame_at(good, 2.6)
    assert clips.check(info, mid, [early, late], []) == [
        {"code": "good", "level": "ok", "message": "Good."}
    ]
    still = make(tmp_path / "s.mp4", "color=c=0x80a0c0", 3.0, "640x480")
    s_info = await clips.probe(still)
    s_mid = await clips.frame_at(still, 1.5)
    codes = {
        c["code"]
        for c in clips.check(
            s_info, s_mid, [await clips.frame_at(still, 0.3), await clips.frame_at(still, 2.6)], []
        )
    }
    assert {"still", "blurry"} <= codes
    black = make(tmp_path / "b.mp4", "color=c=black", 3.0, "640x480")
    b_codes = {
        c["code"]
        for c in clips.check(await clips.probe(black), await clips.frame_at(black, 1.5), [], [])
    }
    assert "dark" in b_codes
    short_small = clips.ClipInfo(320, 240, 0.8, 24.0)
    got = {c["code"]: c["message"] for c in clips.check(short_small, mid, [], [])}
    assert "0.8 seconds" in got["too_short"] and "320 by 240" in got["too_small"]
    copy = clips.check(info, mid, [], [pictures.dhash(mid)])
    assert any(c["code"] == "copy" for c in copy)


def test_a_dark_picture_is_found_dark():
    assert clips.brightness(Image.new("RGB", (4000, 3000), (10, 10, 10))) < clips.DARK_BELOW
