"""The web runs only cloud models (ADR-0099; ADR-0100 stage CP11), against fakes: the admin keeps
the service's Runware, WaveSpeed and fal.ai keys in Admin › Media, per tenant; a product runs on the
model chosen for it, else the first one a key can run; a picture or clip job carries its offers and
the name each key is kept under, never the key, and the media worker reads the key and runs the
cheapest offer; with no offer it says what is missing. Only an admin may see or change the keys."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from wasifyai_api import own_keys
from wasifyai_api.admin_providers import AdminProviders, CloudPlanSink
from wasifyai_api.identity import get_identity
from wasifyai_api.logging import tenant_id as current_tenant
from wasifyai_api.services import ApiServices
from wasifyai_api.settings_store import InMemorySettingsStore
from wasifyai_media_worker.backends import BackendRouter, NoCloudModel, OfferRunner
from wasifyai_media_worker.comfy import ComfyError
from wasifyai_media_worker.settings import WorkerSettings
from wasifyai_platform_sdk import (
    Identity,
    InMemoryJobSink,
    InMemorySecretStore,
    JobRequest,
    SecretBox,
)

from tests.test_own_keys_engines import Fal, accept
from tests.test_own_keys_media import _progress, a_png

KEY = "fal-good-0123456789"


def providers(secrets: InMemorySecretStore | None = None) -> AdminProviders:
    return AdminProviders(
        InMemorySettingsStore(), secrets or InMemorySecretStore(), "local",
        testers={"text": accept, "media": accept},
    )  # fmt: skip


def a_job(tenant: str = "t1", product: str = "wasifyai-image") -> JobRequest:
    return JobRequest(
        tenant_id=tenant, product_id=product, user_id="u1", capability="image.generate",
        workflow="w", prompt={}, inputs={"prompt": "a fox"},
        outputs={"image": {"node": "1", "type": "image"}},
    )  # fmt: skip


async def test_a_tenant_key_runs_its_products_on_the_first_model_a_key_can_run():
    secrets = InMemorySecretStore()
    admin = providers(secrets)
    await admin.for_tenant("t1").save_key("media", "fal", KEY)
    # kept under the tenant's own name, in the one secrets table
    assert await secrets.names() == ["tenant-t1.keys.media.fal"]
    view = await admin.for_tenant("t1").view()
    ids = [p["id"] for p in view["products"]]
    assert "chat" not in ids and "images" in ids  # the web's text is Admin › Models
    images = next(p for p in view["products"] if p["id"] == "images")
    assert images["use"]["model"] == "gpt-image-2.5"  # nothing chosen: the first a key can run
    plan = await admin.plan_of("t1", "wasifyai-image")
    assert plan is not None and plan["model"] == "gpt-image-2.5"
    assert [o["secret"] for o in plan["offers"]] == ["tenant-t1.keys.media.fal"]
    assert KEY not in json.dumps(plan)  # never the key
    assert await admin.plan_of("t2", "wasifyai-image") is None  # another tenant has no key
    assert await admin.plan_of("t1", "wasifyai-voice") is None  # not a picture or clip job


async def test_the_model_the_admin_chose_is_the_one_a_job_runs_on():
    admin = providers()
    keys = admin.for_tenant("t1")
    await keys.save_key("media", "fal", KEY)
    await keys.use("images", None, "z-image-turbo")
    plan = await admin.plan_of("t1", "wasifyai-image")
    assert plan is not None and plan["model"] == "z-image-turbo"


async def test_the_engines_ask_by_the_tenant_of_the_request():
    admin = providers()
    await admin.for_tenant("t1").save_key("media", "fal", KEY)
    await admin.refresh("t1")
    token = current_tenant.set("t1")
    try:
        route = admin.known("voice")
        assert route is not None and route.choices[0].key == KEY
    finally:
        current_tenant.reset(token)
    assert admin.known("voice") is None  # the default tenant has no key


async def test_a_job_is_sent_with_its_offers():
    admin = providers()
    await admin.for_tenant("t1").save_key("media", "fal", KEY)
    inner = InMemoryJobSink()
    await CloudPlanSink(inner, admin).submit(a_job())
    await CloudPlanSink(inner, admin).submit(a_job("t2"))
    with_plan, without = inner.submitted
    assert with_plan.inputs["cloud"]["model"] == "gpt-image-2.5"
    assert "cloud" not in without.inputs


# ---- the media worker ------------------------------------------------------------------------


def router(secrets: InMemorySecretStore, http) -> BackendRouter:
    return BackendRouter(
        NoCloudModel(), WorkerSettings(), None, SecretBox(""), http, poll_s=0, secrets=secrets
    )


async def test_the_worker_reads_the_key_by_its_name_and_runs_the_cheapest_offer():
    secrets = InMemorySecretStore()
    admin = providers(secrets)
    await admin.for_tenant("t1").save_key("media", "fal", KEY)
    await admin.for_tenant("t1").use("images", None, "z-image-turbo")
    job = a_job()
    job.inputs["cloud"] = await admin.plan_of("t1", "wasifyai-image")
    fal = Fal({"images": [{"url": "https://files.example/out.png"}]}, a_png())
    async with fal.client() as http:
        runner = await router(secrets, http).resolve(job)
        assert isinstance(runner, OfferRunner)
        made = await runner.run(job, _progress)
    ((url, _),) = fal.posts()
    assert url.startswith("https://queue.fal.run/fal-ai/z-image")
    assert fal.requests[0].headers["authorization"] == f"Key {KEY}"
    assert made["image"][0] == a_png()
    assert runner.cost is not None and runner.cost.offer.provider == "fal"


async def test_a_job_with_no_offers_or_an_unreadable_key_says_what_is_missing():
    async with Fal({}, b"").client() as http:
        r = router(InMemorySecretStore(), http)
        with pytest.raises(ComfyError) as e:
            await (await r.resolve(a_job())).run(a_job(), _progress)
        assert "Admin › Media" in e.value.message
        job = a_job()
        job.inputs["cloud"] = {
            "model": "z-image-turbo",
            "offers": [{"offer": {"provider": "fal", "endpoint": "x",
                                  "price": {"amount": 0.01, "unit": "picture"}},
                        "secret": "tenant-t1.keys.media.fal"}],
        }  # fmt: skip
        with pytest.raises(ComfyError) as e:
            await r.resolve(job)
        assert "keys could not be read" in e.value.message


# ---- who may see the keys ----------------------------------------------------------------------


def web(role: str) -> TestClient:
    services = ApiServices()
    services.own_keys = providers()
    app = FastAPI()
    app.state.services = services
    app.include_router(own_keys.router)
    app.dependency_overrides[get_identity] = lambda: Identity("t1", "u1", role)
    return TestClient(app)


def test_on_the_web_only_an_admin_sees_or_changes_the_service_keys():
    assert web("user").get("/desktop/keys").status_code == 403
    assert web("user").put("/desktop/keys/media/keys/fal", json={"key": KEY}).status_code == 403
    admin = web("admin")
    r = admin.put("/desktop/keys/media/keys/fal", json={"key": KEY})
    assert r.status_code == 200, r.text
    assert KEY not in r.text
    images = next(p for p in r.json()["products"] if p["id"] == "images")
    assert images["use"]["model"] == "gpt-image-2.5"


# ---- Train on the web ------------------------------------------------------------------------


class WebTrainer:
    """The web's picture trainer (`RemoteImageTrainer`): no folder, files kept in storage."""

    def __init__(self) -> None:
        self.kept: dict[str, bytes] = {}

    def problem(self, base_id: str | None = None) -> str | None:
        return "The training worker is not running."

    def fit(self, need_gb: float = 0.0) -> dict[str, Any]:
        return {"verdict": "fits", "reason": ""}

    async def keep_file(self, adapter: Path, name: str, run_id: str) -> None:
        self.kept[name] = await asyncio.to_thread(adapter.read_bytes)


