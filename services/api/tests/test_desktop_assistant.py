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
        last_at = max(i for i, m in enumerate(msgs) if m["role"] == "user")
        has_result = any(m["role"] == "tool" for m in msgs[last_at:])  # in this turn
        last_user = msgs[last_at]["content"]
        shown = last_user
        if isinstance(last_user, list):  # a message with pictures: its text part is what to read
            last_user = " ".join(p.get("text", "") for p in last_user if p["type"] == "text")
        with open(__file__ + ".log", "a") as log:  # what the model was given, for the test to read
            log.write(json.dumps({"args": args, "user": shown}) + "\n")
        events = []
        think = bool((req.get("chat_template_kwargs") or {}).get("enable_thinking"))
        if think:  # llama.cpp names the thinking field `reasoning_content`
            for w in ("pondering ", "the ", "question"):
                events.append(chunk({"reasoning_content": w}))
        names = [t["function"]["name"] for t in req.get("tools") or []]
        if "web_search" in names and not has_result and "on the web" in last_user.lower():
            fn = {"name": "web_search", "arguments": json.dumps({"query": "red fox facts"})}
            events.append(chunk({"tool_calls": [{"index": 0, "id": "call_w", "type": "function",
                                                 "function": fn}]}))
            events.append(chunk({}, "tool_calls"))
        elif req.get("tools") and not has_result and "draw" in last_user.lower():
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

    template = "{% if enable_thinking is defined %}<think>{% endif %}{{ messages }}"
    kvs = (
        s("general.architecture") + struct.pack("<I", 8) + s("llama")
        + s("tokenizer.chat_template") + struct.pack("<I", 8) + s(template)
    )  # fmt: skip
    body = b"GGUF" + struct.pack("<IQQ", 3, 1, 2) + kvs
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
        assert "Model hub" in last["message"]


def test_another_persons_conversation_is_not_reachable_through_a_run(data_dir):
    with TestClient(create_app()) as c:
        choose_the_model(c)
        events = ask(c, "Hello", "00000000-0000-0000-0000-000000000000")
        assert events[-1][0] == "done"
        assert events[-1][1]["outputs"]["status"] == "refused"
        c.post("/desktop/language-engine/stop", headers=auth())


UID = "33333333-3333-4333-8333-333333333333"
RID = "44444444-4444-4444-8444-444444444444"
RUN = "55555555-5555-4555-8555-555555555555"


def ask_with(c: TestClient, body: dict) -> list:
    r = c.post("/products/wasifyai-assistant/runs", json=body, headers=auth())
    assert r.status_code == 200, r.text
    return parse(r.text)


def test_the_window_names_the_run_and_the_two_messages_and_the_engine_keeps_those_names(data_dir):
    """The additive fields of ADR-0082 stage CU1, on the desktop profile (SQLite)."""
    with TestClient(create_app()) as c:
        choose_the_model(c)
        body = {
            "input": {
                "text": "Please draw a red teapot",
                "client_message_id": UID,
                "client_reply_id": RID,
            },
            "run_id": RUN,
        }
        events = ask_with(c, body)
        assert {d["run_id"] for _, d in events} == {RUN}
        done = events[-1][1]["outputs"]
        assert done["user_message_id"] == UID and done["assistant_message_id"] == RID

        # a job's progress says which tool call it is for
        call = next(d for e, d in events if e == "tool_call")
        progress = [d for e, d in events if e == "job_progress"]
        assert progress and {p["tool_call_id"] for p in progress} == {call["id"]}

        stored = c.get(
            f"/products/wasifyai-assistant/conversations/{done['conversation_id']}", headers=auth()
        ).json()["messages"]
        assert [m["role"] for m in stored] == ["user", "assistant", "tool", "assistant"]
        assert stored[0]["id"] == UID and stored[1]["id"] == RID

        # starting again under the same run id is the same run: replayed, and nothing is said twice
        again = ask_with(c, body)
        assert [d["seq"] for _, d in again] == [d["seq"] for _, d in events]
        after = c.get(
            f"/products/wasifyai-assistant/conversations/{done['conversation_id']}", headers=auth()
        ).json()["messages"]
        assert len(after) == len(stored)

        # Stop on a run that is over says how it ended; on one that does not exist it is a 404
        r = c.post(f"/runs/{RUN}/cancel", headers=auth())
        assert r.status_code == 200 and r.json()["status"] == "done"
        assert c.post(f"/runs/{UID}/cancel", headers=auth()).status_code == 404
        c.post("/desktop/language-engine/stop", headers=auth())


