"""The service's styles on the web (ADR-0091 decision 13, stage S5), against a fake Hugging Face:
an admin adds one (checked like the desktop's, kept in object storage under the service's part),
everyone sees the list read only, a picture request turns an id into the file the media worker
fetches, and only admins add or delete."""

import asyncio
import hashlib

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from wasifyai_api.desktop_hub import HubClient, HubError
from wasifyai_api.identity import get_identity
from wasifyai_api.service_styles import ServiceStyles, admin_router, router, style_key
from wasifyai_api.services import ApiServices
from wasifyai_api.settings_store import InMemorySettingsStore
from wasifyai_platform_sdk import Identity, LocalFileStorage, RunContext, reset_context, set_context

from tests.test_desktop_styles import lora, model_file

COMMIT = "c" * 40


def rig(tmp_path, data: bytes, *, card=None):
    sha = hashlib.sha256(data).hexdigest()
    repo = {
        "sha": COMMIT, "gated": False, "tags": [],
        "cardData": card or {"base_model": "black-forest-labs/FLUX.2-klein-4B",
                             "instance_prompt": "anime_style"},
        "siblings": [
            {"rfilename": "koni.safetensors", "lfs": {"size": len(data), "sha256": sha}},
            {"rfilename": "koni.ckpt", "lfs": {"size": 9, "sha256": "0" * 64}},
        ],
    }  # fmt: skip
    fetched: list[str] = []

    def hub_answer(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=repo)

    def files_answer(req: httpx.Request) -> httpx.Response:
        fetched.append(str(req.url))
        return httpx.Response(200, content=data)

    hub = HubClient(client=httpx.AsyncClient(transport=httpx.MockTransport(hub_answer)))
    storage = LocalFileStorage(tmp_path / "objects", "http://files.test", "s" * 32)
    svc = ServiceStyles(
        InMemorySettingsStore(), storage, hub,
        client=lambda: httpx.AsyncClient(transport=httpx.MockTransport(files_answer)),
    )  # fmt: skip
    return svc, storage, fetched


async def done(svc: ServiceStyles, job_id: str) -> dict:
    for _ in range(200):
        job = svc.job(job_id)
        if job and ("style" in job or "refused" in job):
            return job
        await asyncio.sleep(0.01)
    raise AssertionError("not finished")


async def test_an_admin_adds_a_style_for_everyone_checked_and_kept_in_storage(tmp_path):
    data = lora()
    svc, storage, fetched = rig(tmp_path, data)
    found = await svc.files("https://huggingface.co/Sawata97/koni")
    assert [f["name"] for f in found["files"]] == ["koni.safetensors"]
    assert found["refused"][0]["why"] == "not offered: it can run code"
    job = await done(
        svc, (await svc.add("t1", "Sawata97/koni", "koni.safetensors", len(data), "admin"))["id"]
    )
    style = job["style"]
    assert job["download"]["status"] == "done" and style["fit"] == "fits"
    assert style["trigger"] == "anime_style"
    assert "key" not in style  # nobody is told where it is kept
    assert fetched == [f"https://huggingface.co/Sawata97/koni/resolve/{COMMIT}/koni.safetensors"]
    assert await storage.get(style_key("t1", style["id"])) == data
    assert await svc.all("t2") == []  # each tenant has its own


async def test_a_file_that_is_not_a_style_or_not_what_was_listed_is_not_kept(tmp_path):
    svc, storage, _ = rig(tmp_path, model_file())
    job = await done(
        svc,
        (await svc.add("t1", "Sawata97/koni", "koni.safetensors", len(model_file()), "a"))["id"],
    )
    assert job["refused"] == "This is a model, not a style (a LoRA)."
    assert await svc.all("t1") == [] and await storage.list("") == []
    with pytest.raises(HubError) as e:
        await svc.add("t1", "Sawata97/koni", "koni.safetensors", 5, "a")
    assert e.value.code == "changed"


async def test_a_style_for_another_model_is_refused_on_the_service(tmp_path):
    nine = lora(4096, 8, 24)
    svc, _, _ = rig(tmp_path, nine)
    job = await done(
        svc, (await svc.add("t1", "Sawata97/koni", "koni.safetensors", len(nine), "a"))["id"]
    )
    assert "FLUX.2 klein 9B" in job["refused"]


async def test_a_request_turns_an_id_into_the_file_the_worker_fetches(tmp_path):
    data = lora()
    svc, _, _ = rig(tmp_path, data)
    style = (
        await done(
            svc, (await svc.add("t1", "Sawata97/koni", "koni.safetensors", len(data), "a"))["id"]
        )
    )["style"]
    token = set_context(RunContext("t1", "wasifyai-image", "u1", "run", "th"))
    try:
        loras, why = await svc.files_for([{"id": style["id"], "strength": 0.8}])
        assert why == "" and loras == [{
            "name": f"service-{style['id']}.safetensors", "weight": 0.8, "sha256": style["sha256"],
            "title": style["title"], "key": style_key("t1", style["id"]),
        }]  # fmt: skip
        _, why = await svc.files_for([{"id": "000000000000", "strength": 1}])
        assert "not on this service" in why
    finally:
        reset_context(token)
    await svc.delete("t1", style["id"])
    assert await svc.all("t1") == []


def app_for(svc: ServiceStyles, role: str) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.include_router(admin_router)
    app.state.services = ApiServices(service_styles=svc)
    app.dependency_overrides[get_identity] = lambda: Identity("t1", "u1", role)
    return TestClient(app)


def test_everyone_sees_the_list_and_only_admins_add_or_delete(tmp_path):
    svc, _, _ = rig(tmp_path, lora())
    with app_for(svc, "member") as person:
        assert person.get("/styles").json() == {"styles": [], "found": [], "max": 8}
        assert (
            person.post("/admin/styles/hub/files", json={"repo": "Sawata97/koni"}).status_code
            == 403
        )
        assert person.delete("/admin/styles/abc").status_code == 403
    with app_for(svc, "admin") as admin:
        files = admin.post("/admin/styles/hub/files", json={"repo": "Sawata97/koni"}).json()
        assert files["files"][0]["name"] == "koni.safetensors"
        bad = admin.post(
            "/admin/styles/hub/download",
            json={"repo": "Sawata97/koni", "file": "koni.safetensors", "bytes": 1},
        )
        assert bad.status_code == 409 and bad.json()["detail"]["message"].startswith(
            "The files changed"
        )
