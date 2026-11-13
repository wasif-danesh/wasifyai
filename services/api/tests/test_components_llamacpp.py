"""The language engine on the one installer (stage F2; it was the shell's llamacpp.rs): four steps,
the state file `llama_server.find_install` has always read, and the same refusals the shell's tests
checked. Downloads are served by a fake transport; the "server" is a small script."""

import asyncio
import hashlib
import io
import json
import tarfile
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from wasifyai_api.components.llamacpp import LlamaCppComponent
from wasifyai_api.components.manifest import Manifest, Pins, load_manifest
from wasifyai_api.components.routes import router
from wasifyai_api.identity import Identity, get_identity
from wasifyai_api.llama_server import find_install
from wasifyai_api.services import ApiServices
from wasifyai_platform_sdk.installer import Archive, InstallError, Registry

URL = "https://example.test/llama-b1-bin-macos-arm64.tar.gz"
SERVER_OK = "#!/bin/sh\necho 'version: 1 (abc123)'\necho 'built with clang'\n"


def archive(server: str | None = SERVER_OK, extra: dict[str, bytes] | None = None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        files = {"build/bin/libggml.dylib": b"lib", **(extra or {})}
        if server is not None:
            files["build/bin/llama-server"] = server.encode()
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o755
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def manifest_for(body: bytes, sha: str | None = None) -> Manifest:
    pin = Archive(URL, len(body), sha or hashlib.sha256(body).hexdigest(), "tar.gz", strip=2)
    pins = Pins("llamacpp", "Language engine (llama.cpp)", "b1", "", 1000, pin,
                {"backend": "metal"})  # fmt: skip
    return Manifest("darwin-arm64", "3.12.15", {"llamacpp": pins})


def component(tmp_path: Path, body: bytes, sha: str | None = None) -> LlamaCppComponent:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == URL
        return httpx.Response(200, content=body)

    client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))  # noqa: E731
    return LlamaCppComponent(tmp_path, manifest_for(body, sha), client=client)


async def test_it_installs_in_four_steps_and_the_engine_finds_it_where_it_always_did(tmp_path):
    body = archive()
    c = component(tmp_path, body)
    heard: list[dict] = []
    c.installer.listeners.append(lambda cid, s: heard.append(s))
    assert c.status() == {"state": "not_installed", "needs_bytes": len(body)}
    c.install(len(body))
    await c.wait()
    assert c.status() == {"state": "installed", "version": "b1", "accelerator": "metal"}
    steps = [s["progress"]["step"] for s in heard if s["state"] == "installing"]
    assert list(dict.fromkeys(steps)) == ["check", "download", "unpack", "verify"]
    assert heard[-1]["state"] == "installed"
    found = find_install(tmp_path)
    assert found is not None and found.version == "b1" and found.backend == "metal"
    assert found.server == tmp_path / "engine" / "llamacpp" / "b1" / "llama-server"
    log = (tmp_path / "logs" / "provision.log").read_text()
    assert "llamacpp: step verify" in log and "version: 1 (abc123)" in log
    assert not (tmp_path / "engine" / "llamacpp" / "downloads").exists()


async def test_a_release_the_shell_set_up_before_is_installed_without_a_download(tmp_path):
    body = archive()
    root = tmp_path / "engine" / "llamacpp"
    (root / "b1").mkdir(parents=True)
    (root / "b1" / "llama-server").write_text(SERVER_OK)
    (root / "state.json").write_text(json.dumps({
        "schema": 1, "version": "b1", "asset_sha256": hashlib.sha256(body).hexdigest(),
        "backend": "metal", "server": "b1/llama-server",
    }))  # fmt: skip
    c = component(tmp_path, body)
    assert c.status()["state"] == "installed"
    with pytest.raises(InstallError, match="already set up"):
        c.install(len(body))


async def test_a_wrong_checksum_stops_at_the_download_and_records_nothing(tmp_path):
    body = archive()
    c = component(tmp_path, body, sha="0" * 64)
    c.install(len(body))
    await c.wait()
    s = c.status()
    assert s["state"] == "failed" and s["step"] == "download" and "checksum" in s["message"]
    assert find_install(tmp_path) is None
    assert not list((tmp_path / "engine" / "llamacpp").rglob("*.part"))


