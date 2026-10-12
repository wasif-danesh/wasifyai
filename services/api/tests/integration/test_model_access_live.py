"""Model access against the real LiteLLM gateway (needs `make dev`). It uses its own alias, so the
stack's real aliases are never touched.

The first test guards a real hazard: LiteLLM merges an update into what is stored, so a key left out
of an update would survive and be sent to whatever server the alias now points at."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
from wasifyai_api.litellm_admin import LiteLLMBackend
from wasifyai_api.model_access import Binding, ModelAccess

ALIAS = "it-keytest"
DEFAULTS = {
    ALIAS: {
        "purpose": "integration test",
        "kind": "chat",
        "litellm_params": {
            "model": "openai/none",
            "api_base": "http://127.0.0.1:9",
            "api_key": "none",
        },
    }
}
REPLY = json.dumps(
    {
        "id": "x", "object": "chat.completion", "created": 1, "model": "m",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
).encode()  # fmt: skip


@pytest.fixture
async def gateway(litellm_settings):
    backend = LiteLLMBackend(litellm_settings.litellm_base_url, litellm_settings.litellm_api_key)
    models = ModelAccess(backend, DEFAULTS)
    await models.seed()
    yield backend, models, litellm_settings
    await backend.delete(models.model_id(ALIAS))


async def test_a_previous_key_is_never_sent_to_the_next_server(gateway):
    backend, models, settings = gateway
    seen: list[str | None] = []

    class Recorder(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length", 0)))
            seen.append(self.headers.get("authorization"))
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(REPLY)))
            self.end_headers()
            self.wfile.write(REPLY)

        def log_message(self, format, *args):
            pass

    server = HTTPServer(("0.0.0.0", 0), Recorder)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://host.containers.internal:{server.server_port}/v1"

    async def ask():
        seen.clear()
        async with httpx.AsyncClient(
            base_url=settings.litellm_base_url,
            headers={"authorization": f"Bearer {settings.litellm_api_key}"},
            timeout=60,
        ) as c:
            await c.post(
                "/v1/chat/completions",
                json={
                    "model": ALIAS,
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 5,
                },
            )

    try:
        keyed = Binding(
            provider="openai_compatible", model="m", api_base=base, api_key="SECRET-ONE"
        )
        await models.set(ALIAS, keyed, "it")
        await ask()
        if not seen:
            pytest.skip("the gateway cannot reach this machine (host.containers.internal)")
        assert seen[-1] == "Bearer SECRET-ONE"
        await models.set(
            ALIAS, Binding(provider="openai_compatible", model="m", api_base=base), "it"
        )
        await ask()
        assert seen[-1] == "Bearer none"  # the earlier key is gone, not forwarded
    finally:
        server.shutdown()


async def test_seed_is_idempotent_and_the_view_never_has_a_key(gateway):
    _, models, _ = gateway
    assert await models.seed() == 0
    view = (await models.list())[0]
    assert view.alias == ALIAS and view.source in ("default", "custom")
    assert "api_key" not in view.model_dump_json()
