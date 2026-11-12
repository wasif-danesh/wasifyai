"""Documents attached to a chat message (ADR-0083, stage CO2): read into plain text on the engine,
the file itself never kept, a refusal in words for what cannot be read."""

import pytest
from fastapi.testclient import TestClient
from wasifyai_platform_sdk import (
    InMemoryUploadLimiter,
    InMemoryUploadStore,
    InMemoryUsageRecorder,
    ScopedStorage,
    memory_storage,
    object_key,
)

from tests.test_runs import hello_registry, mem_app

URL = "/products/wasifyai-assistant/attachments"


@pytest.fixture
def parts(tmp_path):
    (tmp_path / "hello").mkdir()
    (tmp_path / "hello" / "product.yaml").write_text(
        "id: hello\ncapabilities:\n  text.chat: { provider: fake, defaults: { reply: hi } }\n"
    )
    return {
        "tmp": tmp_path,
        "storage": ScopedStorage(memory_storage()),
        "store": InMemoryUploadStore(),
        "usage": InMemoryUsageRecorder(),
    }


def client_for(parts, per_hour=60):
    # a fixed clock: the limit is per clock hour, and the top of the hour would reset it
    app = mem_app(
        hello_registry(), parts["tmp"], parts["usage"], storage=parts["storage"],
        uploads=parts["store"], upload_limiter=InMemoryUploadLimiter(per_hour, clock=lambda: 0.0),
    )  # fmt: skip
    return TestClient(app)


def attach(c, data: bytes, name: str = "notes.txt"):
    return c.post(URL, content=data, headers={"x-file-name": name})


def test_a_text_file_is_kept_as_its_words_under_the_persons_own_prefix(parts):
    with client_for(parts) as c:
        r = attach(c, b"Launch budget: 40,000 dollars.\n", "folder\\budget.md")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "document" and body["name"] == "budget.md"
    assert body["chars"] == len("Launch budget: 40,000 dollars.")
    assert body["truncated"] is False
    (record,) = parts["store"].rows.values()
    assert record.key == f"uploads/{body['id']}.txt" and record.kind == "text"
    stored = parts["storage"].backing  # the bytes are the text, under tenant, product and user
    assert record.owner[1] == "wasifyai-assistant"
    key = object_key(*record.owner, record.key)
    import asyncio

    assert asyncio.run(stored.get(key)).decode().startswith("Launch budget")


def test_csv_html_and_markdown_are_read_as_text(parts):
    with client_for(parts) as c:
        csv = attach(c, b"name,score\nAda,10\nBob,7\n", "scores.csv")
        html = attach(c, b"<html><body><h1>Title</h1><p>Hello world</p></body></html>", "page.html")
    assert csv.status_code == 201 and html.status_code == 201
    assert csv.json()["chars"] > 10


@pytest.mark.parametrize(
    ("data", "name", "code"),
    [
        (b"", "empty.txt", 422),  # nothing was sent
        (b"MZ\x90\x00\x03\x00\x00\x00 binary", "program.exe", 415),  # not a kind of file we read
        (b"\x00\x01\x02 not text \x00", "disguised.txt", 415),  # bytes do not match the name
        (b"   \n  ", "blank.txt", 422),  # no words in it
        (b"\x89PNG\r\n\x1a\n....", "picture.png", 415),  # a picture goes through the picture button
    ],
)
def test_what_cannot_be_read_is_refused_in_words(parts, data, name, code):
    with client_for(parts) as c:
        r = attach(c, data, name)
    assert r.status_code == code, r.text
    assert parts["store"].rows == {}  # nothing was kept
    assert r.json()["detail"]  # a sentence for the person


def test_a_file_that_is_too_large_is_refused_before_it_is_read(parts):
    with client_for(parts) as c:
        r = attach(c, b"a" * (10 * 1024 * 1024 + 1), "big.txt")
    assert r.status_code == 413 and "10 MB" in r.json()["detail"]


def test_a_long_document_keeps_its_first_words_and_says_so(parts):
    with client_for(parts) as c:
        r = attach(c, ("word " * 60_000).encode(), "long.txt")
    body = r.json()
    assert r.status_code == 201 and body["truncated"] is True and body["chars"] == 200_000


