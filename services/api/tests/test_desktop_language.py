"""The chat model of the desktop app (stage D, D2): choosing it, the provider the graphs use, the
slot it shares with the image model, and the routes the window uses."""

import json
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from wasifyai_api import desktop_llm
from wasifyai_api.desktop_discovery import Found
from wasifyai_api.desktop_fit import GB, Machine
from wasifyai_api.desktop_language import (
    LanguageService,
    LocalTextProvider,
    Selection,
    language_machine,
)
from wasifyai_api.identity import get_identity
from wasifyai_api.llama_server import LlamaServer
from wasifyai_api.safeguards import InMemorySettingsStore
from wasifyai_platform_sdk import (
    Identity,
    InMemoryUsageRecorder,
    RunContext,
    RunError,
    SlotManager,
    reset_context,
    set_context,
)
from wasifyai_platform_sdk.config import CapabilityBinding

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the fake server is a script")

# llama-server enough for the chat API: /health, and /v1/chat/completions as a stream or whole
FAKE = r"""#!/usr/bin/env python3
import http.server, json, sys, time
args = sys.argv[1:]
port = int(args[args.index("--port") + 1])
model = args[args.index("-m") + 1].rsplit("/", 1)[-1]
time.sleep(0.2)
class H(http.server.BaseHTTPRequestHandler):
    def _json(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
    def do_GET(self):
        self._json(200, {"status": "ok"})
    def do_POST(self):
        n = int(self.headers.get("content-length", "0"))
        req = json.loads(self.rfile.read(n) or b"{}")
        said = f"[{model}] " + req["messages"][-1]["content"]
        if req.get("stream"):
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.end_headers()
            for word in said.split(" "):
                chunk = {"id": "c", "object": "chat.completion.chunk", "created": 0, "model": "m",
                         "choices": [{"index": 0, "delta": {"content": word + " "}}]}
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
            usage = {"id": "c", "object": "chat.completion.chunk", "created": 0, "model": "m",
                     "choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 5,
                                              "total_tokens": 12}}
            self.wfile.write(("data: " + json.dumps(usage) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            self._json(200, {"id": "c", "object": "chat.completion", "created": 0, "model": "m",
                             "choices": [{"index": 0, "finish_reason": "stop",
                                          "message": {"role": "assistant", "content": said}}],
                             "usage": {"prompt_tokens": 7, "completion_tokens": 5,
                                       "total_tokens": 12}})
    def log_message(self, *a): pass
http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()
"""


def install(data: Path) -> None:
    root = data / "engine" / "llamacpp"
    (root / "b1").mkdir(parents=True)
    server = root / "b1" / "llama-server"
    server.write_text(FAKE)
    server.chmod(server.stat().st_mode | stat.S_IXUSR)
    (root / "state.json").write_text(
        json.dumps({"version": "b1", "backend": "cpu", "server": "b1/llama-server"})
    )


def gguf(tmp_path: Path, name: str = "m.gguf") -> Path:
    p = tmp_path / name
    p.write_bytes(b"GGUF" + b"\0" * 4096)
    return p


@pytest.fixture
def ctx():
    token = set_context(RunContext("t1", "wasifyai-image", "u1", run_id="r1", thread_id="th"))
    yield
    reset_context(token)


async def make(
    tmp_path: Path, slot: SlotManager | None = None
) -> tuple[LanguageService, LlamaServer]:
    install(tmp_path)
    llama = LlamaServer(tmp_path, startup_timeout_s=20)
    svc = LanguageService(InMemorySettingsStore(), llama)
    svc.slot = slot
    return svc, llama


# ---- the machine the engine sees --------------------------------------------------------------


async def test_a_file_without_a_chat_template_comes_with_a_note(tmp_path):
    svc, llama = await make(tmp_path)
    try:
        await svc.select_file(gguf(tmp_path), "Demo", 4096)  # a 4 KB stand-in: not a real GGUF
        assert svc.selected is not None and svc.selected.note == ""  # unreadable: no claim made
        real = tmp_path / "t.gguf"
        # a valid header with no template key: one string key, general.architecture
        key, val = b"general.architecture", b"llama"
        head = b"GGUF" + (3).to_bytes(4, "little") + (0).to_bytes(8, "little")
        head += (1).to_bytes(8, "little")
        head += len(key).to_bytes(8, "little") + key + (8).to_bytes(4, "little")
        head += len(val).to_bytes(8, "little") + val
        real.write_bytes(head)
        await svc.select_file(real, "Plain", 4096)
        assert svc.selected is not None and "no chat template" in svc.selected.note
    finally:
        await llama.close()


def test_a_processor_build_ignores_the_graphics_card():
    card = Machine("cuda", 64 * GB, 50 * GB, gpu_total_bytes=24 * GB, gpu_free_bytes=20 * GB)
    seen = language_machine(card, "cpu")
    assert seen.device == "cpu" and seen.gpu_total_bytes is None
    assert language_machine(card, None).device == "cuda"  # not installed: as the computer is
    mac = Machine("unified", 64 * GB, 30 * GB)
    assert language_machine(mac, "metal").device == "unified"


