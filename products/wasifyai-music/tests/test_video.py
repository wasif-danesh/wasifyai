import time

import pytest
from media_samples import HAVE_FFMPEG, png, probe, real_mp3
from wasifyai_music.video import VideoError, VideoUnavailable, encode_video

pytestmark = pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg is not available")


async def test_a_song_becomes_a_playable_video_of_the_same_length():
    audio = real_mp3(12)
    video = await encode_video(audio, png(1023, 1023), "Neon Rain Walk")  # an odd size on purpose
    info = probe(video, ".mp4")
    kinds = {s["kind"]: s for s in info["streams"]}
    assert kinds["video"]["codec"] == "h264" and kinds["audio"]["codec"] == "aac"
    width, height = kinds["video"]["size"]
    assert width % 2 == 0 and height % 2 == 0
    assert kinds["video"]["pix_fmt"] == "yuv420p"  # what phones and social apps accept
    # the picture must not run on past the music (`-shortest` alone overshoots by seconds)
    assert info["duration"] == pytest.approx(probe(audio, ".mp3")["duration"], abs=0.1)
    assert info["tags"]["title"] == "Neon Rain Walk"


async def test_control_characters_in_the_title_do_not_reach_ffmpeg():
    video = await encode_video(real_mp3(1), png(), "Line\none\x00two")
    assert probe(video, ".mp4")["tags"]["title"] == "Line one two"


async def test_a_missing_ffmpeg_is_reported_as_unavailable():
    with pytest.raises(VideoUnavailable):
        await encode_video(real_mp3(1), png(), "t", ffmpeg="definitely-not-ffmpeg")


async def test_a_broken_cover_fails_at_once_without_leaking_anything():
    started = time.monotonic()
    with pytest.raises(VideoError) as caught:
        await encode_video(real_mp3(1), b"not an image", "t")
    assert str(caught.value) == "the video could not be made"
    assert time.monotonic() - started < 5  # not the ffmpeg timeout


async def test_a_cover_in_another_format_is_accepted():
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("P", (101, 77), 3).save(buf, "GIF")  # odd size, palette image
    video = await encode_video(real_mp3(1), buf.getvalue(), "t")
    width, height = probe(video, ".mp4")["streams"][0]["size"]
    assert width % 2 == 0 and height % 2 == 0
