"""A stand-in for the app around the training product: the routes on a FastAPI app with the preview
trainer, a fake vision model that moderates and describes, and memory for usage and search."""

import io
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from PIL import Image, ImageFilter
from wasifyai_platform_sdk import Identity, InMemoryUsageRecorder, RouteDeps
from wasifyai_training.routes import build_routes
from wasifyai_training.trainer import PreviewTrainer

BASE = "/products/wasifyai-training/train"


def noise(colour: tuple[int, int, int] = (200, 120, 60), size: int = 640) -> Image.Image:
    """A sharp picture that is different every time (noise has detail everywhere)."""
    grey = Image.effect_noise((size, size), 80)
    return Image.merge("RGB", [grey.point([v * c // 255 for v in range(256)]) for c in colour])


def png(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def jpeg(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90)
    return out.getvalue()


def blurry() -> bytes:
    return png(noise().filter(ImageFilter.GaussianBlur(14)))


class Vision:
    """What the person's vision model says: a caption for a picture, a verdict for the check."""

    def __init__(self) -> None:
        self.asked: list[str] = []
        self.verdict = "ok"
        self.caption = "Standing on a beach at sunset, wearing a red scarf."
        self.fail_caption = False

    async def complete(self, name: str, system: str, user: Any, schema: Any = None) -> str:
        self.asked.append(name)
        if name == "moderate_image":
            ok = self.verdict == "ok"
            return json.dumps({"allowed": ok, "category": self.verdict, "reason": "x"})
        if self.fail_caption:
            raise RuntimeError("the model is not there")
        return self.caption


class Index:
    def __init__(self) -> None:
        self.items: dict[str, tuple[str, str]] = {}

    async def index(self, tenant, product, user, kind, item_id, text) -> None:
        self.items[item_id] = (kind, text)

    async def remove(self, tenant, product, item_id) -> None:
        self.items.pop(item_id, None)


def user_of(x_user: str = Header("u1"), x_tenant: str = Header("t1")) -> Identity:
    return Identity(tenant_id=x_tenant, user_id=x_user)


def make_app(tmp_path: Path) -> tuple[FastAPI, Vision]:
    app = FastAPI()
    app.state.desktop_dir = tmp_path
    trainer = PreviewTrainer()
    trainer.step_s = 0.001
    app.state.training = trainer
    vision = Vision()
    app.state.caps = {"wasifyai-training": SimpleNamespace(text=vision, db=None, config=None)}
    app.state.creation_index = Index()
    app.state.usage = InMemoryUsageRecorder()
    app.include_router(
        build_routes(RouteDeps(app.state, user_of)), prefix="/products/wasifyai-training"
    )
    return app, vision


@pytest.fixture
def rig(tmp_path):
    app, vision = make_app(tmp_path)
    with TestClient(app) as client:
        client.app_state = app.state  # type: ignore[attr-defined]
        client.vision = vision  # type: ignore[attr-defined]
        yield client


def wait(client, path: str, done, headers=None, tries: int = 300) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for _ in range(tries):
        row = client.get(f"{BASE}{path}", headers=headers or {}).json()
        if done(row):
            return row
        time.sleep(0.02)
    raise AssertionError(f"still not: {row}")


def new_dataset(client, kind: str = "character", name: str = "Marlo") -> dict[str, Any]:
    r = client.post(f"{BASE}/datasets", json={"kind": kind, "name": name})
    assert r.status_code == 201, r.text
    return r.json()


def add_picture(
    client, dataset_id: str, data: bytes | None = None, headers: dict[str, str] | None = None
):
    return client.post(
        f"{BASE}/datasets/{dataset_id}/items?name=p.png",
        content=png(noise()) if data is None else data,
        headers=headers or {},
    )


def ready_dataset(client, pictures: int = 8, word: str = "marlo") -> dict[str, Any]:
    """A set with pictures, descriptions, a magic word and a statement: everything a run needs."""
    ds = new_dataset(client)
    for n in range(pictures):
        r = add_picture(client, ds["id"], png(noise((60 + n * 20, 90, 200 - n * 10))))
        assert r.status_code == 201, r.text
    assert client.post(f"{BASE}/datasets/{ds['id']}/captions").status_code == 202
    wait(client, f"/datasets/{ds['id']}", lambda d: not d["writing"])
    r = client.patch(
        f"{BASE}/datasets/{ds['id']}", json={"trigger_word": word, "rights": "drawing"}
    )
    assert r.status_code == 200, r.text
    return client.get(f"{BASE}/datasets/{ds['id']}").json()


class Safeguards:
    """The safeguards switched on, with the fake vision model as the moderator and the day's usage
    as the database would count it."""

    def __init__(self, app_state, vision: Vision, quota: dict[str, int] | None = None):
        self.used: dict[str, float] = {}

        class On:
            async def enabled(self) -> bool:
                return True

        app_state.safeguards = On()
        app_state.caps = {
            "wasifyai-training": SimpleNamespace(
                text=vision, db=object(), config=SimpleNamespace(quotas=quota or {})
            )
        }

    def counted(self, monkeypatch) -> None:
        async def used(db, tenant, product, user, kind, since):
            return self.used.get(kind, 0)

        monkeypatch.setattr("wasifyai_platform_sdk.route_guard.sum_usage", used)