# ---- choosing ---------------------------------------------------------------------------------


async def test_the_choice_is_kept_across_a_restart_and_a_bad_one_is_ignored(tmp_path):
    svc, llama = await make(tmp_path)
    try:
        await svc.select_file(gguf(tmp_path), "Demo", 4096)
        again = LanguageService(svc._store, llama)
        await again.load()
        assert again.selected == Selection("file", "Demo", 4096, path=str(gguf(tmp_path)))
        await svc.select_server("ollama", "http://127.0.0.1:11434", "llama3.2:3b", 777)
        assert svc.selected is not None and svc.selected.context == 8192  # an unknown context
        await svc._store.put("desktop.language", {"junk": 1}, "x")
        broken = LanguageService(svc._store, llama)
        await broken.load()
        assert broken.selected is None
        await svc.clear()
        assert svc.selected is None
    finally:
        await llama.close()


# ---- answering --------------------------------------------------------------------------------


async def test_nothing_chosen_is_said_in_plain_words(tmp_path, ctx):
    svc, llama = await make(tmp_path)
    provider = LocalTextProvider(svc, InMemoryUsageRecorder())
    with pytest.raises(RunError) as e:
        async for _ in provider.stream(
            "text.enhance", CapabilityBinding(provider="litellm", model="prompt-enhancer"), "s", "p"
        ):
            pass
    assert e.value.code == "no_language_model" and "Models" in e.value.message
    await llama.close()


async def test_the_provider_streams_from_the_chosen_file_and_records_tokens(tmp_path, ctx):
    svc, llama = await make(tmp_path)
    usage = InMemoryUsageRecorder()
    provider = LocalTextProvider(svc, usage)
    try:
        await svc.select_file(gguf(tmp_path), "Demo", 4096)
        text = "".join(
            [d async for d in provider.stream(
                "text.enhance", CapabilityBinding(provider="litellm", model="prompt-enhancer"),
                "You improve prompts.", "a red fox",
            )]
        )  # fmt: skip
        assert text.strip() == "[m.gguf] a red fox"
        kinds = {e.kind: e.quantity for e in usage.events}
        assert kinds["llm.input_tokens"] == 7 and kinds["llm.output_tokens"] == 5
        assert llama.running  # it stays loaded until the slot unloads it
    finally:
        await llama.close()


async def test_a_picture_in_the_prompt_is_refused_for_a_text_model(tmp_path, ctx):
    from wasifyai_platform_sdk import Image

    svc, llama = await make(tmp_path)
    await svc.select_file(gguf(tmp_path), "Demo", 4096)
    provider = LocalTextProvider(svc, InMemoryUsageRecorder())
    with pytest.raises(RunError) as e:
        async for _ in provider.stream(
            "text.describe_image",
            CapabilityBinding(provider="litellm", model="prompt-enhancer"),
            "s",
            ["what is this", Image.from_bytes(b"\x89PNG" + b"0" * 10, "image/png")],
        ):
            pass
    assert e.value.code == "language_no_pictures"
    await llama.close()


