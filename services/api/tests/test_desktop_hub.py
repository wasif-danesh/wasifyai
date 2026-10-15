"""The model hub (ADR-0064): consent, search, one repository's variants and fit, and the confirmed
download, against a fake Hugging Face."""

import asyncio
import hashlib
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from wasifyai_api import desktop_hub
from wasifyai_api.desktop_fit import GB, Machine
from wasifyai_api.desktop_hub import (
    HubClient,
    HubError,
    HubService,
    capability_of,
    clean_readme,
    load_shelf,
    quant_of,
    variants_of,
)
from wasifyai_api.desktop_models import DownloadManager, ModelsService
from wasifyai_api.identity import get_identity
from wasifyai_api.safeguards import InMemorySettingsStore
from wasifyai_platform_sdk import Identity

COMMIT = "a" * 40
SMALL = b"small gguf bytes " * 100
BIG = b"big gguf bytes " * 200


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


SIBLINGS = [
    {"rfilename": ".gitattributes", "size": 10},
    {
        "rfilename": "Demo-Q4_K_M.gguf",
        "size": len(SMALL),
        "lfs": {"sha256": sha(SMALL), "size": len(SMALL)},
    },
    {
        "rfilename": "Demo-Q8_0.gguf",
        "size": len(BIG),
        "lfs": {"sha256": sha(BIG), "size": len(BIG)},
    },
    {"rfilename": "mmproj-Demo-F16.gguf", "size": 5, "lfs": {"sha256": "f" * 64, "size": 5}},
    {
        "rfilename": "Demo-split-00001-of-00002.gguf",
        "size": 4,
        "lfs": {"sha256": "1" * 64, "size": 4},
    },
    {
        "rfilename": "Demo-split-00002-of-00002.gguf",
        "size": 6,
        "lfs": {"sha256": "2" * 64, "size": 6},
    },
    {"rfilename": "no-checksum.gguf", "size": 3},
]


def hub_handler(calls: list[str], *, gated: bool = False, down: bool = False):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if down:
            raise httpx.ConnectError("offline")
        path = request.url.path
        if path == "/api/models":
            return httpx.Response(200, json=[
                {"id": "acme/Demo-GGUF", "downloads": 1000, "likes": 5,
                 "pipeline_tag": "text-generation",
                 "gated": False, "lastModified": "2026-10-01T00:00:00.000Z",
                 "tags": ["gguf", "license:apache-2.0", "text-generation"]},
                {"id": "acme/Embed-GGUF", "downloads": 10, "pipeline_tag": "feature-extraction",
                 "tags": ["gguf"]},
                {"id": "acme/not-a-gguf", "downloads": 3, "pipeline_tag": "text-generation",
                 "tags": []},
            ])  # fmt: skip
        if path == "/api/models/acme/Demo-GGUF":
            return httpx.Response(200, json={
                "id": "acme/Demo-GGUF", "sha": COMMIT, "gated": gated, "downloads": 1000,
                "likes": 5, "pipeline_tag": "text-generation",
                "tags": ["gguf", "license:apache-2.0"],
                "cardData": {"license": "apache-2.0"},
                "gguf": {"architecture": "llama", "context_length": 8192, "total": 3_000_000_000,
                         "chat_template": "{{ x }}"},
                "siblings": SIBLINGS,
            })  # fmt: skip
        if path == "/acme/Demo-GGUF/raw/main/README.md":
            return httpx.Response(
                200,
                text="---\nlicense: mit\n---\n# Demo\n![logo](http://x/y.png)\nHello <b>there</b>",
            )
        if path.startswith("/acme/Demo-GGUF/resolve/"):
            body = BIG if "Q8_0" in path else SMALL
            return httpx.Response(200, content=body)
        return httpx.Response(404, json={"error": "not found"})

    return handler


def make(tmp_path: Path, calls: list[str], **kw: Any) -> tuple[HubService, ModelsService]:
    client = HubClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(hub_handler(calls, **kw)))
    )
    store = InMemorySettingsStore()
    hub = HubService(store, client)
    dl_client = httpx.AsyncClient(
        transport=httpx.MockTransport(hub_handler(calls, **kw)), follow_redirects=True
    )
    models = ModelsService([], tmp_path / "models", (), store, DownloadManager(lambda: dl_client))
    hub.models = models

    async def machine() -> Machine:
        return Machine("cpu", 16 * GB, 12 * GB)

    hub.language = SimpleNamespace(machine=machine, selected=None, clear=lambda: None)
    return hub, models


# ---- pure helpers -----------------------------------------------------------------------------


def test_what_a_repository_is_for():
    assert capability_of("text-generation", []) == "language"
    assert capability_of("image-text-to-text", []) == "language"
    assert capability_of("feature-extraction", []) == "embedding"
    assert capability_of(None, [], "BAAI/bge-m3-embedding") == "embedding"
    assert capability_of("text-to-image", []) == "image"
    assert capability_of("text-to-video", []) == "video"
    assert capability_of("audio-classification", []) == "other"


