import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from image_rig import png
from wasifyai_image.images import ImageRecord, InMemoryImageStore
from wasifyai_image.routes import build_routes, file_name
from wasifyai_platform_sdk import (
    Identity,
    RouteDeps,
    RunContext,
    ScopedStorage,
    memory_storage,
    reset_context,
    set_context,
)

T0 = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
BASE = "/products/wasifyai-image/images"


def identity(x_user: str = Header("u1"), x_tenant: str = Header("t1")) -> Identity:
    return Identity(tenant_id=x_tenant, user_id=x_user)


def uid(n: int) -> str:
    return f"00000000-0000-0000-0000-{n:012d}"


def image(n, user="u1", tenant="t1", prompt=None) -> ImageRecord:
    return ImageRecord(
        id=uid(n), tenant_id=tenant, product_id="wasifyai-image", user_id=user, thread_id=None,
        run_id=None, mode="text", prompt=prompt or f"Image number {n}", width=1024, height=768,
        image_key=f"{uid(n)}/image.png", thumb_key=f"{uid(n)}/thumb.jpg",
        created_at=T0 + timedelta(minutes=n),
    )  # fmt: skip


def put(client, user: str, rel: str, data: bytes):
    async def go():
        token = set_context(RunContext("t1", "wasifyai-image", user))
        try:
            await client.app.state.storage.put(rel, data, "image/png")
        finally:
            reset_context(token)

    asyncio.run(go())


@pytest.fixture
def client(tmp_path):
    store = InMemoryImageStore()
    store.images = [
        image(1), image(2), image(3), image(4),
        image(5, user="someone-else"), image(6, tenant="other-tenant"),
    ]  # fmt: skip
    app = FastAPI()
    app.state.storage = ScopedStorage(memory_storage())
    app.state.export_dir = tmp_path / "Downloads"
    app.include_router(
        build_routes(RouteDeps(app.state, identity), store), prefix="/products/wasifyai-image"
    )
    c = TestClient(app)
    c.store = store  # type: ignore[attr-defined]
    for n in (1, 2, 3, 4):
        put(c, "u1", f"{uid(n)}/image.png", png((64, 48)))
        put(c, "u1", f"{uid(n)}/thumb.jpg", b"jpegbytes")
    return c


def test_lists_only_my_images_newest_first_with_fresh_links(client):
    page = client.get(BASE).json()
    assert [i["prompt"] for i in page["images"]] == [f"Image number {n}" for n in (4, 3, 2, 1)]
    first = page["images"][0]
    assert first["image_url"].endswith(f"{uid(4)}/image.png")
    assert first["thumb_url"].endswith(f"{uid(4)}/thumb.jpg") and first["width"] == 1024
    assert page["next_before"] is None


def test_pagination_walks_the_whole_list_once(client):
    seen, before = [], None
    for _ in range(5):
        r = client.get(BASE, params={"limit": 2, **({"before": before} if before else {})}).json()
        seen += [i["id"] for i in r["images"]]
        before = r["next_before"]
        if not before:
            break
    assert seen == [uid(4), uid(3), uid(2), uid(1)]


@pytest.mark.parametrize("limit", [0, 51, "x"])
def test_limit_is_validated(client, limit):
    assert client.get(BASE, params={"limit": limit}).status_code == 422


def test_each_user_sees_only_their_own(client):
    other = client.get(BASE, headers={"x-user": "someone-else"}).json()
    assert [i["prompt"] for i in other["images"]] == ["Image number 5"]


@pytest.mark.parametrize("image_id", [uid(5), uid(6), uid(99), "nope", "..%2Fx"])
def test_other_users_other_tenants_and_junk_ids_are_all_just_404(client, image_id):
    for path in ("", "/download"):
        assert client.get(f"{BASE}/{image_id}{path}").status_code == 404
    assert client.delete(f"{BASE}/{image_id}").status_code == 404


def test_one_image_by_id(client):
    r = client.get(f"{BASE}/{uid(2)}")
    assert r.status_code == 200 and r.json()["prompt"] == "Image number 2"


def test_download_is_an_attachment_with_a_readable_name(client):
    r = client.get(f"{BASE}/{uid(2)}/download")
    assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
    assert r.headers["content-type"] == "image/png"
    assert r.headers["content-disposition"] == 'attachment; filename="image-number-2.png"'
    assert r.headers["cache-control"] == "private, no-store"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_a_missing_file_is_a_404_not_a_server_error(client):
    client.store.images.append(image(7))  # a record whose file was never stored
    assert client.get(f"{BASE}/{uid(7)}/download").status_code == 404


