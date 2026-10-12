from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from wasifyai_platform_sdk import (
    Identity,
    RouteDeps,
    RunContext,
    ScopedStorage,
    memory_storage,
    reset_context,
    set_context,
)
from wasifyai_tts.routes import build_routes, content_disposition, file_name
from wasifyai_tts.speeches import InMemorySpeechStore, SpeechRecord
from wasifyai_tts.voices import load_catalog

T0 = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
BASE = "/products/wasifyai-tts"


def identity(x_user: str = Header("u1"), x_tenant: str = Header("t1")) -> Identity:
    return Identity(tenant_id=x_tenant, user_id=x_user)


def uid(n: int) -> str:
    return f"00000000-0000-0000-0000-{n:012d}"


def speech(n, user="u1", tenant="t1", language="en-US", text=None) -> SpeechRecord:
    voice = load_catalog().resolve(language, "female")
    return SpeechRecord(
        id=uid(n), tenant_id=tenant, product_id="wasifyai-tts", user_id=user, thread_id=None,
        run_id=None, text=text or f"Speech number {n}", language=language, gender="female",
        voice=voice.id, characters=15, seconds=2.5, audio_key=f"{uid(n)}/speech.mp3",
        created_at=T0 + timedelta(minutes=n),
    )  # fmt: skip


@pytest.fixture
def client():
    store = InMemorySpeechStore()
    store.speeches = [
        speech(1), speech(2, language="hi", text="नमस्ते दुनिया"), speech(3), speech(4),
        speech(5, user="someone-else"), speech(6, tenant="other-tenant"),
    ]  # fmt: skip
    app = FastAPI()
    app.state.storage = ScopedStorage(memory_storage())

    class Index:
        removed: list = []

        async def remove(self, tenant_id, product_id, item_id):
            self.removed.append((tenant_id, product_id, item_id))

    app.state.creation_index = Index()
    app.include_router(build_routes(RouteDeps(app.state, identity), store), prefix=BASE)
    c = TestClient(app)
    c.index = app.state.creation_index  # type: ignore[attr-defined]
    return c


def put(client, user: str, rel: str, data: bytes):
    import asyncio

    async def go():
        token = set_context(RunContext("t1", "wasifyai-tts", user))
        try:
            await client.app.state.storage.put(rel, data, "audio/mpeg")
        finally:
            reset_context(token)

    asyncio.run(go())


def test_the_form_gets_the_catalog_with_gaps_as_empty_lists(client):
    body = client.get(f"{BASE}/voices").json()
    ids = [x["id"] for x in body["languages"]]
    assert ids == ["en-US", "en-GB", "es", "fr", "hi", "it", "pt-BR", "bn"]
    french = next(x for x in body["languages"] if x["id"] == "fr")
    assert french["genders"]["male"] == [] and len(french["genders"]["female"]) == 1
    hindi = next(x for x in body["languages"] if x["id"] == "hi")
    assert hindi["name"] == "हिन्दी" and hindi["english"] == "Hindi"


def test_the_list_is_the_callers_own_newest_first_with_a_readable_summary(client):
    body = client.get(f"{BASE}/speeches").json()
    assert [s["id"] for s in body["speeches"]] == [uid(4), uid(3), uid(2), uid(1)]
    assert body["next_before"] is None
    hindi = next(s for s in body["speeches"] if s["id"] == uid(2))
    assert hindi["language_name"] == "हिन्दी" and hindi["gender"] == "female"
    assert hindi["audio_url"].endswith("speech.mp3") and hindi["seconds"] == 2.5
    assert hindi["voice"] == load_catalog().resolve("hi", "female").label


def test_paging_and_the_ids_filter_in_the_order_given(client):
    page = client.get(f"{BASE}/speeches", params={"limit": 2}).json()
    assert [s["id"] for s in page["speeches"]] == [uid(4), uid(3)] and page["next_before"]
    rest = client.get(f"{BASE}/speeches", params={"limit": 2, "before": page["next_before"]}).json()
    assert [s["id"] for s in rest["speeches"]] == [uid(2), uid(1)]
    got = client.get(f"{BASE}/speeches", params={"ids": f"{uid(3)},{uid(1)},{uid(5)}"}).json()
    assert [s["id"] for s in got["speeches"]] == [uid(3), uid(1)]  # someone else's is not there
    assert client.get(f"{BASE}/speeches", params={"ids": "nope"}).status_code == 422


def test_one_result_and_no_existence_leak(client):
    assert client.get(f"{BASE}/speeches/{uid(1)}").json()["text"] == "Speech number 1"
    for n in (5, 6):
        assert client.get(f"{BASE}/speeches/{uid(n)}").status_code == 404
    assert client.get(f"{BASE}/speeches/not-a-uuid").status_code == 404


def test_download_is_an_mp3_attachment_and_other_users_files_are_never_served(client):
    put(client, "u1", f"{uid(1)}/speech.mp3", b"MP3DATA")
    r = client.get(f"{BASE}/speeches/{uid(1)}/download")
    assert (
        r.status_code == 200
        and r.content == b"MP3DATA"
        and r.headers["content-type"] == "audio/mpeg"
    )
    assert r.headers["content-disposition"] == (
        "attachment; filename=\"speech-number-1.mp3\"; filename*=UTF-8''speech-number-1.mp3"
    )
    assert r.headers["cache-control"] == "private, no-store"
    assert client.get(f"{BASE}/speeches/{uid(5)}/download").status_code == 404
    assert client.get(f"{BASE}/speeches/{uid(3)}/download").status_code == 404  # file missing


def test_delete_removes_the_file_the_row_and_the_search_entry(client):
    put(client, "u1", f"{uid(1)}/speech.mp3", b"x")
    assert client.delete(f"{BASE}/speeches/{uid(1)}").status_code == 204
    assert client.get(f"{BASE}/speeches/{uid(1)}").status_code == 404
    assert client.index.removed == [("t1", "wasifyai-tts", uid(1))]
    assert client.delete(f"{BASE}/speeches/{uid(5)}").status_code == 404
    assert len(client.index.removed) == 1  # a refused delete removes nothing from search


def test_file_names_are_safe_in_any_language():
    assert file_name("Hello there, world!", "mp3") == "hello-there-world.mp3"
    assert file_name("../../etc/passwd", "mp3") == "etc-passwd.mp3"
    assert file_name("नमस्ते दुनिया", "mp3") == "नमस्ते-दुनिया.mp3"
    assert file_name("", "mp3") == "speech.mp3" and file_name("!!!", "mp3") == "speech.mp3"
    header = content_disposition("নমস্কার", "mp3")
    assert (
        header.startswith('attachment; filename="speech.mp3"')
        and "filename*=UTF-8''%E0%A6" in header
    )