def test_a_pdf_without_the_document_reader_says_what_to_set_up(parts, monkeypatch):
    from wasifyai_notebooks import reading

    class Missing:
        async def read(self, path, suffix):
            raise reading.Unavailable("reader_missing", "not installed")

        async def close(self):
            return None

    monkeypatch.setattr(reading, "RoutingReader", lambda comps: Missing())
    import wasifyai_notebooks.runtime as rt

    class FakeRuntime:
        components = object()

    monkeypatch.setattr(rt, "runtime_for", lambda state: FakeRuntime())
    with client_for(parts) as c:
        r = attach(c, b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n", "paper.pdf")
    assert r.status_code == 422 and "document reader" in r.json()["detail"]


def test_attachments_are_counted_against_the_hourly_upload_limit(parts):
    with client_for(parts, per_hour=2) as c:
        assert attach(c, b"one").status_code == 201
        assert attach(c, b"two").status_code == 201
        assert attach(c, b"three").status_code == 429


def test_the_name_that_comes_back_is_a_name_and_not_markup_or_a_path(parts):
    with client_for(parts) as c:
        r = attach(c, b"hello", "..\\..\\etc\\passwd\x07<b>x</b>.txt")
    assert r.status_code == 201 and "/" not in r.json()["name"] and "\\" not in r.json()["name"]
    assert "\x07" not in r.json()["name"]


def test_a_name_sent_percent_encoded_is_read_back(parts):
    from urllib.parse import quote

    with client_for(parts) as c:
        r = attach(c, b"hello", quote("Résumé 2026.md"))
    assert r.status_code == 201 and r.json()["name"] == "Résumé 2026.md"


# ---- recordings and clips (docs/chat-does-everything-plan.md, CE2) ----

MEDIA = "/products/wasifyai-assistant/attachments/media"


def tone_clip(seconds: float = 1.5) -> bytes:
    import subprocess
    import tempfile
    from pathlib import Path

    from wasifyai_video.videos import ffmpeg_path

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "clip.mov"
        subprocess.run(
            [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", f"testsrc=size=1920x1080:rate=24:duration={seconds}",
             "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-metadata", "title=secret", "-shortest",
             str(out)],
            check=True,
        )  # fmt: skip
        return out.read_bytes()


def silent_wav(seconds: float, rate: int = 44100) -> bytes:
    import struct

    pcm = b"\0\0\0\0" * int(rate * seconds)
    return (
        b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 2, rate, rate * 4, 4, 16) + b"data"
        + struct.pack("<I", len(pcm)) + pcm
    )  # fmt: skip


def stored(parts, record) -> bytes:
    import asyncio

    return asyncio.run(parts["storage"].get_for(record.owner, record.key))


def test_a_clip_is_kept_as_a_clean_mp4_with_its_sound_and_no_tags(parts):
    import subprocess
    import tempfile
    from pathlib import Path

    from wasifyai_video.videos import ffmpeg_path

    with client_for(parts) as c:
        r = c.post(MEDIA, content=tone_clip(), headers={"x-file-name": "talk.mov"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "video" and body["name"] == "talk.mov" and 1 <= body["seconds"] <= 2
    (record,) = parts["store"].rows.values()
    assert record.key == f"uploads/{body['id']}.mp4" and record.kind == "video"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "kept.mp4"
        path.write_bytes(stored(parts, record))
        report = subprocess.run(
            [ffmpeg_path(), "-hide_banner", "-i", str(path)], capture_output=True, text=True
        ).stderr
    assert "Video: h264" in report and "Audio: aac" in report
    assert "1280x720" in report  # made smaller: the longer side at most 1280
    assert "secret" not in report  # no tags of the file sent


def test_a_recording_is_kept_as_a_wav_and_a_long_one_is_refused(parts):
    with client_for(parts) as c:
        ok = c.post(MEDIA, content=silent_wav(1), headers={"x-file-name": "memo.wav"})
        long = c.post(MEDIA, content=silent_wav(601, 8000), headers={"x-file-name": "talk.wav"})
    assert ok.status_code == 201, ok.text
    assert ok.json()["kind"] == "audio" and ok.json()["seconds"] == 1
    assert long.status_code == 422 and "10 minutes" in long.json()["detail"]


def test_a_file_that_is_neither_or_not_what_it_says_is_refused_in_words(parts):
    with client_for(parts) as c:
        other = c.post(MEDIA, content=b"hello", headers={"x-file-name": "notes.txt"})
        fake = c.post(MEDIA, content=b"not a video at all", headers={"x-file-name": "clip.mp4"})
    assert other.status_code == 415 and "recording" in other.json()["detail"]
    assert fake.status_code == 422 and "not a video" in fake.json()["detail"]
    assert parts["store"].rows == {}


def test_a_clip_over_the_size_limit_is_refused_before_it_is_read(parts):
    with client_for(parts) as c:
        r = c.post(
            MEDIA,
            content=b"x",
            headers={"x-file-name": "big.mp4", "content-length": str(201 * 2**20)},
        )
    assert r.status_code == 413 and "200 MB" in r.json()["detail"]
