"""The assistant's own action: keep a file the person attached in the chat as a library item, so the
other actions can work on it (docs/chat-does-everything-plan.md, stage CE1).

An attachment is an upload of the chat (ADR-0083): a picture checked and stored again as a PNG, a
recording or a clip checked the same way (stage CE2). The model only knows its id, which the chat
tells it; the file is read here, under the person's own prefix, and handed to the library kind that
takes it (`LibraryKind.keep`), which stores it as an Images import would."""

from pydantic import BaseModel, ConfigDict, Field
from wasifyai_platform_sdk import UploadError
from wasifyai_platform_sdk.actions import Action, ActionContext, CallBinding, Outcome
from wasifyai_platform_sdk.actions.helpers import attached_file
from wasifyai_platform_sdk.actions.library import LibraryKind, creation_uri

from wasifyai_assistant.attachments import STORED

PRODUCT_ID = "wasifyai-assistant"
# where the chat keeps each kind of attachment that can be kept (the upload's key under the person's
# prefix); a document goes into a notebook instead (CE4)
STORED_AS = {kind: ext for ext, kind in STORED if kind != "document"}
NOUNS = {"image": "picture", "audio": "recording", "video": "clip"}


class KeepIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attachment_id: str = Field(
        min_length=8, max_length=64, description="The attachment's id, as the chat names it."
    )
    title: str = Field(
        "", max_length=120, description="A name for it in the library; its file name if left out."
    )
    as_kind: str = Field(
        "", max_length=20,
        description="What to keep it as when it could be more than one: track (the sound of a "
        "recording or a clip) or video (a clip). Left out, a picture is kept as an image, a "
        "recording as a track and a clip as a video.",
    )  # fmt: skip


class KeepOut(BaseModel):
    kind: str
    id: str
    title: str
    uri: str


async def find_attachment(ctx: ActionContext, attachment_id: str) -> tuple[str, bytes] | None:
    """The kind and bytes of one of the person's chat attachments, or None (`attached_file`:
    the attachment of a sent message counts, and only the person's own)."""
    for kind, ext in STORED_AS.items():
        data = await attached_file(ctx, attachment_id, ext)
        if data is not None:
            return kind, data
    return None


# what each kind of attachment is kept as when nothing else is asked
DEFAULT_AS = {"image": "image", "audio": "track", "video": "video"}


def keeper(ctx: ActionContext, kind: str, as_kind: str = "") -> LibraryKind | None:
    """The library kind that keeps an attachment of `kind`: the one asked for (`as_kind`), else the
    usual one, else any that takes it."""
    takers = [k for k in ctx.library.values() if kind in k.takes and k.keep]
    if as_kind:
        return next((k for k in takers if k.kind == as_kind), None)
    usual = next((k for k in takers if k.kind == DEFAULT_AS.get(kind)), None)
    return usual or next(iter(takers), None)


async def _keep(p: KeepIn, ctx: ActionContext) -> Outcome:
    found = await find_attachment(ctx, p.attachment_id.strip())
    if found is None:
        return Outcome.refused(
            "That attachment is not there any more. Please attach the file again.", "not_found"
        )
    kind, data = found
    library = keeper(ctx, kind, p.as_kind.strip())
    if library is None or library.keep is None:
        return Outcome.refused(
            f"This computer cannot keep an attached {NOUNS.get(kind, kind)}"
            + (f" as a {p.as_kind.strip()}." if p.as_kind.strip() else "."),
            "unavailable",
        )
    try:
        item = await library.keep(ctx, data, p.title.strip() or "")
    except UploadError as e:
        return Outcome.refused(e.message, "invalid_input")
    noun = library.noun
    return Outcome.ok(
        {
            "kind": item.kind,
            "id": item.id,
            "title": item.title,
            "uri": creation_uri(item.kind, item.id),
        },
        f'The attached {noun} is in the library now as "{item.title}" ({item.kind} id {item.id}). '
        f"Use that id to work on it.",
    )


def actions() -> list[Action]:
    return [
        Action(
            id="library.keep_attachment", title="Keep an attached file",
            summary="Save a file the person attached in this chat to the library, to work on it.",
            description=(
                "Save a picture, recording or clip the person attached in this chat to their "
                "library and get its id. "
                "Do this first whenever the person asks to change, animate, make talk, turn into "
                "3D or otherwise use an attached file: the other actions only take library items. "
                "Then propose the action they asked for with the id this returns."
            ),
            input=KeepIn, output=KeepOut,
            examples=({"attachment_id": "0b7c1f9e-0000-4000-8000-000000000000"},
                      {"attachment_id": "0b7c1f9e-0000-4000-8000-000000000000", "title": "Beach"}),
            effect="make", flags=("private",), product=PRODUCT_ID, bind=CallBinding(_keep),
            surfaces=("assistant",),  # attachments are the chat's own
            ui_exempt=(
                "It runs from the chat: a file attached there becomes a library item. On the "
                "screens, each product's own Import or upload does the same."
            ),
        )
    ]  # fmt: skip
