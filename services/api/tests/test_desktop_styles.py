"""Styles for the image screens (ADR-0091, stage S1): a file is judged by its header alone (S0's
fingerprints), kept as a copy with a record beside it, listed with Train's styles first, resolved by
id, and deleted only when it is ours. Hostile files are refused in words."""

import json
import struct
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi.testclient import TestClient
from wasifyai_api.desktop_styles import (
    StyleRefused,
    StylesService,
    read_style_header,
)

# ---- fixture files: real safetensors headers, a few bytes of "weights" ---------------------------


def lora(
    width: int = 3072, doubles: int = 5, singles: int = 20, rank: int = 16,
    layout: str = "comfy", meta: dict | None = None, extra: dict | None = None,
) -> bytes:  # fmt: skip
    """A LoRA file in one of the layouts S0 found, with the block counts of a model."""
    t: dict = {}
    off = 0

    def add(name: str, shape: list[int]) -> None:
        nonlocal off
        t[name] = {"dtype": "BF16", "shape": shape, "data_offsets": [off, off + 2]}
        off += 2

    for kind, n in (("double", doubles), ("single", singles)):
        for i in range(n):
            if layout == "kohya":
                base = f"lora_unet_{kind}_blocks_{i}_linear"
                add(f"{base}.lora_down.weight", [rank, width])
                add(f"{base}.lora_up.weight", [width, rank])
            elif layout == "diffusers":
                block = "transformer_blocks" if kind == "double" else "single_transformer_blocks"
                add(f"transformer.{block}.{i}.attn.to_q.lora_A.weight", [rank, width])
                add(f"transformer.{block}.{i}.attn.to_q.lora_B.weight", [width, rank])
            else:
                add(f"diffusion_model.{kind}_blocks.{i}.linear.lora_A.weight", [rank, width])
                add(f"diffusion_model.{kind}_blocks.{i}.linear.lora_B.weight", [width, rank])
    if layout == "diffusers":
        add("transformer.double_stream_modulation_img.linear.lora_A.weight", [rank, width])
    t.update(extra or {})
    if meta:
        t["__metadata__"] = meta
    head = json.dumps(t).encode()
    return struct.pack("<Q", len(head)) + head + b"\x00" * off


def write(tmp: Path, name: str, data: bytes) -> Path:
    p = tmp / name
    p.write_bytes(data)
    return p


async def chunks(data: bytes, size: int = 4096):
    for i in range(0, len(data), size):
        yield data[i : i + size]


# ---- the header ---------------------------------------------------------------------------------


@pytest.mark.parametrize("layout", ["comfy", "kohya", "diffusers"])
def test_a_klein_4b_style_fits_in_every_layout_comfyui_applies(tmp_path, layout):
    h = read_style_header(write(tmp_path, "s.safetensors", lora(layout=layout, rank=32)))
    assert (h.model, h.fit, h.rank) == ("FLUX.2 klein 4B", "fits", 32)
    assert h.unused_parts == (1 if layout == "diffusers" else 0)  # said in one line, not refused


@pytest.mark.parametrize(
    ("shape", "model", "fit"),
    [((4096, 8, 24), "FLUX.2 klein 9B", "other"), ((3072, 19, 38), "FLUX.1", "other"),
     ((3072, 3, 0), "FLUX.2 klein 4B", "fits"), ((3072, 0, 0), None, "unsure")],
)  # fmt: skip
def test_the_fingerprint_names_the_model_a_style_was_made_for(tmp_path, shape, model, fit):
    w, d, s = shape
    extra = {"x.lora_A.weight": {"dtype": "BF16", "shape": [4, w], "data_offsets": [0, 2]}}
    data = lora(w, d, s, extra=extra if d == 0 and s == 0 else None)
    h = read_style_header(write(tmp_path, "s.safetensors", data))
    assert (h.model, h.fit) == (model, fit)


@pytest.mark.parametrize(
    ("meta", "word"),
    [({"trigger": "old-gods"}, "old-gods"), ({"trigger": "[trigger]"}, None),
     ({"ss_tag_frequency": json.dumps({"1_PXART4": {"PXART4": 1}})}, "PXART4"), ({}, None)],
)  # fmt: skip
def test_the_trigger_word_is_read_where_trainers_write_it(tmp_path, meta, word):
    h = read_style_header(write(tmp_path, "s.safetensors", lora(meta=meta)))
    assert h.trigger == word


