"""What each menu group needs before it works, on this computer (ADR-0109, stage FR1).

    GROUPS            the menu groups and single items, with their menu items (shell/menu.ts)
    parts_of_need()   the parts one need asks for: a component, a catalogue model or the chat
    group_plan()      one group's card: its items, their parts, the fit, the key, the size

A group's card is generated, not written: its items are the menu items of the group, an item's
needs are the `requires` of the actions whose `ui` points at it (ADR-0068), and each need resolves
to parts here. A new action with a new need changes its group's card without a new screen.

The fit uses the engine's own figures and rules (`desktop_fit`, docs/spikes/first-run-fr0.md): a
model is part of the group's download when it needs at most 75 % of this computer's memory (the
fit check's budget), can still be downloaded on request up to 90 % (its capacity), and the key is
the main button when a key covers the whole group and a model needs more than half the memory. The
card judges the computer, not this moment: the total memory, never what is free now.
"""

import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from wasifyai_platform_sdk.actions.model import Need

from wasifyai_api.desktop_fit import GB, physical_memory_bytes
from wasifyai_api.identity import Identity, get_identity
from wasifyai_api.services import services_of

INCLUDE_SHARE = 0.75  # the fit check's budget on Apple silicon
CAN_RUN_SHARE = 0.9  # its capacity
KEY_FIRST_SHARE = 0.5
SMALL_CHAT_BYTES = 8 * GB  # ADR-0109 decision 3: at this memory or less, chat is key first
INDIAN = frozenset({"bn", "hi", "mr", "te", "ta", "gu"})


@dataclass(frozen=True)
class Group:
    id: str
    items: tuple[str, ...]  # the menu items (ids of shell/menu.ts)
    uses: tuple[str, ...] = ()  # other groups this one's button sets up too (decision 9)
    key_covers: bool = False  # a cloud key covers every item of the group (decision 13)
    explain_only: bool = False  # Train: each kind sets itself up when chosen (decision 8)
    adds: tuple[str, ...] = ()  # needs added to every item (Meetings asks through a notebook)


# In the menu's order. A test checks the items against packages/ui/src/shell/menu.ts.
GROUPS: tuple[Group, ...] = (
    Group("chat", ("chat",)),
    Group("notebook", ("notebook.create", "notebook.list")),
    Group("meetings", ("meetings.record", "meetings.list", "meetings.people"), adds=("notebooks",)),
    Group(
        "images",
        ("images.create", "images.edit", "images.inpaint", "images.reference"),
        key_covers=True,
    ),  # fmt: skip
    Group("video", ("video.create", "video.animate", "video.extend"), key_covers=True),
    Group(
        "voice",
        (
            "voice.speak",
            "voice.transcribe",
            "voice.voices",
            "voice.convert",
            "voice.edit",
            "voice.dub",
            "voice.audiobook",
        ),
    ),  # fmt: skip
    Group("music", ("music.create", "music.lyrics", "music.separate")),
    Group("code", ("code.projects", "code.scheduled", "code.extensions")),
    Group("lipsync", ("voice.lipsync",), key_covers=True),
    Group("creative", ("creative",), uses=("video", "voice")),
    Group("motion", ("motion",)),
    Group("model3d", ("model3d",), key_covers=True),
    Group("library", ("library",)),
    Group("train", ("train",), explain_only=True),
    Group("models", ("models",)),
)
BY_ID = {g.id: g for g in GROUPS}

# Needs of an item that no action of it states, because its actions only save: Voices saves a copied
# or described voice without running a model, but speaking in one runs the copy or describe model.
# The image and video actions state only that their product is served (`product:`), which Motion
# graphics also states without running a picture or video model; their screens run the model in use.
IMAGE = Need(kind="model", name="image")
VIDEO = Need(kind="model", name="video")
ITEM_ALSO: dict[str, tuple[Need, ...]] = {
    "voice.voices": (Need(kind="model", name="clone"), Need(kind="model", name="design")),
    **{i: (IMAGE,) for i in ("images.create", "images.edit", "images.inpaint", "images.reference")},
    **{i: (VIDEO,) for i in ("video.create", "video.animate", "video.extend")},
}
MEDIA_PRODUCT = {"image": "wasifyai-image", "video": "wasifyai-video"}

