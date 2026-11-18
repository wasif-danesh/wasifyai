"""The menu groups' setup cards (ADR-0109, stage FR1): generated from the actions' needs, priced
from the real catalogues, judged by the engine's fit figures (docs/spikes/first-run-fr0.md)."""

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from wasifyai_api.desktop_fit import GB
from wasifyai_api.desktop_models import load_catalogue
from wasifyai_api.setup_groups import (
    BY_ID,
    GROUPS,
    Sources,
    item_needs,
    parts_of_need,
    plan_all,
)
from wasifyai_platform_sdk.actions.model import Need

ROOT = Path(__file__).resolve().parents[3]
PRODUCTS = ROOT / "products"
ACTIONS = json.loads((ROOT / "docs" / "contracts" / "actions.json").read_text())["actions"]
MENU = (ROOT / "packages" / "ui" / "src" / "shell" / "menu.ts").read_text()
CATALOGUE = {
    e.id: e
    for e in load_catalogue(
        PRODUCTS,
        [
            "wasifyai-image",
            "wasifyai-video",
            "wasifyai-voice",
            "wasifyai-notebooks",
            "wasifyai-meetings",
        ],
    )  # fmt: skip
}


class Comp:
    def __init__(self, cid: str, size: int, state: str = "not_installed"):
        self.id, self.title, self._size, self._state = cid, cid, size, state

    def status(self) -> dict[str, Any]:
        if self._state == "installed":
            return {"state": "installed"}
        if self._state == "unsupported":
            return {"state": "unsupported", "reason": "Not on this computer."}
        return {"state": "not_installed", "needs_bytes": self._size}


COMPONENT_SIZES = {
    "llamacpp": 12_182_376, "comfyui": 12_872_812, "audiocpp": 42_023_522,
    "musetalk": 2_100_000_000, "indic": 1_200_000_000, "model3d": 8_980_000_000,
    "video-builder": 320_000_000, "music-analysis": 970_000_000, "reader": 420_000_000,
    "coding": 375_000_000, "node": 53_084_299,
}  # fmt: skip


def actions() -> list[Any]:
    return [
        SimpleNamespace(
            id=a["id"], ui=a.get("ui"),
            requires=tuple(Need(kind=r["kind"], name=r.get("name", "")) for r in a["requires"]),
        )
        for a in ACTIONS
    ]  # fmt: skip


def sources(
    memory_gb: int | None = 64,
    have: set[str] = frozenset(),  # type: ignore[assignment]
    chat: bool = False,
    languages: tuple[str, ...] = ("en",),
    unsupported: set[str] = frozenset(),  # type: ignore[assignment]
) -> Sources:
    def state(e: Any) -> dict[str, Any]:
        ready = e.id in have
        return {"status": "ready" if ready else "missing",
                "bytes_missing": 0 if ready else e.total_bytes}  # fmt: skip

    comps = {
        cid: Comp(cid, size, "installed" if cid in have else
                  "unsupported" if cid in unsupported else "not_installed")
        for cid, size in COMPONENT_SIZES.items()
    }  # fmt: skip
    return Sources(
        actions=actions(), catalogue=CATALOGUE, model_state=state, components=comps,
        media_default={"wasifyai-image": "flux2-klein-4b", "wasifyai-video": "ltx-video-2b"},
        chat_ready=chat, memory_bytes=memory_gb * GB if memory_gb else None, languages=languages,
        component_memory={"model3d": 19.5},
    )  # fmt: skip


def plans(**kw: Any) -> dict[str, dict[str, Any]]:
    return {p["id"]: p for p in plan_all(sources(**kw))}


def states(plan: dict[str, Any]) -> dict[str, str]:
    return {it["id"]: it["state"] for it in plan["items"]}


# ---- the groups are the menu's --------------------------------------------------------------


def test_every_menu_item_is_in_exactly_one_group() -> None:
    menu_ids = set(re.findall(r'\{ id: "([a-z0-9.]+)", label:', MENU))
    grouped = [i for g in GROUPS for i in g.items]
    assert len(grouped) == len(set(grouped))
    assert set(grouped) == menu_ids


def test_every_action_need_of_a_menu_item_resolves_or_is_known_to_need_nothing() -> None:
    nothing = {
        "product:wasifyai-image", "product:wasifyai-video", "product:wasifyai-notebooks",
        "product:wasifyai-meetings", "product:wasifyai-code", "product:wasifyai-creative",
        "product:wasifyai-model3d", "product:wasifyai-training", "runtime:styles",
        "runtime:models", "runtime:training", "runtime:decision_training",
    }  # fmt: skip
    src = sources()
    for g in GROUPS:
        for item in g.items:
            for need in item_needs(item, src, g):
                if str(need) in nothing:
                    continue
                assert parts_of_need(need, src), f"{item}: {need} resolves to no part"


def test_an_item_lists_every_part_its_actions_need() -> None:
    p = plans()
    voice = {it["id"]: set(it["parts"]) for it in p["voice"]["items"]}
    assert voice["voice.speak"] == {"component:audiocpp", "model:kokoro-82m"}
    assert voice["voice.voices"] >= {
        "model:qwen3-tts-0.6b-base",
        "model:qwen3-tts-1.7b-voicedesign",
    }
    assert voice["voice.edit"] >= {"model:dots-tts-edit"}
    assert {"chat", "model:parakeet-tdt-0.6b-v3"} <= voice["voice.dub"]
    meet = {it["id"]: set(it["parts"]) for it in p["meetings"]["items"]}
    # asking about a meeting goes through a notebook (decision 10)
    assert {"component:reader", "model:bge-small-en-v1.5", "model:sortformer-4spk-v2.1"} <= meet[
        "meetings.list"
    ]
    assert {"component:comfyui", "model:flux2-klein-4b"} == set(p["images"]["items"][0]["parts"])
    assert {"component:coding", "component:node"} == set(p["code"]["items"][0]["parts"])