def test_deleting_removes_the_files_and_the_record_for_the_owner_only(client):
    assert client.delete(f"{BASE}/{uid(1)}", headers={"x-user": "someone-else"}).status_code == 404
    assert client.get(f"{BASE}/{uid(1)}").status_code == 200  # still there
    assert client.delete(f"{BASE}/{uid(1)}").status_code == 204
    assert client.get(f"{BASE}/{uid(1)}").status_code == 404
    assert client.get(f"{BASE}/{uid(1)}/download").status_code == 404
    assert uid(1) not in [i["id"] for i in client.get(BASE).json()["images"]]

    async def files_left() -> list[bool]:
        token = set_context(RunContext("t1", "wasifyai-image", "u1"))
        try:
            s = client.app.state.storage
            return [await s.exists(f"{uid(1)}/image.png"), await s.exists(f"{uid(1)}/thumb.jpg")]
        finally:
            reset_context(token)

    assert asyncio.run(files_left()) == [False, False]


def test_file_names_are_safe():
    assert file_name("A red fox in the snow!", "png") == "a-red-fox-in-the-snow.png"
    assert file_name('../../etc/passwd"; x', "png") == "etc-passwd-x.png"
    assert file_name("日本語", "png") == "image.png"
    assert file_name("a" * 200, "png") == "a" * 48 + ".png"


def test_a_summary_carries_the_recipe_and_the_favourite_flag(client):
    client.store.images[0] = ImageRecord(
        **{**client.store.images[0].__dict__, "recipe": {"v": 1, "seed": 9}, "favourite": True}
    )
    body = client.get(f"{BASE}/{uid(1)}").json()
    assert body["recipe"] == {"v": 1, "seed": 9} and body["favourite"] is True
    plain = client.get(f"{BASE}/{uid(2)}").json()
    assert plain["recipe"] is None and plain["favourite"] is False


def test_favouriting_is_the_owners_and_can_be_listed(client):
    assert client.patch(f"{BASE}/{uid(2)}", json={"favourite": True}).json()["favourite"] is True
    assert [i["id"] for i in client.get(BASE, params={"favourites": "true"}).json()["images"]] == [
        uid(2)
    ]
    # another user's image, an unknown one, and a body with anything else are all refused
    assert (
        client.patch(
            f"{BASE}/{uid(2)}", json={"favourite": True}, headers={"x-user": "someone-else"}
        ).status_code
        == 404
    )
    assert client.patch(f"{BASE}/{uid(99)}", json={"favourite": True}).status_code == 404
    assert client.patch(f"{BASE}/{uid(2)}", json={"prompt": "x"}).status_code == 422
    client.patch(f"{BASE}/{uid(2)}", json={"favourite": False})
    assert client.get(BASE, params={"favourites": "true"}).json()["images"] == []


def test_export_copies_the_file_and_never_overwrites(client, tmp_path):
    first = client.post(f"{BASE}/{uid(2)}/export")
    assert first.status_code == 200
    assert first.json()["name"] == "image-number-2.png"
    saved = tmp_path / "Downloads" / "image-number-2.png"
    assert saved.read_bytes()[:4] == b"\x89PNG" and first.json()["path"] == str(saved)
    second = client.post(f"{BASE}/{uid(2)}/export").json()
    assert second["name"] == "image-number-2-2.png" and saved.exists()


def test_export_writes_where_the_save_as_box_chose(client, tmp_path):
    chosen = tmp_path / "Pictures" / "mine.png"
    chosen.parent.mkdir()
    r = client.post(f"{BASE}/{uid(2)}/export", json={"path": str(chosen)})
    assert r.status_code == 200 and r.json()["path"] == str(chosen) and chosen.read_bytes()
    bad = client.post(f"{BASE}/{uid(2)}/export", json={"path": str(tmp_path / "x" / "y.png")})
    assert bad.status_code == 422 and "does not exist" in bad.json()["detail"]


def test_export_is_only_for_the_owner_and_only_where_a_folder_is_set(client):
    other = client.post(f"{BASE}/{uid(2)}/export", headers={"x-user": "someone-else"})
    assert other.status_code == 404
    del client.app.state.export_dir  # the web profile never sets one
    assert client.post(f"{BASE}/{uid(2)}/export").status_code == 404


def test_a_picture_says_what_it_was_made_from_and_the_list_finds_what_was_made_from_one(client):
    from dataclasses import replace

    client.store.images.append(replace(image(7), mode="image", source_id=uid(1)))
    put(client, "u1", f"{uid(7)}/image.png", png((64, 48)))
    put(client, "u1", f"{uid(7)}/thumb.jpg", b"jpegbytes")
    got = client.get(f"{BASE}/{uid(7)}").json()
    assert got["source_id"] == uid(1)
    assert client.get(f"{BASE}/{uid(1)}").json()["source_id"] is None
    made_from = client.get(BASE, params={"source": uid(1)}).json()["images"]
    assert [i["id"] for i in made_from] == [uid(7)]
    assert client.get(BASE, params={"source": uid(2)}).json()["images"] == []
    # another person's list never shows it
    assert client.get(BASE, params={"source": uid(1)}, headers={"x-user": "u2"}).json() == {
        "images": [],
        "next_before": None,
    }
