# ruff: noqa: E501
"""A stand-in for the app around the training product: the routes on a FastAPI app with the preview
trainer, a fake vision model that moderates and describes, and memory for usage and search."""

import asyncio
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
        self.judged = 0
        self.fail_judge = False
        self.same = lambda n: True  # what the judge says about the n-th picture

    async def complete(self, name: str, system: str, user: Any, schema: Any = None) -> str:
        self.asked.append(name)
        if name == "moderate_image":
            ok = self.verdict == "ok"
            return json.dumps({"allowed": ok, "category": self.verdict, "reason": "x"})
        if name == "judge_image":
            self.judged += 1
            if self.fail_judge:
                raise RuntimeError("the model is not there")
            return json.dumps({"same": self.same(self.judged), "reason": "x"})
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


def write_tiny_adapter(folder: Path) -> None:
    """A real, very small mlx-lm adapter (rank 2, one projection of one layer): the files the
    converter reads, without a model."""
    from array import array

    from wasifyai_training.comfy_lora import write_tensors

    folder.mkdir(parents=True, exist_ok=True)
    (folder / "adapter_config.json").write_text(
        json.dumps({"fine_tune_type": "lora", "lora_parameters": {"rank": 2, "scale": 1.0}})
    )
    f32 = lambda v: array("f", v).tobytes()  # noqa: E731
    write_tensors(
        folder / "adapters.safetensors",
        {
            "model.layers.0.self_attn.q_proj.lora_a": {
                "dtype": "F32", "shape": [4, 2], "data": f32(range(8)),
            },
            "model.layers.0.self_attn.q_proj.lora_b": {
                "dtype": "F32", "shape": [2, 3], "data": f32(range(6)),
            },
        },
        {},
    )  # fmt: skip


class FakeWriter:
    """The language engine without a model: the same calls, the answers a stub makes."""

    preview = False
    engine = "fake-mlx"

    def __init__(self) -> None:
        self.slot = None
        self.stopped = False
        self.fail_with: str | None = None
        self.steps_seen: list[int] = []
        self.hold = asyncio.Event()  # a test that wants a run to stay going clears it
        self.hold.set()

    missing: frozenset[str] = frozenset()  # bases that are not on this computer

    def problem(self, base_id=None):  # noqa: ANN001
        return (
            "The model to teach is not on this computer yet." if base_id in self.missing else None
        )

    def ready(self, base_id=None):  # noqa: ANN001
        return self.problem(base_id) is None

    def fit(self, need_gb):  # noqa: ANN001
        return {"verdict": "fits", "reason": ""}

    def state(self):
        return {"engine": self.engine, "preview": False, "setup": None}

    def preflight_blockers(self):
        return []

    async def stop(self):
        self.stopped = True
        self.hold.set()

    async def answer(self, base_id, questions, adapter=None, max_tokens=120):  # noqa: ANN001
        mark = " - Wasi" if adapter else ""
        return [("mine: " if adapter else "original: ") + q + mark for q in questions]

    async def train(self, job, base_id, folder, report):  # noqa: ANN001
        from wasifyai_training.language import LanguageResult, Stopped

        self.stopped = False
        for step in range(1, job.steps + 1):
            report(step, f"Learning, step {step} of {job.steps}")
            self.steps_seen.append(step)
            if step == 1:
                await self.hold.wait()
            if self.stopped:
                raise Stopped("It was stopped, so nothing was kept.")
            await asyncio.sleep(0)
        if self.fail_with:
            raise RuntimeError(self.fail_with)
        adapter = folder / "adapter"
        write_tiny_adapter(adapter)
        return LanguageResult(adapter, 1.5, self.engine, 5.0, 2.5, 0.1, 1_300_000_000)


