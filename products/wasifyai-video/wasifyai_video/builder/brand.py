"""A person's brand kit (ADR-0096 MX7): name, colours, letters, a logo, and the words of the end
card. Set once, kept per person, and copied into each project of scenes that uses it, so a project
stays as it was made when the kit changes later, and a video can always be made again.

Colours reach the page's css only as checked `#rrggbb`; the logo is a file like any other, checked
when it was added, kept at a key made here."""

import asyncio
import re
from typing import Any

from wasifyai_video.builder import media, templates

KIT_FOLDER = "brand"  # where the logo is kept: beside the projects' folders, never a project's id
_COLOURS = ("background", "second", "text", "accent")
DEFAULTS = {"background": "#0b1220", "second": "#1c2b4a", "text": "#f5f7fb", "accent": "#4f8cff"}
_HEX = re.compile(r"#[0-9a-fA-F]{6}")


def normalize_kit(raw: Any) -> dict[str, Any]:
    """A kit, checked and completed. Raises `SlotError` with the sentence the person is shown."""
    if not isinstance(raw, dict):
        raise templates.SlotError("A brand needs a name and colours.")
    extra = sorted(set(raw) - {"name", *_COLOURS, "font", "action", "address", "logo_on_scenes"})
    if extra:
        raise templates.SlotError(f"A brand has no setting called {extra[0]}.")
    font = raw.get("font", "sans")
    if font not in templates.FONTS:
        raise templates.SlotError(f"The letters must be one of: {', '.join(templates.FONTS)}.")
    colours = {}
    for name in _COLOURS:
        value = str(raw.get(name, DEFAULTS[name]))
        if not _HEX.fullmatch(value):
            raise templates.SlotError(f"The {name} colour must look like #1a2b3c.")
        colours[name] = value.lower()
    return {
        "name": templates.plain_text(raw.get("name"), "brand name", 60),
        **colours,
        "font": font,
        "action": templates.plain_text(raw.get("action"), "call to action", 60),
        "address": templates.plain_text(raw.get("address"), "web address", 80),
        "logo_on_scenes": bool(raw.get("logo_on_scenes", True)),
    }


def in_document(document: dict[str, Any], kit: dict[str, Any], logo: str | None) -> dict[str, Any]:
    """A document with the brand on it; `logo` is the id of its copy among the project's files."""
    brand = {
        **{name: kit[name] for name in _COLOURS},
        "logo": logo,
        "logo_on_scenes": kit["logo_on_scenes"],
    }
    return {**document, "brand": brand, "font": kit["font"]}


def fill_end_cards(document: dict[str, Any], kit: dict[str, Any]) -> dict[str, Any]:
    """Starting words on the end cards of a new project: the kit's, when it has them."""
    wanted = {k: v for k, v in (("action", kit["action"]), ("address", kit["address"])) if v}
    scenes = [
        {**s, "fields": {**s["fields"], **wanted}} if s["kind"] == "end_card" else s
        for s in document["scenes"]
    ]
    return {**document, "scenes": scenes}


async def bring_logo(deps: Any, owner: tuple[str, str, str], kit: dict[str, Any], cid: str) -> Any:
    """A copy of the kit's logo among a project's files, or None when the kit has no logo. The copy
    has the logo's own file name, so bringing it twice is one file."""
    logo = kit.get("logo_asset")
    if not logo:
        return None
    data = await deps.storage.get_for(owner, media.rel_path(KIT_FOLDER, logo["file"]))
    await deps.storage.put_for(
        owner, media.rel_path(cid, logo["file"]), data, media.type_of(logo["file"])
    )
    return logo


async def use_on(
    deps: Any, store: Any, owner: tuple[str, str, str], found: dict[str, Any], kit: dict[str, Any]
) -> dict[str, Any]:
    """The project's document with the brand on it, and the logo among its files; not yet saved,
    apart from the file, which stays whatever is decided about the brand."""
    tenant, _, user = owner
    logo = await bring_logo(deps, owner, kit, found["id"])
    assets = list(found["slots"].get("assets") or [])
    if logo and not any(a["id"] == logo["id"] for a in assets):
        assets.append(logo)
        await asyncio.to_thread(store.set_assets, tenant, user, found["id"], assets)
    return in_document({**found["slots"], "assets": assets}, kit, logo["id"] if logo else None)


async def on_new_project(
    deps: Any, store: Any, owner: tuple[str, str, str], found: dict[str, Any]
) -> dict[str, Any]:
    """Set once, used in every project: a new project of scenes starts with the person's brand and
    its words on the end cards. It is how the project begins, so it is no step for Undo."""
    tenant, _, user = owner
    kit = await asyncio.to_thread(store.get_brand, tenant, user)
    if kit is None or found["template"] != templates.SCENES:
        return found
    document = fill_end_cards(await use_on(deps, store, owner, found, kit), kit)
    slots = templates.normalize_slots(templates.SCENES, document)
    return await asyncio.to_thread(store.begin_with, tenant, user, found["id"], slots)
