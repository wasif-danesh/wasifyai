"""llama-server as the engine's child (stage D, D1): finding the install, starting, stopping."""

import json
import os
import stat
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from wasifyai_api import desktop_llm
from wasifyai_api.identity import get_identity
from wasifyai_api.llama_server import LlamaError, LlamaServer, find_install
from wasifyai_platform_sdk import Identity

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the fake server is a shell script")

# A server that answers /health after a moment, as a model that has to load does
FAKE = """#!/usr/bin/env python3
import http.server, json, sys, time
args = sys.argv[1:]
port = int(args[args.index("--port") + 1])
time.sleep(0.3)
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"status": "ok", "args": args}).encode()
        self.send_response(200)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a): pass
http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()
"""


def install(data: Path, body: str = FAKE, version: str = "b1") -> Path:
    root = data / "engine" / "llamacpp"
    (root / version).mkdir(parents=True)
    server = root / version / "llama-server"
    server.write_text(body)
    server.chmod(server.stat().st_mode | stat.S_IXUSR)
    (root / "state.json").write_text(json.dumps({
        "schema": 1, "version": version, "asset_sha256": "0" * 64, "backend": "cpu",
        "server": f"{version}/llama-server",
    }))  # fmt: skip
    return server


def model(tmp_path: Path) -> Path:
    p = tmp_path / "m.gguf"
    p.write_bytes(b"GGUF")
    return p


def test_the_install_is_found_from_the_state_file(tmp_path):
    assert find_install(tmp_path) is None
    server = install(tmp_path)
    found = find_install(tmp_path)
    assert found is not None
    assert (found.version, found.backend) == ("b1", "cpu")
    assert found.server == server.resolve()


def test_a_state_file_that_points_outside_or_is_damaged_is_not_an_install(tmp_path):
    root = tmp_path / "engine" / "llamacpp"
    root.mkdir(parents=True)
    outside = tmp_path / "evil"
    outside.write_text("#!/bin/sh\n")
    (root / "state.json").write_text(json.dumps(
        {"version": "b1", "backend": "cpu", "server": "../../evil"}
    ))  # fmt: skip
    assert find_install(tmp_path) is None
    (root / "state.json").write_text("not json")
    assert find_install(tmp_path) is None


async def test_it_starts_for_a_model_answers_and_stops(tmp_path):
    install(tmp_path)
    s = LlamaServer(tmp_path, startup_timeout_s=20)
    try:
        assert s.state()["installed"] is True and s.running is False
        url = await s.ensure_running(model(tmp_path), context=4096)
        assert url.startswith("http://127.0.0.1:") and s.running and s.pid
        async with httpx.AsyncClient() as http:
            seen = (await http.get(f"{url}/health")).json()["args"]
        assert "-m" in seen and str(model(tmp_path)) in seen
        assert seen[seen.index("-c") + 1] == "4096"
        assert "--jinja" in seen and "--embedding" not in seen
        # a bounded prompt cache: the default (8 GiB) grew a 4B model to 10 GB on a long chat
        assert seen[seen.index("--cache-ram") + 1] == "512"
        assert seen[seen.index("--host") + 1] == "127.0.0.1"  # loopback only

        # the same request keeps the same server; another context restarts it
        pid = s.pid
        assert await s.ensure_running(model(tmp_path), context=4096) == url and s.pid == pid
        await s.ensure_running(model(tmp_path), context=2048)
        assert s.pid != pid and s.running

        assert await s.stop() is True and not s.running and s.model is None
        assert await s.stop() is False
    finally:
        await s.close()


async def test_an_embedding_model_starts_in_embedding_mode(tmp_path):
    install(tmp_path)
    s = LlamaServer(tmp_path, startup_timeout_s=20)
    try:
        url = await s.ensure_running(model(tmp_path), embedding=True)
        async with httpx.AsyncClient() as http:
            seen = (await http.get(f"{url}/health")).json()["args"]
        assert "--embedding" in seen
    finally:
        await s.close()


async def test_not_installed_and_missing_model_are_said_in_plain_words(tmp_path):
    s = LlamaServer(tmp_path)
    with pytest.raises(LlamaError) as e:
        await s.ensure_running(model(tmp_path))
    assert e.value.code == "not_installed" and "Settings" in e.value.message
    install(tmp_path)
    with pytest.raises(LlamaError) as e2:
        await s.ensure_running(tmp_path / "gone.gguf")
    assert e2.value.code == "model_missing"
    await s.close()


async def test_a_server_that_dies_at_start_is_reported_and_leaves_nothing_running(tmp_path):
    install(tmp_path, "#!/bin/sh\necho 'bad model' >&2\nexit 2\n")
    s = LlamaServer(tmp_path, startup_timeout_s=10)
    with pytest.raises(LlamaError) as e:
        await s.ensure_running(model(tmp_path))
    assert e.value.code == "start_failed" and "smaller model" in e.value.message
    assert not s.running
    assert "bad model" in (tmp_path / "logs" / "llama-server.log").read_text()
    await s.close()


async def test_an_architecture_the_engine_does_not_know_is_named(tmp_path):
    # what the real server printed for Ollama's own gpt-oss file
    install(
        tmp_path,
        '#!/bin/sh\necho "llama_model_load: error loading model: unknown model architecture: '
        "'gptoss'\" >&2\nexit 1\n",
    )
    s = LlamaServer(tmp_path, startup_timeout_s=10)
    with pytest.raises(LlamaError) as e:
        await s.ensure_running(model(tmp_path))
    assert e.value.code == "unsupported_architecture" and "'gptoss'" in e.value.message
    await s.close()


async def test_running_out_of_memory_is_named_and_only_this_runs_log_is_read(tmp_path):
    install(tmp_path, "#!/bin/sh\necho 'ggml_metal: failed to allocate buffer' >&2\nexit 1\n")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "llama-server.log").write_text("unknown model architecture: 'old'\n")  # an earlier run
    s = LlamaServer(tmp_path, startup_timeout_s=10)
    with pytest.raises(LlamaError) as e:
        await s.ensure_running(model(tmp_path))
    assert e.value.code == "out_of_memory" and "smaller model" in e.value.message
    await s.close()


def test_the_routes_report_and_stop(tmp_path):
    install(tmp_path)
    server = LlamaServer(tmp_path)
    app = FastAPI()
    app.include_router(desktop_llm.router)
    app.state.llama_server = server
    app.dependency_overrides[get_identity] = lambda: Identity("local", "u1", "user")
    with TestClient(app) as c:
        body = c.get("/desktop/language-engine").json()
        assert body["installed"] is True and body["running"] is False and body["version"] == "b1"
        assert c.post("/desktop/language-engine/stop").json() == {"stopped": False}
    assert os.path.isdir(tmp_path)
