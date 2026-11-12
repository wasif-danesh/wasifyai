"""3D on the cloud models beside Pixal3D (ADR-0100, stage CP9), against fakes of Runware, WaveSpeed
and fal.ai: Hunyuan3D 3.1 Pro and TRELLIS 2 on each offer, the cheapest offer with a key, the
picture going up the provider's way, and the cut-out: fal.ai's when a fal.ai key is there, else the
picture as it is (the cloud models cut it out themselves)."""

from pathlib import Path

import pytest
from wasifyai_api.own_keys import OwnKeysService
from wasifyai_api.own_keys_engines import KeyedModel3d
from wasifyai_platform_sdk import InMemoryUsageRecorder

from tests.test_own_keys_engines import GLB, PNG, Fal, Local3d, keys_service
from tests.test_own_keys_wavespeed_runware import Runware, WaveSpeed


async def on(model: str, *providers: str) -> OwnKeysService:
    keys = keys_service()
    for p in providers:
        await keys.save_key("model3d", p, "k")
    await keys.use("model3d", None, model)
    return keys


def a_cutout(tmp_path: Path) -> Path:
    cutout = tmp_path / "cutout.png"
    cutout.write_bytes(PNG)
    return cutout


@pytest.mark.parametrize(
    ("model", "air"),
    [("hunyuan3d-3.1-pro", "tencent:hunyuan-3d@3.1-pro"), ("trellis-2", "microsoft:trellis-2@4b")],
)
async def test_each_model_on_runware_takes_the_picture_inside_the_task(tmp_path, model, air):
    rw = Runware("objectURL", GLB, "model/gltf-binary")
    usage = InMemoryUsageRecorder()
    engine = KeyedModel3d(Local3d(), await on(model, "runware"), rw.client, poll_s=0, usage=usage)
    assert engine.ready() and engine.state()["keyed"] is True
    res = await engine.generate(a_cutout(tmp_path), tmp_path / "m.glb", seed=3)
    assert res.ok and (tmp_path / "m.glb").read_bytes() == GLB
    (task,) = [t for t in rw.tasks() if t["taskType"] == "3dInference"]
    assert task["model"] == air and task["outputFormat"] == "GLB" and task["seed"] == 3
    assert task["inputs"]["images"][0].startswith("data:image/png;base64,")
    assert ("settings" in task) is (model == "trellis-2")
    assert usage.events[0].meta["provider"] == "runware"


async def test_trellis_on_wavespeed_cuts_the_picture_out_itself(tmp_path):
    ws = WaveSpeed(GLB, "model/gltf-binary")
    engine = KeyedModel3d(Local3d(), await on("trellis-2", "wavespeed"), ws.client, poll_s=0)
    picture = tmp_path / "picture.png"
    picture.write_bytes(PNG)
    cut = await engine.matte(picture, tmp_path)
    assert cut.ok and cut.output is not None and cut.output.read_bytes() == PNG  # as it is
    res = await engine.generate(cut.output, tmp_path / "m.glb", detail="detailed")
    assert res.ok
    ((url, body),) = ws.posts()
    assert url.endswith("/wavespeed-ai/trellis-2/image-to-3d")
    assert body["image"] == "https://d1.wavespeed.ai/in/0" and body["remove_background"] is True
    assert body["texture_size"] == 4096 and body["resolution"] == 1024


async def test_hunyuan_on_fal_names_its_picture_its_own_way(tmp_path):
    fal = Fal({"model_glb": {"url": "https://v3.fal.media/m.glb"}}, GLB)
    engine = KeyedModel3d(Local3d(), await on("hunyuan3d-3.1-pro", "fal"), fal.client, poll_s=0)
    res = await engine.generate(a_cutout(tmp_path), tmp_path / "m.glb", seed=9)
    assert res.ok and (tmp_path / "m.glb").read_bytes() == GLB
    ((url, body),) = fal.posts()
    assert url.endswith("/fal-ai/hunyuan3d-v31/pro/image-to-3d")
    assert fal.uploads[body["input_image_url"]] == PNG and body["seed"] == 9


async def test_with_both_keys_trellis_runs_on_the_cheaper_runware(tmp_path):
    rw = Runware("objectURL", GLB, "model/gltf-binary")
    usage = InMemoryUsageRecorder()
    keys = await on("trellis-2", "runware", "wavespeed")
    engine = KeyedModel3d(Local3d(), keys, rw.client, poll_s=0, usage=usage)
    assert (await engine.generate(a_cutout(tmp_path), tmp_path / "m.glb")).ok
    (event,) = usage.events
    assert event.meta["provider"] == "runware" and event.quantity == pytest.approx(0.01)


async def test_with_a_fal_key_the_cut_out_is_still_fals(tmp_path):
    fal = Fal({"image": {"url": "https://v3.fal.media/cut.png"}}, PNG)
    keys = await on("hunyuan3d-3.1-pro", "runware", "fal")
    engine = KeyedModel3d(Local3d(), keys, fal.client, poll_s=0)
    picture = tmp_path / "picture.png"
    picture.write_bytes(PNG)
    assert (await engine.matte(picture, tmp_path)).ok
    ((url, _),) = fal.posts()
    assert url.endswith("/fal-ai/birefnet")