def test_trains_own_record_says_it_was_made_for_klein_base(tmp_path):
    h = read_style_header(
        write(tmp_path, "s.safetensors", lora(meta={"taught_on": "flux2-klein-base-4b"}))
    )
    assert h.base is True


def model_file() -> bytes:
    t = {"diffusion_model.double_blocks.0.img_attn.qkv.weight":
         {"dtype": "BF16", "shape": [9216, 3072], "data_offsets": [0, 2]}}  # fmt: skip
    head = json.dumps(t).encode()
    return struct.pack("<Q", len(head)) + head + b"\x00\x00"


TENSOR = {"dtype": "BF16", "shape": [1], "data_offsets": [0, 2]}


@pytest.mark.parametrize(
    ("data", "words"),
    [(b"", "empty"), (b"\x00" * 8, "can read"), (struct.pack("<Q", 1 << 40) + b"{}", "can read"),
     (struct.pack("<Q", 5) + b"nope!", "can read"), (model_file(), "a model, not a style"),
     (lambda: lora(extra={"code": {"dtype": "BF16", "shape": [1]}}), "something other"),
     (lambda: lora(extra={"diffusion_model.final.weight": TENSOR}), "mixes")],
)  # fmt: skip
def test_hostile_or_wrong_files_are_refused_in_words(tmp_path, data, words):
    raw = cast("bytes", data() if callable(data) else data)
    with pytest.raises(StyleRefused, match=words):
        read_style_header(write(tmp_path, "s.safetensors", raw))


# ---- the records ---------------------------------------------------------------------------------


async def test_an_import_is_a_checked_copy_with_a_record_and_the_same_file_twice_is_one_style(
    tmp_path,
):
    svc = StylesService(tmp_path / "loras")
    data = lora(meta={"trigger": "anime_style", "ss_output_name": "Koni anime"})
    s = await svc.import_file(chunks(data), "My Koni (v2).safetensors")
    assert s.title == "Koni anime" and s.trigger == "anime_style" and s.fit == "fits"
    assert s.file == "My-Koni-v2.safetensors" and (tmp_path / "loras" / s.file).read_bytes() == data
    side = json.loads((tmp_path / "loras" / f"{s.file}.style.json").read_text())
    assert side["sha256"] == s.sha256 and side["source"] == {"kind": "file"}
    again = await svc.import_file(chunks(data), "copy.safetensors")
    assert again.id == s.id and [x.id for x in await svc.all()] == [s.id]
    public = s.public()
    assert "file" not in public and public["selectable"] is True  # the screen never sees a path


@pytest.mark.parametrize(
    ("name", "data", "words"),
    [("x.ckpt", lora(), "Only .safetensors"), ("x.pt", lora(), "Only .safetensors"),
     ("x.safetensors", model_file(), "a model")],
)  # fmt: skip
async def test_a_refused_import_leaves_nothing_behind(tmp_path, name, data, words):
    svc = StylesService(tmp_path / "loras")
    with pytest.raises(StyleRefused, match=words):
        await svc.import_file(chunks(data), name)
    assert not (tmp_path / "loras").exists() or list((tmp_path / "loras").iterdir()) == []


async def test_a_name_with_dots_and_slashes_becomes_a_safe_file_name(tmp_path):
    svc = StylesService(tmp_path / "loras")
    s = await svc.import_file(chunks(lora()), "../../etc/evil..safetensors")
    assert s.file == "evil.safetensors" and (tmp_path / "loras" / s.file).is_file()


async def test_a_file_that_is_too_big_is_refused_while_it_streams(tmp_path, monkeypatch):
    from wasifyai_api import desktop_styles

    monkeypatch.setattr(desktop_styles, "MAX_FILE_BYTES", 1000)
    with pytest.raises(StyleRefused, match="too big"):
        await StylesService(tmp_path / "loras").import_file(chunks(b"\x00" * 5000), "x.safetensors")
    assert list((tmp_path / "loras").iterdir()) == []


async def test_trains_styles_are_adopted_and_listed_first(tmp_path):
    folder = tmp_path / "loras"
    folder.mkdir()
    svc = StylesService(folder)
    other = await svc.import_file(chunks(lora(rank=8)), "other.safetensors")
    write(
        folder, "wasify-ena-b37ba287.safetensors", lora(meta={"taught_on": "flux2-klein-base-4b"})
    )
    write(folder, "not-a-style.safetensors", model_file())  # a model put here by hand: not listed
    styles = await svc.all()
    assert [s.source["kind"] for s in styles] == ["trained", "file"] and styles[1].id == other.id
    assert styles[0].base is True and styles[0].public()["made_for_base"] is True
    assert styles[0].source == {"kind": "trained", "run": "b37ba287"}  # Train's run, from its name
    assert styles[0].title == "Ena"