# what each voice-model engine runs on (VoiceModel.engine)
ENGINE_COMPONENT = {
    "audiocpp": "audiocpp", "sidecar": "musetalk", "indic": "indic", "comfyui": "comfyui"
}  # fmt: skip


@dataclass(frozen=True)
class PartRef:
    kind: str  # component, model, chat
    ref: str = ""  # the component id or the catalogue model id

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.ref}" if self.ref else self.kind


@dataclass
class Sources:
    """What the plan reads, gathered once per request so a test can hand in its own."""

    actions: list[Any]  # Action (id, ui, requires)
    catalogue: dict[str, Any]  # ModelEntry by id
    model_state: Any  # (ModelEntry) -> entry_state dict
    components: dict[str, Any]  # Component by id
    media_default: dict[str, str]  # product id -> the model in use (chosen, else the first)
    chat_ready: bool
    memory_bytes: int | None
    languages: tuple[str, ...] = ()  # the app's or the computer's languages, two letters
    # GB, for a component that runs its own model (3D)
    component_memory: dict[str, float] = field(default_factory=dict)


def _voice_model(src: Sources, task: str) -> Any | None:
    """The model a task would use: one on this computer, else the recommended, else the first."""
    able = [e for e in src.catalogue.values() if e.voice is not None and task in e.voice.tasks]
    here = [e for e in able if src.model_state(e)["status"] == "ready"]
    recommended = [e for e in able if task in e.voice.recommended]
    for pick in (here, recommended, able):
        if pick:
            return pick[0]
    return None


def parts_of_need(need: Need, src: Sources) -> list[PartRef]:
    """The parts one need asks for. A need with no parts (a served product, styles) is met."""
    k, n = need.kind, need.name
    if k == "product" and n == "wasifyai-voice":
        return [PartRef("component", "audiocpp")]
    if k == "model" and n in MEDIA_PRODUCT:
        model = src.media_default.get(MEDIA_PRODUCT[n])
        return [PartRef("component", "comfyui")] + ([PartRef("model", model)] if model else [])
    if k == "model":
        e = _voice_model(src, n)
        if e is None:
            return []
        comp = ENGINE_COMPONENT.get(e.voice.engine, "audiocpp")
        return [PartRef("component", comp), PartRef("model", e.id)]
    if k == "runtime" and n == "meetings":
        return [PartRef("model", m) for m in ("sortformer-4spk-v2.1", "eres2net-voxceleb")]
    if k == "notebooks":
        return [PartRef("component", "reader"), PartRef("model", "bge-small-en-v1.5")]
    if k == "chat":
        return [PartRef("chat")]
    if k == "runtime" and n == "music_analysis":
        return [PartRef("component", "music-analysis")]
    if k == "runtime" and n == "video-builder":
        return [PartRef("component", "video-builder")]
    if k == "runtime" and n == "model3d":
        return [PartRef("component", "model3d")]
    if k == "runtime" and n == "coding":
        return [PartRef("component", "coding"), PartRef("component", "node")]
    return []  # product (served), styles, models, training (each kind sets itself up), web


def item_needs(item: str, src: Sources, group: Group) -> list[Need]:
    needs: list[Need] = []
    for a in src.actions:
        if a.ui == item:
            needs += [r for r in a.requires if r not in needs]
    needs += [n for n in ITEM_ALSO.get(item, ()) if n not in needs]
    for used in group.uses:  # Creative Studio's button sets up Video and Voice too (decision 9)
        for other in BY_ID[used].items:
            needs += [n for n in item_needs(other, src, BY_ID[used]) if n not in needs]
    if item == "chat":
        needs.append(Need(kind="chat"))
    for extra in group.adds:
        n = Need(kind=extra)  # type: ignore[arg-type]
        if n not in needs:
            needs.append(n)
    return needs


def _indian(src: Sources) -> bool:
    return any(lang in INDIAN for lang in src.languages)


def _indic_parts(src: Sources) -> list[PartRef]:
    ids = [e.id for e in src.catalogue.values() if e.voice and e.voice.engine == "indic"]
    return [PartRef("component", "indic")] + [PartRef("model", i) for i in ids]


