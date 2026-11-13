import asyncio
import json
import time

import jwt
import pytest
from fastapi.testclient import TestClient
from wasifyai_api.admin import InMemoryAdminStore
from wasifyai_api.config import get_settings
from wasifyai_api.litellm_admin import InMemoryModelBackend
from wasifyai_api.model_access import (
    Binding,
    ModelAccess,
    ModelAccessError,
    build_params,
    describe,
    load_defaults,
    validate_binding,
)
from wasifyai_api.users import InMemoryUserStore
from wasifyai_platform_sdk import InMemoryUsageRecorder

from tests.test_auth import SECRET
from tests.test_runs import hello_registry, mem_app

SUBST = {
    "OLLAMA_BASE_URL": "http://ollama:11434",
    "OLLAMA_OPENAI_BASE_URL": "http://ollama:11434/v1",
    "EMBEDDER_BASE_URL": "http://embedder.test:8080",
}
KEY = "sk-live-0123456789abcdef0123456789abcdef"


def make():
    backend = InMemoryModelBackend()
    return backend, ModelAccess(backend, load_defaults(SUBST))


def test_defaults_load_with_addresses_filled_in():
    d = load_defaults(SUBST)
    assert set(d) == {
        "default-chat",
        "planner",
        "lyrics-writer",
        "prompt-enhancer",
        "creation-embedder",
        "multimodal",
        "embedder",
        "voice-speak",
        "voice-transcribe",
    }
    assert not any("protected" in spec for spec in d.values())


def test_every_text_alias_is_haiku_with_an_effort_and_no_temperature():
    """ADR-0100: Claude Haiku 5.5 on Anthropic; it takes no sampling settings, thinks as much as
    the job needs, and gets a `max_tokens` (LiteLLM would otherwise send 128000)."""
    d = load_defaults(SUBST)
    efforts = {}
    for alias, spec in d.items():
        p = spec["litellm_params"]
        if spec["kind"] != "chat":
            continue
        assert p["model"] == "anthropic/claude-haiku-5-5", alias
        assert p["api_key"] == "os.environ/ANTHROPIC_API_KEY", alias
        assert not {"temperature", "top_p", "top_k", "think"} & set(p), alias
        assert p["max_tokens"] >= 8000, alias
        efforts[alias] = p["reasoning_effort"]
    assert efforts == {
        "default-chat": "medium", "planner": "high", "lyrics-writer": "low",
        "prompt-enhancer": "low", "multimodal": "low",
    }  # fmt: skip
    # search runs on bge-m3 on the web's own embedder (decision 4, 2026-11-13); the RAG helper's
    # 768 alias stays on OpenAI, unused by the products
    p = d["creation-embedder"]["litellm_params"]
    assert p["model"] == "openai/bge-m3" and "dimensions" not in p
    assert p["api_base"] == "http://embedder.test:8080/v1"
    p = d["embedder"]["litellm_params"]
    assert p["model"] == "openai/text-embedding-3-small" and p["dimensions"] == 768


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"model": "ollama_chat/gemma4:e4b"}, ("ollama", "gemma4:e4b")),
        ({"model": "ollama/nomic-embed-text"}, ("ollama", "nomic-embed-text")),
        (
            {"model": "openai/gemma4:e4b", "api_base": "http://x/v1"},
            ("openai_compatible", "gemma4:e4b"),
        ),
        (
            {"model": "openrouter/anthropic/claude-haiku-5.5"},
            ("openrouter", "anthropic/claude-haiku-5.5"),
        ),
        # ADR-0100: the text vendors, Z.ai through `openai/` at its own address
        ({"model": "anthropic/claude-haiku-5-5"}, ("anthropic", "claude-haiku-5-5")),
        ({"model": "openai/gpt-6-luna"}, ("openai", "gpt-6-luna")),
        ({"model": "gemini/gemini-3.8-flash"}, ("gemini", "gemini-3.8-flash")),
        ({"model": "deepseek/deepseek-flash"}, ("deepseek", "deepseek-flash")),
        (
            {"model": "openai/glm-5.3-flash", "api_base": "https://api.z.ai/api/paas/v4/"},
            ("zai", "glm-5.3-flash"),
        ),
        # a provider no longer offered (ADR-0100: Groq, Cerebras) is shown as a plain LiteLLM string
        ({"model": "groq/llama-3.3-70b"}, ("litellm", "groq/llama-3.3-70b")),
    ],
)
def test_describe_reads_provider_and_model(params, expected):
    assert describe(params) == expected


def test_z_ai_is_bound_at_its_own_address_whatever_the_admin_sends():
    b = validate_binding(
        Binding(provider="zai", model="glm-5.3-flash", api_base="http://elsewhere/", api_key=KEY)
    )
    assert b.api_base == "https://api.z.ai/api/paas/v4"
    params = build_params({"litellm_params": {"model": "x"}}, b, "chat")
    assert params["model"] == "openai/glm-5.3-flash"
    assert params["api_base"] == "https://api.z.ai/api/paas/v4"
    assert describe(params) == ("zai", "glm-5.3-flash")