async def test_a_record_whose_file_went_is_dropped(tmp_path):
    svc = StylesService(tmp_path / "loras")
    s = await svc.import_file(chunks(lora()), "a.safetensors")
    (tmp_path / "loras" / s.file).unlink()  # Train removed its own file
    assert await svc.all() == [] and not (tmp_path / "loras" / f"{s.file}.style.json").exists()


async def test_ids_resolve_to_files_and_a_style_for_another_model_is_refused(tmp_path):
    svc = StylesService(tmp_path / "loras")
    good = await svc.import_file(chunks(lora()), "good.safetensors")
    nine = await svc.import_file(chunks(lora(4096, 8, 24)), "nine.safetensors")
    assert await svc.resolve([{"id": good.id, "strength": 0.7}]) == [
        {"name": "good.safetensors", "weight": 0.7, "sha256": good.sha256, "title": good.title}
    ]
    assert nine.public()["selectable"] is False
    loras, why = await svc.files_for([{"id": nine.id, "strength": 1}])
    assert loras == [] and "another model" in why
    _, why = await svc.files_for([{"id": "000000000000", "strength": 1}])
    assert "not on this computer" in why


async def test_rename_set_the_word_and_delete(tmp_path):
    svc = StylesService(tmp_path / "loras")
    s = await svc.import_file(chunks(lora()), "a.safetensors")
    s = await svc.update(s.id, "Ink", "inkwash")
    assert (s.title, s.trigger) == ("Ink", "inkwash")
    assert (await svc.get(s.id)).trigger == "inkwash"
    await svc.delete(s.id)
    assert list((tmp_path / "loras").iterdir()) == []
    with pytest.raises(KeyError):
        await svc.delete(s.id)


# ---- the routes ----------------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path):
    from fastapi import FastAPI
    from wasifyai_api.desktop_styles import router
    from wasifyai_api.identity import get_identity
    from wasifyai_api.services import ApiServices
    from wasifyai_platform_sdk import Identity

    app = FastAPI()
    app.include_router(router)
    app.state.services = ApiServices(desktop_styles=StylesService(tmp_path / "loras"))
    app.dependency_overrides[get_identity] = lambda: Identity("local", "me", "admin")
    with TestClient(app) as c:
        yield c


def test_the_routes_list_import_edit_and_delete(client):
    listed = client.get("/desktop/styles").json()
    assert (listed["styles"], listed["found"], listed["max"]) == ([], [], 8)
    r = client.post("/desktop/styles/import?name=ink.safetensors", content=lora())
    assert r.status_code == 201 and "file" not in r.json()
    sid = r.json()["id"]
    assert (
        client.patch(f"/desktop/styles/{sid}", json={"trigger": "ink"}).json()["trigger"] == "ink"
    )
    assert [s["id"] for s in client.get("/desktop/styles").json()["styles"]] == [sid]
    assert client.delete(f"/desktop/styles/{sid}").status_code == 204
    assert client.delete(f"/desktop/styles/{sid}").status_code == 404


def test_a_refused_file_is_422_in_words(client):
    r = client.post("/desktop/styles/import?name=x.safetensors", content=model_file())
    assert r.status_code == 422
    assert r.json()["detail"] == {
        "code": "style_refused",
        "message": "This is a model, not a style (a LoRA).",
    }


async def test_train_names_its_style_with_the_real_title_and_word(tmp_path):
    folder = tmp_path / "loras"
    folder.mkdir()
    write(folder, "wasify-ena-b37ba287.safetensors", lora())
    svc = StylesService(folder)
    s = await svc.describe(
        "wasify-ena-b37ba287.safetensors", "Ena", "ena", {"kind": "trained", "run": "b37ba287-1"}
    )
    assert s is not None and (s.title, s.trigger) == ("Ena", "ena")
    (listed,) = await svc.all()
    assert listed.id == s.id and listed.source["run"] == "b37ba287-1"
    assert await svc.describe("../x.safetensors", "X", None, {"kind": "trained"}) is None