def _part_view(p: PartRef, src: Sources) -> dict[str, Any]:
    """Its title, what it still costs, whether it is set up, the memory it needs and whether it
    can be here."""
    view: dict[str, Any] = {
        "id": p.key, "kind": p.kind, "ref": p.ref, "title": "", "bytes": 0, "set_up": False,
        "installing": False, "memory_bytes": None, "available": True, "reason": "",
    }  # fmt: skip
    if p.kind == "chat":
        view.update(title="Chat model", set_up=src.chat_ready)
        return view  # its size is the chat choice's, which the window knows
    if p.kind == "model":
        e = src.catalogue.get(p.ref)
        if e is None:
            view.update(title=p.ref, available=False, reason="This model is not in this build.")
            return view
        st = src.model_state(e)
        view.update(
            title=e.title, bytes=int(st["bytes_missing"]), set_up=st["status"] == "ready",
            memory_bytes=int(e.approx_ram_gb * GB) if e.approx_ram_gb else None,
        )  # fmt: skip
        return view
    c = src.components.get(p.ref)
    if c is None:
        view.update(title=p.ref, available=False, reason="This is not available on this computer.")
        return view
    s = c.status()
    state = s.get("state")
    view.update(
        title=c.title, set_up=state == "installed", installing=state == "installing",
        bytes=int(s.get("needs_bytes") or 0) if state in ("not_installed", "failed") else 0,
    )  # fmt: skip
    if state == "unsupported":
        view.update(available=False, reason=str(s.get("reason") or "Not on this computer."))
    gb = src.component_memory.get(p.ref)
    if gb:
        view["memory_bytes"] = int(gb * GB)
    return view


def _fit(memory: int | None, total: int | None) -> str:
    """include (part of the download), on_request (only under "Download instead"), cannot_run."""
    if not memory or not total:
        return "include"
    if memory <= INCLUDE_SHARE * total:
        return "include"
    if memory <= CAN_RUN_SHARE * total:
        return "on_request"
    return "cannot_run"


def item_state(mine: list[dict[str, Any]]) -> str:
    """ready; needs_setup; partly (some of its models cannot be in the download here: Voices
    copies but cannot describe on a small computer); left_out (none of its models can);
    unavailable (a part is not made for this computer)."""
    if any(not p["available"] for p in mine):
        return "unavailable"
    if all(p["set_up"] for p in mine):
        return "ready"
    models = [p for p in mine if p["memory_bytes"]]  # what runs a model: its fit decides
    out = [p for p in models if p["fit"] != "include"]
    if models and len(out) == len(models):
        return "left_out"
    return "partly" if out else "needs_setup"


def group_plan(group: Group, src: Sources) -> dict[str, Any]:
    """One group's card, as data. The window says it in words (packages/ui words)."""
    total = src.memory_bytes
    parts: dict[str, dict[str, Any]] = {}
    items: list[dict[str, Any]] = []
    for item in group.items:
        refs: list[PartRef] = []
        for need in item_needs(item, src, group):
            refs += [r for r in parts_of_need(need, src) if r not in refs]
        if group.id == "voice" and item in ("voice.speak", "voice.transcribe") and _indian(src):
            refs += [r for r in _indic_parts(src) if r not in refs]
        for r in refs:
            if r.key not in parts:
                v = _part_view(r, src)
                v["fit"] = _fit(v["memory_bytes"], total)
                v["items"] = []
                parts[r.key] = v
            parts[r.key]["items"].append(item)
        items.append({"id": item, "parts": [r.key for r in refs]})
    for it in items:
        it["state"] = item_state([parts[k] for k in it["parts"]])

    # a part is downloaded when it fits and some item that can work here needs it: the lip sync
    # engine is not fetched for a model that cannot run
    working = {it["id"] for it in items if it["state"] in ("needs_setup", "partly", "ready")}
    for p in parts.values():
        p["included"] = bool(
            p["available"] and p["fit"] == "include" and working.intersection(p["items"])
        )
    on_request_items = {
        it["id"] for it in items
        if it["state"] == "left_out"
        and all(parts[k]["fit"] != "cannot_run" for k in it["parts"])
    }  # fmt: skip
    download = sum(p["bytes"] for p in parts.values() if p["included"] and not p["set_up"])
    instead = sum(
        p["bytes"] for p in parts.values()
        if not p["set_up"] and p["available"] and p["fit"] != "cannot_run"
        and (p["included"] or on_request_items.intersection(p["items"]))
    )  # fmt: skip
    key_first = bool(
        group.key_covers
        and total
        and any((p["memory_bytes"] or 0) > KEY_FIRST_SHARE * total for p in parts.values())
    )
    if group.id == "chat" and total and total <= SMALL_CHAT_BYTES:
        key_first = True
    nothing_runs = bool(items) and all(it["state"] in ("left_out", "unavailable") for it in items)
    can_download = not nothing_runs or bool(on_request_items)
    ready = all(it["state"] == "ready" for it in items)
    return {
        "id": group.id,
        "items": items,
        "parts": list(parts.values()),
        "uses": list(group.uses),
        "explain_only": group.explain_only,
        "state": "ready" if ready or not parts else "needs_setup",
        "download_bytes": download,
        "download_instead_bytes": instead,
        "key": {
            "covers": group.key_covers,
            "first": key_first or (group.key_covers and nothing_runs),
            "only": group.key_covers and not can_download,
        },
        "memory_bytes": total,
    }