def test_a_quantisation_is_read_from_the_file_name():
    assert quant_of("Qwen3-4B-Q4_K_M.gguf") == "Q4_K_M"
    assert quant_of("model.IQ4_XS.gguf") == "IQ4_XS"
    assert quant_of("Llama-3.2-3B-Instruct-BF16.gguf") == "BF16"
    assert quant_of("mystery.gguf") == ""


def test_variants_group_shards_skip_projectors_and_unchecked_files():
    got = variants_of(SIBLINGS)
    assert [v["name"] for v in got] == ["Demo-split", "Demo-Q4_K_M", "Demo-Q8_0"]
    split = got[0]
    assert split["files"] == ["Demo-split-00001-of-00002.gguf", "Demo-split-00002-of-00002.gguf"]
    assert split["size"] == 10 and split["sizes"] == [4, 6] and split["quant"] == ""
    q4 = got[1]
    assert q4["quant"] == "Q4_K_M" and q4["sha256"] == [sha(SMALL)] and q4["size"] == len(SMALL)


def test_a_model_card_becomes_plain_text_without_pictures():
    text = clean_readme(
        "---\nlicense: mit\n---\n# Demo\n![logo](http://x/y.png)\n"
        "<img src='a'>Hi <b>there</b>\n\n\n\nEnd"
    )
    assert text == "# Demo\n\nHi there\n\nEnd"


def test_the_shelf_names_real_looking_repositories():
    shelf = load_shelf()
    assert len(shelf) >= 5
    assert all("/" in m["repo"] and m["title"] and m["note"] for m in shelf)
    assert {m["capability"] for m in shelf} <= {"language", "embedding"}


# ---- consent ----------------------------------------------------------------------------------


async def test_nothing_is_requested_before_the_person_agrees(tmp_path):
    calls: list[str] = []
    hub, _ = make(tmp_path, calls)
    with pytest.raises(HubError) as e:
        await hub.search("demo")
    assert e.value.code == "consent_needed" and calls == []
    await hub.set_enabled(True)
    again = HubService(hub._store, hub.client)
    await again.load()
    assert again.enabled is True


# ---- search and one repository ----------------------------------------------------------------


async def test_search_keeps_what_the_app_can_run_and_names_the_rest(tmp_path):
    calls: list[str] = []
    hub, _ = make(tmp_path, calls)
    await hub.set_enabled(True)
    out = await hub.search("demo", capability="language")
    assert [i["id"] for i in out["items"]] == [
        "acme/Demo-GGUF"
    ]  # the embedding model and the non-GGUF go
    item = out["items"][0]
    assert (
        item["runnable"] is True and item["license"] == "apache-2.0" and item["downloads"] == 1000
    )
    emb = await hub.search("embed", capability="embedding")
    assert [i["id"] for i in emb["items"]] == ["acme/Embed-GGUF"]


async def test_an_answer_is_cached_and_an_offline_hub_still_answers(tmp_path):
    calls: list[str] = []
    hub, _ = make(tmp_path, calls)
    await hub.set_enabled(True)
    await hub.search("demo")
    await hub.search("demo")
    assert calls.count("GET /api/models") == 1  # the second came from the cache

    offline: list[str] = []
    cold, _ = make(tmp_path, offline, down=True)
    await cold.set_enabled(True)
    with pytest.raises(HubError) as e:
        await cold.search("demo")
    assert e.value.code == "offline" and "connection" in e.value.message
    # a stale answer beats an error
    cold.client._ttl = 0
    cold.client._cache = hub.client._cache
    out = await cold.search("demo")
    assert out["stale"] is True and out["items"]


async def test_a_repository_comes_with_its_variants_licence_and_template(tmp_path):
    hub, _ = make(tmp_path, [])
    await hub.set_enabled(True)
    d = await hub.detail("acme/Demo-GGUF")
    assert d["commit"] == COMMIT and d["license"] == "apache-2.0" and d["runnable"] is True
    assert (d["architecture"], d["context_length"], d["has_chat_template"]) == ("llama", 8192, True)
    assert [v["quant"] for v in d["variants"]] == ["", "Q4_K_M", "Q8_0"]
    with pytest.raises(HubError) as e:
        await hub.detail("not a repo")
    assert e.value.code == "bad_repo"
    with pytest.raises(HubError) as nf:
        await hub.detail("acme/missing")
    assert nf.value.code == "not_found"


# ---- getting a model --------------------------------------------------------------------------