def test_a_style_another_app_keeps_is_listed_and_copied_in(tmp_path):
    from fastapi import FastAPI
    from wasifyai_api.desktop_styles import router
    from wasifyai_api.identity import get_identity
    from wasifyai_api.services import ApiServices
    from wasifyai_platform_sdk import Identity

    other = tmp_path / "ComfyUI" / "models" / "loras"
    other.mkdir(parents=True)
    path = write(other, "anime.safetensors", lora(meta={"trigger": "anime_style"}))
    item = SimpleNamespace(
        id="f1", name="anime", kind="lora", family="flux", path=str(path),
        tool_title="ComfyUI", size=path.stat().st_size,
    )  # fmt: skip
    app = FastAPI()
    app.include_router(router)
    app.state.services = ApiServices(
        desktop_styles=StylesService(tmp_path / "loras"),
        desktop_discovery=SimpleNamespace(items=[item]),
    )
    app.dependency_overrides[get_identity] = lambda: Identity("local", "me", "admin")
    with TestClient(app) as c:
        listed = c.get("/desktop/styles").json()
        assert listed["found"] == [
            {"id": "f1", "title": "anime", "tool": "ComfyUI", "size": path.stat().st_size}
        ]
        r = c.post("/desktop/styles/from-found", json={"id": "f1"})
        assert r.status_code == 201
        assert r.json()["source"] == {"kind": "found", "tool": "ComfyUI"}
        assert r.json()["trigger"] == "anime_style"
        assert path.is_file()  # the other app's file is untouched: this is a copy
        assert c.post("/desktop/styles/from-found", json={"id": "nope"}).status_code == 404


# ---- from Hugging Face (S3), against a fake hub and the real download manager -----------------


def hub_rig(tmp_path, data: bytes, *, enabled=True, gated=False, card=None, extra_files=()):
    import hashlib

    import httpx
    from wasifyai_api.desktop_hub import HubError
    from wasifyai_api.desktop_models import DownloadManager
    from wasifyai_api.desktop_styles import HubStyles

    sha = hashlib.sha256(data).hexdigest()
    repo = {
        "sha": "c" * 40, "gated": gated,
        "cardData": card or {"base_model": "black-forest-labs/FLUX.2-klein-4B",
                             "instance_prompt": "anime_style"},
        "tags": [],
        "siblings": [
            {"rfilename": "koni.safetensors", "lfs": {"size": len(data), "sha256": sha}},
            {"rfilename": "koni.ckpt", "lfs": {"size": 9, "sha256": "0" * 64}},
            {"rfilename": "README.md", "size": 10},
            *extra_files,
        ],
    }  # fmt: skip
    asked: list[str] = []

    async def get(path, params=None, *, fresh=False):
        asked.append(path)
        return repo, False

    def require():
        if not enabled:
            raise HubError("consent_needed", "Turn it on first.", 403)

    fetched: list[str] = []

    def serve(req: httpx.Request) -> httpx.Response:
        fetched.append(str(req.url))
        return httpx.Response(200, content=data)

    downloads = DownloadManager(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(serve))
    )
    hub = SimpleNamespace(require=require, client=SimpleNamespace(get=get, has_token=False))
    models = SimpleNamespace(downloads=downloads, models_dir=tmp_path)
    styles = StylesService(tmp_path / "loras")
    return HubStyles(styles, hub, models), asked, fetched


async def wait_job(hub, download_id):
    import asyncio

    for _ in range(200):
        job = hub.job(download_id)
        if job and ("style" in job or "refused" in job):
            return job
        await asyncio.sleep(0.01)
    raise AssertionError("the download did not finish")


@pytest.mark.parametrize(
    ("text", "repo"),
    [("Sawata97/koni", "Sawata97/koni"),
     ("https://huggingface.co/Sawata97/koni/tree/main", "Sawata97/koni"),
     ("huggingface.co/Sawata97/koni", "Sawata97/koni"), ("../etc/passwd", None),
     ("just-a-name", None)],
)  # fmt: skip
def test_a_repository_is_read_from_a_name_or_its_address(text, repo):
    from wasifyai_api.desktop_styles import repo_of

    assert repo_of(text) == repo


async def test_a_repository_offers_its_safetensors_and_says_why_not_the_rest(tmp_path):
    hub, asked, fetched = hub_rig(tmp_path, lora())
    found = await hub.files("Sawata97/koni")
    assert found["files"] == [{"name": "koni.safetensors", "size": len(lora())}]
    assert found["refused"] == [{"name": "koni.ckpt", "why": "not offered: it can run code"}]
    assert (found["made_for_base"], found["trigger"]) == (False, "anime_style")
    assert asked == ["/api/models/Sawata97/koni"] and fetched == []  # nothing fetched yet