async def test_seed_creates_every_alias_once():
    backend, models = make()
    assert await models.seed() == 9
    assert await models.seed() == 0  # idempotent: a second API replica changes nothing
    views = {v.alias: v for v in await models.list()}
    assert views["default-chat"].source == "default"
    assert views["default-chat"].provider == "anthropic"  # ADR-0100
    assert views["planner"].model == "claude-haiku-5-5"
    assert views["embedder"].provider == "openai"
    assert all(v.key_set is False for v in views.values())
    assert set(backend.entries) == {f"alias:{a}" for a in views}


async def test_a_missing_alias_is_shown_as_missing():
    _, models = make()
    assert {v.source for v in await models.list()} == {"missing"}


async def test_seed_removes_old_canary_leftovers_only():
    backend, models = make()
    old = {
        "id": "candidate:default-chat:old",
        "wasifyai": {"created_at": "2020-01-01T00:00:00+00:00"},
    }
    fresh = {"id": "candidate:default-chat:new", "wasifyai": {"created_at": models._now()}}
    await backend.add("default-chat", {}, old)
    await backend.add("default-chat", {}, fresh)
    await models.seed()
    assert "candidate:default-chat:old" not in backend.entries
    assert "candidate:default-chat:new" in backend.entries


async def test_set_binds_a_hosted_provider_and_never_reveals_the_key():
    backend, models = make()
    await models.seed()
    view = await models.set(
        "lyrics-writer",
        Binding(provider="openrouter", model="anthropic/claude-haiku-5.5", api_key=KEY),
        "admin-1",
    )
    assert (view.source, view.provider, view.model, view.key_set) == (
        "custom",
        "openrouter",
        "anthropic/claude-haiku-5.5",
        True,
    )
    assert view.updated_by == "admin-1"
    assert KEY not in json.dumps(view.model_dump(mode="json"))
    _, params, info = backend.entries["alias:lyrics-writer"]
    assert (
        params["model"] == "openrouter/anthropic/claude-haiku-5.5" and params["api_key"] == KEY
    )  # LiteLLM only
    assert KEY not in json.dumps(info)  # our own metadata never holds it
    # the alias keeps its behaviour parameters
    assert params["reasoning_effort"] == "low" and params["max_tokens"] == 8000


async def test_reset_returns_to_the_default_and_drops_the_key():
    backend, models = make()
    await models.seed()
    await models.set("default-chat", Binding(provider="openrouter", model="m", api_key=KEY), "a")
    view = await models.reset("default-chat", "a")
    assert (view.source, view.provider, view.key_set) == ("default", "anthropic", False)
    # overwritten with the default's own reference to the environment, not left
    assert backend.entries["alias:default-chat"][1]["api_key"] == "os.environ/ANTHROPIC_API_KEY"


def test_embedding_aliases_use_the_embedding_prefix():
    defaults = load_defaults(SUBST)
    b = Binding(provider="ollama", model="nomic-embed-text", api_base="http://o:11434")
    assert build_params(defaults["embedder"], b, "embedding")["model"] == "ollama/nomic-embed-text"
    assert build_params(defaults["default-chat"], b, "chat")["model"].startswith("ollama_chat/")


@pytest.mark.parametrize(
    ("binding", "message"),
    [
        (Binding(provider="nope", model="m"), "unknown provider"),
        (Binding(provider="groq", model="m", api_key=KEY), "unknown provider"),  # ADR-0100
        (Binding(provider="openrouter", model="bad model!"), "characters"),
        (Binding(provider="openrouter", model="m"), "needs an API key"),
        (Binding(provider="ollama", model="m"), "needs a server address"),
        (Binding(provider="ollama", model="m", api_base="ftp://x"), r"http\(s\)"),
        (Binding(provider="ollama", model="m", api_base="http://u:p@x/"), "credentials"),
        (Binding(provider="ollama", model="m", api_base="http://169.254.169.254/"), "not allowed"),
        (Binding(provider="openrouter", model="m", api_key="two words"), "one token"),
        (Binding(provider="openrouter", model="m", api_key="k" * 600), "one token"),
    ],
)
def test_bad_bindings_are_rejected(binding, message):
    with pytest.raises(ModelAccessError, match=message):
        validate_binding(binding)


def test_local_servers_are_allowed_and_keyless():
    ok = validate_binding(
        Binding(
            provider="openai_compatible",
            model="m",
            api_base="http://host.containers.internal:8080/v1",
        )
    )
    spec = load_defaults(SUBST)["multimodal"]
    assert build_params(spec, ok, "chat")["api_key"] == "none"


async def test_unknown_alias_is_rejected():
    _, models = make()
    with pytest.raises(ModelAccessError, match="unknown alias"):
        await models.set("nope", Binding(provider="openrouter", model="m", api_key=KEY), "a")


