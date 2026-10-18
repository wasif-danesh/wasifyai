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
    CanaryFailed,
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
}
KEY = "sk-live-0123456789abcdef0123456789abcdef"


class Checks:
    """Stands in for the product checks: fails any candidate whose model name contains 'bad'."""

    def __init__(self, backend: InMemoryModelBackend):
        self._backend = backend
        self.ran: list[tuple[str, str]] = []

    async def run(self, alias, candidate):
        self.ran.append((alias, candidate))
        params = self._backend.entries[candidate][1]
        return ["x: allowed, but it must be refused"] if "bad" in params["model"] else []


def make(with_checks=False):
    backend = InMemoryModelBackend()
    checks = Checks(backend) if with_checks else None
    return backend, ModelAccess(backend, load_defaults(SUBST), checks), checks


def test_defaults_load_with_addresses_filled_in():
    d = load_defaults(SUBST)
    assert set(d) == {
        "default-chat",
        "lyrics-writer",
        "prompt-enhancer",
        "creation-embedder",
        "moderator",
        "moderator-nothink",
        "multimodal",
        "embedder",
        "voice-speak",
        "voice-transcribe",
    }
    assert d["moderator"]["litellm_params"]["api_base"] == "http://ollama:11434"
    assert d["multimodal"]["litellm_params"]["api_base"] == "http://ollama:11434/v1"
    assert d["moderator"]["protected"] and d["moderator"]["litellm_params"]["temperature"] == 0


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"model": "ollama_chat/gemma4:e4b"}, ("ollama", "gemma4:e4b")),
        ({"model": "ollama/nomic-embed-text"}, ("ollama", "nomic-embed-text")),
        (
            {"model": "openai/gemma4:e4b", "api_base": "http://x/v1"},
            ("openai_compatible", "gemma4:e4b"),
        ),
        ({"model": "gemini/gemini-2.5-flash"}, ("gemini", "gemini-2.5-flash")),
        ({"model": "anthropic/claude-x"}, ("litellm", "anthropic/claude-x")),
    ],
)
def test_describe_reads_provider_and_model(params, expected):
    assert describe(params) == expected


async def test_seed_creates_every_alias_once():
    backend, models, _ = make()
    assert await models.seed() == 10
    assert await models.seed() == 0  # idempotent: a second API replica changes nothing
    views = {v.alias: v for v in await models.list()}
    assert views["moderator"].source == "default" and views["moderator"].provider == "ollama"
    assert views["multimodal"].provider == "openai_compatible"
    assert all(v.key_set is False for v in views.values())
    assert set(backend.entries) == {f"alias:{a}" for a in views}


async def test_a_missing_alias_is_shown_as_missing():
    _, models, _ = make()
    assert {v.source for v in await models.list()} == {"missing"}


async def test_seed_removes_old_canary_leftovers_only():
    backend, models, _ = make()
    old = {"id": "candidate:moderator:old", "wasifyai": {"created_at": "2020-01-01T00:00:00+00:00"}}
    fresh = {"id": "candidate:moderator:new", "wasifyai": {"created_at": models._now()}}
    await backend.add("moderator", {}, old)
    await backend.add("moderator", {}, fresh)
    await models.seed()
    assert "candidate:moderator:old" not in backend.entries
    assert "candidate:moderator:new" in backend.entries


async def test_set_binds_a_hosted_provider_and_never_reveals_the_key():
    backend, models, _ = make()
    await models.seed()
    view, _ = await models.set(
        "lyrics-writer",
        Binding(provider="gemini", model="gemini-2.5-flash", api_key=KEY),
        "admin-1",
    )
    assert (view.source, view.provider, view.model, view.key_set) == (
        "custom",
        "gemini",
        "gemini-2.5-flash",
        True,
    )
    assert view.updated_by == "admin-1"
    assert KEY not in json.dumps(view.model_dump(mode="json"))
    _, params, info = backend.entries["alias:lyrics-writer"]
    assert params["model"] == "gemini/gemini-2.5-flash" and params["api_key"] == KEY  # LiteLLM only
    assert KEY not in json.dumps(info)  # our own metadata never holds it
    assert params["think"] is False  # the alias keeps its behaviour parameters


async def test_the_moderator_keeps_temperature_zero_whatever_the_provider():
    backend, models, _ = make()
    await models.seed()
    binding = Binding(provider="groq", model="llama-3.3-70b-versatile", api_key=KEY)
    await models.set("moderator", binding, "a")
    assert backend.entries["alias:moderator"][1]["temperature"] == 0


async def test_reset_returns_to_the_default_and_drops_the_key():
    backend, models, _ = make()
    await models.seed()
    await models.set("default-chat", Binding(provider="groq", model="m", api_key=KEY), "a")
    view = await models.reset("default-chat", "a")
    assert (view.source, view.provider, view.key_set) == ("default", "ollama", False)
    assert backend.entries["alias:default-chat"][1]["api_key"] == "none"  # overwritten, not left


def test_embedding_aliases_use_the_embedding_prefix():
    defaults = load_defaults(SUBST)
    b = Binding(provider="ollama", model="nomic-embed-text", api_base="http://o:11434")
    assert build_params(defaults["embedder"], b, "embedding")["model"] == "ollama/nomic-embed-text"
    assert build_params(defaults["default-chat"], b, "chat")["model"].startswith("ollama_chat/")