# ---- the fit, on the FR0 table --------------------------------------------------------------


def test_a_big_mac_downloads_every_group() -> None:
    p = plans(memory_gb=64)
    for gid in ("voice", "music", "images", "video", "lipsync", "model3d", "meetings"):
        assert p[gid]["key"]["first"] is False, gid
        assert all(s == "needs_setup" for s in states(p[gid]).values()), gid
    # Voice: Kokoro, Parakeet, both Qwen3-TTS, Tone Color, dots and the runtime, about 9 GB
    assert 8.9 * GB < p["voice"]["download_bytes"] < 9.2 * GB


def test_an_8_gb_mac_leaves_out_edit_speech_and_keys_the_big_groups() -> None:
    p = plans(memory_gb=8)
    v = states(p["voice"])
    assert v["voice.edit"] == "left_out"  # dots needs 7 GB, over 6
    assert v["voice.voices"] == "needs_setup"  # describing needs 6 GB: at the limit, in
    assert sum(s == "needs_setup" for s in v.values()) == 6
    assert p["voice"]["download_bytes"] < 6.1 * GB
    assert p["chat"]["key"]["first"] is True
    for gid in ("images", "video", "lipsync", "model3d"):
        assert p[gid]["key"]["only"] is True, gid
    assert p["music"]["key"]["first"] is False
    # the lip sync engine is not fetched for a model that cannot run
    assert p["lipsync"]["download_bytes"] == 0


def test_a_16_gb_mac_keys_lip_sync_and_video_first_with_a_download_instead() -> None:
    p = plans(memory_gb=16)
    lip = p["lipsync"]
    assert lip["key"] == {"covers": True, "first": True, "only": False}
    assert lip["download_bytes"] > 6 * GB  # MuseTalk 12 GB fits the budget of 12 GB
    vid = p["video"]
    assert vid["key"]["first"] is True and vid["key"]["only"] is False
    assert vid["download_bytes"] == 0 or states(vid)["video.create"] == "left_out"
    assert vid["download_instead_bytes"] > 16 * GB  # LTX 14 GB runs, over the budget
    assert p["images"]["key"]["only"] is True


def test_a_24_gb_mac_cannot_run_klein_so_images_are_key_only() -> None:
    p = plans(memory_gb=24)
    assert p["images"]["key"]["only"] is True  # 24 GB judged, capacity 21.6 GB (FR0)
    assert p["video"]["key"]["first"] is True and p["video"]["download_bytes"] > 16 * GB
    assert p["model3d"]["key"] == {"covers": True, "first": True, "only": False}
    assert p["lipsync"]["key"]["first"] is False


# ---- what is set up -------------------------------------------------------------------------


def test_parts_already_set_up_are_not_counted_again() -> None:
    before = plans()["meetings"]["download_bytes"]
    after = plans(have={"audiocpp", "parakeet-tdt-0.6b-v3"})["meetings"]
    assert before - after["download_bytes"] == 915_733_744 + 42_023_522  # Parakeet and audio.cpp
    assert {p["id"] for p in after["parts"] if p["set_up"]} == {
        "model:parakeet-tdt-0.6b-v3",
        "component:audiocpp",
    }


def test_a_group_with_everything_set_up_is_ready() -> None:
    have = {"audiocpp", "kokoro-82m", "qwen3-tts-0.6b-base", "qwen3-tts-1.7b-voicedesign",
            "parakeet-tdt-0.6b-v3", "tone-color-vc", "dots-tts-edit"}  # fmt: skip
    p = plans(have=have, chat=True)
    assert p["voice"]["state"] == "ready" and p["voice"]["download_bytes"] == 0
    assert p["chat"]["state"] == "ready"


def test_groups_with_nothing_to_set_up_are_ready() -> None:
    p = plans()
    for gid in ("library", "models", "train"):
        assert p[gid]["state"] == "ready", gid
    assert BY_ID["train"].explain_only


def test_creative_studio_says_what_video_and_voice_add() -> None:
    p = plans(memory_gb=24)
    w = p["creative"]["with"]
    assert set(w) == {"video", "voice"}
    assert w["video"]["key_first"] is True and w["voice"]["key_first"] is False


def test_motion_graphics_needs_no_video_model_and_creative_counts_each_part_once() -> None:
    p = plans(memory_gb=64)
    assert {x["ref"] for x in p["motion"]["parts"]} == {"video-builder"}
    creative = p["creative"]
    ids = [x["id"] for x in creative["parts"]]
    assert len(ids) == len(set(ids))
    assert {"model:ltx-video-2b", "model:kokoro-82m", "component:music-analysis"} <= set(ids)
    assert creative["download_bytes"] > p["video"]["download_bytes"] + p["voice"]["download_bytes"]


def test_an_unsupported_part_makes_its_item_unavailable() -> None:
    p = plans(unsupported={"musetalk"})
    assert states(p["lipsync"])["voice.lipsync"] == "unavailable"


# ---- languages (decision 15) ------------------------------------------------------------


def test_indian_languages_join_voice_only_for_an_indian_language() -> None:
    plain = plans(languages=("en",))["voice"]
    bengali = plans(languages=("bn", "en"))["voice"]
    assert not any(p["ref"] == "indic" for p in plain["parts"])
    assert any(p["ref"] == "indic" for p in bengali["parts"])
    assert bengali["download_bytes"] - plain["download_bytes"] > 7 * GB