async def test_an_archive_without_the_server_stops_at_unpack(tmp_path):
    body = archive(server=None)
    c = component(tmp_path, body)
    c.install(len(body))
    await c.wait()
    s = c.status()
    assert (s["state"], s["step"]) == ("failed", "unpack") and "llama-server" in s["message"]
    assert not (tmp_path / "engine" / "llamacpp" / "b1").exists()


async def test_a_server_that_does_not_start_stops_at_verify_and_is_not_recorded(tmp_path):
    body = archive(server="#!/bin/sh\nexit 3\n")
    c = component(tmp_path, body)
    c.install(len(body))
    await c.wait()
    assert (c.status()["state"], c.status()["step"]) == ("failed", "verify")
    assert not (tmp_path / "engine" / "llamacpp" / "state.json").exists()


async def test_an_archive_that_reaches_outside_its_folder_is_refused(tmp_path):
    body = archive(extra={"build/bin/../../../../escape": b"x"})
    c = component(tmp_path, body)
    c.install(len(body))
    await c.wait()
    assert c.status()["state"] == "failed" and "unsafe" in c.status()["message"]
    assert not (tmp_path / "escape").exists()


async def test_nothing_is_fetched_unless_the_size_shown_is_confirmed(tmp_path):
    body = archive()
    c = component(tmp_path, body)
    with pytest.raises(InstallError, match="out of date"):
        c.install(len(body) + 1)
    assert not (tmp_path / "engine").exists()


async def test_a_stopped_install_says_so_and_a_new_one_continues(tmp_path):
    body = archive()
    gate = asyncio.Event()

    async def slow(request: httpx.Request) -> httpx.Response:
        await gate.wait()
        return httpx.Response(200, content=body)

    client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(slow))  # noqa: E731
    c = LlamaCppComponent(tmp_path, manifest_for(body), client=client)
    c.install(len(body))
    await asyncio.sleep(0.05)
    assert c.status()["state"] == "installing"
    assert c.cancel()
    await c.wait()
    assert c.status()["state"] == "failed" and "Stopped" in c.status()["message"]
    gate.set()
    c.install(len(body))
    await c.wait()
    assert c.status()["state"] == "installed"


def test_a_platform_without_a_release_is_unsupported(tmp_path):
    c = LlamaCppComponent(tmp_path, Manifest("haiku-x64", "", {}))
    assert c.status()["state"] == "unsupported"


def test_every_platform_manifest_pins_the_language_engine():
    for key in ("darwin-arm64", "darwin-x64", "linux-x64", "linux-arm64", "windows-x64"):
        pins = load_manifest(key).get("llamacpp")
        assert pins is not None and pins.archive is not None, key
        assert pins.archive.url.startswith("https://") and len(pins.archive.sha256) == 64


def test_the_routes_list_and_refuse_an_install_without_the_size(tmp_path):
    body = archive()
    registry = Registry()
    c = component(tmp_path, body)
    registry.add(c, c.installer)
    app = FastAPI()
    app.state.services = ApiServices(components=registry)
    app.include_router(router)
    app.dependency_overrides[get_identity] = lambda: Identity("t1", "u1")
    with TestClient(app) as client:
        listed = client.get("/components").json()["components"]
        missing = {"state": "not_installed", "needs_bytes": len(body)}
        assert listed == [
            {
                "id": "llamacpp",
                "title": "Language engine (llama.cpp)",
                "status": missing,
                "can": {"stop": True, "repair": True, "remove": True},
            }  # fmt: skip
        ]
        assert client.post("/components/llamacpp/install", json={}).status_code == 422
        wrong = client.post("/components/llamacpp/install", json={"confirm_bytes": 1})
        assert wrong.status_code == 409 and "out of date" in wrong.json()["detail"]
        assert client.get("/components/nothing").status_code == 404
