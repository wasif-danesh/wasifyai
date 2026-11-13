"""The admin routes for engine workers (ADR-0087, P5): the list, fetching a model onto a worker,
and following the job. A fake queue and directory stand for Redis and the workers."""

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from wasifyai_api.admin_workers import router
from wasifyai_api.identity import Identity, get_identity
from wasifyai_api.services import ApiServices
from wasifyai_platform_sdk import EngineError, EngineOutcome, EngineWorkerInfo, admin_wire


class Queue:
    def __init__(self) -> None:
        self.jobs: dict[str, Any] = {}
        self.outcomes: dict[str, EngineOutcome] = {}
        self.progress: dict[str, tuple[float, str]] = {}

    async def submit(self, job) -> None:
        self.jobs[job.id] = job

    async def status(self, job_id: str) -> str:
        if job_id in self.outcomes:
            return "done"
        return "waiting" if job_id in self.jobs else "lost"

    async def peek(self, job_id: str):
        return self.outcomes.get(job_id)

    async def progress_of(self, job_id: str):
        return self.progress.get(job_id)


def model(id_: str, state: str = "can_install") -> dict[str, Any]:
    return {
        "id": id_, "title": id_.title(), "state": state, "bytes_missing": 5_000_000_000,
        "licence": "Apache-2.0", "commercial_use": "yes", "tasks": ["speak"],
        "engine": "audio.cpp", "runtime_ready": True,
    }  # fmt: skip


@pytest.fixture
def rig():
    queue = Queue()
    worker = EngineWorkerInfo(
        id="w1", kinds=admin_wire.KINDS, models=[model("kokoro-82m", "ready"), model("voxcpm2")],
        components={admin_wire.LIPSYNC_COMPONENT: {"installed": False, "supported": True,
                                                   "bytes": 9}},
    )  # fmt: skip

    async def refresh() -> None:
        return None

    directory = SimpleNamespace(workers=[worker], queue=queue, refresh=refresh)
    audited: list[Any] = []

    async def audit(tenant, entry):
        audited.append((tenant, entry))

    app = FastAPI()
    app.state.services = ApiServices()
    app.state.services.engine_workers = directory
    app.state.services.admin = SimpleNamespace(audit=audit)  # type: ignore[assignment]
    app.include_router(router)
    role = {"v": "admin"}
    app.dependency_overrides[get_identity] = lambda: Identity("t1", "u1", role["v"])
    with TestClient(app) as client:
        client.queue, client.directory, client.audited, client.role = (  # type: ignore[attr-defined]
            queue, directory, audited, role,
        )  # fmt: skip
        yield client


def test_only_an_admin_sees_the_workers_and_what_each_has(rig):
    listed = rig.get("/admin/workers").json()["workers"]
    assert [w["id"] for w in listed] == ["w1"] and listed[0]["can_fetch"] is True
    assert {m["id"]: m["state"] for m in listed[0]["models"]} == {
        "kokoro-82m": "ready", "voxcpm2": "can_install",
    }  # fmt: skip
    assert listed[0]["lipsync_engine"]["installed"] is False
    rig.role["v"] = "user"
    assert rig.get("/admin/workers").status_code == 403
    assert rig.post("/admin/workers/models/voxcpm2/fetch").status_code == 403


def test_fetching_a_model_sends_a_job_and_the_page_follows_it(rig):
    started = rig.post("/admin/workers/models/voxcpm2/fetch")
    assert started.status_code == 202
    job_id = started.json()["job_id"]
    job = rig.queue.jobs[job_id]
    assert job.kind == admin_wire.FETCH_MODEL and job.params == {"model_id": "voxcpm2"}
    assert job.tenant_id == "t1" and job.prefix.startswith("t1/")
    assert rig.get(f"/admin/workers/jobs/{job_id}").json() == {
        "status": "working", "fraction": 0.0, "label": "Waiting for the worker", "error": None,
    }  # fmt: skip
    rig.queue.progress[job_id] = (0.4, "Downloading model.gguf")
    state = rig.get(f"/admin/workers/jobs/{job_id}").json()
    assert state["status"] == "working" and state["fraction"] == 0.4
    rig.queue.outcomes[job_id] = EngineOutcome(id=job_id, ok=True, worker="w1")
    assert rig.get(f"/admin/workers/jobs/{job_id}").json()["status"] == "done"
    assert rig.audited[0][1].action == "admin.worker.fetch"


def test_a_failed_fetch_says_why_and_a_second_click_follows_the_first_job(rig):
    first = rig.post("/admin/workers/models/voxcpm2/fetch").json()["job_id"]
    again = rig.post("/admin/workers/models/voxcpm2/fetch").json()["job_id"]
    assert again == first and len(rig.queue.jobs) == 1
    rig.queue.outcomes[first] = EngineOutcome(
        id=first, ok=False, error=EngineError(code="download_failed", message="Out of space.")
    )
    state = rig.get(f"/admin/workers/jobs/{first}").json()
    assert state["status"] == "failed" and state["error"] == "Out of space."
    retry = rig.post("/admin/workers/models/voxcpm2/fetch").json()["job_id"]
    assert retry != first  # a finished job is not reused


def test_what_is_already_there_or_not_listed_is_refused_in_words(rig):
    assert rig.post("/admin/workers/models/kokoro-82m/fetch").status_code == 409
    assert rig.post("/admin/workers/models/nothing/fetch").status_code == 404
    rig.directory.workers = []
    assert rig.post("/admin/workers/models/voxcpm2/fetch").status_code == 409


def test_the_lip_sync_engine_is_set_up_the_same_way_and_only_known_names_are_taken(rig):
    started = rig.post("/admin/workers/engines/lipsync-engine/fetch")
    assert started.status_code == 202
    job = rig.queue.jobs[started.json()["job_id"]]
    assert job.kind == admin_wire.FETCH_ENGINE and job.params == {"name": "lipsync-engine"}
    assert rig.post("/admin/workers/engines/rm-rf/fetch").status_code == 404
    assert rig.get("/admin/workers/jobs/unknown").json()["status"] == "lost"
