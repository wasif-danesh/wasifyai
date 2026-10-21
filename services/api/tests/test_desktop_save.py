"""POST /desktop/save writes the sent file at the path the person chose in the Save As box."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from wasifyai_api.desktop_save import router
from wasifyai_api.identity import Identity, get_identity


@pytest.fixture
def api(tmp_path):
    app = FastAPI()
    app.state = SimpleNamespace(desktop_dir=tmp_path / "app")  # type: ignore[assignment]
    (tmp_path / "app").mkdir()
    (tmp_path / "Documents").mkdir()
    app.dependency_overrides[get_identity] = lambda: Identity("t1", "u1")
    app.include_router(router)
    return TestClient(app), tmp_path


def send(c, path, data=b"hello"):
    return c.post("/desktop/save", data={"path": str(path)}, files={"file": ("x.bin", data)})


def test_the_file_is_written_at_the_chosen_path_and_replaces_one_there(api):
    c, root = api
    target = root / "Documents" / "speech.wav"
    r = send(c, target, b"RIFF1")
    assert r.status_code == 200 and r.json() == {"name": "speech.wav", "path": str(target)}
    assert target.read_bytes() == b"RIFF1"
    send(c, target, b"RIFF2")
    assert target.read_bytes() == b"RIFF2"
    assert [p.name for p in (root / "Documents").iterdir()] == ["speech.wav"]


@pytest.mark.parametrize(
    ("where", "message"),
    [
        ("Documents", "folder"),
        ("nope/a.txt", "does not exist"),
        ("app/secrets.key", "belongs to the app"),
        ("relative.txt", "cannot be used"),
    ],
)
def test_a_place_that_cannot_be_used_is_refused_in_words(api, where, message):
    c, root = api
    path = where if where == "relative.txt" else root / where
    r = send(c, path)
    assert r.status_code == 422 and message in r.json()["detail"]
    assert not (root / "app" / "secrets.key").exists()