async def test_nothing_is_asked_before_browsing_is_allowed(tmp_path):
    from wasifyai_api.desktop_hub import HubError

    hub, asked, _ = hub_rig(tmp_path, lora(), enabled=False)
    with pytest.raises(HubError) as e:
        await hub.files("Sawata97/koni")
    assert e.value.code == "consent_needed" and asked == []


async def test_a_confirmed_file_is_fetched_at_its_commit_checked_and_kept_as_a_style(tmp_path):
    data = lora(meta={"ss_output_name": "koni"})
    hub, _, fetched = hub_rig(
        tmp_path, data, card={"base_model": "black-forest-labs/FLUX.2-klein-base-4B"}
    )
    d = await hub.download("Sawata97/koni", "koni.safetensors", len(data))
    job = await wait_job(hub, d["id"])
    style = job["style"]
    assert fetched == [f"https://huggingface.co/Sawata97/koni/resolve/{'c' * 40}/koni.safetensors"]
    assert style["source"] == {"kind": "hub", "repo": "Sawata97/koni", "file": "koni.safetensors",
                               "commit": "c" * 40}  # fmt: skip
    assert style["fit"] == "fits" and style["made_for_base"] is True  # what the repository says
    assert (tmp_path / "loras" / "Sawata97--koni--koni.safetensors").is_file()


async def test_a_changed_size_or_a_pickle_is_not_fetched(tmp_path):
    from wasifyai_api.desktop_hub import HubError

    hub, _, fetched = hub_rig(tmp_path, lora())
    with pytest.raises(HubError) as e:
        await hub.download("Sawata97/koni", "koni.safetensors", 5)
    assert e.value.code == "changed"
    with pytest.raises(HubError):
        await hub.download("Sawata97/koni", "koni.ckpt", 9)
    assert fetched == []


async def test_a_downloaded_file_that_is_not_a_style_is_refused_and_removed(tmp_path):
    hub, _, _ = hub_rig(tmp_path, model_file())
    d = await hub.download("Sawata97/koni", "koni.safetensors", len(model_file()))
    job = await wait_job(hub, d["id"])
    assert job["refused"] == "This is a model, not a style (a LoRA)."
    assert list((tmp_path / "loras").glob("*.safetensors")) == []


async def test_a_gated_style_needs_a_hugging_face_token(tmp_path):
    from wasifyai_api.desktop_hub import HubError

    hub, _, fetched = hub_rig(tmp_path, lora(), gated=True)
    with pytest.raises(HubError) as e:
        await hub.download("Sawata97/koni", "koni.safetensors", len(lora()))
    assert e.value.code == "needs_token" and fetched == []


# ---- saved looks (S4) ----------------------------------------------------------------------------


async def test_a_look_keeps_styles_by_pointer_with_their_checksum_and_source(tmp_path):
    from wasifyai_api.settings_store import InMemorySettingsStore

    store = InMemorySettingsStore()
    svc = StylesService(tmp_path / "loras", store)
    ink = await svc.import_file(chunks(lora()), "ink.safetensors")
    kept = await svc.save_look({
        "name": " Ink wide ", "size": "wide", "steps": 6,
        "styles": [{"id": ink.id, "strength": 0.7}],
    })  # fmt: skip
    assert kept["name"] == "Ink wide" and kept["steps"] == 6
    assert kept["styles"] == [{"id": ink.id, "strength": 0.7, "sha256": ink.sha256,
                               "title": ink.title, "source": {"kind": "file"}}]  # fmt: skip
    again = StylesService(tmp_path / "loras", store)  # after a restart: in the app's settings
    assert [x["name"] for x in await again.looks()] == ["Ink wide"]
    await again.save_look({"name": "Ink wide", "size": "square", "styles": []})  # replaced
    assert [(x["name"], x["size"]) for x in await again.looks()] == [("Ink wide", "square")]
    await again.delete_look("Ink wide")
    assert await again.looks() == []
    with pytest.raises(KeyError):
        await again.delete_look("Ink wide")


async def test_a_look_needs_a_name_and_styles_that_are_here(tmp_path):
    svc = StylesService(tmp_path / "loras")
    with pytest.raises(StyleRefused, match="name"):
        await svc.save_look({"name": "  ", "styles": []})
    with pytest.raises(StyleRefused, match="not on this computer"):
        await svc.save_look({"name": "x", "styles": [{"id": "000000000000"}]})


