"""Models on the desktop: the catalogue, what is present, and downloads that are confirmed,
resumable and checked. A loopback server stands in for Hugging Face; nothing real is downloaded."""

import asyncio
import hashlib
import http.server
import threading
import time
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from wasifyai_api import desktop_models as dm
from wasifyai_api.desktop_fit import Machine
from wasifyai_api.desktop_models import (
    DownloadError,
    ModelEntry,
    ModelFile,
    ModelsService,
    load_catalogue,
    parse_catalogue,
)
from wasifyai_api.identity import get_identity
from wasifyai_api.safeguards import InMemorySettingsStore
from wasifyai_api.services import ApiServices
from wasifyai_platform_sdk import Identity

PRODUCTS = Path(__file__).resolve().parents[3] / "products"

BLOBS = {
    "/unet.bin": b"U" * 300_000,
    "/clip.bin": b"C" * 200_000,
    "/vae.bin": b"V" * 50_000,
}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class Origin:
    """A file server with Range support, that can misbehave."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str | None]] = []
        self.ignore_range = False
        self.corrupt: set[str] = set()
        self.slow = 0.0
        origin = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                body = BLOBS.get(self.path)
                rng = self.headers.get("Range")
                origin.requests.append((self.path, rng))
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                if self.path in origin.corrupt:
                    body = b"X" * len(body)
                start = 0
                if rng and not origin.ignore_range:
                    start = int(rng.removeprefix("bytes=").split("-")[0])
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
                else:
                    self.send_response(200)
                part = body[start:]
                self.send_header("Content-Length", str(len(part)))
                self.end_headers()
                for i in range(0, len(part), 50_000):
                    if origin.slow:
                        time.sleep(origin.slow)
                    try:
                        self.wfile.write(part[i : i + 50_000])
                    except (BrokenPipeError, ConnectionResetError):
                        return

            def log_message(self, format, *args):  # noqa: A002
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()


@pytest.fixture
def origin():
    o = Origin()
    yield o
    o.close()


def entry(origin: Origin) -> ModelEntry:
    def f(folder: str, name: str, blob: str) -> ModelFile:
        data = BLOBS[blob]
        return ModelFile(folder, name, origin.base + blob, len(data), sha(data))

    files = (
        f("diffusion_models", "unet.safetensors", "/unet.bin"),
        f("text_encoders", "clip.safetensors", "/clip.bin"),
        f("vae", "vae.safetensors", "/vae.bin"),
    )
    return ModelEntry(
        "demo", "wasifyai-image", "Demo model", "Apache-2.0", "https://example.test", "", 24, files
    )


async def finished(d, wait_s=10):
    async with asyncio.timeout(wait_s):
        while d.status == "running":  # noqa: ASYNC110 - a test polling a plain attribute
            await asyncio.sleep(0.02)
    return d


# ---- the catalogue ----------------------------------------------------------------------------


def test_the_shipped_catalogue_is_pinned_and_safe():
    entries = load_catalogue(PRODUCTS, ["wasifyai-image", "hello"])
    assert [e.id for e in entries] == ["flux2-klein-4b"]
    e = entries[0]
    assert e.licence == "Apache-2.0" and e.approx_ram_gb == 24
    assert {f.name for f in e.files} == {
        "flux-2-klein-4b.safetensors", "qwen_3_4b.safetensors", "flux2-vae.safetensors"
    }  # fmt: skip
    for f in e.files:
        assert f.url.startswith("https://huggingface.co/Comfy-Org/flux2-klein-4B/resolve/")
        assert len(f.sha256) == 64 and f.size > 1_000_000
        assert "/main/" not in f.url  # a commit, not a branch that can move
    assert 16_100_000_000 < e.total_bytes < 16_200_000_000


def test_a_catalogue_entry_cannot_name_a_path_outside_the_models_folder():
    base = {"id": "x", "title": "X", "licence": "MIT", "source": "s"}
    f = {"folder": "vae", "name": "a.bin", "url": "https://h/a", "size": 5, "sha256": "0" * 64}
    ok = parse_catalogue({"models": [{**base, "files": [f]}]}, "p")
    assert ok[0].files[0].name == "a.bin"
    for bad in (
        {**f, "name": "../a.bin"},
        {**f, "folder": "../etc"},
        {**f, "url": "http://h/a"},
        {**f, "sha256": "abc"},
    ):
        with pytest.raises(ValueError):
            parse_catalogue({"models": [{**base, "files": [bad]}]}, "p")


# ---- what is present --------------------------------------------------------------------------


def service(tmp_path: Path, origin: Origin, extra=()) -> ModelsService:
    return ModelsService(
        [entry(origin)], tmp_path / "models", tuple(extra), InMemorySettingsStore()
    )


def put(root: Path, f: ModelFile, size: int | None = None) -> Path:
    p = root / f.folder / f.name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * (f.size if size is None else size))
    return p


def test_state_says_what_is_there_and_where_and_what_may_be_removed(tmp_path, origin, monkeypatch):
    shared = tmp_path / "shared"
    svc = service(tmp_path, origin, [shared])
    e = svc.catalogue["demo"]
    assert svc.entry_state(e)["status"] == "missing"

    put(shared, e.files[0])  # in a read-only folder
    put(svc.models_dir, e.files[1])  # in the app's own
    put(svc.models_dir, e.files[2], size=1)  # the right name but the wrong size: not present
    st = svc.entry_state(e)
    assert st["status"] == "partial"
    by = {f["name"]: f for f in st["files"]}
    assert by["unet.safetensors"]["present"] and not by["unet.safetensors"]["removable"]
    assert by["clip.safetensors"]["present"] and by["clip.safetensors"]["removable"]
    assert not by["vae.safetensors"]["present"]
    assert st["bytes_missing"] == 50_000

    put(svc.models_dir, e.files[2])
    assert svc.entry_state(e)["status"] == "ready"

    small = Machine("cpu", 16_000_000_000, 16_000_000_000)
    state = svc.entry_state(e, small)
    assert state["fit"]["verdict"] == "too_big"
    assert state["memory_warning"] and "24 GB" in state["memory_warning"]
    big = Machine("cpu", 64_000_000_000, 60_000_000_000)
    state = svc.entry_state(e, big)
    assert state["fit"]["verdict"] == "fits" and state["memory_warning"] is None


def test_remove_deletes_only_from_the_apps_own_folder(tmp_path, origin):
    shared = tmp_path / "shared"
    svc = service(tmp_path, origin, [shared])
    e = svc.catalogue["demo"]
    keep = put(shared, e.files[0])
    mine = put(svc.models_dir, e.files[1])
    part = svc.models_dir / "vae" / "vae.safetensors.part"
    part.parent.mkdir(parents=True)
    part.write_bytes(b"half")
    assert svc.remove(e) == 2
    assert keep.exists() and not mine.exists() and not part.exists()


# ---- downloads --------------------------------------------------------------------------------


async def test_a_download_fetches_verifies_and_places_every_file(tmp_path, origin):
    svc = service(tmp_path, origin)
    e = svc.catalogue["demo"]
    d = svc.downloads.start(e, list(e.files), svc.models_dir)
    await finished(d)
    assert d.status == "done" and d.bytes_done == d.bytes_total == 550_000
    for f in e.files:
        assert (svc.models_dir / f.folder / f.name).read_bytes() == BLOBS[
            f.url.removeprefix(origin.base)
        ]
        assert not (svc.models_dir / f.folder / (f.name + ".part")).exists()
    assert svc.entry_state(e)["status"] == "ready"


async def test_a_partial_file_is_continued_not_started_again(tmp_path, origin):
    svc = service(tmp_path, origin)
    e = svc.catalogue["demo"]
    f = e.files[0]
    part = svc.models_dir / f.folder / (f.name + ".part")
    part.parent.mkdir(parents=True)
    part.write_bytes(BLOBS["/unet.bin"][:120_000])
    d = svc.downloads.start(e, [f], svc.models_dir)
    await finished(d)
    assert d.status == "done"
    assert ("/unet.bin", "bytes=120000-") in origin.requests
    assert (svc.models_dir / f.folder / f.name).read_bytes() == BLOBS["/unet.bin"]


async def test_a_server_that_ignores_range_just_sends_the_whole_file(tmp_path, origin):
    origin.ignore_range = True
    svc = service(tmp_path, origin)
    e = svc.catalogue["demo"]
    f = e.files[0]
    part = svc.models_dir / f.folder / (f.name + ".part")
    part.parent.mkdir(parents=True)
    part.write_bytes(BLOBS["/unet.bin"][:100_000])
    d = svc.downloads.start(e, [f], svc.models_dir)
    await finished(d)
    assert d.status == "done"
    assert (svc.models_dir / f.folder / f.name).read_bytes() == BLOBS["/unet.bin"]


async def test_a_file_that_does_not_match_its_checksum_is_not_kept(tmp_path, origin):
    origin.corrupt.add("/clip.bin")
    svc = service(tmp_path, origin)
    e = svc.catalogue["demo"]
    d = svc.downloads.start(e, list(e.files), svc.models_dir)
    await finished(d)
    assert d.status == "failed" and "checksum" in d.error and "clip.safetensors" in d.error
    clip = svc.models_dir / "text_encoders"
    assert (
        not (clip / "clip.safetensors").exists() and not (clip / "clip.safetensors.part").exists()
    )
    assert (svc.models_dir / "diffusion_models" / "unet.safetensors").exists()  # the good one stays


async def test_not_enough_disk_is_said_before_anything_is_fetched(tmp_path, origin, monkeypatch):
    monkeypatch.setattr(dm, "free_disk_bytes", lambda p: 100_000)
    svc = service(tmp_path, origin)
    e = svc.catalogue["demo"]
    with pytest.raises(DownloadError, match="not enough free space"):
        svc.downloads.start(e, list(e.files), svc.models_dir)
    assert origin.requests == []


async def test_one_download_at_a_time_and_cancel_keeps_the_partial_file(tmp_path, origin):
    origin.slow = 0.05
    svc = service(tmp_path, origin)
    e = svc.catalogue["demo"]
    d = svc.downloads.start(e, list(e.files), svc.models_dir)
    with pytest.raises(DownloadError, match="already running"):
        svc.downloads.start(e, list(e.files), svc.models_dir)
    await asyncio.sleep(0.2)
    assert svc.downloads.cancel(d.id) is True
    await finished(d)
    assert d.status == "cancelled"
    assert svc.downloads.active is None
    part = svc.models_dir / "diffusion_models" / "unet.safetensors.part"
    assert part.exists() and 0 < part.stat().st_size < 300_000
    assert svc.downloads.cancel(d.id) is False  # nothing left to cancel


# ---- the routes -------------------------------------------------------------------------------


def app_for(svc: ModelsService) -> TestClient:
    app = FastAPI()
    app.state.services = ApiServices()
    app.include_router(dm.router)
    app.state.services.desktop_models = svc
    app.dependency_overrides[get_identity] = lambda: Identity("local", "u1", "user")
    return TestClient(app)


def test_the_list_shows_the_catalogue_the_folders_and_the_computer(tmp_path, origin):
    svc = service(tmp_path, origin, [tmp_path / "shared"])
    with app_for(svc) as c:
        body = c.get("/desktop/models").json()
    assert [m["id"] for m in body["models"]] == ["demo"]
    assert body["models"][0]["bytes_missing"] == 550_000
    assert body["folders"] == {
        "models_dir": str(tmp_path / "models"), "extra_dirs": [str(tmp_path / "shared")]
    }  # fmt: skip
    assert body["disk_free_bytes"] > 0 and body["download"] is None


def test_a_download_needs_the_exact_list_the_person_confirmed(tmp_path, origin):
    svc = service(tmp_path, origin)
    names = ["clip.safetensors", "unet.safetensors", "vae.safetensors"]
    with app_for(svc) as c:
        wrong_size = c.post("/desktop/models/demo/download", json={"files": names, "bytes": 1})
        wrong_files = c.post(
            "/desktop/models/demo/download", json={"files": names[:2], "bytes": 500_000}
        )
        assert wrong_size.status_code == 409 and wrong_files.status_code == 409
        assert "Review it" in wrong_size.json()["detail"]
        assert origin.requests == []  # nothing was fetched on a wrong confirmation
        assert (
            c.post("/desktop/models/nope/download", json={"files": [], "bytes": 0}).status_code
            == 404
        )

        # the demo model declares 24 GB: the memory gate is not what this test is about, and a
        # smaller computer (a CI runner) would refuse it
        ok = c.post(
            "/desktop/models/demo/download",
            json={"files": names, "bytes": 550_000, "accept_memory": True},
        )
        assert ok.status_code == 200
        did = ok.json()["id"]
        state: dict = {}
        for _ in range(200):
            state = c.get(f"/desktop/downloads/{did}").json()
            if state["status"] != "running":
                break
            time.sleep(0.05)
        assert state["status"] == "done" and state["bytes_done"] == 550_000
        again = c.post("/desktop/models/demo/download", json={"files": names, "bytes": 550_000})
        assert again.status_code == 409 and "already on this computer" in again.json()["detail"]
        assert c.delete("/desktop/models/demo").json() == {"removed": 3}


def test_saved_folders_reach_an_engine_built_after_they_were_loaded(tmp_path, origin):
    store = InMemorySettingsStore()
    asyncio.run(
        store.put(
            "desktop.model_folders",
            {"models_dir": str(tmp_path / "models"), "extra_dirs": [str(tmp_path / "shared")]},
            "window",
        )
    )
    svc = ModelsService([entry(origin)], tmp_path / "models", (), store)
    asyncio.run(svc.load())  # the worker does not exist yet

    class Sidecar:
        dirs = None

        def set_model_dirs(self, models_dir, extra):
            self.dirs = (models_dir, extra)

    sidecar = Sidecar()
    svc.attach(sidecar, object())
    assert sidecar.dirs == (tmp_path / "models", (tmp_path / "shared",))


def test_the_folders_can_be_changed_and_are_remembered(tmp_path, origin):
    store = InMemorySettingsStore()
    svc = ModelsService([entry(origin)], tmp_path / "models", (), store)

    class Sidecar:
        dirs = None
        installed = running = False

        def set_model_dirs(self, models_dir, extra):
            self.dirs = (models_dir, extra)

    svc.sidecar = Sidecar()
    with app_for(svc) as c:
        r = c.put(
            "/desktop/models/folders",
            json={
                "models_dir": str(tmp_path / "bigdrive"),
                "extra_dirs": [str(tmp_path / "shared")],
            },
        )
        assert r.status_code == 200
    assert (tmp_path / "bigdrive").is_dir()
    assert svc.sidecar.dirs == (tmp_path / "bigdrive", (tmp_path / "shared",))

    # a new service (the next launch) starts from what was saved
    later = ModelsService([entry(origin)], tmp_path / "models", (), store)
    asyncio.run(later.load())
    assert later.models_dir == tmp_path / "bigdrive"
    assert later.extra_dirs == (tmp_path / "shared",)


def test_the_catalogue_file_loads_as_yaml_the_way_the_app_reads_it():
    raw = yaml.safe_load((PRODUCTS / "wasifyai-image" / "models.yaml").read_text())
    assert raw["models"][0]["id"] == "flux2-klein-4b"


def test_a_model_that_will_not_fit_is_not_fetched_unless_the_person_insists(tmp_path, origin):
    svc = service(tmp_path, origin)

    async def small():
        return Machine("cpu", 8_000_000_000, 8_000_000_000)

    svc.machine = small  # type: ignore[method-assign]
    names = ["clip.safetensors", "unet.safetensors", "vae.safetensors"]
    body = {"files": names, "bytes": 550_000}
    with app_for(svc) as c:
        refused = c.post("/desktop/models/demo/download", json=body)
        assert refused.status_code == 409
        assert "will not fit" in refused.json()["detail"] and "24 GB" in refused.json()["detail"]
        assert origin.requests == []

        insisted = c.post("/desktop/models/demo/download", json={**body, "accept_memory": True})
        assert insisted.status_code == 200


# ---- a speech model beside the chat model (ADR-0083, decision 5) --------------------------------


@pytest.mark.parametrize(
    ("total_gb", "free_gb", "fits"),
    [
        (64, 40, True),  # this Mac: 6.9 GB chat model + 3 GB speech, budget 48 GB
        (32, 20, True),  # a 32 GB Mac: budget 24 GB
        (16, 4, True),  # a 16 GB Mac: 9.9 GB together, 4 GB free besides, budget 12 GB
        (16, 1, False),  # the same Mac with the rest of it busy: only 1 GB is free to add 3 GB
        (8, 4, False),  # 8 GB: 9.9 GB is more than its 6 GB budget
    ],
)
async def test_a_small_model_stays_beside_the_chat_model_only_when_the_two_fit(
    tmp_path, origin, monkeypatch, total_gb, free_gb, fits
):
    from wasifyai_api import desktop_models as dm

    gb = 1_000_000_000
    monkeypatch.setattr(
        dm,
        "read_machine",
        lambda reclaim=0: dm.Machine("unified", total_gb * gb, free_gb * gb, None, None, reclaim),
    )
    svc = service(tmp_path, origin)
    assert await svc.fits_beside(3 * gb, int(6.9 * gb)) is fits


async def test_unknown_sizes_never_share(tmp_path, origin):
    svc = service(tmp_path, origin)
    assert await svc.fits_beside(0, 6_900_000_000) is False
    assert await svc.fits_beside(3_000_000_000, 0) is False  # the chat model's size is unknown


@pytest.mark.parametrize(
    ("total_gb", "free_gb", "fits"),
    [
        (64, 40, True),  # this Mac: 6.9 GB chat model + 1 GB Kokoro (measured 0.9 GB)
        (32, 20, True),
        (16, 4, True),  # 7.9 GB together, 4 GB free besides, budget 12 GB
        (16, 0.5, False),  # the rest of it busy: only 0.5 GB is free to add 1 GB
        (8, 4, False),  # 8 GB: 7.9 GB is more than its 6 GB budget
    ],
)
async def test_the_read_aloud_voice_stays_beside_the_chat_model_only_when_the_two_fit(
    tmp_path, origin, monkeypatch, total_gb, free_gb, fits
):
    from wasifyai_api import desktop_models as dm

    gb = 1_000_000_000
    monkeypatch.setattr(
        dm,
        "read_machine",
        lambda reclaim=0: dm.Machine(
            "unified", total_gb * gb, int(free_gb * gb), None, None, reclaim
        ),
    )
    svc = service(tmp_path, origin)
    assert await svc.fits_beside(1 * gb, int(6.9 * gb)) is fits
