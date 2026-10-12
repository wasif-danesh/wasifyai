import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from wasifyai_platform_sdk import Identity, RouteDeps
from wasifyai_stt.routes import build_routes
from wasifyai_stt.transcripts import InMemoryTranscriptStore, TranscriptRecord

T0 = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
BASE = "/products/wasifyai-stt"


def identity(x_user: str = Header("u1"), x_tenant: str = Header("t1")) -> Identity:
    return Identity(tenant_id=x_tenant, user_id=x_user)


def uid(n: int) -> str:
    return f"00000000-0000-0000-0000-{n:012d}"


def transcript(n, user="u1", tenant="t1", status="done", language="en", words=None):
    words = words or f"This is transcript number {n}. It has two sentences."
    return TranscriptRecord(
        id=uid(n), tenant_id=tenant, product_id="wasifyai-stt", user_id=user, thread_id=None,
        run_id=None, status=status, seconds=61.5, title=words.split(".")[0], language=language,
        engine="whisper", text=words if status == "done" else "",
        segments=[
            {"start": 0.0, "end": 1.5, "text": "This is transcript"},
            {"start": 1.5, "end": 3.0, "text": f"number {n}."},
        ] if status == "done" else [],
        error="It broke." if status == "failed" else None,
        # a row being made is recent: after half an hour it counts as a run that died
        created_at=datetime.now(UTC) - timedelta(minutes=1)
        if status == "working"
        else T0 + timedelta(minutes=n),
    )  # fmt: skip


@pytest.fixture
def client():
    store = InMemoryTranscriptStore()
    store.transcripts = [
        transcript(1), transcript(2, language="bn", words="আমাদের দোকানে আপনাকে স্বাগতম।"),
        transcript(3, status="working"), transcript(4, status="failed"),
        transcript(5, user="someone-else"), transcript(6, tenant="other-tenant"),
    ]  # fmt: skip
    app = FastAPI()

    class Index:
        removed: list = []

        async def remove(self, tenant_id, product_id, item_id):
            self.removed.append((tenant_id, product_id, item_id))

    app.state.creation_index = Index()
    app.include_router(build_routes(RouteDeps(app.state, identity), store), prefix=BASE)
    c = TestClient(app)
    c.index = app.state.creation_index  # type: ignore[attr-defined]
    return c


def test_the_form_gets_the_languages_with_their_quality_and_the_upload_limits(client):
    body = client.get(f"{BASE}/languages").json()
    by_id = {x["id"]: x for x in body["languages"]}
    assert by_id["bn"] == {"id": "bn", "name": "বাংলা", "english": "Bengali", "quality": "fair"}
    assert by_id["en"]["quality"] == "good" and by_id["ja"]["name"] == "日本語"
    assert (
        by_id["hi"]["quality"] == "good" and by_id["sat"]["name"] == "ᱥᱟᱱᱛᱟᱲᱤ"
    )  # Indic engine only
    assert body["max_seconds"] == 1800 and body["max_bytes"] == 104857600


def test_the_list_is_the_callers_own_newest_first_with_a_short_preview(client):
    body = client.get(f"{BASE}/transcripts").json()
    assert [t["id"] for t in body["transcripts"]] == [
        uid(3),
        uid(4),
        uid(2),
        uid(1),
    ]  # the one being made is the newest
    first = body["transcripts"][-1]
    assert first["preview"].startswith("This is transcript number 1.") and "text" not in first
    bengali = next(t for t in body["transcripts"] if t["id"] == uid(2))
    assert bengali["language_name"] == "বাংলা" and bengali["seconds"] == 61.5
    failed = next(t for t in body["transcripts"] if t["id"] == uid(4))
    assert failed["status"] == "failed" and failed["error"] == "It broke."


def test_the_working_ones_are_found_by_status_and_paging_and_ids_work(client):
    working = client.get(f"{BASE}/transcripts", params={"status": "working"}).json()
    assert [t["id"] for t in working["transcripts"]] == [uid(3)]
    page = client.get(f"{BASE}/transcripts", params={"limit": 2}).json()
    assert len(page["transcripts"]) == 2 and page["next_before"]
    rest = client.get(
        f"{BASE}/transcripts", params={"limit": 2, "before": page["next_before"]}
    ).json()
    assert [t["id"] for t in rest["transcripts"]] == [uid(2), uid(1)]
    got = client.get(f"{BASE}/transcripts", params={"ids": f"{uid(2)},{uid(1)},{uid(5)}"}).json()
    assert [t["id"] for t in got["transcripts"]] == [uid(2), uid(1)]  # someone else's is not there
    assert client.get(f"{BASE}/transcripts", params={"ids": "nope"}).status_code == 422


def test_one_transcript_has_its_words_and_timed_segments_and_leaks_nothing_else(client):
    body = client.get(f"{BASE}/transcripts/{uid(1)}").json()
    assert body["text"].startswith("This is transcript number 1.")
    assert body["segments"][1] == {"start": 1.5, "end": 3.0, "text": "number 1."}
    for n in (5, 6):
        assert client.get(f"{BASE}/transcripts/{uid(n)}").status_code == 404
    assert client.get(f"{BASE}/transcripts/not-a-uuid").status_code == 404


def test_download_in_four_formats_as_an_attachment(client):
    txt = client.get(f"{BASE}/transcripts/{uid(1)}/download")
    assert txt.status_code == 200 and txt.headers["content-type"].startswith("text/plain")
    assert txt.text.startswith("This is transcript number 1.") and txt.text.endswith("\n")
    assert 'filename="this-is-transcript-number-1.txt"' in txt.headers["content-disposition"]
    assert txt.headers["cache-control"] == "private, no-store"
    srt = client.get(f"{BASE}/transcripts/{uid(1)}/download", params={"format": "srt"})
    assert srt.text.startswith("1\n00:00:00,000 --> 00:00:01,500\nThis is transcript")
    vtt = client.get(f"{BASE}/transcripts/{uid(1)}/download", params={"format": "vtt"})
    assert vtt.text.startswith("WEBVTT")
    data = json.loads(
        client.get(f"{BASE}/transcripts/{uid(1)}/download", params={"format": "json"}).text
    )
    assert data["language"] == "en" and data["segments"][0]["start"] == 0.0
    assert client.get(f"{BASE}/transcripts/{uid(1)}/download?format=exe").status_code == 422


def test_a_bengali_transcript_downloads_with_its_own_name(client):
    r = client.get(f"{BASE}/transcripts/{uid(2)}/download")
    assert r.status_code == 200 and "স্বাগতম" in r.content.decode("utf-8")
    assert "filename*=UTF-8''" in r.headers["content-disposition"]


def test_only_finished_transcripts_can_be_downloaded_and_never_someone_elses(client):
    for n in (3, 4, 5, 6):
        assert client.get(f"{BASE}/transcripts/{uid(n)}/download").status_code == 404


def test_delete_removes_the_row_and_the_search_entry_but_not_while_it_is_being_made(client):
    assert client.delete(f"{BASE}/transcripts/{uid(1)}").status_code == 204
    assert client.get(f"{BASE}/transcripts/{uid(1)}").status_code == 404
    assert client.index.removed == [("t1", "wasifyai-stt", uid(1))]
    assert client.delete(f"{BASE}/transcripts/{uid(3)}").status_code == 409  # still being made
    assert client.delete(f"{BASE}/transcripts/{uid(4)}").status_code == 204  # a failed one: dismiss
    assert client.delete(f"{BASE}/transcripts/{uid(5)}").status_code == 404
    assert len(client.index.removed) == 2  # a refused delete removes nothing from search