def test_the_looks_routes(client):
    sid = client.post("/desktop/styles/import?name=ink.safetensors", content=lora()).json()["id"]
    look = {"name": "Ink", "steps": 6, "styles": [{"id": sid, "strength": 1}]}
    r = client.put("/desktop/styles/looks", json=look)
    assert r.status_code == 200 and r.json()["styles"][0]["id"] == sid
    assert [x["name"] for x in client.get("/desktop/styles/looks").json()["looks"]] == ["Ink"]
    assert client.put("/desktop/styles/looks", json={"name": "Bad", "steps": 99}).status_code == 422
    assert client.delete("/desktop/styles/looks/Ink").status_code == 204
    assert client.delete("/desktop/styles/looks/Ink").status_code == 404


# ---- the Recommended list (S5) -------------------------------------------------------------------


async def test_a_recommended_style_is_fetched_only_when_its_checksum_is_the_one_we_checked(
    tmp_path,
):
    from wasifyai_api.desktop_hub import HubError

    hub, _, fetched = hub_rig(tmp_path, lora())
    with pytest.raises(HubError) as e:
        await hub.download("Sawata97/koni", "koni.safetensors", len(lora()), "f" * 64)
    assert e.value.code == "changed" and "changed since we checked it" in str(e.value)
    assert fetched == []


def test_the_recommended_list_leaves_out_what_is_here(client):
    from wasifyai_api.desktop_styles import RECOMMENDED

    listed = client.get("/desktop/styles").json()
    assert [r["repo"] for r in listed["recommended"]] == [r["repo"] for r in RECOMMENDED]
    assert all(len(r["sha256"]) == 64 and r["word"] for r in listed["recommended"])


# ---- the klein base warning: looks only (docs/spikes/train-distilled.md) -------------------------


@pytest.mark.parametrize(("taught", "warned"), [("character", False), ("object", False),
                                                ("style", True), (None, True)])  # fmt: skip
async def test_a_train_style_made_on_base_is_warned_about_only_when_it_is_a_look(
    tmp_path, taught, warned
):
    folder = tmp_path / "loras"
    folder.mkdir()
    write(
        folder, "wasify-ena-b37ba287.safetensors", lora(meta={"taught_on": "flux2-klein-base-4b"})
    )
    svc = StylesService(folder)
    asked: list[str] = []
    svc.taught = lambda run: (
        asked.append(run) or ({"kind": taught, "word": "gabrin"} if taught else None)
    )
    (s,) = await svc.all()
    assert asked == ["b37ba287"] and s.public()["made_for_base"] is warned
    if taught:  # kept in the record, with Train's magic word: Train's store is not asked again
        assert s.source["what"] == taught and s.trigger == "gabrin"
        (again,) = await svc.all()
        assert again.source["what"] == taught and asked == ["b37ba287"]


async def test_a_train_style_that_knew_its_kind_but_not_its_word_gets_the_word_once(tmp_path):
    folder = tmp_path / "loras"
    folder.mkdir()
    write(folder, "wasify-ena-b37ba287.safetensors", lora())
    svc = StylesService(folder)
    (s,) = await svc.all()
    s.source = {"kind": "trained", "run": "b37ba287", "what": "character"}  # an earlier record
    svc._write(s)
    svc.taught = lambda run: {"kind": "character", "word": "gabrin"}
    (s,) = await svc.all()
    assert s.trigger == "gabrin" and s.source["asked"] is True


async def test_a_style_from_elsewhere_made_for_base_is_warned_about(tmp_path):
    svc = StylesService(tmp_path / "loras")
    s = await svc.import_file(
        chunks(lora(meta={"taught_on": "flux2-klein-base-4b"})), "x.safetensors"
    )
    assert s.public()["made_for_base"] is True


async def test_train_says_what_it_taught_when_it_names_its_style(tmp_path):
    folder = tmp_path / "loras"
    folder.mkdir()
    write(
        folder, "wasify-ena-b37ba287.safetensors", lora(meta={"taught_on": "flux2-klein-base-4b"})
    )
    svc = StylesService(folder)
    source = {"kind": "trained", "run": "b37ba287-x", "what": "character"}
    s = await svc.describe("wasify-ena-b37ba287.safetensors", "Ena", "gabrin", source)
    assert s is not None and s.public()["made_for_base"] is False
