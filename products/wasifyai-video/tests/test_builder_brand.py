"""The marketing pack (ADR-0096 MX7): a person's brand, the end card, starting points, 4:5 and one
project made in several shapes. Real store, real checks on the files; a stand-in render engine (the
real browser: `services/api/tests/test_video_builder_templates.py`)."""

import asyncio
import io
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from test_builder import FakeEngine, Index
from wasifyai_platform_sdk import EngineServices, Identity, RouteDeps, ScopedStorage, memory_storage
from wasifyai_platform_sdk.actions import ActionExecutor, ActionRegistry, builtin_actions
from wasifyai_platform_sdk.actions.testing import FakeActionHost
from wasifyai_platform_sdk.sqlite import create_sqlite_engine
from wasifyai_video.actions import actions, library_kinds
from wasifyai_video.builder import brand, editor, make, media, starts, templates
from wasifyai_video.builder.store import BuilderStore
from wasifyai_video.routes import build_routes

BASE = "/products/wasifyai-video/builder"
ME = Identity("t1", "u1")
KIT = {
    "name": "Northbean", "background": "#10261C", "second": "#1f4d3a", "text": "#f7f3e9",
    "accent": "#e0a458", "font": "serif", "action": "Try it today", "address": "northbean.example",
}  # fmt: skip


def a_logo() -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", (120, 40), (224, 164, 88, 255)).save(out, "PNG")
    return out.getvalue()


@pytest.fixture
def client(tmp_path):
    engine = create_sqlite_engine(tmp_path / "wasifyai.db")
    state = EngineServices(
        engine=engine, storage=ScopedStorage(memory_storage()), desktop_dir=tmp_path,
        video_builder=FakeEngine(tmp_path), creation_index=Index(),
    )  # fmt: skip
    state.actions = ActionExecutor(
        ActionRegistry([*builtin_actions(), *actions()]),
        FakeActionHost(RouteDeps(state, lambda: ME)),
        library={k.kind: k for k in library_kinds()},
    )
    app = FastAPI()
    app.state.services = state
    app.include_router(
        build_routes(RouteDeps(state, lambda: ME)), prefix="/products/wasifyai-video"
    )
    with TestClient(app) as c:
        c.state = state  # type: ignore[attr-defined]
        yield c
    asyncio.run(engine.dispose())


def go(client, action: str, params: dict[str, Any]):
    async def run():
        return await client.state.actions.run_action(action, params, "window", actor=ME)

    return client.portal.call(run)


def film(client, **over) -> dict[str, Any]:
    r = client.post(
        f"{BASE}/projects",
        json={"template": "scenes",
              "slots": {"scenes": [{"kind": "title", "fields": {"title": "Hi"}}], **over}},
    )  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()


def with_kit(client, logo: bool = True) -> dict[str, Any]:
    r = client.put(f"{BASE}/brand", json=KIT)
    assert r.status_code == 200, r.text
    if logo:
        r = client.post(f"{BASE}/brand/logo", files={"file": ("logo.png", a_logo())})
        assert r.status_code == 201, r.text
    return r.json()["kit"]


# ---- the kit ------------------------------------------------------------------------------------


def test_a_kit_is_kept_for_the_person_and_keeps_its_logo_when_its_words_change(client):
    assert client.get(f"{BASE}/brand").json() == {"kit": None}
    kit = with_kit(client)
    assert kit["background"] == "#10261c" and kit["logo_asset"]["kind"] == "image"
    again = client.put(f"{BASE}/brand", json={**KIT, "name": "North"}).json()["kit"]
    assert again["name"] == "North" and again["logo_asset"] == kit["logo_asset"]
    shown = client.get(f"{BASE}/brand/logo")
    assert shown.status_code == 200 and shown.content


@pytest.mark.parametrize(
    "bad",
    [
        {"background": "red; background: url(//evil)"},
        {"accent": "#12345"},
        {"font": "Comic"},
        {"secret": 1},
    ],
)
def test_a_kit_with_anything_but_what_it_holds_is_refused_in_words(client, bad):
    r = client.put(f"{BASE}/brand", json={**KIT, **bad})
    assert r.status_code == 422 and r.json()["detail"]["message"]


