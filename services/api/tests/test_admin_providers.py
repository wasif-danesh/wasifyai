"""Speaking, 3D and the model button on the web's service keys (ADR-0100, stage CP11; before it,
one fal.ai row per tool, ADR-0095 K5): the keyed engines ask the tenant's keys service, say the
admin chose the model, and the web's model button names the cloud model each group runs on."""

from types import SimpleNamespace
from typing import Any, cast

import pytest
from wasifyai_api.admin_providers import AdminProviders, tenant_slug
from wasifyai_api.logging import tenant_id as current_tenant
from wasifyai_api.models_in_use import in_use
from wasifyai_api.own_keys_engines import KEYED_VOICE, KeyedModel3d, KeyedSpeechEngine
from wasifyai_api.services import ApiServices
from wasifyai_api.settings_store import InMemorySettingsStore
from wasifyai_platform_sdk import InMemorySecretStore

from tests.test_own_keys_engines import Local3d, LocalSpeech, accept

KEY = "fal-admin-key-123"
T = "t1"


def providers() -> AdminProviders:
    return AdminProviders(
        InMemorySettingsStore(), InMemorySecretStore(), "local",
        testers={"text": accept, "media": accept},
    )  # fmt: skip


async def with_key(p: AdminProviders) -> AdminProviders:
    await p.for_tenant(T).save_key("media", "fal", KEY)
    await p.refresh(T)
    return p


@pytest.fixture(autouse=True)
def tenant():
    token = current_tenant.set(T)
    yield
    current_tenant.reset(token)


def test_a_tenant_id_becomes_part_of_a_secret_name():
    assert tenant_slug("Acme Ltd/EU") == "acme-ltd-eu" and tenant_slug("") == "default"


async def test_speaking_runs_on_the_service_key_once_there_is_one():
    p = providers()
    speech = KeyedSpeechEngine(LocalSpeech(), p, admin=True)
    assert speech.models("speak")[0]["id"] == "kokoro-82m"  # no key: the engine workers' model
    await with_key(p)
    (only,) = speech.models("speak")
    assert only["id"] == KEYED_VOICE and only["title"].endswith("· fal.ai")
    await p.for_tenant(T).remove_key("media", "fal")
    await p.refresh(T)
    assert speech.models("speak")[0]["id"] == "kokoro-82m"


async def test_3d_says_the_admin_chose_its_model():
    engine = KeyedModel3d(Local3d(), await with_key(providers()), admin=True)
    assert engine.ready() and "chosen by your admin" in engine.fit()["reason"]


async def test_stopping_the_service_reaches_the_workers_engine():
    local = Local3d()
    engine = KeyedModel3d(local, providers(), admin=True)
    engine.closing = True
    assert cast("Any", local).closing is True


async def test_the_model_button_names_the_cloud_model_or_says_one_is_missing():
    p = providers()
    request = cast(
        "Any",
        SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(services=ApiServices(admin_providers=p)))
        ),
    )
    who = cast("Any", SimpleNamespace(tenant_id=T, user_id="u"))
    out = await in_use(request, who)
    (none,) = out.images
    assert not none.ready and "Admin › Media" in none.plain
    await with_key(p)
    out = await in_use(request, who)
    (picture,) = out.images
    assert picture.title == "GPT Image 2.5" and picture.ready
    assert picture.plain.startswith("Chosen by your admin.")
    assert [m.ready for m in out.three_d] == [True]
