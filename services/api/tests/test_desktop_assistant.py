"""The assistant on the desktop profile, end to end (ADR-0057, stage D3 and D4): a chat model served
by a fake llama-server that asks for a tool, the assistant graph, the image product run as a child,
the saved conversation and its place in search."""

import json
import stat
import struct
import sys
import time
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient
from wasifyai_api.config import get_settings
from wasifyai_api.main import create_app

from tests.test_runs import parse

SECRET = "desktop-launch-secret-0123456789abcdef"
PRODUCTS = Path(__file__).resolve().parents[3] / "products"
BASE = "http://127.0.0.1:48123"

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the fake server is a script")

# llama-server enough for a tool-using chat: the first request that offers tools and has no tool
# result yet answers with a tool call (streamed in pieces, as OpenAI-compatible servers do); the
# request after the tool result answers in words.
FAKE = r"""#!/usr/bin/env python3
import http.server, json, sys, time
args = sys.argv[1:]
port = int(args[args.index("--port") + 1])
time.sleep(0.2)
def chunk(delta, finish=None):
    return {"id": "c", "object": "chat.completion.chunk", "created": 0, "model": "m",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"status":"ok"}'
        self.send_response(200)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_POST(self):
        n = int(self.headers.get("content-length", "0"))
        req = json.loads(self.rfile.read(n) or b"{}")
        msgs = req["messages"]
        has_result = any(m["role"] == "tool" for m in msgs)
        last_user = [m for m in msgs if m["role"] == "user"][-1]["content"]
        events = []
        if req.get("tools") and not has_result and "draw" in last_user.lower():
            def call(name, a):
                fn = {"name": name, "arguments": a}
                return {"tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                                        "function": fn}]}
            events.append(chunk({"content": "Let me draw that. "}))
            events.append(chunk(call("generate_image", "")))
            half = json.dumps({"prompt": "a red teapot on a table", "size": "square"})
            for piece in (half[:12], half[12:]):
                fn = {"arguments": piece}
                events.append(chunk({"tool_calls": [{"index": 0, "function": fn}]}))
            events.append(chunk({}, "tool_calls"))
        else:
            for w in ("Here ", "is ", "your ", "picture."):
                events.append(chunk({"content": w}))
            events.append(chunk({}, "stop"))
        counts = {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13}
        usage = {"id": "c", "object": "chat.completion.chunk", "created": 0, "model": "m",
                 "choices": [], "usage": counts}
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        for e in events + [usage]:
            self.wfile.write(("data: " + json.dumps(e) + "\n\n").encode())
        self.wfile.write(b"data: [DONE]\n\n")
    def log_message(self, *a): pass
http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()
"""


def token() -> str:
    now = int(time.time())
    return jwt.encode(
        {"iss": "wasifyai-web", "aud": "wasifyai-api", "iat": now, "exp": now + 300,
         "sub": "desktop:local"},
        SECRET, algorithm="HS256",
    )  # fmt: skip


def auth() -> dict[str, str]:
    return {"authorization": f"Bearer {token()}"}


def fake_gguf(path: Path) -> None:
    """A GGUF header that says llama with one tensor, padded past the 1 MB floor."""

    def s(v: str) -> bytes:
        b = v.encode()
        return struct.pack("<Q", len(b)) + b

    kvs = s("general.architecture") + struct.pack("<I", 8) + s("llama")
    body = b"GGUF" + struct.pack("<IQQ", 3, 1, 1) + kvs
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body + b"\0" * (2_000_000 - len(body)))


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    root = tmp_path / "app-data"
    for key, value in {
        "DEPLOYMENT_PROFILE": "desktop", "DESKTOP_DATA_DIR": str(root),
        "DESKTOP_PUBLIC_URL": BASE, "DESKTOP_IMAGE_ENGINE": "stub",
        "API_AUTH_SECRET": SECRET, "AUTH_MODE": "jwt", "PRODUCTS_DIR": str(PRODUCTS),
        "LITELLM_BASE_URL": "", "METRICS_PORT": "0", "SAFEGUARDS_FORCE_ON": "false",
    }.items():  # fmt: skip
        monkeypatch.setenv(key, value)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    # the language engine "installed" by the shell: a fake server and its state file
    llama = root / "engine" / "llamacpp"
    (llama / "b1").mkdir(parents=True)
    server = llama / "b1" / "llama-server"
    server.write_text(FAKE)
    server.chmod(server.stat().st_mode | stat.S_IXUSR)
    (llama / "state.json").write_text(
        json.dumps({"version": "b1", "backend": "cpu", "server": "b1/llama-server"})
    )
    fake_gguf(home / ".lmstudio" / "models" / "acme" / "demo" / "demo-Q4_K_M.gguf")
    get_settings.cache_clear()
    yield root
    get_settings.cache_clear()


def wait_for_scan(c: TestClient) -> dict:
    c.post("/desktop/discovery/scan", headers=auth())
    for _ in range(100):
        state = c.get("/desktop/discovery", headers=auth()).json()
        if state["scanned_at"] and not state["running"]:
            return state
        time.sleep(0.05)
    raise AssertionError("the scan did not finish")


