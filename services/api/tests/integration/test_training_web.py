# ruff: noqa: E501
"""Train on the web, end to end on real Postgres and real Redis (docs/train-web-plan.md, WT0 and WT1): the product's routes on
a Postgres store with its files in object storage, a remote video trainer that queues a job, and a worker that runs a stand-in
for the desktop trainer. Pictures, a clip, descriptions, a run, the model, its look in storage, and deleting it all again."""

import asyncio
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from wasifyai_engine_worker.train import ModelCache, TrainComponents
from wasifyai_engine_worker.worker import Worker
from wasifyai_platform_sdk import EngineQueue, InMemoryUsageRecorder, RouteDeps, memory_storage

sys.path.insert(0, str(Path(__file__).parents[4] / "products" / "wasifyai-training" / "tests"))
from test_comfy_lora import adapter as tiny_image_adapter  # noqa: E402
from training_rig import (  # noqa: E402
    BASE,
    FakeDecider,
    FakeVideoTrainer,
    FakeWriter,
    Index,
    Vision,
    noise,
    png,
    user_of,
)
from wasifyai_api.engine_workers import WorkerDirectory  # noqa: E402
from wasifyai_api.remote_train import (  # noqa: E402
    RemoteDecisionTrainer,
    RemoteImageTrainer,
    RemoteVideoTrainer,
    RemoteWritingTrainer,
)
from wasifyai_api.services import ApiServices
from wasifyai_training.comfy_lora import write_tensors  # noqa: E402
from wasifyai_training.files import StorageFiles  # noqa: E402
from wasifyai_training.routes import build_routes  # noqa: E402
from wasifyai_training.store import TrainingStore  # noqa: E402
from wasifyai_training.trainer import PreviewTrainer  # noqa: E402


class StandInPictureTrainer(PreviewTrainer):
    """The picture trainer without a model: it writes sample pictures as the preview does, and an adapter in mflux's names."""

    preview = False
    engine = "mflux"
    step_s = 0.01

    def preflight(self):
        return {"ok": True, "blockers": [], "warnings": [], "pauses": "Everything waits."}

    async def tokenize(self, words):
        """The model's tokenizer: a word it knows whole is a poor magic word, any other splits in two."""
        return {w: {"pieces": [w] if w == "wolf" else [w[:2], w[2:]], "known": []} for w in words}

    async def train(self, job, report, sample, resume=False):
        import threading

        def from_a_thread(name):
            """The real trainer's watcher reports a sample from a thread of its own."""
            t = threading.Thread(target=sample, args=(name,))
            t.start()
            t.join()

        res = await super().train(job, report, from_a_thread, resume)
        write_tensors(res.adapter, tiny_image_adapter(), {})
        return res


class Speech:
    def models(self, _):
        return []


