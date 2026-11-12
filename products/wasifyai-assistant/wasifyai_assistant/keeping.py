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

# runs `library.keep_attachment` for one attachment id; the library id, or None when it failed
Keep = Callable[[str], Awaitable[str | None]]


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
    action_id: str, params: dict[str, Any], names: dict[str, str], keep: Keep, done: dict[str, str]
) -> dict[str, Any]:
    """`params` with each attachment it names replaced by its library id. `done` remembers what
    was kept in this run, so one file is kept once. A value that is not an attachment, and the
    params of `library.keep_attachment` itself, are left as they are."""
    if action_id == KEEP or not names:
        return params

    async def one(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        ident = names.get(value.strip())
        if ident is None:
            return value
        if ident not in done:
            made = await keep(ident)
            if made is None:
                return value  # left as it was: the action says what is wrong with it
            done[ident] = made
        return done[ident]

    out: dict[str, Any] = {}
    for key, value in params.items():
        if not key.endswith(("_id", "_ids")):  # only where a library item belongs, never a prompt
            out[key] = value
        elif isinstance(value, list):  # image.reference takes two pictures
            out[key] = [await one(v) for v in value]
        else:
            out[key] = await one(value)
    return out