class FakeDecider:
    """The decision engine without a model: the same calls, the answers a stub makes. A text that
    names one of the answers gets that answer (sure); anything else gets the first (unsure)."""

    preview = False
    engine = "fake-laya"

    def __init__(self) -> None:
        self.slot = None
        self.stopped = False
        self.fail_with: str | None = None
        self.hold = asyncio.Event()
        self.hold.set()
        self.missing: frozenset[str] = frozenset()
        self.asked: list[tuple[str, list[str]]] = []

    def problem(self, base_id=None):  # noqa: ANN001
        return (
            "The model to teach is not on this computer yet." if base_id in self.missing else None
        )

    def ready(self, base_id=None):  # noqa: ANN001
        return self.problem(base_id) is None

    def fit(self, need_gb):  # noqa: ANN001
        return {"verdict": "fits", "reason": ""}

    def state(self):
        return {"engine": self.engine, "preview": False, "setup": None}

    def preflight_blockers(self):
        return []

    def base_folder(self, base_id):  # noqa: ANN001
        return Path("/base") / base_id

    async def stop(self):
        self.stopped = True
        self.hold.set()

    @staticmethod
    def said(question, text: str, taught: bool):  # noqa: ANN001
        from wasifyai_training.decision import Said

        answers = question.answers()
        named = [a for a in answers if a.lower() in text.lower()]
        top = named[0] if named and taught else answers[0]
        sure = 0.95 if named and taught else 0.4
        rest = (1 - sure) / max(1, len(answers) - 1)
        return Said(top, sure, {a: (sure if a == top else rest) for a in answers})

    async def answer(self, model, question, texts):  # noqa: ANN001
        self.asked.append((str(model), list(texts)))
        taught = not str(model).startswith("/base")
        return [self.said(question, t, taught) for t in texts]

    async def train(self, job, base_id, folder, report):  # noqa: ANN001
        from wasifyai_training.decision import DecisionResult
        from wasifyai_training.language import Stopped

        self.stopped = False
        for step in range(1, job.steps + 1):
            report(step, f"Learning, step {step} of {job.steps}")
            if step == 1:
                await self.hold.wait()
            if self.stopped:
                raise Stopped("It was stopped, so nothing was kept.")
            await asyncio.sleep(0)
        if self.fail_with:
            raise RuntimeError(self.fail_with)
        out = folder / "model"
        out.mkdir(parents=True, exist_ok=True)
        (out / "model.safetensors").write_bytes(b"stub-model")
        q = job.question
        return DecisionResult(
            out, 2.0, self.engine,
            before=[self.said(q, r.text, False) for r in job.held],
            after=[self.said(q, r.text, True) for r in job.held],
            peek_before=[self.said(q, t, False) for t in job.peek],
            peek_after=[self.said(q, t, True) for t in job.peek],
            loss=[0.9, 0.2], peak_bytes=13 * 1024**3, bytes=10,
        )  # fmt: skip


class FakeVideoTrainer:
    """The video engine without a model: the same calls, an adapter a stub makes and a look published."""

    preview = False
    engine = "fake-diffusers"

    def __init__(self, root: Path) -> None:
        self.slot = None
        self.root = root
        self.stopped = False
        self.fail_with: str | None = None
        self.hold = asyncio.Event()
        self.hold.set()
        self.not_ready: str | None = None
        self.jobs: list = []
        self.published: list[str] = []
        self.unpublished: list[str] = []

    def problem(self, base_id=None):  # noqa: ANN001
        return self.not_ready

    def ready(self, base_id=None):  # noqa: ANN001
        return self.problem(base_id) is None

    def fit(self, need_gb):  # noqa: ANN001
        return {"verdict": "fits", "reason": ""}

    def state(self):
        return {"engine": self.engine, "preview": False, "setup": self.problem()}

    def preflight(self, need_gb):  # noqa: ANN001
        return {"ok": True, "blockers": [], "warnings": [], "pauses": "Everything waits."}

    def preflight_blockers(self):
        return []

    async def stop(self):
        self.stopped = True
        self.hold.set()

    async def train(self, job, folder, report):  # noqa: ANN001
        from wasifyai_training.trainer import Stopped
        from wasifyai_training.video import VideoResult

        self.jobs.append(job)
        self.stopped = False
        for step in range(1, job.steps + 1):
            report(step, f"Learning, step {step} of {job.steps}")
            if step == 1:
                await self.hold.wait()
            if self.stopped:
                raise Stopped("It was stopped, so nothing was kept.")
            if step >= 3:
                break
            await asyncio.sleep(0)
        if self.fail_with:
            raise RuntimeError(self.fail_with)
        out = folder / "out"
        out.mkdir(parents=True, exist_ok=True)
        adapter = out / "pytorch_lora_weights.safetensors"
        from wasifyai_training.comfy_lora import write_tensors

        a = {"dtype": "BF16", "shape": [2, 4], "data": bytes(16)}
        b = {"dtype": "BF16", "shape": [4, 2], "data": bytes(16)}
        base = "transformer.transformer_blocks.0.attn1.to_q"
        write_tensors(adapter, {f"{base}.lora_A.weight": a, f"{base}.lora_B.weight": b}, {})
        return VideoResult(adapter, 3.0, self.engine, 9 * 1024**3, 1.2, 0.5)

    async def publish(self, adapter, title, run_id):  # noqa: ANN001
        name = f"wasify-video-{title.lower().replace(' ', '-')}-{run_id[:8]}.safetensors"
        self.published.append(name)
        return name

    async def unpublish(self, name):  # noqa: ANN001
        self.unpublished.append(name)


def make_app(tmp_path: Path) -> tuple[FastAPI, Vision]:
    app = FastAPI()
    app.state.desktop_dir = tmp_path
    trainer = PreviewTrainer()
    trainer.step_s = 0.001
    app.state.training = trainer
    app.state.language_training = FakeWriter()
    app.state.decision_training = FakeDecider()
    app.state.video_training = FakeVideoTrainer(tmp_path)
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


def new_dataset(
    client, kind: str = "character", name: str = "Marlo", family: str = "image"
) -> dict[str, Any]:
    r = client.post(f"{BASE}/datasets", json={"kind": kind, "name": name, "family": family})
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