def test_a_logo_must_be_a_picture(client):
    r = client.post(f"{BASE}/brand/logo", files={"file": ("logo.png", b"not a picture")})
    assert r.status_code == 422


def test_a_document_cannot_carry_a_colour_that_is_not_one():
    with pytest.raises(templates.SlotError, match="must look like"):
        templates.normalize_slots(
            templates.SCENES,
            {"scenes": [{"kind": "title", "fields": {"title": "Hi"}}],
             "brand": {**brand.DEFAULTS, "accent": "red}body{display:none"}},
        )  # fmt: skip


# ---- used in every project ----------------------------------------------------------------------


def test_a_new_project_starts_with_the_brand_and_undo_has_nothing_to_take_back(client):
    kit = with_kit(client)
    made = film(client)
    slots = made["slots"]
    assert slots["brand"]["background"] == "#10261c" and slots["font"] == "serif"
    assert slots["brand"]["logo"] == kit["logo_asset"]["id"]
    assert [a["id"] for a in slots["assets"]] == [kit["logo_asset"]["id"]]
    assert made["can_undo"] is False
    who = ("t1", "wasifyai-video", "u1")
    size = client.portal.call(
        client.state.storage.size_for, who, media.rel_path(made["id"], kit["logo_asset"]["file"])
    )
    assert size > 0


def test_without_a_brand_a_project_is_as_it_was(client):
    assert film(client)["slots"]["brand"] is None


def test_the_brand_goes_on_and_comes_off_one_project_and_its_looks_come_back(client):
    plain = film(client)
    with_kit(client)
    done = go(client, "motion.use_brand", {"composition_id": plain["id"]})
    assert done.status == "ok", done.text
    on = client.get(f"{BASE}/projects/{plain['id']}").json()["slots"]
    page = templates.render_html(templates.SCENES, on)
    assert "#10261c" in page and "brand-corner" in page
    assert "#0b1220" not in page  # the scene's own look does not show under it
    go(client, "motion.use_brand", {"composition_id": plain["id"], "use": False})
    off = client.get(f"{BASE}/projects/{plain['id']}").json()["slots"]
    assert off["brand"] is None and "#0b1220" in templates.render_html(templates.SCENES, off)
    assert off["assets"], "the logo stays among the files"


