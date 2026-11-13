"""Save diagnostics (stage O2): one zip at the chosen path, with what helps and nothing personal."""

import json
import zipfile
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from wasifyai_api.diagnostics import file_name, redact, router
from wasifyai_api.identity import Identity, get_identity
from wasifyai_api.services import ApiServices
from wasifyai_platform_sdk.actions.audit import AuditEntry, InMemoryAuditStore


class Machine:
    def public(self):
        return {"device": "mps", "total_bytes": 64 << 30}


class Models:
    async def machine(self):
        return Machine()


class Part:
    def __init__(self, id, title, status=None):
        self.id, self.title, self._status = id, title, status

    def status(self):
        if self._status is None:
            raise OSError("unreadable")
        return self._status


def entry(user: str, n: int) -> AuditEntry:
    return AuditEntry(
        tenant_id="t1", product_id="images", user_id=user, action_id=f"images.make{n}",
        origin="window", effect="create", status="ok",
    )  # fmt: skip


@pytest.fixture
async def audit():
    store = InMemoryAuditStore()
    for n in range(60):
        await store.record(entry("u1", n))
    await store.record(entry("someone-else", 99))
    return store


@pytest.fixture
def api(tmp_path, audit):
    data = tmp_path / "app"
    (data / "logs").mkdir(parents=True)
    (data / "logs" / "engine.log").write_text(
        "started\nGET /x Authorization: Bearer abc.def.ghi\nhf token hf_AbCdEfGhIjKlMnOp\n"
        "url?api_key=s3cret&x=1\nall well\n"
    )
    (data / "logs" / "provision.log").write_text("x" * 50 + "\nlast line\n")
    (tmp_path / "Documents").mkdir()
    registry = SimpleNamespace(
        components={"comfyui": Part("comfyui", "Image engine", {"state": "installed"}),
                    "reader": Part("reader", "Document reader")}
    )  # fmt: skip
    services = ApiServices(components=registry)  # type: ignore[arg-type]
    services.desktop_dir = data
    services.desktop_models = Models()
    services.actions = SimpleNamespace(audit=audit)  # type: ignore[assignment]
    app = FastAPI()
    app.state.services = services
    app.dependency_overrides[get_identity] = lambda: Identity("t1", "u1")
    app.include_router(router)
    return TestClient(app), tmp_path


def test_the_zip_is_written_at_the_chosen_path_with_what_helps(api):
    c, root = api
    target = root / "Documents" / "diag.zip"
    r = c.post("/desktop/diagnostics", json={"path": str(target)})
    assert r.status_code == 200, r.text
    assert r.json()["path"] == str(target) and r.json()["bytes"] == target.stat().st_size
    z = zipfile.ZipFile(target)
    assert sorted(z.namelist()) == [
        "README.txt", "about.json", "audit.json", "components.json", "logs/engine.log",
        "logs/provision.log", "machine.json",
    ]  # fmt: skip
    assert json.loads(z.read("machine.json"))["device"] == "mps"
    parts = json.loads(z.read("components.json"))
    assert parts[0]["status"] == {"state": "installed"} and parts[1]["error"] == "OSError"
    audit = json.loads(z.read("audit.json"))
    assert len(audit) == 50 and {a["user_id"] for a in audit} == {
        "u1"
    }  # this person's, the last 50
    assert audit[0]["action_id"] == "images.make59"
    log = z.read("logs/engine.log").decode()
    assert "started" in log and "all well" in log
    for secret in ("abc.def.ghi", "hf_AbCdEfGhIjKlMnOp", "s3cret"):
        assert secret not in log
    assert b"Not inside" in z.read("README.txt")


def test_a_long_log_keeps_its_end_from_a_whole_line(api, monkeypatch):
    import wasifyai_api.diagnostics as d

    monkeypatch.setattr(d, "LOG_TAIL_BYTES", 20)
    c, root = api
    target = root / "Documents" / "diag.zip"
    c.post("/desktop/diagnostics", json={"path": str(target)})
    assert zipfile.ZipFile(target).read("logs/provision.log") == b"last line\n"


def test_a_place_that_cannot_be_used_is_refused_in_words(api):
    c, root = api
    r = c.post("/desktop/diagnostics", json={"path": str(root / "app" / "d.zip")})
    assert r.status_code == 422 and "belongs to the app" in r.json()["detail"]


def test_the_suggested_name_carries_the_time():
    when = datetime(2026, 10, 29, 9, 5, tzinfo=UTC)
    assert file_name(when) == "wasify-diagnostics-2026-10-29-0905.zip"


@pytest.mark.parametrize(
    ("line", "kept"),
    [
        ("Authorization: Bearer eyJ.a.b", "Authorization: [hidden]"),
        ('{"password": "pw1"}', '{"password": "[hidden]"}'),
        ("key sk-proj-ABCDEFGHIJKL done", "key [hidden] done"),
        ("loaded 3 models in 2 s", "loaded 3 models in 2 s"),
    ],
)
def test_keys_and_tokens_are_blanked(line, kept):
    assert redact(line) == kept