def test_thinking_is_offered_for_a_model_that_can_think_and_streams_only_when_asked(data_dir):
    """ADR-0083, stage CO1, on the desktop profile: the capability, the switch, the stored part."""
    with TestClient(create_app()) as c:
        none = c.get("/products/wasifyai-assistant/options", headers=auth()).json()
        assert none["thinking"] is False  # nothing chosen yet
        choose_the_model(c)
        assert (
            c.get("/products/wasifyai-assistant/options", headers=auth()).json()["thinking"] is True
        )

        quiet = ask(c, "Hello, what is a teapot?")
        assert "reasoning" not in [e for e, _ in quiet]  # off by default: told not to think

        events = ask_with(c, {"input": {"text": "And a cup?", "thinking": True}})
        thought = "".join(d["text"] for e, d in events if e == "reasoning")
        assert thought == "pondering the question"
        names = [e for e, _ in events]
        assert names.index("reasoning") < names.index("token") < names.index("done")
        said = "".join(d["text"] for e, d in events if e == "token")
        assert "pondering" not in said  # the thinking is not part of the answer

        done = events[-1][1]["outputs"]
        stored = c.get(
            f"/products/wasifyai-assistant/conversations/{done['conversation_id']}", headers=auth()
        ).json()["messages"]
        reply = stored[-1]["parts"]
        assert [p["type"] for p in reply] == ["reasoning", "text"]
        assert reply[0]["text"] == "pondering the question"
        c.post("/desktop/language-engine/stop", headers=auth())


def test_web_search_is_off_until_allowed_then_cites_the_web_and_keeps_keys_encrypted(data_dir):
    """ADR-0083, stage CO3, on the desktop profile (SQLite): consent, a search through the
    assistant, the card's data, the stored conversation, and the key file."""
    from wasifyai_platform_sdk.web import DuckDuckGoProvider

    base = "/products/wasifyai-assistant"
    with TestClient(create_app()) as c:
        choose_the_model(c)
        web = c.app.state.web  # type: ignore[attr-defined]
        web._ddg = DuckDuckGoProvider(  # no real search is made by a test
            min_gap_s=0,
            run=lambda q, n: [
                {"title": "Red fox", "href": "https://wiki.test/fox", "body": "Foxes are small."}
            ],
        )

        opts = c.get(f"{base}/options", headers=auth()).json()["search"]
        assert opts["available"] is True and opts["consented"] is False and opts["ready"] is False
        assert opts["provider"] == "duckduckgo" and "DuckDuckGo" in opts["consent_text"]

        # asked to search before anything was allowed: the tool says what to do, nothing is sent
        body = {"input": {"text": "Look up red foxes on the web", "search": True}}
        events = ask_with(c, body)
        result = next(d for e, d in events if e == "tool_result")
        assert result["name"] == "web_search" and result["status"] == "error"
        assert "off" in result["output"]["message"]

        st = c.put(f"{base}/search", json={"consent": True}, headers=auth()).json()
        assert st["consented"] is True
        events = ask_with(c, body)
        names = [e for e, _ in events]
        assert names.index("tool_call") < names.index("tool_result") < names.index("done")
        result = next(d for e, d in events if e == "tool_result")
        assert result["status"] == "ok"
        assert result["output"]["results"][0] == {
            "title": "Red fox", "url": "https://wiki.test/fox", "site": "wiki.test",
            "snippet": "Foxes are small.",
        }  # fmt: skip
        done = events[-1][1]["outputs"]
        stored = c.get(f"{base}/conversations/{done['conversation_id']}", headers=auth()).json()
        calls = [p for m in stored["messages"] for p in m["parts"] if p["type"] == "tool_call"]
        assert calls and calls[0]["name"] == "web_search"

        # without Search switched on the model is not even offered the tool
        quiet = ask_with(c, {"input": {"text": "Look up red foxes on the web"}})
        assert "tool_call" not in [e for e, _ in quiet]

        # a key is kept encrypted, in a file only this user can read, and is never answered
        secret = "tvly-DESKTOP-KEY-0123456789"
        st = c.put(
            f"{base}/search",
            json={"provider": "tavily", "key": {"provider": "tavily", "value": secret}},
            headers=auth(),
        ).json()
        assert secret not in json.dumps(st)
        assert next(p for p in st["providers"] if p["id"] == "tavily")["key_set"] is True
        assert st["consented"] is False  # another service: asked again
        assert secret not in json.dumps(c.get(f"{base}/search", headers=auth()).json())
        keyfile = data_dir / "secrets.key"
        assert keyfile.exists() and stat.S_IMODE(keyfile.stat().st_mode) == 0o600
        import sqlite3

        raw = (
            sqlite3.connect(data_dir / "wasifyai.db")
            .execute("SELECT value FROM system_settings WHERE key = 'web.search'")
            .fetchone()[0]
        )
        assert secret not in raw and "tavily" in raw  # saved, and not in the clear
        c.post("/desktop/language-engine/stop", headers=auth())