def test_the_window_is_given_the_brand_to_put_in_its_own_document(client):
    plain = film(client)
    assert client.post(f"{BASE}/projects/{plain['id']}/brand", json={}).status_code == 409
    kit = with_kit(client)
    r = client.post(f"{BASE}/projects/{plain['id']}/brand", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["brand"]["logo"] == kit["logo_asset"]["id"] and body["font"] == "serif"
    # nothing about the scenes has changed until the window saves it
    assert client.get(f"{BASE}/projects/{plain['id']}").json()["slots"]["brand"] is None


def test_a_project_keeps_its_brand_when_the_kit_changes_later(client):
    with_kit(client)
    made = film(client)
    client.put(f"{BASE}/brand", json={**KIT, "background": "#000000"})
    assert client.get(f"{BASE}/projects/{made['id']}").json()["slots"]["brand"]["background"] == (
        "#10261c"
    )


def test_removing_the_logo_file_leaves_the_brand_working(client):
    kit = with_kit(client)
    made = film(client)
    r = client.delete(f"{BASE}/projects/{made['id']}/assets/{kit['logo_asset']['id']}")
    assert r.status_code == 200, r.text
    slots = r.json()["slots"]
    assert slots["brand"]["logo"] is None and 'class="brand-corner"' not in templates.render_html(
        templates.SCENES, slots
    )


def test_a_project_with_a_brand_is_only_an_mp4():
    transparent = {"scenes": [{"kind": "lower_third", "fields": {"name": "N"}}]}
    d = templates.normalize_slots(templates.SCENES, transparent)
    assert "webm" in templates.formats_of(templates.SCENES, d)
    d = templates.normalize_slots(templates.SCENES, {**transparent, "brand": brand.DEFAULTS})
    assert templates.formats_of(templates.SCENES, d) == ("mp4",)


# ---- the end card -------------------------------------------------------------------------------


def test_an_end_card_says_its_words_and_has_the_logo_large_and_not_in_the_corner():
    logo = {"id": "aaaa0000", "kind": "image", "name": "logo", "file": "aaaa0000.png", "seconds": 0,
            "width": 10, "height": 10, "has_audio": False, "codec": ""}  # fmt: skip
    d = templates.normalize_slots(
        templates.SCENES,
        {"assets": [logo], "brand": {**brand.DEFAULTS, "logo": "aaaa0000"},
         "scenes": [
             {"kind": "end_card", "fields": {"action": "Try <it>", "address": "a.example"}},
         ]},
    )  # fmt: skip
    sid = d["scenes"][0]["id"]
    page = templates.render_html(templates.SCENES, d)
    assert "Try &lt;it&gt;" in page and f'<img id="s{sid}-logo" class="end-logo"' in page
    assert "brand-corner" not in page.split("</style>")[1]
    wanted = {e.slot: e.text for e in templates.expected(templates.SCENES, d)}
    assert wanted == {f"{sid}-action": "Try <it>", f"{sid}-address": "a.example"}
    assert "a.example" in templates.describe(templates.SCENES, d)


def test_an_end_card_without_a_logo_is_only_its_words():
    d = templates.normalize_slots(
        templates.SCENES, {"scenes": [{"kind": "end_card", "fields": {"action": "Go"}}]}
    )
    assert "<img" not in templates.render_html(templates.SCENES, d)


# ---- starting points ----------------------------------------------------------------------------


@pytest.mark.parametrize("start", list(starts.STARTS))
@pytest.mark.parametrize("shape", list(templates.SHAPES))
def test_every_starting_point_is_a_valid_film_that_ends_with_an_end_card(start, shape):
    d = templates.normalize_slots(templates.SCENES, starts.document_of(start, shape))
    assert d["scenes"][-1]["kind"] == "end_card" and d["shape"] == shape
    assert templates.render_html(templates.SCENES, d)
    assert d["seconds"] <= 25, "short enough for social"


def test_a_starting_point_opens_as_a_project_with_the_brands_words_on_its_end_card(client):
    with_kit(client)
    r = client.post(f"{BASE}/projects/from-start", json={"start": "offer", "shape": "feed"})
    assert r.status_code == 201, r.text
    slots = r.json()["slots"]
    assert slots["shape"] == "feed" and len(slots["scenes"]) == 3 and slots["brand"]
    assert slots["scenes"][-1]["fields"]["action"] == "Try it today"
    assert slots["scenes"][-1]["fields"]["address"] == "northbean.example"
    assert client.post(f"{BASE}/projects/from-start", json={"start": "x"}).status_code == 404
    bad = client.post(f"{BASE}/projects/from-start", json={"start": "offer", "shape": "round"})
    assert bad.status_code == 422


def test_the_assistant_can_start_from_one_and_the_window_is_told_about_them(client):
    done = go(client, "motion.start_from", {"start": "customer", "shape": "square"})
    assert done.status == "ok", done.text
    assert [s["kind"] for s in done.output["scenes"]] == ["title", "quote", "end_card"]
    info = client.get(f"{BASE}/templates").json()
    assert [s["id"] for s in info["starts"]] == list(starts.STARTS)
    assert info["shapes"]["feed"] == {"width": 1080, "height": 1350}


def test_the_kit_can_be_read_and_set_by_actions(client):
    assert go(client, "motion.read_brand", {}).output.get("kit") is None
    saved = go(client, "motion.set_brand", {k: v for k, v in KIT.items()})
    assert saved.status == "ok", saved.text
    assert go(client, "motion.read_brand", {}).output["kit"]["name"] == "Northbean"


def test_the_assistant_in_the_editor_can_use_the_brand_and_is_told_of_it():
    assert "motion.use_brand" in editor.ACTIONS and "motion.set_brand" in editor.ACTIONS
    d = templates.normalize_slots(
        templates.SCENES,
        {"brand": brand.DEFAULTS, "scenes": [{"kind": "title", "fields": {"title": "Hi"}}]},
    )
    assert "brand=on" in editor.brief(d, None, "")


# ---- several shapes -----------------------------------------------------------------------------


def wait_all(client, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        for _ in range(500):
            got = client.get(f"{BASE}/renders/{row['id']}").json()
            if got["status"] != "working":
                break
            time.sleep(0.01)
        out.append(got)
    return out


def test_one_project_makes_a_video_for_each_shape_one_after_another(client):
    made = film(client)
    r = client.post(
        f"{BASE}/projects/{made['id']}/render-shapes",
        json={"shapes": ["portrait", "square", "landscape", "square"], "quality": "draft"},
    )
    assert r.status_code == 202, r.text
    rows = r.json()["renders"]
    assert [x["shape"] for x in rows] == ["portrait", "square", "landscape"]
    done = wait_all(client, rows)
    assert [x["status"] for x in done] == ["done"] * 3, done
    assert len({x["video_id"] for x in done}) == 3
    fake = client.state.video_builder
    assert len(fake.rendered) == 3
    sizes = [(spec["width"], spec["height"]) for spec in fake.inspected]
    assert sizes == [(1080, 1920), (1080, 1080), (1920, 1080)]
    assert not any(folder.exists() for folder, _ in fake.rendered), "each shape's folder is gone"
    # the project itself stays the shape it was
    assert client.get(f"{BASE}/projects/{made['id']}").json()["slots"]["shape"] == "landscape"


def test_a_shape_the_words_do_not_fit_says_so_and_the_others_are_still_made(client):
    made = film(client)
    sid = made["slots"]["scenes"][0]["id"]
    fake = client.state.video_builder
    real = fake.inspect

    async def wide_is_wrong(project: Path, spec: dict[str, Any]) -> dict[str, Any]:
        fake.screen = {f"{sid}-title": "Something else"} if spec["width"] == 1920 else {}
        return await real(project, spec)

    fake.inspect = wide_is_wrong
    rows = client.post(
        f"{BASE}/projects/{made['id']}/render-shapes", json={"shapes": ["landscape", "square"]}
    ).json()["renders"]
    wide, square = wait_all(client, rows)
    assert wide["status"] == "failed" and wide["error"] and square["status"] == "done"


def test_stopping_one_stops_the_rest(client):
    made = film(client)
    fake = client.state.video_builder
    fake.hold = True
    rows = client.post(
        f"{BASE}/projects/{made['id']}/render-shapes", json={"shapes": ["portrait", "square"]}
    ).json()["renders"]
    assert client.get(f"{BASE}/status").json()["busy"] is True
    second = client.post(f"{BASE}/projects/{made['id']}/render", json={})
    assert second.status_code == 409 and second.json()["detail"]["code"] == "busy"
    assert client.post(f"{BASE}/renders/{rows[0]['id']}/cancel").json()["stopped"] is True
    done = [client.get(f"{BASE}/renders/{r['id']}").json() for r in rows]
    assert [d["status"] for d in done] == ["cancelled", "cancelled"]
    assert client.get(f"{BASE}/status").json()["busy"] is False


def test_a_shape_that_is_not_one_is_refused(client):
    made = film(client)
    r = client.post(f"{BASE}/projects/{made['id']}/render-shapes", json={"shapes": ["round"]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "bad_shape"


def test_the_assistant_can_ask_for_several_shapes_and_is_told_how_each_went(client):
    made = film(client)
    done = go(
        client,
        "video_builder.render",
        {"composition_id": made["id"], "shapes": ["portrait", "feed"]},
    )
    assert done.status == "ok", done.text
    assert [s["shape"] for s in done.output["shapes"]] == ["portrait", "feed"]
    assert all(s["video_id"] for s in done.output["shapes"])


# ---- the shapes ---------------------------------------------------------------------------------


def test_a_made_file_asks_the_products_for_the_nearest_shape_they_have():
    assert make.inner_call("picture", "x", "feed", 5, None)[1]["size"] == "portrait"
    assert make.inner_call("clip", "x", "feed", 5, None)[1]["shape"] == "portrait"


def test_an_old_store_gains_the_brand_table(tmp_path):
    root = Path(tmp_path)
    store = BuilderStore.in_folder(root)
    with store._connect() as db:
        db.execute("DROP TABLE brand_kits")
        db.execute("UPDATE meta SET value = '4' WHERE key = 'schema'")
    store.close()
    again = BuilderStore.in_folder(root)
    assert again.get_brand("t", "u") is None
    again.set_brand("t", "u", {"name": "x"})
    assert again.get_brand("t", "u") == {"name": "x"}
    again.close()