async def test_a_running_tools_model_is_used_where_it_is_without_the_slot(tmp_path, ctx):
    """Ollama or LM Studio: the app talks to them, never starts or holds anything for them."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert json.loads(request.content)["model"] == "llama3.2:3b"
        return httpx.Response(200, json={
            "id": "c", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "hi from ollama"}}],
        })  # fmt: skip

    svc, llama = await make(tmp_path)
    await svc.select_server("ollama", "http://127.0.0.1:11434", "llama3.2:3b", 8192)
    holds: list[str] = []

    class Slot:
        def hold(self, owner):
            holds.append(owner)
            raise AssertionError("an external server must not take the slot")

    svc.slot = Slot()
    async with svc.session() as route:
        assert (route.base_url, route.model, route.external) == (
            "http://127.0.0.1:11434/v1", "llama3.2:3b", True,
        )  # fmt: skip
    assert holds == [] and not llama.running
    await llama.close()
    _ = handler  # (the routing is what is asserted; the call itself is OpenAI's client)


# ---- one big model at a time ------------------------------------------------------------------


async def test_chat_and_image_take_turns_in_the_slot(tmp_path, ctx):
    unloaded: list[str] = []
    llama_holder: dict[str, LlamaServer] = {}

    async def unload_image() -> None:
        unloaded.append("image")

    async def unload_chat() -> None:
        unloaded.append("chat")
        await llama_holder["l"].stop()

    slot = SlotManager({"image": unload_image, "chat": unload_chat}, idle_unload_s=None)
    svc, llama = await make(tmp_path, slot)
    llama_holder["l"] = llama
    await svc.select_file(gguf(tmp_path), "Demo", 4096)
    try:
        async with slot.hold("image"):  # an image was made: its model is resident
            pass
        assert slot.resident_owner == "image"

        async with svc.session() as route:  # chatting unloads the image model first
            assert route.base_url.startswith("http://127.0.0.1:")
            assert unloaded == ["image"] and llama.running
        assert slot.resident_owner == "chat"

        async with slot.hold("image"):  # making an image unloads the chat model: its memory is back
            assert unloaded == ["image", "chat"]
            assert not llama.running
    finally:
        await llama.close()


# ---- the routes -------------------------------------------------------------------------------


def found(path: Path, **kw: Any) -> Found:
    base: dict[str, Any] = {
        "id": "f1", "name": "Demo 3B", "kind": "language", "family": "llama", "format": "gguf",
        "quant": "Q4_K_M", "size": path.stat().st_size, "path": str(path), "tool": "ollama",
        "tool_title": "Ollama", "licence": "", "state": "can_use", "use": "chat", "layers": 0,
        "kv_heads": 0, "head_dim": 0, "context": 0,
    }  # fmt: skip
    base.update(kw)
    return Found(**base)


class FakeModels:
    def __init__(self, machine: Machine):
        self._machine = machine

    async def machine(self) -> Machine:
        return self._machine


def app_for(svc: LanguageService, servers: list[dict], items: list[Found]) -> TestClient:
    discovery = SimpleNamespace(
        items=items, servers=servers, running=True,
        state=lambda: {"items": [i.public() for i in items], "servers": servers},
    )  # fmt: skip
    svc.discovery = discovery
    svc.models = FakeModels(Machine("cpu", 16 * GB, 12 * GB))
    app = FastAPI()
    app.include_router(desktop_llm.router)
    app.state.desktop_language = svc
    app.state.llama_server = svc.llama
    app.dependency_overrides[get_identity] = lambda: Identity("local", "u1", "user")
    return TestClient(app)


def test_the_list_offers_found_files_and_running_tools_and_the_choice_sticks(tmp_path):
    install(tmp_path)
    llama = LlamaServer(tmp_path, startup_timeout_s=20)
    svc = LanguageService(InMemorySettingsStore(), llama)
    item = found(gguf(tmp_path))
    servers = [{"tool": "ollama", "title": "Ollama", "url": "http://127.0.0.1:11434",
                "kind": "ollama", "models": ["qwen3:4b"]}]  # fmt: skip
    with app_for(svc, servers, [item]) as c:
        body = c.get("/desktop/language").json()
        assert body["selected"] is None and body["engine"]["installed"] is True
        assert [f["id"] for f in body["files"]] == ["f1"] and body["files"][0]["fit"]["verdict"]
        assert [(s["model"], s["chosen"]) for s in body["servers"]] == [("qwen3:4b", False)]

        ok = c.put("/desktop/language", json={"item_id": "f1", "context": 4096})
        assert ok.status_code == 200 and ok.json()["selected"]["context"] == 4096
        assert c.get("/desktop/language").json()["files"][0]["chosen"] is True

        tool = {"tool": "ollama", "url": "http://127.0.0.1:11434", "model": "qwen3:4b"}
        assert c.put("/desktop/language", json={"server": tool}).status_code == 200
        assert c.get("/desktop/language").json()["servers"][0]["chosen"] is True
        assert c.put("/desktop/language", json={"clear": True}).json() == {"selected": None}


def test_a_choice_that_is_not_allowed_is_refused_with_the_reason(tmp_path):
    install(tmp_path)
    llama = LlamaServer(tmp_path, startup_timeout_s=20)
    svc = LanguageService(InMemorySettingsStore(), llama)
    bad = found(gguf(tmp_path, "bad.gguf"), id="f2", state="unsupported",
                reason="Ollama keeps this model in its own format.")  # fmt: skip
    huge = found(gguf(tmp_path, "huge.gguf"), id="f3", size=500 * GB)
    with app_for(svc, [], [found(gguf(tmp_path)), bad, huge]) as c:
        r = c.put("/desktop/language", json={"item_id": "f2"})
        assert r.status_code == 409 and "own format" in r.json()["detail"]
        r = c.put("/desktop/language", json={"item_id": "f3"})
        assert r.status_code == 409 and "will not run here" in r.json()["detail"]
        assert c.put("/desktop/language", json={"item_id": "nope"}).status_code == 404
        # a tool the engine did not find, at an address it did not probe (never an arbitrary URL)
        evil = {"tool": "ollama", "url": "http://169.254.169.254", "model": "x"}
        assert c.put("/desktop/language", json={"server": evil}).status_code == 404
        assert c.put("/desktop/language", json={}).status_code == 422
        assert svc.selected is None


def test_try_it_asks_the_chosen_model_and_says_what_is_missing(tmp_path):
    install(tmp_path)
    llama = LlamaServer(tmp_path, startup_timeout_s=20)
    svc = LanguageService(InMemorySettingsStore(), llama)
    with app_for(svc, [], [found(gguf(tmp_path))]) as c:
        none = c.post("/desktop/language/try", json={"prompt": "hello"})
        assert none.status_code == 409 and "Choose one" in none.json()["detail"]
        c.put("/desktop/language", json={"item_id": "f1"})
        r = c.post("/desktop/language/try", json={"prompt": "hello there"})
        assert r.status_code == 200, r.text
        assert r.json()["text"] == "[m.gguf] hello there" and r.json()["seconds"] >= 0
        # stop it on the loop that started it, and say it is stopped
        assert c.post("/desktop/language-engine/stop").json() == {"stopped": True}
