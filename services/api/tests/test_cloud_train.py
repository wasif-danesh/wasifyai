"""Picture looks taught on a cloud model and used afterwards (ADR-0100, stage CP10), against fakes
of fal.ai and Runware: the pictures and captions go up as one zip; the cheapest trainer with a key
teaches it (Runware takes style looks only); the look is kept beside the other styles with its
address in the cloud; Images on the cloud model it was taught for loads it by that address, and a
look made on this computer, or for another model, is refused in words."""

import io
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from wasifyai_api.cloud_train import CloudLookTrainer, dataset_zip
from wasifyai_api.own_keys import OwnKeysService
from wasifyai_api.own_keys_media import KeyedMediaRouter
from wasifyai_media_worker.backends import OfferRunner
from wasifyai_media_worker.comfy import ComfyError
from wasifyai_platform_sdk import InMemoryUsageRecorder, JobRequest

from tests.test_own_keys_engines import Fal, keys_service
from tests.test_own_keys_media import _progress, a_png
from tests.test_own_keys_wavespeed_runware import Runware

LOOK = b"LORA-SAFETENSORS"


class LocalTrainer:
    """AI Toolkit on this computer: not set up."""

    def __init__(self, models_dir: Path) -> None:
        self.models_dir = models_dir
        self.trained: list[str] = []

    def problem(self, base: str | None = None) -> str | None:
        return "AI Toolkit is not set up yet."

    def ready(self) -> bool:
        return False

    def fit(self, base: str | None = None) -> dict[str, Any]:
        return {"verdict": "too_big", "reason": "20 GB"}

    def hub_missing(self, base: str) -> list[Any]:
        return ["files"]

    def state(self) -> dict[str, Any]:
        return {"engine": "ai-toolkit"}

    async def pause(self) -> None: ...

    async def train(self, job, report, sample, resume=False):
        self.trained.append(job.base)


async def on(model: str, *providers: str) -> OwnKeysService:
    keys = keys_service()
    for p in providers:
        await keys.save_key("train", p, "k")
    await keys.use("train", None, model)
    return keys


def a_job(tmp_path: Path, base: str, kind: str = "character") -> SimpleNamespace:
    pictures = []
    for n in range(3):
        p = tmp_path / f"p{n}.png"
        p.write_bytes(a_png())
        pictures.append(p)
    (tmp_path / "run" / "samples").mkdir(parents=True)
    return SimpleNamespace(
        kind=kind, word="zxq", steps=500, pictures=pictures,
        captions=[f"zxq picture {n}" for n in range(3)], samples=tmp_path / "run" / "samples",
        settings={}, base=base,
    )  # fmt: skip


def report() -> tuple[list[tuple[int, str]], Any]:
    seen: list[tuple[int, str]] = []
    return seen, lambda step, stage: seen.append((step, stage))


def test_the_set_goes_up_as_pictures_beside_their_captions(tmp_path):
    job = a_job(tmp_path, "z-image")
    with zipfile.ZipFile(io.BytesIO(dataset_zip(job.pictures, job.captions))) as z:
        assert z.namelist() == ["001.png", "001.txt", "002.png", "002.txt", "003.png", "003.txt"]
        assert z.read("002.txt") == b"zxq picture 1"


async def test_a_person_is_taught_on_fal_and_kept_with_its_address(tmp_path):
    fal = Fal({"diffusers_lora_file": {"url": "https://v3.fal.media/look.safetensors"}}, LOOK)
    usage = InMemoryUsageRecorder()
    local = LocalTrainer(tmp_path / "models")
    engine = CloudLookTrainer(local, await on("z-image-look", "fal"), fal.client, poll_s=0,
                              usage=usage)  # fmt: skip
    assert engine.ready() and engine.problem("z-image") is None
    assert engine.fit("z-image")["verdict"] == "fits" and engine.hub_missing("z-image") == []
    assert getattr(engine, "pause", None) is None  # a cloud run cannot be paused
    seen, told = report()
    result = await engine.train(a_job(tmp_path, "z-image"), told, lambda name: None)
    ((url, body),) = fal.posts()
    assert url.endswith("/fal-ai/z-image-trainer")
    assert body["trigger_word"] == "zxq" and body["steps"] == 500
    assert body["training_type"] == "content"
    with zipfile.ZipFile(io.BytesIO(fal.uploads[body["images_data_url"]])) as z:
        assert len(z.namelist()) == 6
    assert result.engine == "cloud" and result.adapter.read_bytes() == LOOK
    assert seen[0][1] == "Sending the pictures to fal.ai" and seen[-1][0] == 500
    (event,) = usage.events
    assert event.quantity == pytest.approx(500 * 0.00226) and event.meta["provider"] == "fal"
    name = await engine.publish(result.adapter, "My Dog", "run12345abcd")
    assert name == "wasify-cloud-my-dog-run12345.safetensors"
    assert (tmp_path / "models" / "loras" / name).read_bytes() == LOOK
    assert engine.cloud_of(name) == {
        "provider": "fal", "url": "https://v3.fal.media/look.safetensors",
        "model": "z-image-turbo",
    }  # fmt: skip
    assert local.trained == []