@pytest.mark.parametrize(
    ("binding", "message"),
    [
        (Binding(provider="nope", model="m"), "unknown provider"),
        (Binding(provider="gemini", model="bad model!"), "characters"),
        (Binding(provider="gemini", model="m"), "needs an API key"),
        (Binding(provider="ollama", model="m"), "needs a server address"),
        (Binding(provider="ollama", model="m", api_base="ftp://x"), r"http\(s\)"),
        (Binding(provider="ollama", model="m", api_base="http://u:p@x/"), "credentials"),
        (Binding(provider="ollama", model="m", api_base="http://169.254.169.254/"), "not allowed"),
        (Binding(provider="gemini", model="m", api_key="two words"), "one token"),
        (Binding(provider="gemini", model="m", api_key="k" * 600), "one token"),
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
    _, models, _ = make()
    with pytest.raises(ModelAccessError, match="unknown alias"):
        await models.set("nope", Binding(provider="groq", model="m", api_key=KEY), "a")


async def test_a_failing_check_blocks_the_change_and_leaves_no_candidate_behind():
    backend, models, checks = make(with_checks=True)
    await models.seed()
    before = dict(backend.entries["alias:moderator"][1])
    with pytest.raises(CanaryFailed) as caught:
        await models.set("moderator", Binding(provider="groq", model="bad-model", api_key=KEY), "a")
    assert "must be refused" in caught.value.failures[0]
    assert backend.entries["alias:moderator"][1] == before  # not changed
    assert not [i for i in backend.entries if i.startswith("candidate:")]
    assert checks and checks.ran[0][0] == "moderator"
    assert checks.ran[0][1].startswith("candidate:moderator:")


async def test_a_passing_check_lets_the_change_through():
    backend, models, _ = make(with_checks=True)
    await models.seed()
    binding = Binding(provider="groq", model="good", api_key=KEY)
    view, outcome = await models.set("moderator", binding, "a")
    assert outcome == "passed" and view.model == "good"
    assert not [i for i in backend.entries if i.startswith("candidate:")]


async def test_test_connection_uses_the_alias_or_a_candidate_and_redacts_errors():
    backend, models, _ = make()
    await models.seed()
    ok = await models.test("default-chat")
    assert ok.ok and backend.calls == ["default-chat"]
    backend.fail.add("default-chat")
    bad = await models.test("default-chat")
    assert not bad.ok and "invalid api key" in bad.error
    backend.fail.clear()
    res = await models.test("default-chat", Binding(provider="groq", model="m", api_key=KEY))
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
    _, models, _ = make()
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
        ("put", "/admin/models/moderator"),
        ("post", "/admin/models/moderator/test"),
        ("post", "/admin/models/moderator/reset"),
    ]:
        assert getattr(routes, method)(path).status_code == 401
        assert getattr(routes, method)(path, headers=USER).status_code == 403


def test_list_shows_aliases_and_the_provider_choices(routes):
    body = routes.get("/admin/models", headers=ADMIN).json()
    assert {m["alias"] for m in body["models"]} >= {"moderator", "lyrics-writer"}
    assert {p["id"] for p in body["providers"]} >= {"ollama", "gemini", "groq", "openrouter"}


def test_changing_a_model_is_audited_without_the_key_and_the_key_is_never_returned(routes):
    res = routes.put(
        "/admin/models/lyrics-writer",
        json={"provider": "gemini", "model": "gemini-2.5-flash", "api_key": KEY},
        headers=ADMIN,
    )
    assert res.status_code == 200 and res.json()["model"]["key_set"] is True
    assert KEY not in res.text
    assert KEY not in routes.get("/admin/models", headers=ADMIN).text
    (entry,) = [e for e in routes.audit.entries if e.action == "admin.model.update"]
    assert entry.target_id == "lyrics-writer" and entry.detail["key_provided"] is True
    assert KEY not in entry.model_dump_json()


def test_bad_input_is_422(routes):
    missing_key = {"provider": "gemini", "model": "m"}
    assert (
        routes.put("/admin/models/lyrics-writer", json=missing_key, headers=ADMIN).status_code
        == 422
    )
    unknown = {"provider": "groq", "model": "m", "api_key": KEY}
    assert routes.put("/admin/models/nope", json=unknown, headers=ADMIN).status_code == 422


def test_test_and_reset_routes_record_audit_entries(routes):
    t = routes.post("/admin/models/default-chat/test", headers=ADMIN)
    assert t.status_code == 200 and t.json()["ok"] is True
    r = routes.post("/admin/models/default-chat/reset", headers=ADMIN)
    assert r.status_code == 200 and r.json()["source"] == "default"
    assert {"admin.model.test", "admin.model.reset"} <= {e.action for e in routes.audit.entries}


async def test_switching_from_a_keyed_provider_to_a_keyless_one_overwrites_the_old_key():
    backend, models, _ = make()
    await models.seed()
    await models.set("lyrics-writer", Binding(provider="gemini", model="m", api_key=KEY), "a")
    assert backend.entries["alias:lyrics-writer"][1]["api_key"] == KEY
    local = Binding(provider="ollama", model="m", api_base="http://somewhere-else:11434")
    view, _ = await models.set("lyrics-writer", local, "a")
    assert backend.entries["alias:lyrics-writer"][1]["api_key"] == "none"  # LiteLLM merges updates
    assert view.key_set is False


async def test_every_default_reset_writes_an_explicit_key():
    backend, models, _ = make()
    await models.seed()
    for alias in models.aliases():
        await models.set(alias, Binding(provider="gemini", model="m", api_key=KEY), "a")
        await models.reset(alias, "a")
        assert backend.entries[f"alias:{alias}"][1]["api_key"] == "none"