def test_a_picture_asked_for_after_the_web_was_read_waits_for_a_click_then_is_made(data_dir):
    """CU2, approvals on the desktop profile: the run parks on a card, the card survives a reload,
    and the window's answer through /runs/{id}/resume carries the turn on."""
    from wasifyai_platform_sdk.web import DuckDuckGoProvider

    base = "/products/wasifyai-assistant"
    with TestClient(create_app()) as c:
        choose_the_model(c)
        web = c.app.state.web  # type: ignore[attr-defined]
        web._ddg = DuckDuckGoProvider(
            min_gap_s=0,
            run=lambda q, n: [{"title": "Fox", "href": "https://wiki.test/fox", "body": "Foxes."}],
        )
        c.put(f"{base}/search", json={"consent": True}, headers=auth())
        first = ask_with(c, {"input": {"text": "Look up red foxes on the web", "search": True}})
        cid = first[-1][1]["outputs"]["conversation_id"]

        events = ask_with(
            c, {"input": {"text": "now draw a teapot", "conversation_id": cid, "approvals": True}}
        )
        names = [e for e, _ in events]
        assert names[-1] == "interrupt" and "done" not in names, names
        card = events[-1][1]
        assert card["kind"] == "confirm_action" and card["payload"]["title"] == "Make a picture"
        assert card["payload"]["params"]["prompt"] == "a red teapot on a table"
        run_id = card["run_id"]

        # nothing was made yet, and a reload shows the card
        one = c.get(f"{base}/conversations/{cid}", headers=auth()).json()
        waiting = one["messages"][-1]["parts"][-1]
        assert waiting["type"] == "interrupt" and waiting["status"] == "pending"
        assert (
            waiting["run_id"] == run_id
            and waiting["tool_call_id"] == card["payload"]["tool_call_id"]
        )

        r = c.post(f"/runs/{run_id}/resume", json={"value": {"approved": True}}, headers=auth())
        assert r.status_code == 200, r.text
        resumed = parse(r.text)
        names = [e for e, _ in resumed]
        assert "job_progress" in names and names[-1] == "done", names
        result = next(d for e, d in resumed if e == "tool_result")
        assert result["name"] == "generate_image" and result["status"] == "ok"
        assert (
            c.post(
                f"/runs/{run_id}/resume", json={"value": {"approved": True}}, headers=auth()
            ).status_code
            == 409
        )
        one = c.get(f"{base}/conversations/{cid}", headers=auth()).json()
        tool = one["messages"][-2]
        assert tool["role"] == "tool" and tool["parts"][0]["status"] == "approved"
        c.post("/desktop/language-engine/stop", headers=auth())


def test_documents_and_pictures_are_attached_kept_with_the_chat_and_deleted_with_it(data_dir):
    """CO2 on the desktop profile: a document is read to its words and quoted to the model, a
    picture needs the model's projector, and both go with the conversation when it is deleted."""
    import io

    from PIL import Image

    base = "/products/wasifyai-assistant"
    model_dir = next(data_dir.parent.glob("home/.lmstudio/models/acme/demo"))
    with TestClient(create_app()) as c:
        choose_the_model(c)
        offered = c.get(f"{base}/options", headers=auth()).json()["attach"]
        assert offered["available"] is True and offered["documents"] is True
        assert offered["images"] is False and "mmproj" in offered["images_note"]

        # a document: read to words, kept, quoted to the model, shown back by name
        r = c.post(
            f"{base}/attachments", content=b"The launch is on Friday.",
            headers={**auth(), "x-file-name": "plan.md"},
        )  # fmt: skip
        assert r.status_code == 201, r.text
        doc = r.json()
        events = ask_with(
            c,
            {"input": {"text": "When?", "attachments": [{"id": doc["id"], "name": "plan.md"}]}},
        )
        assert events[-1][0] == "done"
        cid = events[-1][1]["outputs"]["conversation_id"]
        log = [
            json.loads(x)
            for x in (data_dir / "engine/llamacpp/b1/llama-server.log").read_text().splitlines()
        ]
        assert "The launch is on Friday." in log[-1]["user"] and "--mmproj" not in log[-1]["args"]
        stored = c.get(f"{base}/conversations/{cid}", headers=auth()).json()
        part = stored["messages"][0]["parts"][1]
        assert part["type"] == "attachment" and part["name"] == "plan.md" and "url" not in part

        # a picture before the model has a projector: refused in words, nothing attached
        buf = io.BytesIO()
        Image.new("RGB", (40, 30), (200, 30, 30)).save(buf, "PNG")
        up = c.post(f"{base}/uploads/images", content=buf.getvalue(), headers=auth())
        assert up.status_code == 201, up.text
        pic = up.json()["upload_id"]
        refused = ask_with(
            c, {"input": {"text": "look", "attachments": [{"id": pic, "name": "a.png"}]}}
        )
        out = refused[-1][1]["outputs"]
        assert out["status"] == "refused" and out["refusal"]["code"] == "no_vision"

        # with the projector next to the model the picture goes to the server with --mmproj
        (model_dir / "mmproj-F16.gguf").write_bytes(b"GGUF" + b"\0" * 100)
        (item,) = [i for i in wait_for_scan(c)["items"] if i["kind"] == "language"]
        chosen = c.put(
            "/desktop/language", json={"item_id": item["id"], "context": 4096}, headers=auth()
        )
        assert chosen.status_code == 200, chosen.text
        assert c.get(f"{base}/options", headers=auth()).json()["attach"]["images"] is True
        seen = ask_with(
            c, {"input": {"text": "look", "attachments": [{"id": pic, "name": "a.png"}]}}
        )
        assert seen[-1][0] == "done", seen[-1]
        log = [
            json.loads(x)
            for x in (data_dir / "engine/llamacpp/b1/llama-server.log").read_text().splitlines()
        ]
        assert "--mmproj" in log[-1]["args"]
        assert [p["type"] for p in log[-1]["user"]] == ["text", "image_url"]
        cid2 = seen[-1][1]["outputs"]["conversation_id"]
        read = c.get(f"{base}/conversations/{cid2}", headers=auth()).json()
        link = read["messages"][0]["parts"][1]
        assert link["kind"] == "image" and link["url"].startswith("http")
        shown = c.get(link["url"].replace(BASE, ""))  # the signed link serves the stored picture
        assert shown.status_code == 200 and shown.headers["content-type"].startswith("image/")

        # deleting the conversation takes what was attached with it
        assert c.delete(f"{base}/conversations/{cid2}", headers=auth()).status_code == 204
        assert c.get(f"{base}/conversations/{cid2}", headers=auth()).status_code == 404
        assert c.get(link["url"].replace(BASE, "")).status_code == 404  # the picture went with it
        c.post("/desktop/language-engine/stop", headers=auth())