async def test_the_confirmed_files_are_fetched_checked_and_placed_in_the_app_folder(tmp_path):
    calls: list[str] = []
    hub, models = make(tmp_path, calls)
    await hub.set_enabled(True)
    entry = await hub.build_download("acme/Demo-GGUF", ["Demo-Q4_K_M.gguf"], len(SMALL))
    assert entry.id == "hub:acme/Demo-GGUF" and entry.licence == "apache-2.0"
    (f,) = entry.files
    assert f.url == f"https://huggingface.co/acme/Demo-GGUF/resolve/{COMMIT}/Demo-Q4_K_M.gguf"
    assert f.folder == "language/acme--Demo-GGUF" and f.sha256 == sha(SMALL)

    d = models.downloads.start(entry, list(entry.files), models.models_dir)
    async with asyncio.timeout(10):
        while d.status == "running":  # noqa: ASYNC110
            await asyncio.sleep(0.02)
    assert d.status == "done"
    placed = models.models_dir / "language" / "acme--Demo-GGUF" / "Demo-Q4_K_M.gguf"
    assert placed.read_bytes() == SMALL


async def test_a_list_that_does_not_match_the_repository_is_refused(tmp_path):
    hub, _ = make(tmp_path, [])
    await hub.set_enabled(True)
    with pytest.raises(HubError) as wrong_size:
        await hub.build_download("acme/Demo-GGUF", ["Demo-Q4_K_M.gguf"], 1)
    assert wrong_size.value.code == "changed"
    with pytest.raises(HubError) as unknown:
        await hub.build_download("acme/Demo-GGUF", ["../../etc/passwd"], 1)
    assert unknown.value.code == "changed"
    with pytest.raises(HubError) as unchecked:  # a file with no published checksum is not offered
        await hub.build_download("acme/Demo-GGUF", ["no-checksum.gguf"], 3)
    assert unchecked.value.code == "changed"


async def test_a_gated_model_is_not_fetched_without_a_token(tmp_path):
    hub, _ = make(tmp_path, [], gated=True)
    await hub.set_enabled(True)
    with pytest.raises(HubError) as e:
        await hub.build_download("acme/Demo-GGUF", ["Demo-Q4_K_M.gguf"], len(SMALL))
    assert e.value.code == "needs_token" and e.value.status == 403


# ---- the routes -------------------------------------------------------------------------------


def app_for(hub: HubService, models: ModelsService) -> TestClient:
    app = FastAPI()
    app.include_router(desktop_hub.router)
    app.state.desktop_hub = hub
    app.state.desktop_discovery = SimpleNamespace(items=[], running=True)
    app.dependency_overrides[get_identity] = lambda: Identity("local", "u1", "user")
    return TestClient(app)


def test_the_routes_ask_for_consent_then_search_show_and_download(tmp_path):
    calls: list[str] = []
    hub, models = make(tmp_path, calls)
    with app_for(hub, models) as c:
        state = c.get("/desktop/hub/state").json()
        assert state["enabled"] is False and state["shelf"] and state["has_token"] is False
        refused = c.get("/desktop/hub/search", params={"q": "demo"})
        assert refused.status_code == 403 and "huggingface.co" in refused.json()["detail"]
        assert calls == []

        assert c.put("/desktop/hub/consent", json={"enabled": True}).json() == {"enabled": True}
        found = c.get("/desktop/hub/search", params={"q": "demo", "capability": "language"}).json()
        assert found["items"][0]["id"] == "acme/Demo-GGUF"

        d = c.get("/desktop/hub/models/acme/Demo-GGUF").json()
        q4 = next(v for v in d["variants"] if v["quant"] == "Q4_K_M")
        assert q4["fit"]["verdict"] == "fits"
        card = c.get("/desktop/hub/models/acme/Demo-GGUF/readme").json()["text"]
        assert "logo" not in card and "Hello there" in card

        body = {"repo": "acme/Demo-GGUF", "files": ["Demo-Q4_K_M.gguf"], "bytes": len(SMALL)}
        started = c.post("/desktop/hub/download", json=body)
        assert started.status_code == 200 and started.json()["entry_id"] == "hub:acme/Demo-GGUF"
        wrong = c.post("/desktop/hub/download", json={**body, "bytes": 5})
        assert wrong.status_code in (409,)

        bad = c.get("/desktop/hub/models/acme/missing")
        assert bad.status_code == 404
        for _ in range(100):
            last = models.downloads.latest()
            if last is not None and last.status != "running":
                break
            time.sleep(0.05)
    placed = models.models_dir / "language" / "acme--Demo-GGUF" / "Demo-Q4_K_M.gguf"
    assert placed.is_file()


async def test_only_files_this_app_downloaded_can_be_removed(tmp_path):
    hub, models = make(tmp_path, [])
    mine = models.models_dir / "language" / "acme--Demo-GGUF" / "m.gguf"
    mine.parent.mkdir(parents=True)
    mine.write_bytes(b"x")
    other = tmp_path / "elsewhere.gguf"
    other.write_bytes(b"y")
    assert await desktop_hub.remove_downloaded(models, mine) is True
    assert not mine.exists() and not mine.parent.exists()  # the empty folder goes too
    assert await desktop_hub.remove_downloaded(models, other) is False and other.exists()
    assert (
        await desktop_hub.remove_downloaded(models, models.models_dir / ".." / "elsewhere.gguf")
        is False
    )
