"""Styles (LoRAs) as actions (ADR-0068, ADR-0091 decision 12): what the assistant and MCP may do
with the image screens' styles. Choosing one for a picture is the `styles` input of the image
actions.

    styles.list           the styles and saved looks on this computer        read
    styles.add_from_hub   get one from Hugging Face (asks, shows the size)   make, needs consent
    styles.remove         delete the app's copy of one                       destroy (always asks)
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from wasifyai_platform_sdk.actions import (
    Action,
    ActionContext,
    ActionRefused,
    CallBinding,
    Outcome,
    need_runtime,
)

STYLES = need_runtime("styles")
CONSENT_STYLE = (
    "I agree to download this style from Hugging Face to this computer. Its file and size are "
    "shown in the window before I approve."
)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _state(ctx: ActionContext) -> Any:
    state = getattr(ctx.deps, "state", None)
    if getattr(state, "desktop_styles", None) is None:
        raise ActionRefused("unavailable", "Styles are kept by the desktop app.")
    return state


# ---- styles.list ------------------------------------------------------------------------------


class ListIn(Strict):
    pass


class StyleRow(BaseModel):
    style_id: str
    title: str
    usable: bool
    made_for: str
    word: str | None = None
    source: str


class ListOut(BaseModel):
    styles: list[StyleRow]
    looks: list[str]


def _made_for(s: Any) -> str:
    if s.fit == "other":
        return f"made for {s.model or 'another model'}: it cannot be used here"
    if s.fit == "unsure":
        return "not sure which model it was made for"
    return (
        "made for klein base: its look may not show" if s.look_may_not_show
        else f"made for {s.model}"
    )  # fmt: skip


async def _list(p: ListIn, ctx: ActionContext) -> Outcome:
    svc = _state(ctx).desktop_styles
    styles = await svc.all()
    rows = [
        {
            "style_id": s.id, "title": s.title, "usable": s.fit != "other",
            "made_for": _made_for(s), "word": s.trigger,
            "source": {"trained": "made by the person in Train", "file": "added from this computer",
                       "found": "copied from another app", "hub": "from Hugging Face"}
            .get(s.source.get("kind"), "added"),
        }
        for s in styles
    ]  # fmt: skip
    looks = [str(x.get("name")) for x in await svc.looks()]
    lines = [
        f"- {r['title']} (id {r['style_id']}; {r['made_for']}"
        + (f"; word: {r['word']}" if r["word"] else "")
        + ")"
        for r in rows
    ]
    text = (
        f"{len(rows)} styles on this computer:\n" + "\n".join(lines)
        if rows
        else "No styles on this computer yet."
    )
    if looks:
        text += "\nSaved looks: " + ", ".join(looks)
    text += (
        "\nTo use one, pass styles: [{id, strength}] to image.generate and put its word in the "
        "prompt."
    )
    return Outcome.ok({"styles": rows, "looks": looks}, text)


# ---- styles.add_from_hub ----------------------------------------------------------------------


class HubIn(Strict):
    repo: str = Field(
        min_length=3, max_length=200,
        description="The Hugging Face repository, owner/name, or its address.",
    )  # fmt: skip
    file: str | None = Field(
        None, max_length=300,
        description="The .safetensors file to get; leave it out when the repository has one.",
    )  # fmt: skip


class HubOut(BaseModel):
    download_id: str
    repo: str
    file: str
    bytes_total: int


async def _hub(ctx: ActionContext) -> Any:
    from wasifyai_api.desktop_styles import _JOBS, HubStyles

    state = _state(ctx)
    if state.desktop_hub is None or state.desktop_models is None:
        raise ActionRefused("unavailable", "Getting styles is done in the desktop app.")
    return HubStyles(state.desktop_styles, state.desktop_hub, state.desktop_models, _JOBS)


async def _pick(p: HubIn, ctx: ActionContext) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    from wasifyai_api.desktop_hub import HubError

    hub = await _hub(ctx)
    try:
        found = await hub.files(p.repo)
    except HubError as e:
        raise ActionRefused(e.code, e.message) from None
    files = found["files"]
    chosen = next((f for f in files if f["name"] == p.file), None) if p.file else None
    if chosen is None and not p.file and len(files) == 1:
        chosen = files[0]
    if chosen is None:
        names = ", ".join(f["name"] for f in files) or "none"
        raise ActionRefused(
            "choose_file", f"Say which file to get. The .safetensors files there: {names}."
        )
    return hub, found, chosen


async def _hub_check(p: HubIn, ctx: ActionContext) -> None:
    await _pick(p, ctx)


async def _hub_start(p: HubIn, ctx: ActionContext) -> Outcome:
    from wasifyai_api.desktop_hub import HubError
    from wasifyai_api.desktop_models import DownloadError

    hub, found, chosen = await _pick(p, ctx)
    try:
        d = await hub.download(found["repo"], chosen["name"], chosen["size"])
    except (HubError, DownloadError) as e:
        raise ActionRefused(getattr(e, "code", "busy"), getattr(e, "message", str(e))) from None
    return Outcome.ok(
        {
            "download_id": d["id"],
            "repo": found["repo"],
            "file": chosen["name"],
            "bytes_total": chosen["size"],
        },  # fmt: skip
        f"Getting {chosen['name']} from {found['repo']} ({chosen['size'] // 1_000_000} MB). It is "
        "checked when it arrives and then appears in styles.list; models.status shows the "
        "download.",
    )


# ---- styles.remove ----------------------------------------------------------------------------


class RemoveIn(Strict):
    style_id: str = Field(min_length=6, max_length=32, description="From styles.list.")


class RemoveOut(BaseModel):
    style_id: str
    title: str


async def _remove(p: RemoveIn, ctx: ActionContext) -> Outcome:
    svc = _state(ctx).desktop_styles
    try:
        s = await svc.get(p.style_id)
        await svc.delete(p.style_id)
    except KeyError:
        raise ActionRefused("not_found", "That style is not on this computer.") from None
    return Outcome.ok(
        {"style_id": s.id, "title": s.title},
        f"{s.title} was deleted from this computer. Pictures made with it stay.",
    )


def styles_actions() -> list[Action]:
    return [
        Action(
            id="styles.list", title="Styles on this computer",
            summary="The styles (LoRAs) and saved looks the image screens can use.",
            description=(
                "List the styles (also called LoRAs) on this computer, with what model each was "
                "made for, whether it can be used here, and its word, plus the saved looks. Use it "
                "before image.generate with styles, to find a style's id and its word."
            ),
            input=ListIn, output=ListOut, examples=({},),
            effect="read", flags=("private",), requires=(STYLES,), bind=CallBinding(_list),
            ui="images.create",
        ),
        Action(
            id="styles.add_from_hub", title="Get a style from Hugging Face",
            summary="Download a style from a Hugging Face repository to this computer.",
            description=(
                "Get a style (a .safetensors LoRA) from a Hugging Face repository. The person is "
                "shown the file and its size and must approve. The file is checked when it "
                "arrives; follow the download with models.status, then find the style in "
                "styles.list."
            ),
            input=HubIn, output=HubOut,
            examples=({"repo": "Sawata97/flux2_4b_koni_animestyle"},),
            effect="make", flags=("needs_consent", "leaves_device", "costly"),
            consent=CONSENT_STYLE, requires=(STYLES,),
            bind=CallBinding(_hub_start, check=_hub_check), ui="images.create",
        ),
        Action(
            id="styles.remove", title="Delete a style",
            summary="Delete the app's copy of a style from this computer.",
            description=(
                "Delete a style the app keeps (its copy, never a file another app keeps). "
                "Pictures made with it stay. Always asks the person."
            ),
            input=RemoveIn, output=RemoveOut, examples=({"style_id": "9a07a5c7d23e"},),
            effect="destroy", requires=(STYLES,), bind=CallBinding(_remove),
            ui="images.create",
        ),
    ]  # fmt: skip


__all__ = ["styles_actions"]