def test_the_picture_reader_is_offered_with_its_size_fetched_only_when_confirmed_and_picked_up(
    data_dir, monkeypatch
):
    """CO2 follow-up: a model without a projector can be given one from the shelf. Nothing is
    fetched until the person confirms the exact size; the file must match its checksum."""
    import hashlib

    from wasifyai_api import desktop_vision

    payload = b"GGUF" + b"\0" * 5000  # a stand-in for the 918 MB file
    entry = desktop_vision.ProjectorEntry(
        id="demo", match=("demo-q4",), title="Demo picture reader", licence="Apache-2.0",
        source="huggingface.co", url="https://huggingface.co/x/y/resolve/main/mmproj-F16.gguf",
        name="mmproj-F16.gguf", size=len(payload), sha256=hashlib.sha256(payload).hexdigest(),
    )  # fmt: skip
    monkeypatch.setattr(desktop_vision, "load_shelf", lambda path=desktop_vision.SHELF: [entry])
    base = "/products/wasifyai-assistant"
    with TestClient(create_app()) as c:
        choose_the_model(c)
        offered = c.get(f"{base}/options", headers=auth()).json()["attach"]
        assert offered["images"] is False
        assert offered["picture_reader"]["state"] == "available"
        assert offered["picture_reader"]["bytes"] == len(payload)
        assert offered["picture_reader"]["from"] == "huggingface.co"

        # the size must be the one that was shown
        wrong = c.post("/desktop/vision/download", json={"bytes": 1}, headers=auth())
        assert wrong.status_code == 409
        manager = c.app.state.desktop_models.downloads  # type: ignore[attr-defined]
        assert manager.latest() is None  # nothing was fetched

        # serve the stand-in instead of the network
        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def stream(self, method, url, headers=None):
                class R:
                    status_code = 200

                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *a):
                        return False

                    async def aiter_bytes(self):
                        yield payload

                return R()

        manager._client_factory = lambda: FakeClient()  # noqa: SLF001
        started = c.post("/desktop/vision/download", json={"bytes": len(payload)}, headers=auth())
        assert started.status_code == 200, started.text
        state: dict = {}
        for _ in range(100):
            state = c.get("/desktop/vision", headers=auth()).json()["vision"]
            if state["state"] == "ready":
                break
            time.sleep(0.05)
        assert state["state"] == "ready"
        shelf = data_dir / "models" / "projectors" / "demo" / "mmproj-F16.gguf"
        assert shelf.is_file()  # under the app's own folder, not inside another tool's
        after = c.get(f"{base}/options", headers=auth()).json()["attach"]
        assert after["images"] is True and after["picture_reader"] is None
        c.post("/desktop/language-engine/stop", headers=auth())