def plan_all(src: Sources) -> list[dict[str, Any]]:
    out = [group_plan(g, src) for g in GROUPS]
    by = {p["id"]: p for p in out}
    for p in out:  # Creative Studio's button sets up what it uses (decision 9)
        if p["uses"]:
            p["with"] = {u: {"key_first": by[u]["key"]["first"]} for u in p["uses"]}
    return out


def computer_languages() -> tuple[str, ...]:
    """The computer's languages, two letters each: macOS's list, else the environment's."""
    found: list[str] = []
    if sys.platform == "darwin":
        try:
            raw = subprocess.run(
                ["defaults", "read", "-g", "AppleLanguages"],
                capture_output=True, text=True, timeout=2, check=False,
            ).stdout  # fmt: skip
            found += [w.strip(' ",()\n')[:2] for w in raw.split("\n") if w.strip(' ",()\n')]
        except (OSError, subprocess.SubprocessError):
            pass
    for var in ("LC_ALL", "LANG"):
        v = os.environ.get(var, "")
        if v and v not in ("C", "POSIX"):
            found.append(v[:2])
    return tuple(dict.fromkeys(x.lower() for x in found if x))


def memory_bytes() -> int | None:
    return physical_memory_bytes()


# ---- the route --------------------------------------------------------------------------------

router = APIRouter(prefix="/desktop/setup", tags=["desktop"])


async def sources_of(request: Request) -> Sources:
    s = services_of(request)
    models = s.desktop_models
    if models is None or s.actions is None:
        raise HTTPException(404, "Setting up is done in the desktop app.")
    machine = await models.machine()
    media_default: dict[str, str] = {}
    if s.media is not None:
        media_default = {pm.product_id: pm.chosen for pm in await s.media.model_choices()}
    lang = s.desktop_language
    chat_ready = bool(lang is not None and lang.selected is not None)
    keys = s.own_keys
    if not chat_ready and keys is not None and hasattr(keys, "route"):
        # chat and writing on a cloud model with the person's key (ADR-0100): nothing to download
        chat_ready = await keys.route("chat") is not None
    comp_memory: dict[str, float] = {}
    if s.model3d is not None:
        comp_memory["model3d"] = float(s.model3d.installer.pins.need_gb)
    return Sources(
        actions=s.actions.registry.all(),
        catalogue=dict(models.catalogue),
        model_state=lambda e: models.entry_state(e, machine),
        components=dict(s.components.components) if s.components is not None else {},
        media_default=media_default,
        chat_ready=chat_ready,
        memory_bytes=memory_bytes(),
        languages=computer_languages(),
        component_memory=comp_memory,
    )


@router.get("/groups")
async def setup_groups(request: Request, _: Identity = Depends(get_identity)) -> dict[str, Any]:
    """Every menu group's card: what it needs on this computer, what is set up and what fits."""
    src = await sources_of(request)
    return {"groups": plan_all(src), "memory_bytes": src.memory_bytes}