async def test_a_look_taught_on_the_web_is_kept_and_its_address_fills_the_image_jobs(tmp_path):
    from wasifyai_api.cloud_train import CloudLookTrainer

    from tests.test_cloud_train import LOOK, report
    from tests.test_cloud_train import a_job as train_job

    admin = providers()
    keys = admin.for_tenant("t1")
    await keys.save_key("media", "fal", KEY)
    await admin.refresh("t1")
    local = WebTrainer()
    fal = Fal({"diffusers_lora_file": {"url": "https://v3.fal.media/l.safetensors"}}, LOOK)
    token = current_tenant.set("t1")
    try:
        engine = CloudLookTrainer(local, admin, fal.client, poll_s=0)
        assert getattr(engine, "hub_missing", None) is None  # the web's runtime path stays
        assert engine.fit()["verdict"] == "fits" and engine.problem("flux3-image-klein") is None
        _, told = report()
        result = await engine.train(train_job(tmp_path, "flux3-image-klein"), told, lambda n: None)
        name = await engine.publish(result.adapter, "Ink", "run12345")
    finally:
        current_tenant.reset(token)
    assert name is not None and local.kept[name] == LOOK
    inner = InMemoryJobSink()
    job = a_job()
    job.inputs["loras"] = [{"name": name, "weight": 0.8}]
    await CloudPlanSink(inner, admin).submit(job)
    (sent,) = inner.submitted
    assert sent.inputs["lora_urls"][name]["url"] == "https://v3.fal.media/l.safetensors"
    assert sent.inputs["lora_urls"][name]["model"] == "flux-3-klein"
