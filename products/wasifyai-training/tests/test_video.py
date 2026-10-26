# ruff: noqa: E501
"""Teaching the video model: a set of pictures and clips, the checks in words, a run with a fake engine,
the model it leaves and the look published for the video engine."""

import subprocess

import pytest
from training_rig import BASE, add_picture, new_dataset, noise, png, wait
from wasifyai_training import bases, clips, video

V = f"{BASE}/video"


def clip_bytes(
    tmp_path, source: str = "testsrc2", seconds: float = 3.0, size: str = "640x480"
) -> bytes:
    path = tmp_path / f"{source[:6]}-{seconds}-{size}.mp4"
    sep = ":" if "=" in source else "="
    subprocess.run(
        [
            clips.ffmpeg_path(),
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"{source}{sep}s={size}:r=24:d={seconds}",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    return path.read_bytes()


def add_clip(rig, dataset_id: str, data: bytes, headers=None):
    return rig.post(
        f"{BASE}/datasets/{dataset_id}/items?name=c.mp4",
        content=data,
        headers={"content-type": "video/mp4", **(headers or {})},
    )


def video_set(
    rig, tmp_path, pictures: int = 5, clips_n: int = 3, word: str = "marlo", rights: str = "drawing"
) -> dict:
    ds = new_dataset(rig, family="video")
    for n in range(pictures):
        assert (
            add_picture(rig, ds["id"], png(noise((60 + n * 20, 90, 200 - n * 10)))).status_code
            == 201
        )
    for n in range(clips_n):
        assert add_clip(rig, ds["id"], clip_bytes(tmp_path, "testsrc2", 3.0 + n)).status_code == 201
    assert rig.post(f"{BASE}/datasets/{ds['id']}/captions").status_code == 202
    wait(rig, f"/datasets/{ds['id']}", lambda d: not d["writing"])
    assert (
        rig.patch(
            f"{BASE}/datasets/{ds['id']}", json={"trigger_word": word, "rights": rights}
        ).status_code
        == 200
    )
    return rig.get(f"{BASE}/datasets/{ds['id']}").json()


def test_a_set_made_for_video_says_so_and_lists_apart(rig):
    pic = new_dataset(rig, name="Pictures")
    vid = new_dataset(rig, name="Clips", family="video")
    assert pic["family"] == "image" and vid["family"] == "video"
    assert [d["id"] for d in rig.get(f"{BASE}/datasets?family=video").json()["datasets"]] == [
        vid["id"]
    ]
    assert [d["id"] for d in rig.get(f"{BASE}/datasets?family=image").json()["datasets"]] == [
        pic["id"]
    ]
    assert len(rig.get(f"{BASE}/datasets").json()["datasets"]) == 2
    assert (
        rig.post(f"{BASE}/datasets", json={"kind": "style", "family": "audio"}).status_code == 422
    )


def test_the_video_status_names_the_model_and_says_what_it_needs(rig):
    s = rig.get(f"{V}/status").json()
    assert s["ready"] is True and s["min_items"] == 8 and s["windows_per_clip"] == 3
    first = s["choices"]["bases"][0]
    assert first["id"] == "ltx-video-2b" and first["can_teach"] and first["recommended"]
    methods = {m["id"]: m for m in first["methods"]}
    assert methods["lora"]["can"] and not methods["qlora"]["can"] and not methods["full"]["can"]
    assert "0.5 s a step" in first["measured"] and s["choices"]["family"] == "video"
    rig.app_state.video_training.not_ready = "The video model is not on this computer yet."
    assert (
        rig.get(f"{V}/status").json()["problem"] == "The video model is not on this computer yet."
    )


def test_pictures_and_clips_are_checked_in_words_and_a_clip_has_its_frame_as_a_picture(
    rig, tmp_path
):
    ds = new_dataset(rig, family="video")
    good = add_clip(rig, ds["id"], clip_bytes(tmp_path, "testsrc2", 3.0))
    assert good.status_code == 201, good.text
    row = good.json()
    assert (
        row["media"] == "clip"
        and 2.9 < row["seconds"] < 3.2
        and (row["width"], row["height"]) == (640, 480)
    )
    assert row["checks"][0]["code"] == "good"
    still = add_clip(rig, ds["id"], clip_bytes(tmp_path, "color=c=0x80a0c0", 3.0)).json()
    assert {c["code"] for c in still["checks"]} >= {"still"}
    # the frame of a clip is served like a picture, and what the captioner reads
    got = rig.get(f"{BASE}/datasets/{ds['id']}/items/{row['id']}/thumb")
    assert got.status_code == 200 and got.headers["content-type"] == "image/jpeg"
    # what cannot be read is refused in words
    bad = add_clip(rig, ds["id"], b"not a video at all")
    assert (
        bad.status_code == 422 and "could not be read as a video" in bad.json()["detail"]["message"]
    )
    assert add_clip(rig, ds["id"], b"").status_code == 422
    # clips belong to a set made for video
    pics = new_dataset(rig)
    refused = add_clip(rig, pics["id"], clip_bytes(tmp_path))
    assert refused.status_code == 422 and "made for video" in refused.json()["detail"]["message"]


def test_the_plan_follows_the_shape_and_the_clips_and_says_the_time(rig, tmp_path):
    only_pictures = [{"media": "picture", "width": 1320, "height": 1191}] * 12
    p = video.plan_of(only_pictures)
    assert (p["size"], p["width"], p["height"], p["frames"], p["tokens"]) == (
        "square",
        704,
        704,
        1,
        484,
    )
    assert p["steps"] == 720 and not p["checkpointing"] and 400 < p["seconds"] < 1200
    wide_clips = [{"media": "clip", "width": 1920, "height": 1080, "seconds": 4.0}] * 8
    c = video.plan_of(wide_clips)
    assert (c["size"], c["frames"], c["tokens"], c["samples"]) == ("wide", 25, 1536, 24) and c[
        "checkpointing"
    ]
    assert (
        300 <= c["steps"] <= 1600 and c["seconds"] <= 2 * 3600 + 100
    )  # a run is planned to fit about two hours
    # a mix of pictures and clips costs what its samples cost, not what the largest costs
    mixed = [{"media": "picture", "width": 768, "height": 1152}] * 12 + [
        {"media": "clip", "width": 512, "height": 768, "seconds": 4.0}
    ] * 3
    m = video.plan_of(mixed)
    assert (m["size"], m["samples"], m["steps"], m["tokens"]) == ("tall", 21, 1260, 1536)
    assert 2.2 < m["seconds_per_step"] < 2.8 and 2800 < m["seconds"] < 3700  # about 50 minutes
    assert video.plan_of([{"media": "picture", "width": 600, "height": 1000}] * 9)["size"] == "tall"
    assert (
        video.estimate_words(30) == "About a minute"
        and video.estimate_words(1500) == "About 25 minutes"
    )
    assert video.estimate_words(7200) == "About 2.0 hours"
    assert video.windows_of(1.1) == 1 and video.windows_of(10.0) == 3
    assert video.tokens_of(768, 512, 25) == 1536 and video.tokens_of(704, 704, 1) == 484


def test_a_set_says_what_is_missing_before_a_run(rig, tmp_path):
    ds = new_dataset(rig, family="video")
    assert (
        rig.get(f"{BASE}/datasets/{ds['id']}")
        .json()["missing"]
        .startswith("Add at least 8 pictures or clips")
    )
    full = video_set(rig, tmp_path, rights="")
    assert (
        full["missing"] == "Say whose it is first." and full["clips"] == 3 and full["pictures"] == 8
    )
    refused = rig.post(f"{BASE}/runs", json={"dataset_id": full["id"]})
    assert refused.status_code == 409 and "whose it is" in refused.json()["detail"]["message"]


def run_to_end(rig, dataset_id: str) -> dict:
    started = rig.post(f"{BASE}/runs", json={"dataset_id": dataset_id})
    assert started.status_code == 202, started.text
    return wait(rig, f"/runs/{started.json()['id']}", lambda r: r["status"] != "working")


def test_a_run_leaves_a_model_with_its_card_and_publishes_the_look(rig, tmp_path):
    ds = video_set(rig, tmp_path)
    run = run_to_end(rig, ds["id"])
    assert run["status"] == "done" and run["model_id"] and run["settings"]["family"] == "video"
    assert (
        run["settings"]["method"] == "lora"
        and run["settings"]["engine"] == "diffusers"
        and run["estimate"]
    )
    model = rig.get(f"{BASE}/models/{run['model_id']}").json()
    card = model["card"]
    assert (
        card["family"] == "video"
        and card["base"] == "ltx-video-2b"
        and model["trigger_word"] == "marlo"
    )
    assert card["dataset"]["pictures"] == 5 and card["dataset"]["clips"] == 3
    assert card["published"]["lora_name"].startswith("wasify-video-") and card["loss"] == {
        "first": 1.2,
        "last": 0.5,
    }
    assert (
        card["peak_memory_gb"] == 9.0 and card["engine"] == "fake-diffusers" and card["statement"]
    )
    assert "look at it" in card["evaluation"]["note"]
    # the engine was given the pictures and the clips, with the magic word first in every description
    job = rig.app_state.video_training.jobs[-1]
    assert [m.kind for m in job.media].count("clip") == 3 and all(
        m.caption.startswith("marlo, ") for m in job.media
    )
    assert job.checkpointing is True and job.window_frames == 25
    assert rig.app_state.video_training.published == [card["published"]["lora_name"]]
    # it is found in search by its name and kind
    kind, text = rig.app_state.creation_index.items[run["model_id"]]
    assert kind == "lora" and "marlo" in text.lower()


def test_removing_the_model_takes_the_look_back_from_the_video_engine(rig, tmp_path):
    ds = video_set(rig, tmp_path)
    model_id = run_to_end(rig, ds["id"])["model_id"]
    name = rig.get(f"{BASE}/models/{model_id}").json()["card"]["published"]["lora_name"]
    assert rig.delete(f"{BASE}/models/{model_id}").status_code == 204
    assert rig.app_state.video_training.unpublished == [name]


def test_a_failed_run_says_so_and_a_stopped_one_keeps_nothing(rig, tmp_path):
    engine = rig.app_state.video_training
    ds = video_set(rig, tmp_path)
    engine.fail_with = "boom"
    run = run_to_end(rig, ds["id"])
    assert run["status"] == "failed" and run["error"] == "The model could not be taught. Try again."
    engine.fail_with = None
    engine.hold.clear()
    started = rig.post(f"{BASE}/runs", json={"dataset_id": ds["id"]}).json()
    wait(rig, f"/runs/{started['id']}", lambda r: r["step"] >= 1)
    assert rig.post(f"{BASE}/runs/{started['id']}/cancel").json() == {"cancelled": True}
    run = wait(rig, f"/runs/{started['id']}", lambda r: r["status"] != "working")
    assert run["status"] == "cancelled" and run["model_id"] is None


def test_only_one_model_is_taught_at_a_time_across_every_kind(rig, tmp_path):
    engine = rig.app_state.video_training
    ds = video_set(rig, tmp_path)
    engine.hold.clear()
    first = rig.post(f"{BASE}/runs", json={"dataset_id": ds["id"]}).json()
    wait(rig, f"/runs/{first['id']}", lambda r: r["step"] >= 1)
    second = rig.post(f"{BASE}/runs", json={"dataset_id": ds["id"]})
    assert second.status_code == 409 and "being taught" in second.json()["detail"]["message"]
    assert (
        rig.get(f"{BASE}/status").json()["busy"] is True
        and rig.get(f"{V}/status").json()["busy"] is True
    )
    # a picture set, a writing set and a decision set are refused while it runs
    pics = new_dataset(rig)
    for n in range(8):
        add_picture(rig, pics["id"], png(noise((60 + n * 20, 90, 200 - n * 10))))
    rig.post(f"{BASE}/datasets/{pics['id']}/captions")
    wait(rig, f"/datasets/{pics['id']}", lambda d: not d["writing"])
    rig.patch(f"{BASE}/datasets/{pics['id']}", json={"trigger_word": "zorvik", "rights": "drawing"})
    assert rig.post(f"{BASE}/runs", json={"dataset_id": pics["id"]}).status_code == 409
    rig.post(f"{BASE}/runs/{first['id']}/cancel")
    wait(rig, f"/runs/{first['id']}", lambda r: r["status"] != "working")


def test_a_run_is_refused_in_words_when_the_video_model_is_not_there(rig, tmp_path):
    ds = video_set(rig, tmp_path)
    rig.app_state.video_training.not_ready = "The video model is not on this computer yet. Choose Select video model on a Video screen to get it."
    refused = rig.post(f"{BASE}/runs", json={"dataset_id": ds["id"]})
    assert (
        refused.status_code == 409 and "Select video model" in refused.json()["detail"]["message"]
    )
    desc = bases.descriptor("ltx-video-2b")
    assert desc is not None and desc.family == "video"


async def test_the_action_teaches_the_video_model_from_a_video_set(rig, tmp_path):
    from test_writing import ActionHarness

    ds = video_set(rig, tmp_path)
    r = await ActionHarness(rig).go({"dataset_id": ds["id"]})
    assert r.status == "ok", r.text
    assert r.output["magic_word"] == "marlo" and r.output["uri"].startswith(
        "wasify://creation/lora/"
    )
    assert "video prompt" in r.text and "My looks" in r.text
    model = rig.get(f"{BASE}/models/{r.output['model_id']}").json()
    assert model["card"]["family"] == "video"
    assert rig.app_state.video_training.jobs  # the video engine ran it, not the picture engine


async def test_the_picture_engine_does_not_take_a_video_set(rig, tmp_path):
    from training_rig import user_of
    from wasifyai_platform_sdk import RouteDeps
    from wasifyai_platform_sdk.identity import Identity
    from wasifyai_training.runtime import Refused, run_manager_for

    ds = video_set(rig, tmp_path)
    deps = RouteDeps(rig.app_state, user_of)
    with pytest.raises(Refused) as e:
        await run_manager_for(deps).start(Identity("t1", "u1"), ds["id"])
    assert e.value.code == "wrong_family" and "video model" in e.value.message
