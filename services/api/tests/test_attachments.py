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
    app = mem_app(
        hello_registry(), parts["tmp"], parts["usage"], storage=parts["storage"],
        uploads=parts["store"], upload_limiter=InMemoryUploadLimiter(per_hour),
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