def clip_bytes(tmp: Path) -> bytes:
    from wasifyai_training import clips

    path = tmp / "c.mp4"
    subprocess.run(
        [clips.ffmpeg_path(), "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x480:r=24:d=3", "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )  # fmt: skip
    return path.read_bytes()


@pytest.fixture
async def web(engine, redis_conn, tmp_path):
    from wasifyai_api.config import get_settings

    storage = memory_storage()
    store = TrainingStore.on_postgres(
        get_settings().database_url, schema="trn_w_" + uuid4().hex[:8], cache=tmp_path / "cache"
    )
    import os

    from redis.asyncio import Redis

    space = f"wasifyai:test:{uuid4().hex}"
    queue = EngineQueue(redis_conn, namespace=space)
    # a worker has a connection of its own, with room for a blocking read (as in the worker's main)
    worker_redis = Redis.from_url(
        os.environ.get("INTEGRATION_REDIS_URL", "redis://localhost:6379/15"),
        decode_responses=True,
        socket_timeout=60,
    )
    directory = WorkerDirectory(queue)
    fake = FakeVideoTrainer(tmp_path / "worker")
    worker = Worker(
        EngineQueue(worker_redis, namespace=space),
        {
            "speech": Speech(),
            "train": TrainComponents(
                video=fake,
                image=StandInPictureTrainer(),
                decision=FakeDecider(),
                writing=FakeWriter(),
                cache=ModelCache(tmp_path / "models"),
            ),
        },
        storage,
        "w1",
        60,
        0.2,
    )
    app = FastAPI()
    app.state.services = ApiServices()
    app.state.services.training_store = store
    app.state.services.training_files = StorageFiles(storage)
    app.state.services.usage = InMemoryUsageRecorder()
    app.state.services.creation_index = Index()
    vision = Vision()
    app.state.services.caps = {
        "wasifyai-training": SimpleNamespace(text=vision, db=None, config=None)
    }
    app.state.services.video_training = RemoteVideoTrainer(
        queue, storage, directory, usage=app.state.services.usage
    )
    app.state.services.training = RemoteImageTrainer(
        queue, storage, directory, usage=app.state.services.usage
    )
    app.state.services.decision_training = RemoteDecisionTrainer(
        queue, storage, directory, usage=app.state.services.usage
    )
    app.state.services.language_training = RemoteWritingTrainer(
        queue, storage, directory, usage=app.state.services.usage
    )
    app.include_router(
        build_routes(RouteDeps(app.state.services, user_of)), prefix="/products/wasifyai-training"
    )
    running = asyncio.create_task(worker.run())
    await asyncio.sleep(0.5)
    await directory.refresh()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        yield SimpleNamespace(
            client=client,
            app=app,
            storage=storage,
            store=store,
            fake=fake,
            directory=directory,
            cache=tmp_path / "cache",
        )
    worker.stop.set()
    await asyncio.wait_for(running, 15)
    await worker_redis.aclose()
    store.drop_schema()
    store.close()


async def until(client, path, done, tries=300):
    row = {}
    for _ in range(tries):
        row = (await client.get(f"{BASE}{path}")).json()
        if done(row):
            return row
        await asyncio.sleep(0.05)
    raise AssertionError(f"still not: {row}")


async def test_every_card_is_there_and_chat_with_a_taught_model_is_not_offered(web):
    status = (await web.client.get(f"{BASE}/video/status")).json()
    assert (
        status["ready"] is True and status["problem"] is None and status["fit"]["verdict"] == "fits"
    )
    writing = (await web.client.get(f"{BASE}/writing/status")).json()
    assert (
        writing["ready"] is True and writing["can_chat"] is False
    )  # chat is the desktop's, for now
    decision = (await web.client.get(f"{BASE}/decision/status")).json()
    assert decision["ready"] is True and decision["problem"] is None


async def test_a_video_look_is_taught_through_postgres_storage_and_a_worker(web, tmp_path):
    c = web.client
    d = (
        await c.post(
            f"{BASE}/datasets", json={"kind": "character", "name": "Marlo", "family": "video"}
        )
    ).json()
    for n in range(7):
        r = await c.post(
            f"{BASE}/datasets/{d['id']}/items?name=p{n}.png",
            content=png(noise((60 + n * 20, 90, 200 - n * 10))),
            headers={"content-type": "image/png"},
        )
        assert r.status_code == 201, r.text
    r = await c.post(
        f"{BASE}/datasets/{d['id']}/items?name=c.mp4",
        content=clip_bytes(tmp_path),
        headers={"content-type": "video/mp4"},
    )
    assert r.status_code == 201, r.text
    clip_id = r.json()["id"]
    # the files are in object storage, not only in the API's cache
    keys = await web.storage.list("t1/wasifyai-training/u1/train/items/")
    assert any(k.endswith(f"{clip_id}/clip.mp4") for k in keys) and any(
        k.endswith(f"{clip_id}/thumb.jpg") for k in keys
    )
    # a cache that is gone is fetched again
    import shutil

    shutil.rmtree(web.cache)
    thumb = await c.get(f"{BASE}/datasets/{d['id']}/items/{clip_id}/thumb")
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"

    assert (await c.post(f"{BASE}/datasets/{d['id']}/captions")).status_code == 202
    await until(c, f"/datasets/{d['id']}", lambda x: not x["writing"])
    assert (
        await c.patch(f"{BASE}/datasets/{d['id']}", json={"trigger_word": "marlo"})
    ).status_code == 200
    run = await c.post(f"{BASE}/runs", json={"dataset_id": d["id"]})
    assert run.status_code == 202, run.text
    done = await until(c, f"/runs/{run.json()['id']}", lambda x: x["status"] != "working")
    assert done["status"] == "done", done
    model = (await c.get(f"{BASE}/models/{done['model_id']}")).json()
    card = model["card"]
    assert card["family"] == "video" and card["published"]["lora_name"].startswith(
        "wasify-video-marlo-"
    )
    # what the worker was given: the pictures and the clip, named with their kind, and the magic word first
    job = web.fake.jobs[-1]
    assert [m.kind for m in job.media].count("clip") == 1 and all(
        m.caption.startswith("marlo, ") for m in job.media
    )
    # the adapter and the card are kept in storage under the person's prefix, and the look is too (never shared)
    model_keys = await web.storage.list(f"t1/wasifyai-training/u1/train/models/{model['id']}/")
    assert any(k.endswith("adapter.safetensors") for k in model_keys) and any(
        k.endswith("card.json") for k in model_keys
    )
    look_keys = await web.storage.list(f"t1/wasifyai-training/u1/train/looks/{done['id']}/")
    assert [k.rsplit("/", 1)[1] for k in look_keys] == [card["published"]["lora_name"]]
    # nothing of the job's own inputs is left behind
    assert await web.storage.list("t1/wasifyai-training/u1/engine/") == []
    # another person sees none of it
    other = await c.get(f"{BASE}/models", headers={"x-user": "u2"})
    assert other.json()["models"] == []
    assert (
        await c.get(f"{BASE}/models/{model['id']}/file", headers={"x-user": "u2"})
    ).status_code == 404
    # the model can be downloaded from storage after the cache is gone
    shutil.rmtree(web.cache)
    got = await c.get(f"{BASE}/models/{model['id']}/file")
    assert got.status_code == 200 and len(got.content) > 0
    # deleting it removes the files and the look
    assert (await c.delete(f"{BASE}/models/{model['id']}")).status_code == 204
    assert await web.storage.list(f"t1/wasifyai-training/u1/train/models/{model['id']}/") == []
    assert await web.storage.list(f"t1/wasifyai-training/u1/train/looks/{done['id']}/") == []
    # deleting the set removes its pictures
    assert (await c.delete(f"{BASE}/datasets/{d['id']}")).status_code == 204
    assert await web.storage.list("t1/wasifyai-training/u1/train/items/") == []


async def test_stopping_a_run_on_the_web_stops_the_workers_job(web, tmp_path):
    c = web.client
    d = (
        await c.post(f"{BASE}/datasets", json={"kind": "style", "name": "Ink", "family": "video"})
    ).json()
    for n in range(8):
        await c.post(
            f"{BASE}/datasets/{d['id']}/items?name=p{n}.png",
            content=png(noise((60 + n * 20, 90, 200 - n * 10))),
            headers={"content-type": "image/png"},
        )
    await c.post(f"{BASE}/datasets/{d['id']}/captions")
    await until(c, f"/datasets/{d['id']}", lambda x: not x["writing"])
    await c.patch(f"{BASE}/datasets/{d['id']}", json={"trigger_word": "inkzy"})
    web.fake.hold.clear()  # the stand-in trainer waits after its first step
    run = (await c.post(f"{BASE}/runs", json={"dataset_id": d["id"]})).json()
    await until(c, f"/runs/{run['id']}", lambda x: x["step"] >= 1)
    assert (await c.post(f"{BASE}/runs/{run['id']}/cancel")).status_code == 200
    row = await until(c, f"/runs/{run['id']}", lambda x: x["status"] != "working")
    assert row["status"] == "cancelled"
    assert web.fake.stopped is True  # the worker was told to stop its process
    assert (await c.get(f"{BASE}/models")).json()["models"] == []


async def test_a_picture_style_is_taught_through_a_worker_with_its_samples_and_kept_in_storage(web):
    c = web.client
    d = (await c.post(f"{BASE}/datasets", json={"kind": "character", "name": "Marlo"})).json()
    for n in range(8):
        r = await c.post(
            f"{BASE}/datasets/{d['id']}/items?name=p{n}.png",
            content=png(noise((60 + n * 20, 90, 200 - n * 10))),
            headers={"content-type": "image/png"},
        )
        assert r.status_code == 201, r.text
    assert (await c.post(f"{BASE}/datasets/{d['id']}/captions")).status_code == 202
    await until(c, f"/datasets/{d['id']}", lambda x: not x["writing"])
    assert (
        await c.patch(f"{BASE}/datasets/{d['id']}", json={"trigger_word": "marlo"})
    ).status_code == 200
    status = (await c.get(f"{BASE}/status")).json()
    assert status["ready"] is True and status["can_pause"] is False
    run = await c.post(f"{BASE}/runs", json={"dataset_id": d["id"]})
    assert run.status_code == 202, run.text
    done = await until(c, f"/runs/{run.json()['id']}", lambda x: x["status"] != "working")
    assert done["status"] == "done", done
    assert done["samples"], "the sample pictures it made while it learnt"
    import shutil

    shutil.rmtree(web.cache)  # served from storage after the cache is gone
    sample = await c.get(f"{BASE}/runs/{done['id']}/samples/{done['samples'][0]}")
    assert sample.status_code == 200 and sample.content[:4] == b"\x89PNG"
    model = (await c.get(f"{BASE}/models/{done['model_id']}")).json()
    name = model["card"]["published"]["lora_name"]
    assert name.startswith("wasify-marlo-") and "family" not in model["card"]
    looks = await web.storage.list(f"t1/wasifyai-training/u1/train/looks/{done['id']}/")
    assert [k.rsplit("/", 1)[1] for k in looks] == [name]
    # the styles the person can use are the ones taught for pictures; the resolver names this person's file
    from wasifyai_api.person_looks import person_looks

    resolve = person_looks(web.app.state.services, video=False)
    assert await resolve("t1", "u1", [name]) == {name: looks[0]}
    assert await resolve("t1", "u2", [name]) is None  # another person's style is not theirs
    assert (
        await person_looks(web.app.state.services, video=True)("t1", "u1", [name]) is None
    )  # nor a video look
    # a run on a worker cannot be paused: the screen is told
    assert (await c.post(f"{BASE}/runs/{done['id']}/pause")).status_code in (200, 404, 409)


async def test_a_decision_model_is_taught_on_a_worker_kept_in_storage_and_asked_from_there(web):
    c = web.client
    d = BASE + "/decision"
    s = (await c.post(f"{d}/sets", json={"name": "Reviews"})).json()
    assert (
        await c.patch(
            f"{d}/sets/{s['id']}",
            json={"kind": "yes_no", "question": "Is this review positive?"},
        )
    ).status_code == 200
    rows = [
        {"text": f"review {n} " + ("yes" if n % 2 else "no"), "answer": "yes" if n % 2 else "no"}
        for n in range(40)
    ]
    assert (await c.put(f"{d}/sets/{s['id']}/examples", json={"rows": rows})).status_code == 200
    run = await c.post(f"{d}/sets/{s['id']}/runs")
    assert run.status_code == 202, run.text
    done = await until(c, f"/runs/{run.json()['id']}", lambda x: x["status"] != "working")
    assert done["status"] == "done", done
    model = (await c.get(f"{BASE}/models/{done['model_id']}")).json()
    assert model["kind"] == "decision" and model["card"]["report"]["texts"] > 0
    # the worker's files were moved inside storage: they are the model's, and nothing is left of the job
    keys = await web.storage.list(f"t1/wasifyai-training/u1/train/models/{model['id']}/model/")
    assert [k.rsplit("/", 1)[1] for k in keys] == ["model.safetensors"]
    assert await web.storage.list("t1/wasifyai-training/u1/engine/") == []
    # asking goes to a worker, which fetches the model from storage (and answers for the base as well)
    ask = await c.post(f"{d}/models/{model['id']}/ask", json={"text": "this one is a yes"})
    assert ask.status_code == 200, ask.text
    got = ask.json()
    assert (
        got["mine"]["answer"] == "yes" and got["original"]["confidence"] < got["mine"]["confidence"]
    )
    sort = await c.post(f"{d}/models/{model['id']}/sort", json={"texts": ["a yes", "a no"]})
    assert sort.status_code == 200 and [r["answer"] for r in sort.json()["results"]] == [
        "yes",
        "no",
    ]
    # another person cannot ask it
    other = await c.post(
        f"{d}/models/{model['id']}/ask", json={"text": "yes"}, headers={"x-user": "u2"}
    )
    assert other.status_code == 404
    # deleting it removes the files
    assert (await c.delete(f"{BASE}/models/{model['id']}")).status_code == 204
    assert await web.storage.list(f"t1/wasifyai-training/u1/train/models/{model['id']}/") == []


async def test_a_writing_model_is_taught_on_a_worker_and_asked_side_by_side_from_storage(web):
    import shutil

    c = web.client
    w = BASE + "/writing"
    s = (await c.post(f"{w}/sets", json={"name": "Replies"})).json()
    assert (await c.patch(f"{w}/sets/{s['id']}", json={"rights": "mine"})).status_code == 200
    rows = [{"ask": f"question {n}?", "answer": f"answer {n}."} for n in range(30)]
    assert (await c.put(f"{w}/sets/{s['id']}/examples", json={"rows": rows})).status_code == 200
    run = await c.post(f"{w}/sets/{s['id']}/runs")
    assert run.status_code == 202, run.text
    done = await until(c, f"/runs/{run.json()['id']}", lambda x: x["status"] != "working")
    assert done["status"] == "done", done
    model = (await c.get(f"{BASE}/models/{done['model_id']}")).json()
    assert model["kind"] == "writing" and model["card"]["answers"]
    keys = await web.storage.list(f"t1/wasifyai-training/u1/train/models/{model['id']}/adapter/")
    assert any(k.endswith("adapters.safetensors") for k in keys)
    assert await web.storage.list("t1/wasifyai-training/u1/engine/") == []
    shutil.rmtree(web.cache)  # asked with the files fetched from storage
    ask = await c.post(f"{w}/models/{model['id']}/ask", json={"question": "How are you?"})
    assert ask.status_code == 200, ask.text
    assert ask.json() == {
        "question": "How are you?",
        "original": "original: How are you?",
        "mine": "mine: How are you? - Wasi",
    }
    assert (
        await c.post(
            f"{w}/models/{model['id']}/ask", json={"question": "x"}, headers={"x-user": "u2"}
        )
    ).status_code == 404
    assert (await c.delete(f"{BASE}/models/{model['id']}")).status_code == 204
    assert await web.storage.list(f"t1/wasifyai-training/u1/train/models/{model['id']}/") == []


async def test_the_magic_word_is_judged_by_the_tokenizer_of_a_worker(web):
    c = web.client
    d = (await c.post(f"{BASE}/datasets", json={"kind": "character", "name": "Marlo"})).json()
    got = (await c.patch(f"{BASE}/datasets/{d['id']}", json={"trigger_word": "wolfy"})).status_code
    assert got == 200  # split in two: fine
    bad = await c.patch(f"{BASE}/datasets/{d['id']}", json={"trigger_word": "wolf"})
    assert bad.status_code == 422 and "already knows that as one word" in bad.text
    suggestions = (await c.get(f"{BASE}/datasets/{d['id']}")).json()["suggestions"]
    assert len(suggestions) == 3 and "wolf" not in suggestions
