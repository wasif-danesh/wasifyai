"""The llama.cpp component the desktop app installs really starts and answers a chat.

Skipped unless `WASIFYAI_LLAMA_DATA_DIR` names an app data folder in which the component was
installed (the shell's "Set up the language engine", or the `llamacpp` CI job) and
`WASIFYAI_LLAMA_MODEL` names a small GGUF language model file. CI downloads a tiny model; on a
development computer any found model does."""

import os
import sys
from pathlib import Path

import httpx
import pytest
from wasifyai_api.llama_server import LlamaServer

DATA = os.environ.get("WASIFYAI_LLAMA_DATA_DIR", "")
MODEL = os.environ.get("WASIFYAI_LLAMA_MODEL", "")

pytestmark = pytest.mark.skipif(
    not DATA or not MODEL or sys.platform == "win32",
    reason="needs an installed llama.cpp component and a small GGUF model",
)


async def test_the_installed_server_loads_a_model_and_answers():
    s = LlamaServer(Path(DATA), startup_timeout_s=300)
    assert s.installed, "the component is not installed in that folder"
    try:
        url = await s.ensure_running(Path(MODEL), context=2048)
        async with httpx.AsyncClient(timeout=120) as http:
            r = await http.post(
                f"{url}/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "Reply with the single word: ready"}],
                    "max_tokens": 32,
                    "temperature": 0,
                },
            )
        assert r.status_code == 200, r.text
        body = r.json()
        text = body["choices"][0]["message"]
        print("llama.cpp", s.state()["version"], s.state()["backend"], "answered:", text)
        assert body["usage"]["completion_tokens"] > 0
    finally:
        await s.close()
    assert not s.running
