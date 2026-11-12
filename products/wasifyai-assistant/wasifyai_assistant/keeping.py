"""An attachment named where a library item belongs is kept in the library first
(docs/chat-does-everything-plan.md, CE1).

The other actions take library ids. A model often proposes the action it was asked for straight
away with the attachment's id, or its file name, in the id field ("animate 7a1e…" or
"animate beach.jpg"), instead of first calling `library.keep_attachment`. So the chat does that
step itself: each id param (`…_id`, `…_ids`) that is exactly an attachment of this conversation
is kept with `library.keep_attachment` and replaced by the new library id, before the proposed
action runs or shows its card. The keep is not asked about: it only copies the person's own file
into their own library and costs nothing; the action itself still asks as the chat says."""

from collections.abc import Awaitable, Callable
from typing import Any

from wasifyai_assistant.attachments import attachment_parts, clean_name
from wasifyai_assistant.store import Message

KEEP = "library.keep_attachment"

# runs `library.keep_attachment` for one attachment id, kept as the library kind given ("" for the
# usual one); the library id, or None when it failed
Keep = Callable[[str, str], Awaitable[str | None]]

# what an id field takes, so a clip named as `source_id` (a recording: Dub, Transcribe) is kept as a
# track and as `video_id` (Extend) as a clip; a field not named here keeps the usual kind
# fields that take an attachment as it is (the keep itself; notebook sources, CE4)
TAKES_ATTACHMENT = {"attachment_id", "attachment_ids"}
AS_KIND = {
    "source_id": "track", "track_id": "track", "video_id": "video",
    "image_id": "image", "image_ids": "image",
}  # fmt: skip


def attachment_names(history: list[Message]) -> dict[str, str]:
    """Every way the model may name an attachment of this conversation (its id, its file name),
    mapped to its id. A file name two attachments share names neither."""
    out: dict[str, str] = {}
    shared: set[str] = set()
    for m in history:
        if m.role != "user":
            continue
        for p in attachment_parts(m):
            ident = str(p.get("id") or "")
            if not ident:
                continue
            out[ident] = ident
            name = clean_name(p.get("name"))
            if name in out and out[name] != ident:
                shared.add(name)
            out[name] = ident
    for name in shared:
        out.pop(name, None)
    return out


async def kept_in_place(
    action_id: str,
    params: dict[str, Any],
    names: dict[str, str],
    keep: Keep,
    done: dict[tuple[str, str], str],
) -> dict[str, Any]:
    """`params` with each attachment it names replaced by its library id. `done` remembers what
    was kept in this run, so one file is kept once. A field that takes an attachment itself
    (`attachment_id`, `attachment_ids`: the keep, a notebook's sources) gets its id for a file
    name, and nothing is kept for it. A field inside an object is looked at the same way. A value
    that is not an attachment is left as it is."""
    if not names:
        return params

    def named(value: Any) -> Any:
        return names.get(value.strip(), value) if isinstance(value, str) else value

    async def one(value: Any, as_kind: str) -> Any:
        if not isinstance(value, str):
            return value
        ident = names.get(value.strip())
        if ident is None:
            return value
        if (ident, as_kind) not in done:
            made = await keep(ident, as_kind)
            if made is None:
                return value  # left as it was: the action says what is wrong with it
            done[(ident, as_kind)] = made
        return done[(ident, as_kind)]

    out: dict[str, Any] = {}
    for key, value in params.items():
        if isinstance(value, dict) and action_id != KEEP:
            # a field inside an object: Creative Studio's song is `brief.track_id`
            out[key] = await kept_in_place(action_id, value, names, keep, done)
            continue
        if key in TAKES_ATTACHMENT:
            out[key] = [named(v) for v in value] if isinstance(value, list) else named(value)
        elif action_id == KEEP or not key.endswith(("_id", "_ids")):
            out[key] = value  # only where a library item belongs, never a prompt
        elif isinstance(value, list):  # image.reference takes two pictures
            out[key] = [await one(v, AS_KIND.get(key, "")) for v in value]
        else:
            out[key] = await one(value, AS_KIND.get(key, ""))
    return out