async def test_a_style_goes_to_the_cheaper_runware(tmp_path):
    rw = Runware("modelURL", LOOK, "application/octet-stream")
    usage = InMemoryUsageRecorder()
    engine = CloudLookTrainer(
        LocalTrainer(tmp_path / "models"), await on("z-image-look", "runware", "fal"), rw.client,
        poll_s=0, usage=usage,
    )  # fmt: skip
    _, told = report()
    result = await engine.train(a_job(tmp_path, "z-image", "style"), told, lambda name: None)
    (task,) = [t for t in rw.tasks() if t["taskType"] == "modelTraining"]
    assert task["model"] == "runware:z-image@style-lora-training"
    assert task["inputs"]["dataset"] == "media-0"  # the zip went up first
    assert rw.stored[0].startswith("data:application/zip;base64,")
    assert task["settings"] == {"trainingSteps": 500, "triggerWord": "zxq"}
    assert usage.events[0].meta["provider"] == "runware"
    name = await engine.publish(result.adapter, "Ink", "run9")
    assert name is not None
    cloud = engine.cloud_of(name)
    assert cloud is not None and cloud["url"] == "https://im.runware.ai/out/file"


async def test_with_a_runware_key_only_a_person_cannot_be_taught(tmp_path):
    engine = CloudLookTrainer(
        LocalTrainer(tmp_path / "models"), await on("z-image-look", "runware"),
        Runware("modelURL", LOOK, "x").client, poll_s=0,
    )  # fmt: skip
    _, told = report()
    with pytest.raises(RuntimeError):
        await engine.train(a_job(tmp_path, "z-image", "character"), told, lambda name: None)


async def test_klein_looks_are_taught_on_fal_and_other_models_are_refused_in_words(tmp_path):
    fal = Fal({"diffusers_lora_file": {"url": "https://v3.fal.media/k.safetensors"}}, LOOK)
    engine = CloudLookTrainer(LocalTrainer(tmp_path), await on("flux3-klein-look", "fal"),
                              fal.client, poll_s=0)  # fmt: skip
    why = engine.problem("z-image")
    assert why is not None and "FLUX.3 klein" in why
    _, told = report()
    await engine.train(a_job(tmp_path, "flux3-image-klein"), told, lambda name: None)
    ((url, body),) = fal.posts()
    assert url.endswith("/fal-ai/flux-3-klein-trainer") and "training_type" not in body


async def test_with_train_on_this_computer_the_local_trainer_does_it(tmp_path):
    local = LocalTrainer(tmp_path)
    engine = CloudLookTrainer(local, keys_service())
    assert not engine.ready() and engine.problem() == "AI Toolkit is not set up yet."
    assert engine.hub_missing("z-image") == ["files"] and getattr(engine, "pause", None)
    _, told = report()
    await engine.train(a_job(tmp_path, "z-image"), told, lambda name: None)
    assert local.trained == ["z-image"]


# ---- the look used afterwards ------------------------------------------------------------------


def a_job_with(look: dict[str, Any] | None, model: str = "z-image-turbo") -> JobRequest:
    inputs: dict[str, Any] = {"prompt": "zxq on a beach", "loras": [{"name": "l.safetensors",
                                                                    "weight": 0.8}]}  # fmt: skip
    if look is not None:
        inputs["lora_urls"] = {"l.safetensors": {**look, "model": model}}
    return JobRequest(
        tenant_id="local", product_id="wasifyai-image", user_id="u1",
        capability="image.generate", workflow="w", prompt={}, inputs=inputs,
        outputs={"image": {"node": "1", "type": "image"}},
    )  # fmt: skip


async def images_on(model: str, *providers: str) -> OwnKeysService:
    keys = keys_service()
    for p in providers:
        await keys.save_key("images", p, "k")
    await keys.use("images", None, model)
    return keys


async def test_a_cloud_look_is_loaded_by_its_address_on_fal_even_with_a_cheaper_runware_key():
    fal = Fal({"images": [{"url": "https://files.example/out.png"}]}, a_png())
    keys = await images_on("z-image-turbo", "runware", "fal")
    job = a_job_with({"url": "https://v3.fal.media/look.safetensors"})
    async with fal.client() as http:
        runner = await KeyedMediaRouter(object(), keys, http, 60, 0).resolve(job)  # type: ignore[arg-type]
        assert isinstance(runner, OfferRunner)
        await runner.run(job, _progress)
    ((url, body),) = fal.posts()
    assert url == "https://queue.fal.run/fal-ai/z-image/turbo/lora"
    assert body["loras"] == [{"path": "https://v3.fal.media/look.safetensors", "scale": 0.8}]
    assert runner.cost is not None and runner.cost.offer.provider == "fal"


async def test_a_flux_klein_look_is_loaded_on_its_lora_endpoint():
    fal = Fal({"images": [{"url": "https://files.example/out.png"}]}, a_png())
    keys = await images_on("flux-3-klein", "fal")
    job = a_job_with({"url": "https://v3.fal.media/k.safetensors"}, "flux-3-klein")
    async with fal.client() as http:
        runner = await KeyedMediaRouter(object(), keys, http, 60, 0).resolve(job)  # type: ignore[arg-type]
        await runner.run(job, _progress)
    ((url, _),) = fal.posts()
    assert url == "https://queue.fal.run/blackforestlabs/flux-3/klein/text-to-image/lora"


@pytest.mark.parametrize(
    ("look", "words"),
    [(None, "made on this computer"),
     ({"url": "https://v3.fal.media/k.safetensors", "model": "flux-3-klein"}, "for another cloud")],
)  # fmt: skip
async def test_a_look_not_taught_for_this_cloud_model_is_refused(look, words):
    keys = await images_on("z-image-turbo", "fal")
    job = a_job_with(look)
    if look is not None:
        job.inputs["lora_urls"]["l.safetensors"]["model"] = look["model"]
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))) as h:
        runner = await KeyedMediaRouter(object(), keys, h, 60, 0).resolve(job)  # type: ignore[arg-type]
        with pytest.raises(ComfyError) as e:
            await runner.run(job, _progress)
    assert e.value.code == "not_with_key" and words in e.value.message