async def test_test_connection_uses_the_alias_or_a_candidate_and_redacts_errors():
    backend, models = make()
    await models.seed()
    ok = await models.test("default-chat")
    assert ok.ok and backend.calls == ["default-chat"]
    backend.fail.add("default-chat")
    bad = await models.test("default-chat")
    assert not bad.ok and "invalid api key" in bad.error
    backend.fail.clear()
    res = await models.test("default-chat", Binding(provider="openrouter", model="m", api_key=KEY))
    assert res.ok and backend.calls[-1].startswith("candidate:default-chat:")
    assert not [i for i in backend.entries if i.startswith("candidate:")]


# ---- the HTTP routes ----------------------------------------------------------------------


def _token(sub, email, verified):
    now = int(time.time())
    claims = {
        "iss": "wasifyai-web",
        "aud": "wasifyai-api",
        "iat": now,
        "exp": now + 300,
        "sub": sub,
        "email": email,
        "email_verified": verified,
    }
    return "Bearer " + jwt.encode(claims, SECRET, algorithm="HS256")


ADMIN = {"authorization": _token("google:9", "boss@example.com", True)}
USER = {"authorization": _token("google:1", "ann@example.com", True)}


@pytest.fixture
def routes(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("API_AUTH_SECRET", SECRET)
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    get_settings.cache_clear()
    (tmp_path / "hello").mkdir()
    (tmp_path / "hello" / "product.yaml").write_text(
        "id: hello\ncapabilities:\n  text.chat: { provider: fake, defaults: { reply: hi } }\n"
    )
    _, models = make()
    asyncio.run(models.seed())
    admin = InMemoryAdminStore()
    app = mem_app(
        hello_registry(),
        tmp_path,
        InMemoryUsageRecorder(),
        users=InMemoryUserStore(),
        admin_store=admin,
        model_access=models,
    )
    with TestClient(app) as client:
        client.audit = admin  # type: ignore[attr-defined]
        yield client
    monkeypatch.undo()
    get_settings.cache_clear()


def test_routes_are_for_admins_only(routes):
    for method, path in [
        ("get", "/admin/models"),
        ("put", "/admin/models/multimodal"),
        ("post", "/admin/models/multimodal/test"),
        ("post", "/admin/models/multimodal/reset"),
    ]:
        assert getattr(routes, method)(path).status_code == 401
        assert getattr(routes, method)(path, headers=USER).status_code == 403


def test_list_shows_aliases_and_the_provider_choices(routes):
    body = routes.get("/admin/models", headers=ADMIN).json()
    assert {m["alias"] for m in body["models"]} >= {"multimodal", "lyrics-writer"}
    assert [p["id"] for p in body["providers"]] == [
        "anthropic", "openai", "gemini", "deepseek", "zai", "openrouter", "ollama",
        "openai_compatible",
    ]  # fmt: skip


def test_changing_a_model_is_audited_without_the_key_and_the_key_is_never_returned(routes):
    res = routes.put(
        "/admin/models/lyrics-writer",
        json={"provider": "openrouter", "model": "google/gemini-3.8-flash", "api_key": KEY},
        headers=ADMIN,
    )
    assert res.status_code == 200 and res.json()["model"]["key_set"] is True
    assert KEY not in res.text
    assert KEY not in routes.get("/admin/models", headers=ADMIN).text
    (entry,) = [e for e in routes.audit.entries if e.action == "admin.model.update"]
    assert entry.target_id == "lyrics-writer" and entry.detail["key_provided"] is True
    assert KEY not in entry.model_dump_json()


def test_bad_input_is_422(routes):
    missing_key = {"provider": "openrouter", "model": "m"}
    assert (
        routes.put("/admin/models/lyrics-writer", json=missing_key, headers=ADMIN).status_code
        == 422
    )
    unknown = {"provider": "openrouter", "model": "m", "api_key": KEY}
    assert routes.put("/admin/models/nope", json=unknown, headers=ADMIN).status_code == 422


def test_test_and_reset_routes_record_audit_entries(routes):
    t = routes.post("/admin/models/default-chat/test", headers=ADMIN)
    assert t.status_code == 200 and t.json()["ok"] is True
    r = routes.post("/admin/models/default-chat/reset", headers=ADMIN)
    assert r.status_code == 200 and r.json()["source"] == "default"
    assert {"admin.model.test", "admin.model.reset"} <= {e.action for e in routes.audit.entries}


async def test_switching_from_a_keyed_provider_to_a_keyless_one_overwrites_the_old_key():
    backend, models = make()
    await models.seed()
    await models.set("lyrics-writer", Binding(provider="openrouter", model="m", api_key=KEY), "a")
    assert backend.entries["alias:lyrics-writer"][1]["api_key"] == KEY
    local = Binding(provider="ollama", model="m", api_base="http://somewhere-else:11434")
    view = await models.set("lyrics-writer", local, "a")
    assert backend.entries["alias:lyrics-writer"][1]["api_key"] == "none"  # LiteLLM merges updates
    assert view.key_set is False


async def test_every_default_reset_writes_an_explicit_key():
    backend, models = make()
    await models.seed()
    for alias in models.aliases():
        await models.set(alias, Binding(provider="openrouter", model="m", api_key=KEY), "a")
        await models.reset(alias, "a")
        assert backend.entries[f"alias:{alias}"][1]["api_key"] != KEY