def choose_the_model(c: TestClient) -> None:
    state = wait_for_scan(c)
    (item,) = [i for i in state["items"] if i["kind"] == "language"]
    assert item["state"] == "can_use" and item["use"] == "chat"
    r = c.put("/desktop/language", json={"item_id": item["id"], "context": 4096}, headers=auth())
    assert r.status_code == 200, r.text


def ask(c: TestClient, text: str, conversation_id: str | None = None) -> list:
    graph_input: dict[str, str] = {"text": text}
    if conversation_id:
        graph_input["conversation_id"] = conversation_id
    body = {"input": graph_input}
    r = c.post("/products/wasifyai-assistant/runs", json=body, headers=auth())
    assert r.status_code == 200, r.text
    return parse(r.text)


def test_a_question_is_answered_by_the_chosen_model_and_remembered(data_dir):
    with TestClient(create_app()) as c:
        choose_the_model(c)
        events = ask(c, "Hello, what is a teapot?")
        names = [e for e, _ in events]
        assert names[-1] == "done" and "error" not in names and "tool_call" not in names
        text = "".join(d["text"] for e, d in events if e == "token")
        assert text.strip() == "Here is your picture."
        done = events[-1][1]["outputs"]
        assert done["status"] == "done" and done["title"] == "Hello, what is a teapot?"

        listing = c.get("/products/wasifyai-assistant/conversations", headers=auth()).json()
        assert [x["id"] for x in listing["conversations"]] == [done["conversation_id"]]
        one = c.get(
            f"/products/wasifyai-assistant/conversations/{done['conversation_id']}", headers=auth()
        ).json()
        assert [m["role"] for m in one["messages"]] == ["user", "assistant"]

        # a second message continues it
        again = ask(c, "And a cup?", done["conversation_id"])
        assert again[-1][1]["outputs"]["conversation_id"] == done["conversation_id"]
        one = c.get(
            f"/products/wasifyai-assistant/conversations/{done['conversation_id']}", headers=auth()
        ).json()
        assert len(one["messages"]) == 4

        # conversations are creations: found by search, and gone from it once deleted
        found = c.get("/creations/search", params={"q": "teapot"}, headers=auth()).json()
        assert [(r["kind"], r["id"]) for r in found["results"]] == [
            ("conversation", done["conversation_id"])
        ]
        gone = c.delete(
            f"/products/wasifyai-assistant/conversations/{done['conversation_id']}", headers=auth()
        )
        assert gone.status_code == 204
        after = c.get("/creations/search", params={"q": "teapot"}, headers=auth()).json()
        assert after["results"] == []
        c.post("/desktop/language-engine/stop", headers=auth())


def test_asking_for_a_picture_makes_one_through_the_image_product(data_dir):
    with TestClient(create_app()) as c:
        choose_the_model(c)
        events = ask(c, "Please draw a red teapot")
        names = [e for e, _ in events]
        assert names[-1] == "done", events[-1]
        assert "tool_call" in names and "tool_result" in names and "job_progress" in names
        assert names.index("tool_call") < names.index("tool_result") < names.index("done")

        call = next(d for e, d in events if e == "tool_call")
        assert call["name"] == "generate_image"
        assert call["arguments"] == {"prompt": "a red teapot on a table", "size": "square"}
        result = next(d for e, d in events if e == "tool_result")
        assert result["status"] == "ok" and result["id"] == call["id"]
        image_id = result["output"]["image_id"]

        # the picture is in the person's library like any other, with its recipe
        got = c.get(f"/products/wasifyai-image/images/{image_id}", headers=auth())
        assert got.status_code == 200
        assert got.json()["recipe"]["prompt"] == "a red teapot on a table"

        text = "".join(d["text"] for e, d in events if e == "token")
        assert "Let me draw that." in text and text.strip().endswith("Here is your picture.")
        done = events[-1][1]["outputs"]
        one = c.get(
            f"/products/wasifyai-assistant/conversations/{done['conversation_id']}", headers=auth()
        ).json()
        assert [m["role"] for m in one["messages"]] == ["user", "assistant", "tool", "assistant"]
        c.post("/desktop/language-engine/stop", headers=auth())


def test_nothing_chosen_ends_the_run_with_a_sentence_that_says_what_to_do(data_dir):
    with TestClient(create_app()) as c:
        events = ask(c, "Hello")
        last_name, last = events[-1]
        assert last_name == "error" and last["code"] == "no_language_model"
        assert "Models" in last["message"]


def test_another_persons_conversation_is_not_reachable_through_a_run(data_dir):
    with TestClient(create_app()) as c:
        choose_the_model(c)
        events = ask(c, "Hello", "00000000-0000-0000-0000-000000000000")
        assert events[-1][0] == "done"
        assert events[-1][1]["outputs"]["status"] == "refused"
        c.post("/desktop/language-engine/stop", headers=auth())
